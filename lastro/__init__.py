from typing import Any

from flask import Flask, Response, abort, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from .statement import Preview, Problem, format_date, format_money, read_statement


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=10 * 1024 * 1024, TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"])
    if config:
        app.config.update(config)
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

    def render_preview(result: Preview, status: int) -> tuple[str, int]:
        template = "preview.html" if request.headers.get("HX-Request") == "true" else "index.html"
        return render_template(template, result=result), status

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(error: RequestEntityTooLarge) -> tuple[str, int]:
        limit = app.config["MAX_CONTENT_LENGTH"] / (1024 * 1024)
        result = Preview(problems=[Problem("Arquivo muito grande.", f"Exporte um período menor. O limite da requisição é {limit:g} MiB.")])
        return render_preview(result, 413)

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.post("/previa")
    def preview() -> tuple[str, int]:
        uploaded = request.files.get("arquivo")
        if uploaded is None or not uploaded.filename:
            return render_preview(Preview(problems=[Problem("Nenhum arquivo selecionado.", "Selecione um arquivo CSV de extrato de conta corrente.")]), 422)
        result = read_statement(uploaded.read())
        return render_preview(result, 422 if result.problems else 200)

    return app
