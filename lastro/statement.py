import csv
import re
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from io import StringIO


@dataclass(frozen=True)
class Movement:
    date: date
    history: str
    description: str
    amount: Decimal
    balance: Decimal


@dataclass(frozen=True)
class Statement:
    account: str
    start: date
    end: date
    balance: Decimal
    movements: list[Movement]


COLUMNS = ["Data Lançamento", "Histórico", "Descrição", "Valor", "Saldo"]
GUIDANCE = "Exporte novamente o extrato de conta corrente no formato CSV suportado, sem editar sua estrutura."


@dataclass(frozen=True)
class Problem:
    reason: str
    guidance: str = GUIDANCE
    line: int | None = None
    field: str | None = None


@dataclass
class Preview:
    statement: Statement | None = None
    problems: list[Problem] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=lambda: {
        "Formato CSV reconhecido": False,
        "Metadados de conta, período e saldo": False,
        "Colunas obrigatórias": False,
        "Presença de movimentações": False,
        "Campos, datas e valores das movimentações": False,
    })


def brazilian_date(value: str) -> date:
    if not re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}", value.strip()):
        raise ValueError("Data ilegível; use DD/MM/AAAA.")
    return datetime.strptime(value.strip(), "%d/%m/%Y").date()


def money(value: str) -> Decimal:
    if not re.fullmatch(r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+),[0-9]{2}", value.strip()):
        raise ValueError("Valor monetário ilegível; use vírgula e duas casas decimais.")
    return Decimal(value.strip().replace(".", "").replace(",", "."))


def read_statement(content: bytes) -> Preview:
    result = Preview()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        result.problems.append(Problem("Codificação ilegível: esperado CSV UTF-8.", "Exporte novamente como CSV UTF-8 (com ou sem BOM)."))
        return result
    reader = csv.reader(StringIO(text, newline=""), delimiter=";", strict=True)
    rows: list[tuple[int, list[str]]] = []
    previous_line = 0
    try:
        for row in reader:
            line = previous_line + 1
            previous_line = reader.line_num
            if any(value.strip() for value in row):
                rows.append((line, [value.strip() for value in row]))
    except csv.Error:
        result.problems.append(Problem("Estrutura CSV ilegível: aspas ou separadores inválidos.", line=previous_line + 1, field="Registro"))
        return result
    if not rows or rows[0][1][0] != "Extrato Conta Corrente":
        result.problems.append(Problem("Formato desconhecido: esperado extrato de conta corrente separado por ponto e vírgula."))
        return result
    result.checks["Formato CSV reconhecido"] = True
    header = next((i for i, (_, row) in enumerate(rows) if row[0] == "Data Lançamento"), None)
    if header is None or rows[header][1] != COLUMNS:
        result.problems.append(Problem("Colunas obrigatórias ausentes ou diferentes: " + ", ".join(COLUMNS) + "."))
        return result
    result.checks["Colunas obrigatórias"] = True
    metadata: dict[str, tuple[int, str]] = {}
    for line, row in rows[1:header]:
        name = row[0]
        if name not in ("Conta", "Período", "Saldo"):
            result.problems.append(Problem("Linha inesperada antes da tabela; formato desconhecido.", line=line, field="Registro"))
        elif name in metadata:
            result.problems.append(Problem(f"Metadado duplicado: {name}.", line=line, field=name))
        elif len(row) < 2 or any(row[2:]):
            result.problems.append(Problem("Estrutura do metadado inválida: esperado rótulo e valor.", line=line, field=name))
        else:
            metadata[name] = (line, row[1])
    for name in ("Conta", "Período", "Saldo"):
        if name not in metadata or not metadata[name][1]:
            result.problems.append(Problem(f"Metadado obrigatório ausente: {name}."))
    start = end = None
    balance = None
    if "Período" in metadata and metadata["Período"][1]:
        try:
            start_text, end_text = metadata["Período"][1].split(" a ")
            start, end = brazilian_date(start_text), brazilian_date(end_text)
            if start > end:
                result.problems.append(Problem("Período invertido: início posterior ao fim.", line=metadata["Período"][0], field="Período"))
        except ValueError:
            result.problems.append(Problem("Período ilegível; esperado DD/MM/AAAA a DD/MM/AAAA.", line=metadata["Período"][0], field="Período"))
    if "Saldo" in metadata and metadata["Saldo"][1]:
        try:
            balance = money(metadata["Saldo"][1])
        except ValueError as error:
            result.problems.append(Problem(str(error), line=metadata["Saldo"][0], field="Saldo"))
    result.checks["Metadados de conta, período e saldo"] = not result.problems
    if not rows[header + 1:]:
        result.problems.append(Problem("Nenhuma movimentação encontrada no extrato."))
    else:
        result.checks["Presença de movimentações"] = True
    movements: list[Movement] = []
    record_problems_before = len(result.problems)
    for line, row in rows[header + 1:]:
        problems_before = len(result.problems)
        for i, name in enumerate(COLUMNS):
            if i >= len(row):
                result.problems.append(Problem("Campo obrigatório ausente.", "Confira a linha no arquivo original e exporte novamente com as cinco colunas.", line, name))
            elif not row[i]:
                result.problems.append(Problem("Campo obrigatório vazio.", "Confira o campo no arquivo original e exporte novamente o extrato completo.", line, name))
        if len(row) > len(COLUMNS):
            result.problems.append(Problem("Colunas extras na movimentação.", "Confira o separador ponto e vírgula e as aspas dos campos no arquivo original.", line, "Registro"))
        movement_date = None
        if row[0]:
            try:
                movement_date = brazilian_date(row[0])
            except ValueError:
                result.problems.append(Problem("Data ilegível ou inexistente.", "Confira a data no arquivo original; esperado DD/MM/AAAA.", line, "Data Lançamento"))
        amounts: dict[str, Decimal] = {}
        for name, value in zip(("Valor", "Saldo"), row[3:5]):
            if not value:
                continue
            try:
                amounts[name] = money(value)
            except ValueError as error:
                result.problems.append(Problem(str(error), "Confira o valor no arquivo original; exemplo válido: -1.234,56.", line, name))
        if len(result.problems) == problems_before and movement_date is not None:
            movements.append(Movement(movement_date, row[1], row[2], amounts["Valor"], amounts["Saldo"]))
    result.checks["Campos, datas e valores das movimentações"] = bool(movements) and len(result.problems) == record_problems_before
    if result.checks["Metadados de conta, período e saldo"] and start is not None and end is not None and balance is not None:
        result.statement = Statement(metadata["Conta"][1], start, end, balance, movements)
    return result


def format_money(value: Decimal) -> str:
    formatted = f"{value.copy_abs():,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{'-' if value < 0 else ''}R$ {formatted}"


def format_date(value: date) -> str:
    return f"{value.day:02d}/{value.month:02d}/{value.year:04d}"
