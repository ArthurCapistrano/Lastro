import os
import sqlite3
from pathlib import Path
from secrets import token_hex
from typing import Any

from flask import Flask, Response, abort, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.wrappers import Response as WerkzeugResponse

from .statement import Preview, Problem, format_date, format_money, read_statement
from .storage import ImportUnavailable, Storage


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=10 * 1024 * 1024, TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"])
    if config:
        app.config.update(config)
    storage = Storage(Path(app.config.get("STORAGE_PATH", os.environ.get("LASTRO_STORAGE_PATH", app.instance_path))).resolve())
    previews: dict[str, tuple[str, bytes]] = {}
    app.jinja_env.filters["money"] = format_money
    app.jinja_env.filters["date_br"] = format_date

    @app.before_request
    def require_local_access() -> None:
        if request.remote_addr not in ("127.0.0.1", "::1"):
            abort(403)

    @app.after_request
    def disable_caching(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Vary"] = "HX-Request"
        return response

    def render_preview(result: Preview, status: int, token: str | None = None, failure: str | None = None) -> tuple[str, int]:
        template = "preview.html" if request.headers.get("HX-Request") == "true" else "index.html"
        return render_template(template, result=result, token=token, failure=failure), status

    @app.errorhandler(OSError)
    @app.errorhandler(sqlite3.Error)
    def storage_unavailable(error: Exception) -> tuple[str, int]:
        token = (request.view_args or {}).get("token")
        pending = previews.get(token) if token else None
        result = read_statement(pending[1]) if pending else Preview()
        return render_preview(result, 503, token if pending else None, "Não foi possível acessar o armazenamento local. Confira o espaço e as permissões e tente novamente. Repetir a confirmação é seguro.")

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(error: RequestEntityTooLarge) -> tuple[str, int]:
        limit = app.config["MAX_CONTENT_LENGTH"] / (1024 * 1024)
        result = Preview(problems=[Problem("Arquivo muito grande.", f"Exporte um período menor. O limite da requisição é {limit:g} MiB.")])
        return render_preview(result, 413)

    @app.get("/")
    def index() -> str:
        return render_template("index.html", imported=storage.first())

    @app.post("/previa")
    def preview() -> tuple[str, int]:
        if storage.first() is not None:
            return render_preview(Preview(problems=[Problem("Importações sucessivas ainda não estão disponíveis.", "Consulte a primeira importação confirmada em Importações.")]), 409)
        uploaded = request.files.get("arquivo")
        if uploaded is None or not uploaded.filename:
            return render_preview(Preview(problems=[Problem("Nenhum arquivo selecionado.", "Selecione um arquivo CSV de extrato de conta corrente.")]), 422)
        content = uploaded.read()
        result = read_statement(content)
        token = token_hex(32)
        previews[token] = (uploaded.filename, content)
        return render_preview(result, 422 if result.problems else 200, token)

    @app.post("/previas/<token>/cancelar")
    def cancel(token: str) -> WerkzeugResponse:
        previews.pop(token, None)
        return redirect(url_for("index"), code=303)

    @app.post("/previas/<token>/confirmar")
    def confirm(token: str) -> WerkzeugResponse | tuple[str, int]:
        imported = storage.first()
        if imported is not None:
            if imported.id == token:
                return redirect(url_for("import_detail", id=token), code=303)
            return render_preview(Preview(problems=[Problem("Importações sucessivas ainda não estão disponíveis.", "Consulte a primeira importação confirmada em Importações.")]), 409)
        pending = previews.get(token)
        if pending is None:
            imported = storage.first()
            if imported is not None and imported.id == token:
                return redirect(url_for("import_detail", id=token), code=303)
            abort(404, "Prévia indisponível. Envie o arquivo novamente.")
        filename, content = pending
        result = read_statement(content)
        if result.problems or result.statement is None:
            return render_preview(result, 422, token)
        if request.form.get("confirmar") != "sim":
            return render_preview(result, 422, token, "Confirmação explícita obrigatória. Confira a prévia e clique em Confirmar importação.")
        try:
            storage.confirm(token, filename, content, result.statement)
        except ImportUnavailable:
            return render_preview(Preview(problems=[Problem("Importações sucessivas ainda não estão disponíveis.", "Consulte Importações.")]), 409)
        previews.pop(token, None)
        return redirect(url_for("import_detail", id=token), code=303)

    @app.get("/importacoes")
    def imports() -> str:
        return render_template("history.html", imported=storage.first(), view="imports")

    @app.get("/importacoes/<id>")
    def import_detail(id: str) -> str:
        imported = storage.first()
        if imported is None or imported.id != id:
            abort(404)
        return render_template("history.html", imported=imported, view="detail")

    @app.get("/importacoes/<id>/original")
    def original(id: str) -> Response:
        imported = storage.first()
        if imported is None or imported.id != id:
            abort(404)
        return send_file(storage.original_path(id), as_attachment=True, download_name=imported.filename, mimetype="text/csv")

    @app.get("/movimentacoes")
    def movements() -> str:
        return render_template("history.html", imported=storage.first(), view="movements")

    return app
