from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup
from flask.testing import FlaskClient
import pytest

from lastro import create_app


HEADER = """Extrato Conta Corrente;;;;
Conta;00012345;;;
Período;01/10/2026 a 08/10/2026;;;
Saldo;-19,00;;;
Data Lançamento;Histórico;Descrição;Valor;Saldo
"""
EARLY = "01/10/2026;Crédito B3;Resgate;1.234,56;1.234,56\n"
LATE = "08/10/2026;Pagamento;Compra;-1.253,56;-19,00\n"


def import_file(client: FlaskClient, content: str, filename: str, *, keep: bool = False) -> str:
    response = client.post("/previa", data={"arquivo": (BytesIO(content.encode()), filename)})
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    form = page.select_one('form[action$="/confirmar"]')
    assert form is not None
    response = client.post(str(form["action"]), data={
        "confirmar": "sim", "guardar_sem_novidades": "sim" if keep else "",
        "reconhecer_avisos": [str(box["value"]) for box in page.select('input[name="reconhecer_avisos"]')],
    })
    assert response.status_code == 303
    return response.headers["Location"]


def test_confirmed_movements_are_newest_first_with_bank_fields_after_restart(tmp_path: Path) -> None:
    config = {"TESTING": True, "STORAGE_PATH": str(tmp_path)}
    client = create_app(config).test_client()
    import_file(client, HEADER + EARLY + LATE, "fonte.csv")
    client.post("/previa", data={"arquivo": (BytesIO((HEADER + LATE.replace("Compra", "Pendente")).encode()), "pendente.csv")})
    client = create_app(config).test_client()
    response = client.get("/movimentacoes")
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    assert page.title is not None and page.title.get_text() == "Lastro — Movimentações"
    assert [[cell.get_text(strip=True) for cell in row.select("td")[1:]] for row in page.select("tbody tr")] == [
        ["08/10/2026", "Pagamento", "Compra", "-R$ 1.253,56", "-R$ 19,00"],
        ["01/10/2026", "Crédito B3", "Resgate", "R$ 1.234,56", "R$ 1.234,56"],
    ]
    assert "Saldo após a movimentação" in page.get_text()
    assert "saldo atual" not in page.get_text().lower()
    assert "Pendente" not in page.get_text()


@pytest.mark.parametrize("query, dates", [
    ("inicio=2026-01-01&fim=2026-12-31", ["08/10/2026", "01/10/2026"]),
    ("inicio=2026-10-08&fim=2026-10-08", ["08/10/2026"]),
    ("inicio=2026-10-02", ["08/10/2026"]),
    ("fim=2026-10-01", ["01/10/2026"]),
    ("inicio=&fim=", ["08/10/2026", "01/10/2026"]),
])
def test_date_filter_is_inclusive_and_allows_open_bounds(query: str, dates: list[str]) -> None:
    client = create_app({"TESTING": True}).test_client()
    import_file(client, HEADER + EARLY + LATE, "fonte.csv")
    response = client.get("/movimentacoes?" + query)
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    assert [row.select("td")[1].get_text(strip=True) for row in page.select("tbody tr")] == dates
    form = page.select_one('form[action="/movimentacoes"]')
    assert form is not None and form.get("method") == "get"
    for field in ("inicio", "fim"):
        assert form.select_one(f'input[type="date"][name="{field}"]') is not None
    assert page.select_one('main a[href="/movimentacoes"]') is not None


@pytest.mark.parametrize("query, message", [
    ("inicio=2026-02-30", "Data inicial inválida"),
    ("fim=texto", "Data final inválida"),
    ("inicio=20261001", "Data inicial inválida"),
    ("inicio=2026-10-08&fim=2026-10-01", "A data inicial deve ser anterior ou igual à data final"),
])
def test_invalid_filters_explain_problem_without_showing_unfiltered_results(query: str, message: str) -> None:
    client = create_app({"TESTING": True}).test_client()
    import_file(client, HEADER + EARLY + LATE, "fonte.csv")
    response = client.get("/movimentacoes?" + query)
    assert response.status_code == 422
    page = BeautifulSoup(response.data, "html.parser")
    alert = page.select_one('[role="alert"]')
    assert alert is not None and message in alert.get_text()
    assert not page.select("tbody tr")
    assert "Nenhuma movimentação" not in page.get_text()


def test_empty_history_and_empty_interval_have_distinct_guidance() -> None:
    client = create_app({"TESTING": True}).test_client()
    response = client.get("/movimentacoes")
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    assert "Nenhuma movimentação confirmada" in page.get_text()
    assert page.select_one('main a[href="/"]') is not None
    import_file(client, HEADER + EARLY + LATE, "fonte.csv")
    response = client.get("/movimentacoes?inicio=2026-10-02&fim=2026-10-07")
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    assert "Nenhuma movimentação no intervalo informado" in page.get_text()
    assert "Nenhuma movimentação confirmada" not in page.get_text()
    assert not page.select("tbody tr")
    assert page.select_one('input[name="inicio"][value="2026-10-02"]') is not None
    assert page.select_one('input[name="fim"][value="2026-10-07"]') is not None


def test_each_legitimate_occurrence_lists_all_named_sources_and_original_lines_after_restart(tmp_path: Path) -> None:
    config = {"TESTING": True, "STORAGE_PATH": str(tmp_path)}
    client = create_app(config).test_client()
    first = import_file(client, HEADER + LATE * 2, "primeiro.csv")
    second = import_file(client, HEADER + "\n" + LATE * 3, "sobreposto.csv")
    third = import_file(client, HEADER + "\n\n" + LATE, "registro.csv", keep=True)
    client = create_app(config).test_client()
    page = BeautifulSoup(client.get("/movimentacoes?inicio=2026-10-08&fim=2026-10-08").data, "html.parser")
    rows = page.select("tbody tr")
    assert len(rows) == 3
    for row, expected in zip(rows, [
        {(first, "primeiro.csv — linha 6"), (second, "sobreposto.csv — linha 7"), (third, "registro.csv — linha 8")},
        {(first, "primeiro.csv — linha 7"), (second, "sobreposto.csv — linha 8")},
        {(second, "sobreposto.csv — linha 9")},
    ]):
        assert {(str(link["href"]), link.get_text(strip=True)) for link in row.select("a")} == expected
        assert [cell.get_text(strip=True) for cell in row.select("td")[1:]] == [
            "08/10/2026", "Pagamento", "Compra", "-R$ 1.253,56", "-R$ 19,00",
        ]
        for link in row.select("a"):
            detail = client.get(str(link["href"]))
            assert detail.status_code == 200
            origin = BeautifulSoup(detail.data, "html.parser")
            line = link.get_text().split("linha ")[1]
            assert line in [item.select("td")[0].get_text(strip=True) for item in origin.select("tbody tr")]
