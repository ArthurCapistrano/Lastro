# Lastro
Organização, Autonomia, Segurança e Gestão financeira

## Executar localmente

Requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 20+ e npm.
O Node é usado somente para compilar o CSS do Tailwind e copiar o HTMX; não há
frontend separado, CDN nem necessidade de acesso à internet durante o uso.

```sh
make setup
make run
```

Abra **http://127.0.0.1:5000**. Para encerrar, use `Ctrl+C` no terminal.
Sem `make`, execute `uv sync --locked`, `npm ci`, `npm run build` e
`uv run python -m lastro` nessa ordem.

O servidor escuta somente em `127.0.0.1`, sem debug. A aplicação também rejeita
requisições de endereços não loopback e hosts diferentes de localhost/loopback.
Não exponha o servidor por proxy, túnel ou rede. Não há login: a conta do sistema
operacional é o limite de acesso assumido.

## Conferir um extrato

1. Selecione um CSV e clique em **Conferir prévia**.
2. Confira conta, período, saldo informado, checklist e movimentações.
3. Se houver erros, veja a linha original, o campo, o motivo e a orientação.
   Nenhum erro pode ser ignorado por checkbox.
4. **Cancelar prévia** volta ao início. Nada é gravado, inclusive após uma
   leitura válida. A confirmação persistente pertence ao próximo ticket.

O upload é lido em memória, sem guardar o arquivo, criar banco de dados, vincular
conta ou manter informações na sessão. As respostas não são armazenáveis em
cache. O formulário funciona sem JavaScript; HTMX atualiza só a região da prévia
quando disponível.

### Formato suportado

CSV UTF-8 (com ou sem BOM), separado por ponto e vírgula, com este bloco inicial
e estas colunas, na ordem indicada. Linhas vazias são permitidas. Exemplo
**inteiramente sintético**:

```text
Extrato Conta Corrente;;;;
Conta;00012345;;;
Período;01/10/2026 a 08/10/2026;;;
Saldo;-19,00;;;
;;;;
Data Lançamento;Histórico;Descrição;Valor;Saldo
07/10/2026;Crédito B3;Resgate de aplicação;1.234,56;1.234,56
08/10/2026;Pagamento;Compra;-1.253,56;-19,00
```

Datas usam `DD/MM/AAAA`; valores usam vírgula e duas casas decimais, com ponto
de milhar opcional. Entradas, saídas e saldos negativos são válidos. Histórico e
descrição permanecem separados; só os espaços nas extremidades são removidos.
O saldo de cada linha é apresentado como **Saldo após a movimentação**, sem
categorização ou interpretação como gasto/rendimento. O limite da requisição de
upload, incluindo o formulário, é de 10 MiB.

## Privacidade e Git

Não versione extratos pessoais nem os publique em Issues, logs ou capturas.
Arquivos `*.csv`, bancos locais e `instance/` estão ignorados. Os testes usam
somente amostras sintéticas construídas em Python. O arquivo pessoal usado como
referência local não é necessário para executar a aplicação ou os testes.

## Verificação

```sh
make typecheck
make test
make browser-install
make browser-check
```

Os testes usam a interface HTTP pública do Flask, sem consultas internas ao
banco. A conferência adicional usa Chromium/Playwright com um servidor loopback
temporário: verifica HTMX, erros, cancelamento, funcionamento sem JavaScript e
layout em desktop e celular. Salva capturas **sintéticas** em
`/tmp/opencode/lastro-browser/` para inspeção visual. Em ambientes sem bibliotecas
de sistema do Chromium, instale-as conforme as instruções do Playwright.
