from io import BytesIO

from bs4 import BeautifulSoup, Tag
import pytest

from lastro import create_app


SAMPLE = """Extrato Conta Corrente;;;;
Conta;99900001;;;
Período;01/10/2026 a 08/10/2026;;;
Saldo;0,10;;;
Data Lançamento;Histórico;Descrição;Valor;Saldo
07/10/2026;Crédito;Exemplo sintético;0,10;0,10
"""


def test_upload_cancel_and_reopen_do_not_keep_preview_or_bind_account() -> None:
    client = create_app({"TESTING": True}).test_client()
    response = client.post("/previa", data={"arquivo": (BytesIO(SAMPLE.encode()), "sintetico.csv")})
    page = BeautifulSoup(response.data, "html.parser")
    cancel = page.find("a", string="Cancelar prévia")
    assert isinstance(cancel, Tag)
    assert cancel.get("href") == "/"
    assert "Nada foi gravado" in page.get_text()
    assert "1 movimentação" in page.get_text()
    assert "Set-Cookie" not in response.headers
    for fresh_client in (client, create_app({"TESTING": True}).test_client()):
        home = fresh_client.get("/")
        assert "99900001" not in home.get_data(as_text=True)
        assert not BeautifulSoup(home.data, "html.parser").select("tbody tr")
        other = fresh_client.post("/previa", data={"arquivo": (BytesIO(SAMPLE.replace("99900001", "99900002").encode()), "outra.csv")})
        assert other.status_code == 200
        assert "99900002" in other.get_data(as_text=True)


@pytest.mark.parametrize("data", [{}, {"arquivo": (BytesIO(b""), "")}])
def test_missing_upload_has_guidance(data: dict[str, object]) -> None:
    response = create_app({"TESTING": True}).test_client().post("/previa", data=data)
    assert response.status_code == 422
    assert "Selecione um arquivo CSV" in response.get_data(as_text=True)


def test_upload_size_limit_is_explained() -> None:
    client = create_app({"TESTING": True, "MAX_CONTENT_LENGTH": 100}).test_client()
    response = client.post("/previa", data={"arquivo": (BytesIO(SAMPLE.encode()), "sintetico.csv")})
    assert response.status_code == 413
    assert "Arquivo muito grande" in response.get_data(as_text=True)


def test_htmx_returns_only_the_preview_region_and_does_not_cache_financial_data() -> None:
    client = create_app({"TESTING": True}).test_client()
    response = client.post("/previa", headers={"HX-Request": "true"}, data={"arquivo": (BytesIO(SAMPLE.encode()), "sintetico.csv")})
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    assert page.find(id="resultado")
    assert page.find("html") is None
    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.parametrize("address", ["192.168.1.2", "203.0.113.1"])
def test_non_loopback_requests_are_rejected(address: str) -> None:
    response = create_app({"TESTING": True}).test_client().get("/", environ_overrides={"REMOTE_ADDR": address})
    assert response.status_code == 403


def test_dns_rebinding_host_is_rejected() -> None:
    response = create_app({"TESTING": True}).test_client().get("/", base_url="http://externo.example")
    assert response.status_code == 400
