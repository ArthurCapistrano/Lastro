from io import BytesIO
from pathlib import Path
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

from bs4 import BeautifulSoup
from flask.testing import FlaskClient
import pytest

from lastro import create_app


SAMPLE = """Extrato Conta Corrente;;;;
Conta;00012345;;;
Período;01/10/2026 a 08/10/2026;;;
Saldo;-19,00;;;
Data Lançamento;Histórico;Descrição;Valor;Saldo
07/10/2026;Crédito B3;Resgate;1.234,56;1.234,56
08/10/2026;Pagamento;Compra;-1.253,56;-19,00
"""


def upload(client: FlaskClient, content: str = SAMPLE) -> str:
    response = client.post("/previa", data={"arquivo": (BytesIO(content.encode("utf-8-sig")), "sintetico.csv")})
    assert response.status_code == 200
    form = BeautifulSoup(response.data, "html.parser").select_one('form[action$="/confirmar"]')
    assert form is not None
    return str(form["action"])


def test_confirmation_requires_explicit_consent_and_survives_restart(tmp_path: Path) -> None:
    config = {"TESTING": True, "STORAGE_PATH": str(tmp_path)}
    client = create_app(config).test_client()
    action = upload(client)
    assert "Nenhuma importação confirmada" in client.get("/importacoes").get_data(as_text=True)
    assert client.post(action).status_code == 422
    response = client.post(action, data={"confirmar": "sim"})
    assert response.status_code == 303
    location = response.headers["Location"]
    client = create_app(config).test_client()
    page = BeautifulSoup(client.get(location).data, "html.parser")
    text = page.get_text(" ", strip=True)
    for expected in ("Importação confirmada", "sintetico.csv", "00012345", "01/10/2026 a 08/10/2026", "2 novas", "0 já existentes", "Data de importação"):
        assert expected in text
    assert len(page.select("tbody tr")) == 2
    assert "Crédito B3" in client.get("/movimentacoes").get_data(as_text=True)
    original = client.get(location + "/original")
    assert original.data == SAMPLE.encode("utf-8-sig")
    assert "attachment" in original.headers["Content-Disposition"]
    assert "sintetico.csv" in client.get("/importacoes").get_data(as_text=True)


def test_original_storage_failure_leaves_no_history_and_allows_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    action = upload(client)

    def fail_sync(fd: int) -> None:
        raise OSError("Synthetic disk failure")

    with monkeypatch.context() as failure:
        failure.setattr(os, "fsync", fail_sync)
        response = client.post(action, data={"confirmar": "sim"})
    assert response.status_code == 503
    page = BeautifulSoup(response.data, "html.parser")
    assert "Nenhum histórico foi incorporado" in page.get_text()
    assert page.select_one('button[name="confirmar"]') is not None
    for route in ("/importacoes", "/movimentacoes"):
        assert "Nenhuma importação confirmada" in client.get(route).get_data(as_text=True)
    response = client.post(action, data={"confirmar": "sim"})
    assert response.status_code == 303
    assert client.get(response.headers["Location"] + "/original").data == SAMPLE.encode("utf-8-sig")


def test_repeated_confirmation_preserves_identical_occurrences_and_line_origins(tmp_path: Path) -> None:
    config = {"TESTING": True, "STORAGE_PATH": str(tmp_path)}
    app = create_app(config)
    client = app.test_client()
    content = SAMPLE + "\n08/10/2026;Pagamento;Compra;-1.253,56;-19,00\n"
    action = upload(client, content)

    def confirm() -> tuple[int, str]:
        response = app.test_client().post(action, data={"confirmar": "sim"})
        return response.status_code, response.headers.get("Location", "")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: confirm(), range(2)))
    assert results[0] == results[1]
    assert results[0][0] == 303
    location = results[0][1]
    reopened = create_app(config).test_client()
    assert reopened.post(action, data={"confirmar": "sim"}).headers["Location"] == location
    for route in (location, "/movimentacoes"):
        page = BeautifulSoup(reopened.get(route).data, "html.parser")
        rows = [[cell.get_text(strip=True) for cell in row.select("td")] for row in page.select("tbody tr")]
        assert rows == [
            ["6", "07/10/2026", "Crédito B3", "Resgate", "R$ 1.234,56", "R$ 1.234,56"],
            ["7", "08/10/2026", "Pagamento", "Compra", "-R$ 1.253,56", "-R$ 19,00"],
            ["9", "08/10/2026", "Pagamento", "Compra", "-R$ 1.253,56", "-R$ 19,00"],
        ]
        assert "3 novas" in page.get_text()
    assert reopened.get(location + "/original").data == content.encode("utf-8-sig")


def test_cancelled_preview_cannot_be_confirmed_and_does_not_bind_account(tmp_path: Path) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    action = upload(client)
    assert client.post(action.removesuffix("confirmar") + "cancelar").status_code == 303
    assert client.post(action, data={"confirmar": "sim"}).status_code == 404
    assert "Nenhuma importação confirmada" in client.get("/importacoes").get_data(as_text=True)
    other = upload(client, SAMPLE.replace("00012345", "99999999"))
    response = client.post(other, data={"confirmar": "sim"})
    assert response.status_code == 303
    assert "99999999" in client.get(response.headers["Location"]).get_data(as_text=True)


def test_blocked_preview_cannot_be_confirmed_over_http(tmp_path: Path) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    response = client.post("/previa", data={"arquivo": (BytesIO(SAMPLE.replace("-1.253,56", "inválido").encode()), "bloqueado.csv")})
    assert response.status_code == 422
    page = BeautifulSoup(response.data, "html.parser")
    cancel = page.select_one('form[action$="/cancelar"]')
    assert cancel is not None
    action = str(cancel["action"]).removesuffix("cancelar") + "confirmar"
    response = client.post(action, data={"confirmar": "sim", "ignorar_erros": "on"})
    assert response.status_code == 422
    assert "Linha 7 — Valor" in response.get_data(as_text=True)
    assert "Nenhuma importação confirmada" in client.get("/importacoes").get_data(as_text=True)
    assert client.post("/previas/inexistente/confirmar", data={"confirmar": "sim"}).status_code == 404


def test_other_account_uploads_and_stale_confirmations_are_blocked(tmp_path: Path) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    first = upload(client)
    stale = upload(client, SAMPLE.replace("00012345", "99999999"))
    response = client.post(first, data={"confirmar": "sim"})
    location = response.headers["Location"]
    response = client.post("/previa", data={"arquivo": (BytesIO(SAMPLE.replace("00012345", "99999999").encode()), "novo.csv")})
    assert response.status_code == 409
    assert "Conta diferente da conta vinculada (00012345)" in response.get_data(as_text=True)
    assert client.post(stale, data={"confirmar": "sim"}).status_code == 409
    assert len(BeautifulSoup(client.get(location).data, "html.parser").select("tbody tr")) == 2
    assert "99999999" not in client.get("/importacoes").get_data(as_text=True)


def test_database_commit_failure_rolls_back_and_does_not_bind_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = {"TESTING": True, "STORAGE_PATH": str(tmp_path)}
    client = create_app(config).test_client()
    action = upload(client)
    original_connect = sqlite3.connect

    class FailingConnection(sqlite3.Connection):
        def commit(self) -> None:
            raise sqlite3.OperationalError("Synthetic commit failure")

    def connect(database: str | Path) -> sqlite3.Connection:
        return original_connect(database, factory=FailingConnection)

    with monkeypatch.context() as failure:
        failure.setattr(sqlite3, "connect", connect)
        assert client.post(action, data={"confirmar": "sim"}).status_code == 503
    reopened = create_app(config).test_client()
    for route in ("/importacoes", "/movimentacoes"):
        assert "Nenhuma importação confirmada" in reopened.get(route).get_data(as_text=True)
    other = upload(client, SAMPLE.replace("00012345", "99999999"))
    response = client.post(other, data={"confirmar": "sim"})
    assert response.status_code == 303
    assert "99999999" in client.get(response.headers["Location"]).get_data(as_text=True)
    assert client.post(action, data={"confirmar": "sim"}).status_code == 409


def test_confirmation_returns_existing_result_when_other_request_removes_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)})
    client = app.test_client()
    action = upload(client)
    original_connect = sqlite3.connect
    paused, resume = Event(), Event()

    class PausingConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
            cursor = super().execute(sql, parameters)
            if "UNION ALL SELECT import_id AS id FROM confirmations" in sql and not paused.is_set():
                paused.set()
                assert resume.wait(timeout=10)
            return cursor

    def connect(database: str | Path) -> sqlite3.Connection:
        return original_connect(database, factory=PausingConnection)

    def confirm() -> tuple[int, str]:
        response = app.test_client().post(action, data={"confirmar": "sim"})
        return response.status_code, response.headers.get("Location", "")

    with monkeypatch.context() as failure, ThreadPoolExecutor(max_workers=1) as executor:
        failure.setattr(sqlite3, "connect", connect)
        pending = executor.submit(confirm)
        try:
            assert paused.wait(timeout=10)
            completed = confirm()
        finally:
            resume.set()
        assert pending.result(timeout=10) == completed
    assert completed[0] == 303


def test_interruption_after_commit_does_not_remove_confirmed_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = {"TESTING": True, "STORAGE_PATH": str(tmp_path)}
    client = create_app(config).test_client()
    action = upload(client)
    original_connect = sqlite3.connect

    class InterruptedConnection(sqlite3.Connection):
        def commit(self) -> None:
            super().commit()
            raise KeyboardInterrupt

    def connect(database: str | Path) -> sqlite3.Connection:
        return original_connect(database, factory=InterruptedConnection)

    with monkeypatch.context() as failure:
        failure.setattr(sqlite3, "connect", connect)
        with pytest.raises(KeyboardInterrupt):
            client.post(action, data={"confirmar": "sim"})
    reopened = create_app(config).test_client()
    response = reopened.post(action, data={"confirmar": "sim"})
    assert response.status_code == 303
    location = response.headers["Location"]
    assert len(BeautifulSoup(reopened.get(location).data, "html.parser").select("tbody tr")) == 2
    assert reopened.get(location + "/original").data == SAMPLE.encode("utf-8-sig")


def test_database_open_failure_returns_retryable_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    action = upload(client)

    def connect(database: str | Path) -> sqlite3.Connection:
        raise sqlite3.OperationalError("Synthetic unavailable database")

    with monkeypatch.context() as failure:
        failure.setattr(sqlite3, "connect", connect)
        response = client.post(action, data={"confirmar": "sim"})
    assert response.status_code == 503
    page = BeautifulSoup(response.data, "html.parser")
    assert "armazenamento" in page.get_text()
    assert page.select_one('button[name="confirmar"]') is not None
    assert "Nenhuma importação confirmada" in client.get("/importacoes").get_data(as_text=True)
    assert client.post(action, data={"confirmar": "sim"}).status_code == 303


def test_relative_storage_path_keeps_original_downloadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = {"TESTING": True, "STORAGE_PATH": "storage"}
    client = create_app(config).test_client()
    action = upload(client)
    response = client.post(action, data={"confirmar": "sim"})
    assert response.status_code == 303
    reopened = create_app(config).test_client()
    assert reopened.get(response.headers["Location"] + "/original").data == SAMPLE.encode("utf-8-sig")
