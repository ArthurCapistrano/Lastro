from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup
from flask.testing import FlaskClient
import pytest

from lastro import create_app


HEADER = """Extrato Conta Corrente;;;;
Conta;00012345;;;
Período;01/10/2026 a 08/10/2026;;;
Saldo;-25,00;;;
Data Lançamento;Histórico;Descrição;Valor;Saldo
"""
FIRST = "07/10/2026;Pagamento;Compra;-10,00;-10,00\n"
INCONSISTENT = "08/10/2026;Pagamento;Outra compra;-10,00;-25,00\n"


def upload(client: FlaskClient, content: str) -> tuple[str, BeautifulSoup]:
    response = client.post("/previa", data={"arquivo": (BytesIO(content.encode()), "avisos.csv")})
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    form = page.select_one('form[action$="/confirmar"]')
    assert form is not None
    return str(form["action"]), page


def acknowledgments(page: BeautifulSoup) -> list[str]:
    return [str(box["value"]) for box in page.select('input[name="reconhecer_avisos"]')]


def test_inconsistent_balances_require_review_and_preserve_bank_values(tmp_path: Path) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    content = HEADER + FIRST + INCONSISTENT
    action, page = upload(client, content)
    text = page.get_text(" ", strip=True)
    assert "Aviso aguardando revisão" in text
    assert "Linhas 6 e 7" in text
    assert "-R$ 20,00" in text
    assert "-R$ 25,00" in text
    assert "não comprova que o extrato está completo" in text
    boxes = page.select('input[name="reconhecer_avisos"]')
    assert len(boxes) == 1
    assert boxes[0].has_attr("required") and not boxes[0].has_attr("checked")
    for value in (None, "sim", "inventado"):
        data = {"confirmar": "sim", "guardar_sem_novidades": "sim"}
        if value:
            data["reconhecer_avisos"] = value
        response = client.post(action, data=data)
        assert response.status_code == 422
        assert "Reconheça explicitamente todos os avisos" in response.get_data(as_text=True)
        assert not BeautifulSoup(client.get("/movimentacoes").data, "html.parser").select("tbody tr")
    response = client.post(action, data={"confirmar": "sim", "reconhecer_avisos": acknowledgments(page)})
    assert response.status_code == 303
    detail = response.headers["Location"]
    rows = BeautifulSoup(client.get(detail).data, "html.parser").select("tbody tr")
    assert [row.select("td")[-1].get_text(strip=True) for row in rows] == ["-R$ 10,00", "-R$ 25,00"]
    assert client.get(detail + "/original").data == content.encode()
    assert client.post(action, data={"confirmar": "sim"}).headers["Location"] == detail


def test_different_known_balance_warns_without_merging_or_overwriting(tmp_path: Path) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    action, _ = upload(client, HEADER + FIRST)
    first = client.post(action, data={"confirmar": "sim"}).headers["Location"]
    changed = FIRST.replace(";-10,00\n", ";-15,00\n").replace("Pagamento;Compra", "  Pagamento  ; Compra ")
    action, page = upload(client, HEADER + changed)
    text = page.get_text(" ", strip=True)
    assert "possível divergência" in text
    assert "movimentação legítima repetida" in text
    assert "Linha 6" in text and "-R$ 10,00" in text and "-R$ 15,00" in text
    assert page.select_one(f'a[href="{first}"]') is not None
    assert client.post(action, data={"confirmar": "sim"}).status_code == 422
    response = client.post(action, data={"confirmar": "sim", "reconhecer_avisos": acknowledgments(page)})
    assert response.status_code == 303
    second = response.headers["Location"]
    rows = BeautifulSoup(client.get("/movimentacoes").data, "html.parser").select("tbody tr")
    assert [row.select("td")[-1].get_text(strip=True) for row in rows] == ["-R$ 10,00", "-R$ 15,00"]
    assert client.get(first + "/original").data == (HEADER + FIRST).encode()
    assert client.get(second + "/original").data == (HEADER + changed).encode()
    action, page = upload(client, HEADER + FIRST + "\n")
    assert not acknowledgments(page)
    assert "0 novas · 1 já existentes" in page.get_text(" ", strip=True)
    assert client.post(action, data={"confirmar": "sim", "guardar_sem_novidades": "sim"}).status_code == 303


def test_each_warning_requires_its_own_acknowledgment(tmp_path: Path) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    action, page = upload(client, HEADER + FIRST + INCONSISTENT + "08/10/2026;Crédito;Transferência;5,00;-15,00\n")
    keys = acknowledgments(page)
    assert len(keys) == 2 and len(set(keys)) == 2
    assert client.post(action, data={"confirmar": "sim", "reconhecer_avisos": keys[:1]}).status_code == 422
    assert client.post(action, data={"confirmar": "sim", "reconhecer_avisos": keys}).status_code == 303


def test_previously_imported_inconsistent_rows_do_not_require_new_review(tmp_path: Path) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    content = HEADER + FIRST + INCONSISTENT
    action, page = upload(client, content)
    assert client.post(action, data={"confirmar": "sim", "reconhecer_avisos": acknowledgments(page)}).status_code == 303
    action, page = upload(client, content + "\n")
    assert "0 novas · 2 já existentes" in page.get_text(" ", strip=True)
    assert not acknowledgments(page)
    assert client.post(action, data={"confirmar": "sim", "guardar_sem_novidades": "sim"}).status_code == 303


def test_stale_preview_requires_review_of_newly_known_divergence(tmp_path: Path) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    stale, page = upload(client, HEADER + FIRST.replace(";-10,00\n", ";-15,00\n"))
    assert not acknowledgments(page)
    action, _ = upload(client, HEADER + FIRST)
    assert client.post(action, data={"confirmar": "sim"}).status_code == 303
    response = client.post(stale, data={"confirmar": "sim"})
    assert response.status_code == 422
    page = BeautifulSoup(response.data, "html.parser")
    assert "possível divergência" in page.get_text()
    assert client.post(stale, data={"confirmar": "sim", "reconhecer_avisos": acknowledgments(page)}).status_code == 303


@pytest.mark.parametrize("invalid", ["inválido", ""])
def test_warning_checkboxes_cannot_bypass_blocking_errors(tmp_path: Path, invalid: str) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    _, valid_page = upload(client, HEADER + FIRST + INCONSISTENT)
    content = HEADER + FIRST + INCONSISTENT + f"08/10/2026;Crédito;Transferência;{invalid};-15,00\n"
    response = client.post("/previa", data={"arquivo": (BytesIO(content.encode()), "bloqueado.csv")})
    assert response.status_code == 422
    page = BeautifulSoup(response.data, "html.parser")
    assert not page.select('input[type="checkbox"]')
    cancel = page.select_one('form[action$="/cancelar"]')
    assert cancel is not None
    action = str(cancel["action"]).removesuffix("cancelar") + "confirmar"
    response = client.post(action, data={"confirmar": "sim", "guardar_sem_novidades": "sim", "reconhecer_avisos": acknowledgments(valid_page)})
    assert response.status_code == 422
    assert "Linha 8 — Valor" in response.get_data(as_text=True)
    assert "Nenhuma importação confirmada" in client.get("/importacoes").get_data(as_text=True)


@pytest.mark.parametrize("records, count", [
    (FIRST, 0),
    (FIRST + INCONSISTENT.replace("-25,00", "-20,00"), 0),
    (FIRST + INCONSISTENT.replace("08/10/2026", "07/10/2026"), 1),
    (INCONSISTENT + FIRST, 1),
    (INCONSISTENT.replace("-25,00", "-20,00") + FIRST, 0),
    (INCONSISTENT + FIRST + "08/10/2026;Crédito;Transferência;5,00;-15,00\n", 0),
    (INCONSISTENT + FIRST.replace("07/10/2026", "08/10/2026") + FIRST, 0),
])
def test_balance_review_only_uses_comparable_sequences(tmp_path: Path, records: str, count: int) -> None:
    client = create_app({"TESTING": True, "STORAGE_PATH": str(tmp_path)}).test_client()
    _, page = upload(client, HEADER + records)
    assert len(acknowledgments(page)) == count
    assert "ordem ambígua não é conferida" in page.get_text(" ", strip=True)
