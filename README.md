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
4. **Cancelar prévia** descarta a prévia sem incorporar histórico ou vincular conta.
5. **Confirmar importação** guarda as ocorrências novas e o CSV original, vincula
   a conta na primeira confirmação e abre o comprovante. Repetir a confirmação
   retorna o mesmo resultado.
6. Consulte o comprovante em **Importações** ou os registros em **Movimentações**.
   O comprovante informa as linhas de origem e permite baixar o CSV intacto.

As prévias são temporárias, mantidas em memória no servidor, sem dados financeiros
em cookies. Ao encerrar a aplicação, prévias não confirmadas são descartadas;
envie o arquivo novamente. As respostas não são armazenáveis em cache. Os
formulários funcionam sem JavaScript; HTMX atualiza a região da prévia no upload.

Novos extratos da conta vinculada são permitidos; outras contas são bloqueadas.
A prévia informa quantidades novas e já existentes e sobreposição de períodos,
que não é um erro. A comparação usa conta, data, histórico, descrição, valor e
saldo interpretados, preservando a quantidade de ocorrências idênticas. Campos
diferentes podem gerar registros novos; registros anteriores não são sobrescritos.
Todas as linhas ficam vinculadas às ocorrências correspondentes, e uma
movimentação pode ter origem em vários extratos.

Um CSV com bytes idênticos abre a importação anterior, sem nova cópia. Um arquivo
diferente sem movimentações novas só é guardado se você marcar **Guardar este
extrato apenas para registro**. A confirmação reavalia o histórico; se outra
importação deixou a prévia sem novidades, esse consentimento será solicitado.
Avisos de divergências de saldo e filtros de consulta pertencem aos próximos tickets.

### Armazenamento e falhas

A aplicação cria automaticamente `instance/lastro.sqlite3` e `instance/originals/`,
fora do Git. Para escolher outro local, defina `LASTRO_STORAGE_PATH` antes de
executar. Reabra com o mesmo armazenamento para consultar o histórico. Para backup,
encerre a aplicação e copie a pasta inteira, incluindo banco e originais.

Uma transação SQLite serializa a confirmação: o original é gravado e sincronizado
em disco antes de confirmar os registros. Falhas revertem os registros e não
vinculam conta; a prévia permite tentar novamente. Uma falha no commit ou interrupção pode
deixar um CSV sem referência, mas nunca o apresenta como importação confirmada.
Não mova ou apague arquivos do armazenamento manualmente.

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

Datas usam `DD/MM/AAAA`; valores aceitam números inteiros ou vírgula com uma ou
duas casas decimais, com ponto de milhar opcional. Por exemplo, `-19`, `-51,8` e
`1.234,56` são aceitos e exibidos como `-R$ 19,00`, `-R$ 51,80` e `R$ 1.234,56`.
Isso vale para Valor, Saldo após a movimentação e saldo informado nos metadados.
Mais de duas casas decimais são rejeitadas, sem arredondamento automático.
Entradas, saídas e saldos negativos são válidos. Histórico e
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
layout em desktop e celular, além de sobreposição, origens compartilhadas,
redirecionamento de arquivo idêntico e consentimento para zero novas.
Salva capturas **sintéticas** em
`/tmp/opencode/lastro-browser/` para inspeção visual. Em ambientes sem bibliotecas
de sistema do Chromium, instale-as conforme as instruções do Playwright.
