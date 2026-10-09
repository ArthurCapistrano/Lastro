from io import BytesIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3

import pytest

from bs4 import BeautifulSoup
from flask.testing import FlaskClient

from lastro import create_app


HEADER = """Extrato Conta Corrente;;;;
Conta;00012345;;;
Período;01/10/2026 a 08/10/2026;;;
Saldo;80,00;;;
Data Lançamento;Histórico;Descrição;Valor;Saldo
"""
PAYMENT = "07/10/2026;Pagamento;Compra;-10,00;90,00\n"
SECOND = "07/10/2026;Pagamento;Compra;-10,00;80,00\n"
NEW = "07/10/2026;Crédito;Transferência;5,00;85,00\n"


def preview(client: FlaskClient, content: str, filename: str = "extrato.csv") -> tuple[str, str]:
    response = client.post("/previa", data={"arquivo": (BytesIO(content.encode()), filename)})
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    form = page.select_one('form[action$="/confirmar"]')
    assert form is not None
    return str(form["action"]), page.get_text(" ", strip=True)


def confirm(client: FlaskClient, action: str, *, keep: bool = False) -> str:
    data = {"confirmar": "sim"}
    if keep:
        data["guardar_sem_novidades"] = "sim"
    response = client.post(action, data=data)
    assert response.status_code == 303
    return response.headers["Location"]


def rows(client: FlaskClient, route: str) -> list[list[str]]:
    page = BeautifulSoup(client.get(route).data, "html.parser")
    return [[cell.get_text(" ", strip=True) for cell in row.select("td")] for row in page.select("tbody tr")]


def test_overlapping_statement_keeps_repeated_payments_and_new_movements_on_same_day(tmp_path: Path) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    action, _ = preview(client, HEADER + PAYMENT + SECOND, "primeiro.csv")
    first = confirm(client, action)
    action, text = preview(client, HEADER + PAYMENT + SECOND + NEW, "posterior.csv")
    assert "1 novas · 2 já existentes" in text
    assert "Sobreposição de períodos" in text
    second = confirm(client, action)
    assert len(rows(client, "/movimentacoes")) == 3
    assert len(rows(client, first)) == 2
    assert len(rows(client, second)) == 3
    assert "1 novas · 2 já existentes" in client.get(second).get_data(as_text=True)
    origins = BeautifulSoup(client.get("/movimentacoes").data, "html.parser").select("tbody tr")[0].select("a")
    assert {link["href"] for link in origins} == {first, second}
    assert client.get(second + "/original").data == (HEADER + PAYMENT + SECOND + NEW).encode()


def test_identical_occurrences_use_maximum_multiplicity_and_interpreted_fields(tmp_path: Path) -> None:
    config = {"TESTING": True, "STORAGE_PATH": str(tmp_path)}
    client = create_app(config).test_client()
    action, _ = preview(client, HEADER + PAYMENT * 2)
    confirm(client, action)
    normalized = PAYMENT.replace("Pagamento;Compra", "  Pagamento  ;  Compra  ").replace("-10,00;90,00", "-10;90")
    action, text = preview(client, HEADER + normalized * 3, "tres.csv")
    assert "1 novas · 2 já existentes" in text
    second = confirm(client, action)
    assert len(rows(client, second)) == 3
    assert len(rows(client, "/movimentacoes")) == 3
    client = create_app(config).test_client()
    action, text = preview(client, HEADER + PAYMENT + NEW, "menos.csv")
    assert "1 novas · 1 já existentes" in text
    confirm(client, action)
    consolidated = rows(client, "/movimentacoes")
    assert len(consolidated) == 4
    assert [row[2:6] for row in consolidated[:3]] == [["Pagamento", "Compra", "-R$ 10,00", "R$ 90,00"]] * 3


def test_different_file_without_new_movements_requires_explicit_consent(tmp_path: Path) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    action, _ = preview(client, HEADER + PAYMENT * 2, "primeiro.csv")
    first = confirm(client, action)
    content = HEADER + PAYMENT + "\n"
    action, text = preview(client, content, "registro.csv")
    assert "0 novas · 1 já existentes" in text
    assert "Guardar este extrato apenas para registro" in text
    response = client.post(action, data={"confirmar": "sim"})
    assert response.status_code == 422
    assert "consentimento explícito" in response.get_data(as_text=True)
    assert "registro.csv" not in client.get("/importacoes").get_data(as_text=True)
    assert len(rows(client, "/movimentacoes")) == 2
    second = confirm(client, action, keep=True)
    assert len(rows(client, second)) == 1
    assert "0 novas · 1 já existentes" in client.get(second).get_data(as_text=True)
    assert client.get(second + "/original").data == content.encode()
    assert confirm(client, action) == second
    origins = BeautifulSoup(client.get("/movimentacoes").data, "html.parser").select("tbody tr")
    assert {a["href"] for a in origins[0].select("a")} == {first, second}
    assert {a["href"] for a in origins[1].select("a")} == {first}


def test_identical_bytes_redirect_to_existing_import_even_with_another_filename(tmp_path: Path) -> None:
    config = {"TESTING": True, "STORAGE_PATH": str(tmp_path)}
    client = create_app(config).test_client()
    content = HEADER + PAYMENT
    action, _ = preview(client, content, "original.csv")
    stale, _ = preview(client, content, "repetido.csv")
    first = confirm(client, action)
    assert confirm(client, stale) == first
    client = create_app(config).test_client()
    assert confirm(client, stale) == first
    response = client.post("/previa", data={"arquivo": (BytesIO(content.encode()), "outro-nome.csv")})
    assert response.status_code == 303
    assert response.headers["Location"] == first
    assert "outro-nome.csv" not in client.get("/importacoes").get_data(as_text=True)
    assert len(rows(client, "/movimentacoes")) == 1
    assert len(list((tmp_path / "originals").glob("*.csv"))) == 1
    response = client.post("/previa", headers={"HX-Request": "true"}, data={"arquivo": (BytesIO(content.encode()), "htmx.csv")})
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == first


def test_stale_preview_rechecks_history_and_requests_zero_new_consent(tmp_path: Path) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    action, _ = preview(client, HEADER + PAYMENT)
    confirm(client, action)
    action, _ = preview(client, HEADER + PAYMENT + NEW, "novo.csv")
    stale, text = preview(client, HEADER + NEW + PAYMENT, "reordenado.csv")
    assert "1 novas · 1 já existentes" in text
    confirm(client, action)
    response = client.post(stale, data={"confirmar": "sim"})
    assert response.status_code == 422
    assert "0 novas · 2 já existentes" in response.get_data(as_text=True)
    assert "reordenado.csv" not in client.get("/importacoes").get_data(as_text=True)
    location = confirm(client, stale, keep=True)
    assert len(rows(client, location)) == 2
    assert len(rows(client, "/movimentacoes")) == 2


def test_simultaneous_different_previews_confirm_only_unrepresented_occurrences(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)})
    client = app.test_client()
    first, _ = preview(client, HEADER + PAYMENT)
    confirm(client, first)
    left, _ = preview(client, HEADER + PAYMENT * 2 + NEW, "esquerdo.csv")
    right, _ = preview(client, HEADER + NEW + PAYMENT * 3, "direito.csv")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda action: confirm(app.test_client(), action, keep=True), [left, right]))
    assert len(set(results)) == 2
    assert len(rows(client, "/movimentacoes")) == 4
    assert len(rows(client, results[0])) == 3
    assert len(rows(client, results[1])) == 4
    assert confirm(client, left) == results[0]
    assert confirm(client, right) == results[1]


def test_failure_in_later_import_preserves_history_and_allows_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    action, _ = preview(client, HEADER + PAYMENT, "primeiro.csv")
    first = confirm(client, action)
    before = rows(client, "/movimentacoes")
    action, _ = preview(client, HEADER + PAYMENT + NEW, "posterior.csv")

    def fail_sync(fd: int) -> None:
        raise OSError("Synthetic disk failure")

    with monkeypatch.context() as failure:
        failure.setattr(os, "fsync", fail_sync)
        assert client.post(action, data={"confirmar": "sim"}).status_code == 503
    assert rows(client, "/movimentacoes") == before
    assert "posterior.csv" not in client.get("/importacoes").get_data(as_text=True)
    assert client.get(first + "/original").data == (HEADER + PAYMENT).encode()
    second = confirm(client, action)
    assert len(rows(client, second)) == 2
    assert len(rows(client, "/movimentacoes")) == 2


def test_nonoverlapping_period_and_changed_fields_are_new_without_overwriting(tmp_path: Path) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    action, _ = preview(client, HEADER + PAYMENT)
    first = confirm(client, action)
    action, text = preview(client, HEADER + PAYMENT.replace("90,00", "89,00"), "saldo-diferente.csv")
    assert "1 novas · 0 já existentes" in text
    confirm(client, action)
    assert rows(client, first)[0][-1] == "R$ 90,00"
    later = HEADER.replace("01/10/2026 a 08/10/2026", "09/10/2026 a 10/10/2026") + PAYMENT.replace("07/10/2026", "09/10/2026")
    action, text = preview(client, later)
    assert "1 novas · 0 já existentes" in text
    assert "Sobreposição de períodos" not in text
    confirm(client, action)
    assert len(rows(client, "/movimentacoes")) == 3


def test_existing_single_import_storage_is_migrated_without_losing_origins(tmp_path: Path) -> None:
    # Seed the previous release's on-disk format; verify only through HTTP.
    with sqlite3.connect(tmp_path / "lastro.sqlite3") as connection:
        connection.executescript("""
            CREATE TABLE imports (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, imported_at TEXT NOT NULL,
                account TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
                balance TEXT NOT NULL, new_count INTEGER NOT NULL, existing_count INTEGER NOT NULL
            );
            CREATE TABLE movements (
                id INTEGER PRIMARY KEY, import_id TEXT NOT NULL REFERENCES imports(id),
                source_line INTEGER NOT NULL, date TEXT NOT NULL, history TEXT NOT NULL,
                description TEXT NOT NULL, amount TEXT NOT NULL, balance TEXT NOT NULL
            );
            INSERT INTO imports VALUES ('legacy', 'anterior.csv', '2026-10-08T12:00:00+00:00',
                '00012345', '2026-10-01', '2026-10-08', '80.00', 1, 0);
            INSERT INTO movements VALUES (1, 'legacy', 6, '2026-10-07', 'Pagamento', 'Compra', '-10.00', '90.00');
        """)
    (tmp_path / "originals").mkdir()
    (tmp_path / "originals" / "legacy.csv").write_bytes((HEADER + PAYMENT).encode())
    config = {"TESTING": True, "STORAGE_PATH": str(tmp_path)}
    client = create_app(config).test_client()
    assert rows(client, "/importacoes/legacy") == [["6", "07/10/2026", "Pagamento", "Compra", "-R$ 10,00", "R$ 90,00"]]
    response = client.post("/previa", data={"arquivo": (BytesIO((HEADER + PAYMENT).encode()), "igual.csv")})
    assert response.headers["Location"] == "/importacoes/legacy"
    action, text = preview(client, HEADER + PAYMENT + NEW, "posterior.csv")
    assert "1 novas · 1 já existentes" in text
    location = confirm(client, action)
    client = create_app(config).test_client()
    assert len(rows(client, "/movimentacoes")) == 2
    links = BeautifulSoup(client.get("/movimentacoes").data, "html.parser").select("tbody tr")[0].select("a")
    assert {a["href"] for a in links} == {"/importacoes/legacy", location}
    assert client.get("/importacoes/legacy/original").data == (HEADER + PAYMENT).encode()
