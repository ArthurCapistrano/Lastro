from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup
from flask.testing import FlaskClient
import pytest

from lastro import create_app


HEADER = """Extrato Conta Corrente;;;;
Conta;00012345;;;
Período;01/10/2026 a 08/10/2026;;;
Saldo;85,00;;;
Data Lançamento;Histórico;Descrição;Valor;Saldo
"""
PAYMENT = "07/10/2026;Pagamento;Compra;-10,00;90,00\n"
CREDIT = "08/10/2026;Crédito;Transferência;5,00;95,00\n"


def import_file(client: FlaskClient, content: bytes, filename: str, *, keep: bool = False) -> str:
    response = client.post("/previa", data={"arquivo": (BytesIO(content), filename)})
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    form = page.select_one('form[action$="/confirmar"]')
    assert form is not None
    response = client.post(str(form["action"]), data={"confirmar": "sim", "guardar_sem_novidades": "sim" if keep else ""})
    assert response.status_code == 303
    return response.headers["Location"]


def test_empty_imports_page_offers_upload_without_pending_or_cancelled_files() -> None:
    client = create_app({"TESTING": True}).test_client()
    response = client.post("/previa", data={"arquivo": (BytesIO((HEADER + PAYMENT).encode()), "pendente.csv")})
    page = BeautifulSoup(response.data, "html.parser")
    cancel = page.select_one('form[action$="/cancelar"]')
    assert cancel is not None
    for cancelled in (False, True):
        if cancelled:
            assert client.post(str(cancel["action"])).status_code == 303
        response = client.get("/importacoes")
        assert response.status_code == 200
        page = BeautifulSoup(response.data, "html.parser")
        assert "Nenhuma importação confirmada" in page.get_text()
        assert "pendente.csv" not in page.get_text()
        link = page.select_one('a[href="/"]:not(header a)')
        assert link is not None and link["href"] == "/"
        assert page.title is not None and page.title.get_text() == "Lastro — Importações"


def test_listing_and_details_keep_counts_all_occurrences_and_downloads_after_restart(tmp_path: Path) -> None:
    config = {"TESTING": True, "STORAGE_PATH": str(tmp_path)}
    client = create_app(config).test_client()
    before = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    first_content = (HEADER + PAYMENT).encode("utf-8-sig")
    first = import_file(client, first_content, "primeiro.csv")
    second_content = (HEADER + "\n" + PAYMENT + CREDIT).replace("\n", "\r\n").encode("utf-8-sig")
    second = import_file(client, second_content, "sobreposto.csv")
    zero_content = (HEADER + "\n\n" + PAYMENT + CREDIT).encode()
    zero = import_file(client, zero_content, "apenas-registro.csv", keep=True)
    client = create_app(config).test_client()
    response = client.get("/importacoes")
    assert response.status_code == 200
    listing = BeautifulSoup(response.data, "html.parser")
    for location, filename, content, counts, expected_rows in (
        (first, "primeiro.csv", first_content, "1 novas · 0 já existentes · 1 movimentações confirmadas", [
            ["6", "07/10/2026", "Pagamento", "Compra", "-R$ 10,00", "R$ 90,00"],
        ]),
        (second, "sobreposto.csv", second_content, "1 novas · 1 já existentes · 2 movimentações confirmadas", [
            ["7", "07/10/2026", "Pagamento", "Compra", "-R$ 10,00", "R$ 90,00"],
            ["8", "08/10/2026", "Crédito", "Transferência", "R$ 5,00", "R$ 95,00"],
        ]),
        (zero, "apenas-registro.csv", zero_content, "0 novas · 2 já existentes · 2 movimentações confirmadas", [
            ["8", "07/10/2026", "Pagamento", "Compra", "-R$ 10,00", "R$ 90,00"],
            ["9", "08/10/2026", "Crédito", "Transferência", "R$ 5,00", "R$ 95,00"],
        ]),
    ):
        link = listing.select_one(f'h2 a[href="{location}"]')
        assert link is not None
        assert link.get_text() == filename
        card = link.find_parent("section")
        assert card is not None
        for text in ("Conta: 00012345", "01/10/2026 a 08/10/2026", counts):
            assert text in card.get_text(" ", strip=True)
        assert any(day in card.get_text() for day in (before, datetime.now(timezone.utc).strftime("%d/%m/%Y")))
        response = client.get(str(link["href"]))
        assert response.status_code == 200
        detail = BeautifulSoup(response.data, "html.parser")
        assert detail.title is not None and detail.title.get_text() == "Lastro — Importação confirmada"
        assert counts in detail.get_text(" ", strip=True)
        assert "Saldo informado: R$ 85,00" in detail.get_text(" ", strip=True)
        rows = [[cell.get_text(strip=True) for cell in row.select("td")] for row in detail.select("tbody tr")]
        assert rows == expected_rows
        download = detail.select_one('a[href$="/original"]')
        assert download is not None
        original = client.get(str(download["href"]))
        assert original.status_code == 200 and original.data == content
        assert original.mimetype == "text/csv"
        assert original.headers["Content-Disposition"] == f"attachment; filename={filename}"
        assert original.headers["Cache-Control"] == "no-store"
        assert not detail.select('form, a[href$="/excluir"], a[href$="/editar"]')
        back = detail.select_one('main > a[href="/importacoes"]')
        assert back is not None and back["href"] == "/importacoes"


@pytest.mark.parametrize("id", ["inexistente", "sem-referencia", "..", "' OR 1=1 --"])
@pytest.mark.parametrize("suffix", ["", "/original"])
def test_unknown_import_has_clear_not_found_page_and_never_exposes_unrelated_storage(tmp_path: Path, id: str, suffix: str) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    location = import_file(client, (HEADER + PAYMENT).encode(), "confirmado.csv")
    # Simulate an unreferenced file left after an interrupted confirmation.
    (tmp_path / "originals" / "sem-referencia.csv").write_bytes(b"unrelated synthetic content")
    (tmp_path / "private.csv").write_bytes(b"other synthetic content")
    response = client.get(f"/importacoes/{id}{suffix}")
    assert response.status_code == 404
    page = BeautifulSoup(response.data, "html.parser")
    assert "Importação não encontrada" in page.get_text()
    assert "unrelated synthetic content" not in page.get_text()
    assert "other synthetic content" not in page.get_text()
    assert "confirmado.csv" not in page.get_text()
    back = page.select_one('main a[href="/importacoes"]')
    assert back is not None
    assert "Content-Disposition" not in response.headers
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get(location + "/original").data == (HEADER + PAYMENT).encode()


@pytest.mark.parametrize("htmx", [False, True])
def test_repeated_file_reaches_previous_import_and_its_original_after_restart(tmp_path: Path, htmx: bool) -> None:
    config = {"TESTING": True, "STORAGE_PATH": str(tmp_path)}
    client = create_app(config).test_client()
    content = (HEADER + PAYMENT).encode("utf-8-sig")
    location = import_file(client, content, "fonte.csv")
    client = create_app(config).test_client()
    response = client.post("/previa", headers={"HX-Request": "true"} if htmx else {}, data={"arquivo": (BytesIO(content), "renomeado.csv")})
    assert response.status_code == (200 if htmx else 303)
    target = response.headers["HX-Redirect" if htmx else "Location"]
    assert target == location
    detail = BeautifulSoup(client.get(target).data, "html.parser")
    assert "fonte.csv" in detail.get_text() and "renomeado.csv" not in detail.get_text()
    download = detail.select_one('a[href$="/original"]')
    assert download is not None
    assert client.get(str(download["href"])).data == content
    listing = BeautifulSoup(client.get("/importacoes").data, "html.parser")
    assert len(listing.select("h2 a")) == 1
