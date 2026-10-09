"""Repeatable browser check using only synthetic financial data."""

from pathlib import Path
from threading import Thread
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from lastro import create_app


SAMPLE = """Extrato Conta Corrente;;;;
Conta;00012345;;;
Período;01/10/2026 a 08/10/2026;;;
Saldo;-19,00;;;
;;;;
Data Lançamento;Histórico;Descrição;Valor;Saldo
07/10/2026;  Crédito B3  ;  Resgate de aplicação  ;1.234,56;1.234,56
08/10/2026;Pagamento;Compra de exemplo;-1.253,56;-19,00
"""


def main() -> None:
    output = Path("/tmp/opencode/lastro-browser")
    output.mkdir(parents=True, exist_ok=True)
    storage = TemporaryDirectory(prefix="lastro-browser-", dir="/tmp/opencode")
    server = make_server("127.0.0.1", 0, create_app({"STORAGE_PATH": storage.name}))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1050})
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base_url)
            page.get_by_role("link", name="Importações", exact=True).click()
            expect(page).to_have_title("Lastro — Importações")
            expect(page.get_by_text("Nenhuma importação confirmada.")).to_be_visible()
            page.screenshot(path=str(output / "desktop-imports-empty.png"), full_page=True)
            page.get_by_role("link", name="Enviar um extrato").click()
            page.wait_for_load_state("load")
            assert page.evaluate("typeof htmx") == "object"
            assert page.get_by_role("button", name="Conferir prévia").evaluate("element => getComputedStyle(element).backgroundColor") != "rgba(0, 0, 0, 0)"
            page.locator("#arquivo").set_input_files({"name": "sintetico.csv", "mimeType": "text/csv", "buffer": SAMPLE.encode()})
            with page.expect_response(lambda response: response.url.endswith("/previa")) as response:
                page.get_by_role("button", name="Conferir prévia").click()
            assert response.value.request.headers.get("hx-request") == "true"
            assert page.url == base_url + "/"
            expect(page.locator("tbody tr")).to_have_count(2)
            expect(page.get_by_text("Saldo informado:")).to_contain_text("-R$ 19,00")
            expect(page.locator('input[name="reconhecer_avisos"]')).to_have_count(0)
            expect(page.get_by_role("columnheader", name="Saldo após a movimentação")).to_be_visible()
            page.screenshot(path=str(output / "desktop-preview.png"), full_page=True)
            page.set_viewport_size({"width": 375, "height": 812})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            expect(page.get_by_role("button", name="Cancelar prévia")).to_be_visible()
            page.screenshot(path=str(output / "mobile-preview.png"), full_page=True)
            page.get_by_role("button", name="Cancelar prévia").click()
            expect(page.locator("tbody tr")).to_have_count(0)
            variable_decimals = SAMPLE.replace("Saldo;-19,00", "Saldo;-19").replace("1.234,56;1.234,56", "-19;1.234,5").replace("-1.253,56;-19,00", "-51,8;1.313")
            page.locator("#arquivo").set_input_files({"name": "casas-variaveis.csv", "mimeType": "text/csv", "buffer": variable_decimals.encode()})
            page.get_by_role("button", name="Conferir prévia").click()
            expect(page.locator("tbody tr")).to_have_count(2)
            expect(page.locator("tbody tr").nth(0).locator("td").nth(3)).to_have_text("-R$ 19,00")
            expect(page.locator("tbody tr").nth(0).locator("td").nth(4)).to_have_text("R$ 1.234,50")
            expect(page.locator("tbody tr").nth(1).locator("td").nth(3)).to_have_text("-R$ 51,80")
            expect(page.locator("tbody tr").nth(1).locator("td").nth(4)).to_have_text("R$ 1.313,00")
            expect(page.get_by_text("Saldo informado:")).to_contain_text("-R$ 19,00")
            review = page.get_by_role("checkbox", name="Reconheço o aviso:")
            expect(review).not_to_be_checked()
            page.get_by_role("button", name="Confirmar importação").click()
            expect(page.get_by_role("heading", name="Prévia do extrato")).to_be_visible()
            assert review.evaluate("element => element.validity.valueMissing")
            page.screenshot(path=str(output / "mobile-variable-decimals.png"), full_page=True)
            page.locator("#arquivo").set_input_files({"name": "invalido.csv", "mimeType": "text/csv", "buffer": SAMPLE.replace("-1.253,56", "inválido").encode()})
            page.get_by_role("button", name="Conferir prévia").click()
            expect(page.get_by_role("heading", name="Prévia bloqueada")).to_be_visible()
            expect(page.get_by_text("Linha 8 — Valor:")).to_be_visible()
            expect(page.locator('input[type="checkbox"]')).to_have_count(0)
            page.screenshot(path=str(output / "mobile-errors.png"), full_page=True)
            assert not errors, errors
            context.close()
            no_js = browser.new_context(java_script_enabled=False)
            page = no_js.new_page()
            page.goto(base_url)
            page.locator("#arquivo").set_input_files({"name": "sintetico.csv", "mimeType": "text/csv", "buffer": SAMPLE.encode()})
            page.get_by_role("button", name="Conferir prévia").click()
            expect(page.locator("tbody tr")).to_have_count(2)
            assert page.url.endswith("/previa")
            page.get_by_role("button", name="Cancelar prévia").click()
            expect(page.locator("tbody tr")).to_have_count(0)
            page.locator("#arquivo").set_input_files({"name": "sintetico.csv", "mimeType": "text/csv", "buffer": SAMPLE.encode()})
            page.get_by_role("button", name="Conferir prévia").click()
            page.get_by_role("button", name="Confirmar importação").click()
            expect(page.get_by_role("heading", name="Importação confirmada")).to_be_visible()
            expect(page.locator("tbody tr")).to_have_count(2)
            expect(page.get_by_text("2 novas · 0 já existentes")).to_be_visible()
            detail_url = page.url
            no_js.close()
            context = browser.new_context(viewport={"width": 1440, "height": 1050})
            page = context.new_page()
            page.goto(detail_url)
            page.screenshot(path=str(output / "desktop-confirmed.png"), full_page=True)
            with page.expect_download() as download:
                page.get_by_role("link", name="Baixar CSV original").click()
            downloaded = download.value.path()
            assert downloaded is not None and Path(downloaded).read_bytes() == SAMPLE.encode()
            page.set_viewport_size({"width": 375, "height": 812})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(output / "mobile-confirmed.png"), full_page=True)
            page.get_by_role("link", name="Importações", exact=True).click()
            expect(page.get_by_role("link", name="sintetico.csv")).to_be_visible()
            page.get_by_role("link", name="sintetico.csv").click()
            expect(page).to_have_url(detail_url)
            page.get_by_role("link", name="Voltar para Importações").click()
            expect(page).to_have_title("Lastro — Importações")
            page.goto(base_url)
            expect(page.get_by_text("Conta vinculada: 00012345.")).to_be_visible()
            overlapping = SAMPLE + "08/10/2026;Crédito;Transferência;5,00;-14,00\n"
            page.locator("#arquivo").set_input_files({"name": "sobreposto.csv", "mimeType": "text/csv", "buffer": overlapping.encode()})
            page.get_by_role("button", name="Conferir prévia").click()
            expect(page.get_by_text("1 novas · 2 já existentes.")).to_be_visible()
            expect(page.get_by_text("Sobreposição de períodos:")).to_be_visible()
            page.screenshot(path=str(output / "mobile-overlap.png"), full_page=True)
            page.get_by_role("button", name="Confirmar importação").click()
            expect(page.locator("tbody tr")).to_have_count(3)
            page.get_by_role("link", name="Movimentações", exact=True).click()
            expect(page.locator("tbody tr")).to_have_count(3)
            expect(page.locator("tbody tr").first.locator("a")).to_have_count(2)
            page.goto(base_url)
            page.locator("#arquivo").set_input_files({"name": "registro.csv", "mimeType": "text/csv", "buffer": (SAMPLE + "\n").encode()})
            page.get_by_role("button", name="Conferir prévia").click()
            expect(page.get_by_text("0 novas · 2 já existentes.")).to_be_visible()
            consent = page.get_by_role("checkbox", name="Guardar este extrato apenas para registro")
            expect(consent).not_to_be_checked()
            page.get_by_role("button", name="Confirmar importação").click()
            expect(page.get_by_role("heading", name="Prévia do extrato")).to_be_visible()
            page.screenshot(path=str(output / "mobile-zero-new.png"), full_page=True)
            consent.check()
            page.get_by_role("button", name="Confirmar importação").click()
            expect(page.get_by_text("0 novas · 2 já existentes")).to_be_visible()
            expect(page.locator("tbody tr")).to_have_count(2)
            page.screenshot(path=str(output / "mobile-zero-new-confirmed.png"), full_page=True)
            page.get_by_role("link", name="Voltar para Importações").click()
            expect(page.get_by_role("link", name="registro.csv")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(output / "mobile-imports.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1050})
            page.screenshot(path=str(output / "desktop-imports.png"), full_page=True)
            page.get_by_role("link", name="sobreposto.csv").click()
            expect(page.locator("tbody tr")).to_have_count(3)
            expect(page.get_by_text("1 novas · 2 já existentes")).to_be_visible()
            page.screenshot(path=str(output / "desktop-overlapping-import.png"), full_page=True)
            page.set_viewport_size({"width": 375, "height": 812})
            response_missing = page.goto(base_url + "/importacoes/inexistente")
            assert response_missing is not None and response_missing.status == 404
            expect(page.get_by_role("heading", name="Importação não encontrada")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(output / "mobile-import-missing.png"), full_page=True)
            page.get_by_role("link", name="Voltar para Importações").click()
            expect(page.get_by_role("link", name="sintetico.csv")).to_be_visible()
            page.goto(base_url)
            page.locator("#arquivo").set_input_files({"name": "identico.csv", "mimeType": "text/csv", "buffer": SAMPLE.encode()})
            page.get_by_role("button", name="Conferir prévia").click()
            expect(page).to_have_url(detail_url)
            page.goto(base_url)
            divergent = SAMPLE.replace("-1.253,56;-19,00", "-1.253,56;-25,00")
            page.locator("#arquivo").set_input_files({"name": "divergente.csv", "mimeType": "text/csv", "buffer": divergent.encode()})
            with page.expect_response(lambda response: response.url.endswith("/previa")) as response:
                page.get_by_role("button", name="Conferir prévia").click()
            assert response.value.request.headers.get("hx-request") == "true"
            reviews = page.locator('input[name="reconhecer_avisos"]')
            expect(reviews).to_have_count(2)
            expect(reviews.nth(0)).not_to_be_checked()
            expect(reviews.nth(1)).not_to_be_checked()
            expect(page.get_by_role("link", name="Consultar importação anterior")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(output / "mobile-warnings.png"), full_page=True)
            reviews.nth(0).check()
            page.get_by_role("button", name="Confirmar importação").click()
            expect(page.get_by_role("heading", name="Prévia do extrato")).to_be_visible()
            reviews.nth(1).check()
            page.get_by_role("button", name="Confirmar importação").click()
            expect(page.get_by_role("heading", name="Importação confirmada")).to_be_visible()
            expect(page.locator("tbody tr").nth(1).locator("td").last).to_have_text("-R$ 25,00")
            page.goto(base_url)
            page.locator("#arquivo").set_input_files({"name": "outra-conta.csv", "mimeType": "text/csv", "buffer": SAMPLE.replace("00012345", "99999999").encode()})
            page.get_by_role("button", name="Conferir prévia").click()
            expect(page.get_by_text("Conta diferente da conta vinculada (00012345).")).to_be_visible()
            expect(page.get_by_role("button", name="Confirmar importação")).to_have_count(0)
            assert not errors, errors
            context.close()
            browser.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
        storage.cleanup()
    print(f"Browser checks passed. Synthetic screenshots: {output}")


if __name__ == "__main__":
    main()
