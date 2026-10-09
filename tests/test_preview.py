from io import BytesIO

from bs4 import BeautifulSoup
import pytest

from lastro import create_app


STATEMENT = """ Extrato Conta Corrente ;;;;
Conta ;00012345;;;
Período ;01/10/2026 a 08/10/2026;;;
Saldo ;-19,00;;;
;;;;
Data Lançamento;Histórico;Descrição;Valor;Saldo
07/10/2026;  Crédito B3  ;  Resgate de aplicação  ;1.234,56;1.234,56
08/10/2026;Pagamento;Compra;-1.253,56;-19,00
"""


def test_upload_displays_metadata_and_all_movements() -> None:
    client = create_app({"TESTING": True}).test_client()
    response = client.post(
        "/previa", data={"arquivo": (BytesIO(STATEMENT.encode()), "sintetico.csv")}
    )
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    text = page.get_text(" ", strip=True)
    assert "00012345" in text
    assert "01/10/2026 a 08/10/2026" in text
    assert "Saldo informado: -R$ 19,00" in text
    assert "Saldo após a movimentação" in text
    rows = page.select("tbody tr")
    assert [[cell.get_text(strip=True) for cell in row.select("td")] for row in rows] == [
        ["07/10/2026", "Crédito B3", "Resgate de aplicação", "R$ 1.234,56", "R$ 1.234,56"],
        ["08/10/2026", "Pagamento", "Compra", "-R$ 1.253,56", "-R$ 19,00"],
    ]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("qualquer arquivo", "Formato desconhecido"),
        (STATEMENT.replace("Conta ;00012345;;;\n", ""), "Metadado obrigatório ausente: Conta"),
        (STATEMENT.replace("Período ;01/10/2026 a 08/10/2026;;;\n", ""), "Metadado obrigatório ausente: Período"),
        (STATEMENT.replace("Saldo ;-19,00;;;\n", ""), "Metadado obrigatório ausente: Saldo"),
        (STATEMENT.replace("Data Lançamento;Histórico;Descrição;Valor;Saldo", "Data Lançamento;Histórico;Descrição;Valor"), "Colunas obrigatórias"),
        ("\n".join(STATEMENT.splitlines()[:6]), "Nenhuma movimentação"),
    ],
)
def test_invalid_structure_is_blocked_with_guidance(content: str, message: str) -> None:
    client = create_app({"TESTING": True}).test_client()
    response = client.post("/previa", data={"arquivo": (BytesIO(content.encode()), "sintetico.csv")})
    assert response.status_code == 422
    page = BeautifulSoup(response.data, "html.parser")
    assert message in page.get_text(" ", strip=True)
    assert "Exporte" in page.get_text(" ", strip=True)
    assert "Bloqueada" in page.get_text(" ", strip=True)
    assert not page.select('input[type="checkbox"]')
    assert not page.select('button[name="confirmar"]')


@pytest.mark.parametrize(
    ("original", "replacement", "field", "reason"),
    [
        ("08/10/2026;Pagamento", "31/02/2026;Pagamento", "Data Lançamento", "Data ilegível"),
        ("08/10/2026;Pagamento", "8/10/2026;Pagamento", "Data Lançamento", "Data ilegível"),
        (";Pagamento;Compra;", ";;Compra;", "Histórico", "Campo obrigatório vazio"),
        (";Pagamento;Compra;", ";Pagamento;;", "Descrição", "Campo obrigatório vazio"),
        ("-1.253,56;-19,00", "inválido;-19,00", "Valor", "Valor monetário ilegível"),
        ("-1.253,56;-19,00", "1.25,56;-19,00", "Valor", "Valor monetário ilegível"),
        ("-1.253,56;-19,00", "1,234;-19,00", "Valor", "Valor monetário ilegível"),
        ("-1.253,56;-19,00", "NaN;-19,00", "Valor", "Valor monetário ilegível"),
        ("-1.253,56;-19,00", "1e3;-19,00", "Valor", "Valor monetário ilegível"),
        ("-1.253,56;-19,00", "-1.253,56;", "Saldo", "Campo obrigatório vazio"),
        ("-1.253,56;-19,00", "-1.253,56;abc", "Saldo", "Valor monetário ilegível"),
        ("08/10/2026;Pagamento;Compra;-1.253,56;-19,00", "08/10/2026;Pagamento;Compra;-1.253,56", "Saldo", "Campo obrigatório ausente"),
    ],
)
def test_record_errors_report_original_line_field_and_guidance(
    original: str, replacement: str, field: str, reason: str
) -> None:
    # An extra blank physical line must not renumber the invalid record.
    content = STATEMENT.replace("\n08/10/2026;", "\n\n08/10/2026;").replace(original, replacement)
    response = create_app({"TESTING": True}).test_client().post(
        "/previa", data={"arquivo": (BytesIO(content.encode()), "sintetico.csv")}
    )
    assert response.status_code == 422
    text = BeautifulSoup(response.data, "html.parser").get_text(" ", strip=True)
    assert f"Linha 9 — {field}" in text
    assert reason in text
    assert "Confira" in text


@pytest.mark.parametrize(
    ("original", "replacement", "field"),
    [
        ("01/10/2026 a 08/10/2026", "não é um período", "Período"),
        ("01/10/2026 a 08/10/2026", "08/10/2026 a 01/10/2026", "Período"),
        ("Saldo ;-19,00", "Saldo ;nan", "Saldo"),
    ],
)
def test_invalid_metadata_is_explained(original: str, replacement: str, field: str) -> None:
    response = create_app({"TESTING": True}).test_client().post(
        "/previa", data={"arquivo": (BytesIO(STATEMENT.replace(original, replacement).encode()), "sintetico.csv")}
    )
    assert response.status_code == 422
    text = BeautifulSoup(response.data, "html.parser").get_text(" ", strip=True)
    assert field in text
    assert "ilegível" in text or "invertido" in text


@pytest.mark.parametrize("content", [b"\xff\xfe\x00", b'"aspas sem fechamento', b""])
def test_unreadable_files_have_actionable_errors(content: bytes) -> None:
    response = create_app({"TESTING": True}).test_client().post(
        "/previa", data={"arquivo": (BytesIO(content), "sintetico.csv")}
    )
    assert response.status_code == 422
    text = BeautifulSoup(response.data, "html.parser").get_text(" ", strip=True)
    assert "Exporte" in text
    assert "bloqueada" in text


def test_blank_lines_quoted_fields_and_internal_whitespace_are_preserved() -> None:
    content = STATEMENT.replace("Compra", '"  Compra;  dois espaços\nsegunda linha  "') + "\n;;;;\n"
    response = create_app({"TESTING": True}).test_client().post(
        "/previa", data={"arquivo": (BytesIO(content.encode("utf-8-sig")), "sintetico.csv")}
    )
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    assert page.select("tbody tr")[1].select("td")[2].get_text() == "Compra;  dois espaços\nsegunda linha"


def test_all_errors_are_reported_and_checkbox_cannot_override_them() -> None:
    content = STATEMENT.replace("-1.253,56;-19,00", "abc;def").replace("07/10/2026;", "31/02/2026;")
    response = create_app({"TESTING": True}).test_client().post(
        "/previa", data={"arquivo": (BytesIO(content.encode()), "sintetico.csv"), "ignorar_erros": "on"}
    )
    assert response.status_code == 422
    text = BeautifulSoup(response.data, "html.parser").get_text(" ", strip=True)
    for message in ("Linha 7 — Data Lançamento", "Linha 8 — Valor", "Linha 8 — Saldo"):
        assert message in text


def test_money_is_not_rounded_even_above_decimal_context_precision() -> None:
    content = STATEMENT.replace("1.234,56", "123456789012345678901234567890,12")
    response = create_app({"TESTING": True}).test_client().post(
        "/previa", data={"arquivo": (BytesIO(content.encode()), "sintetico.csv")}
    )
    assert response.status_code == 200
    assert "R$ 123.456.789.012.345.678.901.234.567.890,12" in response.get_data(as_text=True)


def test_metadata_error_does_not_hide_record_errors() -> None:
    content = STATEMENT.replace("Saldo ;-19,00", "Saldo ;ilegível").replace("-1.253,56;-19,00", "abc;def")
    response = create_app({"TESTING": True}).test_client().post(
        "/previa", data={"arquivo": (BytesIO(content.encode()), "sintetico.csv")}
    )
    assert response.status_code == 422
    text = BeautifulSoup(response.data, "html.parser").get_text(" ", strip=True)
    for message in ("Linha 4 — Saldo", "Linha 8 — Valor", "Linha 8 — Saldo"):
        assert message in text


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("07/10/2026;Crédito;Registro antecipado;1,00;1,00\n", "Linha inesperada antes da tabela"),
        ("Conta;99999999;;;\n", "Metadado duplicado: Conta"),
        ("Saldo;-19,00;;;\n", "Metadado duplicado: Saldo"),
    ],
)
def test_unexpected_and_duplicate_metadata_cannot_be_silently_discarded(extra: str, message: str) -> None:
    content = STATEMENT.replace("Data Lançamento;", extra + "Data Lançamento;")
    response = create_app({"TESTING": True}).test_client().post(
        "/previa", data={"arquivo": (BytesIO(content.encode()), "sintetico.csv")}
    )
    assert response.status_code == 422
    text = BeautifulSoup(response.data, "html.parser").get_text(" ", strip=True)
    assert message in text
    assert "Linha 6" in text


def test_four_digit_year_is_preserved_in_metadata_and_movements() -> None:
    response = create_app({"TESTING": True}).test_client().post(
        "/previa", data={"arquivo": (BytesIO(STATEMENT.replace("2026", "0001").encode()), "sintetico.csv")}
    )
    assert response.status_code == 200
    text = BeautifulSoup(response.data, "html.parser").get_text(" ", strip=True)
    assert "01/10/0001 a 08/10/0001" in text
    assert "07/10/0001" in text


def test_empty_field_does_not_hide_other_errors_in_same_record() -> None:
    content = STATEMENT.replace("08/10/2026;Pagamento;Compra;-1.253,56;-19,00", "31/02/2026;;Compra;abc;def")
    response = create_app({"TESTING": True}).test_client().post(
        "/previa", data={"arquivo": (BytesIO(content.encode()), "sintetico.csv")}
    )
    assert response.status_code == 422
    text = BeautifulSoup(response.data, "html.parser").get_text(" ", strip=True)
    for field in ("Data Lançamento", "Histórico", "Valor", "Saldo"):
        assert f"Linha 8 — {field}" in text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("-19", "-R$ 19,00"),
        ("-51,8", "-R$ 51,80"),
        ("-24,9", "-R$ 24,90"),
        ("-6", "-R$ 6,00"),
        ("123", "R$ 123,00"),
        ("123,4", "R$ 123,40"),
        ("123,45", "R$ 123,45"),
        ("0", "R$ 0,00"),
        ("0,1", "R$ 0,10"),
        ("-0,1", "-R$ 0,10"),
        ("+19", "R$ 19,00"),
        ("  -19  ", "-R$ 19,00"),
        ("1.234", "R$ 1.234,00"),
        ("1.234,5", "R$ 1.234,50"),
        ("1.234,56", "R$ 1.234,56"),
        ("-1.234,5", "-R$ 1.234,50"),
    ],
)
def test_preview_accepts_zero_one_or_two_decimal_places_in_all_money_fields(
    value: str, expected: str
) -> None:
    content = f"""Extrato Conta Corrente;;;;
Conta;00012345;;;
Período;01/10/2026 a 08/10/2026;;;
Saldo;{value};;;
Data Lançamento;Histórico;Descrição;Valor;Saldo
07/10/2026;Pix enviado;Exemplo sintético;{value};{value}
"""
    response = create_app({"TESTING": True}).test_client().post(
        "/previa", data={"arquivo": (BytesIO(content.encode()), "sintetico.csv")}
    )
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    assert f"Saldo informado: {expected}" in page.get_text(" ", strip=True)
    assert [[cell.get_text(strip=True) for cell in row.select("td")] for row in page.select("tbody tr")] == [
        ["07/10/2026", "Pix enviado", "Exemplo sintético", expected, expected]
    ]
    assert "Bloqueada" not in page.get_text()


@pytest.mark.parametrize(
    "value",
    ["1,234", "1.23", "1.23,4", "1.234,", "19,", ",5", "1e3", "NaN", "1,2,3", "1.234.56", "++19", "19 00"],
)
def test_optional_decimal_places_do_not_allow_malformed_money_or_rounding(value: str) -> None:
    content = f"""Extrato Conta Corrente;;;;
Conta;00012345;;;
Período;01/10/2026 a 08/10/2026;;;
Saldo;{value};;;
Data Lançamento;Histórico;Descrição;Valor;Saldo
07/10/2026;Pix enviado;Exemplo sintético;{value};{value}
"""
    response = create_app({"TESTING": True}).test_client().post(
        "/previa", data={"arquivo": (BytesIO(content.encode()), "sintetico.csv")}
    )
    assert response.status_code == 422
    page = BeautifulSoup(response.data, "html.parser")
    text = page.get_text(" ", strip=True)
    for message in ("Linha 4 — Saldo", "Linha 6 — Valor", "Linha 6 — Saldo"):
        assert message in text
    assert "use um número inteiro ou vírgula com uma ou duas casas decimais" in text
    assert not page.select("tbody tr")
