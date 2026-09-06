"""Regras de leitura, limpeza e análise. Não depende de navegador ou Flask."""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

ZERO = Decimal(0)
Cell = str | int | float | bool | None
Matrix = list[list[Cell]]


def normalize(value: Any) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(value if value is not None else "")) if not unicodedata.combining(c)).lower().strip()


def empty(value: Any) -> bool:
    return value is None or isinstance(value, str) and not value.strip()


def number_value(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        result = Decimal(str(value))
        return result if result.is_finite() else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"^(R\$|US\$|\$|€|£)\s*", "", value.strip())
    text = re.sub(r"\s", "", text)
    if re.fullmatch(r"\(.*\)", text):
        text = "-" + text[1:-1]
    if not re.fullmatch(r"[+-]?\d[\d.,]*%?", text):
        return None
    percent = text.endswith("%")
    text = text.removesuffix("%")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        text = text.replace(",", "") if re.fullmatch(r"[+-]?\d{1,3}(,\d{3}){2,}", text) else text.replace(",", ".")
    elif re.fullmatch(r"[+-]?\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        result = Decimal(text)
        return result / 100 if percent else result
    except InvalidOperation:
        return None


def date_value(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    text = value.strip()
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:T.*)?", text)
    br = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    try:
        if iso:
            return date(*map(int, iso.groups())).isoformat()
        if br:
            day, month, year = map(int, br.groups())
            return date(year, month, day).isoformat()
    except ValueError:
        pass
    return None


@dataclass(frozen=True)
class Rules:
    trim: bool = True
    deduplicate: bool = False


@dataclass
class Column:
    index: int
    name: str
    kind: str
    missing: int


@dataclass
class Dataset:
    columns: list[Column]
    rows: Matrix
    header: int
    empty_rows: int
    duplicates: int
    removed: int
    missing: int

    @property
    def completeness(self) -> float:
        cells = len(self.rows) * len(self.columns)
        return 100 * (1 - self.missing / cells) if cells else 0


@dataclass
class Mapping:
    metric: int = -1
    group: int = -1
    date: int = -1
    type: int = -1
    mode: str = "general"
    currency: bool = False


@dataclass
class Filters:
    search: str = ""
    category: str = ""
    start: str = ""
    end: str = ""


def detect_header(matrix: Matrix) -> int:
    best, score = 0, -1.0
    for i, row in enumerate(matrix[:30]):
        filled = [v for v in row if not empty(v)]
        strings = sum(isinstance(v, str) and number_value(v) is None and date_value(v) is None for v in filled)
        following = matrix[i + 1:i + 5]
        density = sum(sum(not empty(v) for v in r) for r in following) / len(following) if following else 0
        candidate = len(filled) + strings * .8 + min(density, len(filled)) * .3 - i * .12
        if candidate > score:
            best, score = i, candidate
    return best


def prepare(matrix: Matrix, header: int = 0, rules: Rules = Rules()) -> Dataset:
    if not matrix or not 0 <= header < min(30, len(matrix)):
        raise ValueError("Escolha uma linha de cabeçalho válida.")
    width = max(map(len, matrix[header:]), default=0)
    used, names = set(), []
    for i in range(width):
        base = str(matrix[header][i] if i < len(matrix[header]) and not empty(matrix[header][i]) else f"Coluna {i + 1}").strip()
        name, suffix = base, 2
        while name in used:
            name, suffix = f"{base} ({suffix})", suffix + 1
        used.add(name)
        names.append(name)
    seen, rows = set(), []
    blank = duplicates = removed = 0
    for source in matrix[header + 1:]:
        row = [source[i] if i < len(source) else None for i in range(width)]
        if rules.trim:
            row = [v.strip() if isinstance(v, str) else v for v in row]
        if all(empty(v) for v in row):
            blank += 1
            continue
        key = json.dumps(row, ensure_ascii=False, default=str)
        if key in seen:
            duplicates += 1
            if rules.deduplicate:
                removed += 1
                continue
        seen.add(key)
        rows.append(row)
    columns = []
    for i, name in enumerate(names):
        values = [r[i] for r in rows if not empty(r[i])]
        sample = values[:1000]
        identifier = bool(re.search(r"\b(id|codigo|cep|cpf|cnpj|telefone|sku|matricula)\b", normalize(name))) or any(isinstance(v, str) and re.fullmatch(r"0\d+", v) for v in sample)
        kind = "text"
        if sample and sum(date_value(v) is not None for v in sample) / len(sample) >= .8:
            kind = "date"
        elif sample and not identifier and sum(number_value(v) is not None for v in sample) / len(sample) >= .8:
            kind = "number"
        columns.append(Column(i, name, kind, len(rows) - len(values)))
    return Dataset(columns, rows, header, blank, duplicates, removed, sum(c.missing for c in columns))


def direction(value: Any) -> int:
    word = normalize(value)
    if word in {"receita", "receitas", "entrada", "entradas", "credito", "income", "revenue", "credit"}:
        return 1
    if word in {"despesa", "despesas", "saida", "saidas", "debito", "expense", "expenses", "debit"}:
        return -1
    return 0


def infer_mapping(data: Dataset) -> Mapping:
    def find(pattern: str, kind: str | None = None) -> int:
        return next((c.index for c in data.columns if (not kind or c.kind == kind) and re.search(pattern, normalize(c.name))), -1)
    metric = find(r"^(valor|receita|faturamento|total|saldo|valor em estoque)$", "number")
    if metric < 0:
        metric = find(r"valor|receita|faturamento|total|saldo|preco|quantidade", "number")
    if metric < 0:
        metric = find(".", "number")
    movement = find(r"^(tipo|natureza|movimento|type)$")
    group = find(r"^categoria$")
    if group < 0:
        group = find(r"categoria|departamento|produto|canal|equipe|setor")
    if group < 0:
        group = next((c.index for c in data.columns if c.kind == "text" and c.index != movement), -1)
    financial = movement >= 0 and any(direction(row[movement]) for row in data.rows)
    currency = financial or metric >= 0 and bool(re.search(r"valor|receita|faturamento|preco|saldo|custo", normalize(data.columns[metric].name)))
    return Mapping(metric, group, find(".", "date"), movement, "finance" if financial else "general", currency)


def category_name(row: list, mapping: Mapping) -> str:
    return str(row[mapping.group]) if mapping.group >= 0 and not empty(row[mapping.group]) else "Sem categoria" if mapping.group >= 0 else "Todos"


def filter_rows(data: Dataset, mapping: Mapping, filters: Filters) -> Matrix:
    result = []
    for row in data.rows:
        if filters.search and not any(normalize(filters.search) in normalize(v) for v in row):
            continue
        if filters.category and category_name(row, mapping) != filters.category:
            continue
        if mapping.date >= 0 and (filters.start or filters.end):
            value = date_value(row[mapping.date])
            if not value or filters.start and value < filters.start or filters.end and value > filters.end:
                continue
        result.append(row)
    return result


def analyze(rows: Matrix, mapping: Mapping) -> dict:
    totals = dict(total=ZERO, income=ZERO, expense=ZERO, valid=0, invalid=0, unclassified=0, undated=0, count=len(rows))
    groups, timeline = {}, {}
    for row in rows:
        value = number_value(row[mapping.metric]) if mapping.metric >= 0 else None
        if value is None and mapping.metric >= 0:
            totals["invalid"] += 1
        if value is not None:
            totals["valid"] += 1
            totals["total"] += value
        sign = direction(row[mapping.type]) if mapping.type >= 0 else (1 if value >= 0 else -1) if value is not None else 0
        inc = abs(value) if mapping.mode == "finance" and value is not None and sign == 1 else ZERO
        exp = abs(value) if mapping.mode == "finance" and value is not None and sign == -1 else ZERO
        totals["income"] += inc
        totals["expense"] += exp
        if mapping.mode == "finance" and value is not None and not sign:
            totals["unclassified"] += 1
        key = category_name(row, mapping)
        group = groups.setdefault(key, dict(name=key, value=ZERO, count=0))
        group["count"] += 1
        group["value"] += exp if mapping.mode == "finance" else value if value is not None else Decimal(mapping.metric < 0)
        if mapping.date >= 0:
            day = date_value(row[mapping.date])
            if day:
                point = timeline.setdefault(day[:7], dict(name=day[:7], value=ZERO, income=ZERO, expense=ZERO, count=0))
                point["count"] += 1
                point["value"] += value if value is not None else Decimal(mapping.metric < 0)
                point["income"] += inc
                point["expense"] += exp
            else:
                totals["undated"] += 1
    totals.update(balance=totals["income"] - totals["expense"], average=totals["total"] / totals["valid"] if totals["valid"] else ZERO,
                  groups=sorted(groups.values(), key=lambda g: abs(g["value"]), reverse=True),
                  timeline=sorted(timeline.values(), key=lambda p: p["name"]))
    return totals


def sort_rows(rows: Matrix, columns: list[Column], column: int = -1, descending: bool = False) -> Matrix:
    if not 0 <= column < len(columns):
        return rows
    kind = columns[column].kind
    def key(row):
        value = row[column]
        parsed = number_value(value) if kind == "number" else date_value(value) if kind == "date" else normalize(value)
        return (parsed is not None, parsed if parsed is not None else ZERO if kind == "number" else "")
    return sorted(rows, key=key, reverse=descending)


def export_csv(columns: list[Column], rows: Matrix) -> str:
    def safe(value):
        if isinstance(value, str) and re.match(r"^\s*[=+\-@\t\r]", value):
            return "'" + value
        return "" if value is None else value
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow([safe(c.name) for c in columns])
    writer.writerows([[safe(v) for v in row] for row in rows])
    return "\ufeff" + output.getvalue()


def format_number(value: Any, currency: bool = False) -> str:
    number = number_value(value)
    if number is None:
        return "—"
    precision = 2 if currency else 0 if number == number.to_integral() else 2
    text = f"{number:,.{precision}f}".replace(",", "\0").replace(".", ",").replace("\0", ".")
    return ("R$ " if currency else "") + text


def demo_book(kind: str = "finance") -> dict:
    rows = []
    if kind == "finance":
        rows.append(["Data", "Descrição", "Categoria", "Tipo", "Valor", "Status"])
        for m, total in enumerate([12800, 17200, 14500, 23400, 20800, 28400, 26300, 32800]):
            for i in range(16):
                expense = i >= 8
                value = int((Decimal(total) * (Decimal(".48") + Decimal(m % 3) * Decimal(".05")) / 8).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if expense else total / 8
                rows.append([f"2026-{m+1:02d}-{i+3:02d}", ["Aluguel e serviços", "Folha de pagamento", "Campanhas digitais", "Software e ferramentas"][i % 4] if expense else f"Recebimento de cliente {i+1}",
                             ["Operacional", "Equipe", "Marketing", "Tecnologia"][i % 4] if expense else "Vendas", "Despesa" if expense else "Receita", value, "Pendente" if i % 7 == 0 else "Concluído"])
    elif kind == "sales":
        rows.append(["Data", "Produto", "Canal", "Quantidade", "Valor", "Status"])
        for m in range(8):
            for i in range(10):
                rows.append([f"2026-{m+1:02d}-{i+4:02d}", ["Plano Pro", "Plano Team", "Consultoria"][i % 3], ["Site", "Indicação", "Parceiro"][i % 3], i % 4 + 1, (i % 4 + 1) * [149, 399, 1200][i % 3] + m * 20, "Concluído"])
    elif kind == "stock":
        rows.append(["SKU", "Produto", "Categoria", "Quantidade", "Estoque mínimo", "Custo unitário"])
        for i in range(30):
            rows.append([f"00{100+i}", ["Teclado", "Monitor", "Mouse", "Headset", "Notebook"][i % 5] + f" {i+1}", ["Periféricos", "Telas", "Periféricos", "Áudio", "Computadores"][i % 5], i * 13 % 70, 10, [180, 1100, 89, 240, 4500][i % 5]])
    else:
        raise ValueError("Exemplo inválido.")
    return dict(name={"finance": "Financeiro 2026", "sales": "Vendas 2026", "stock": "Controle de estoque"}[kind], demo=kind, sheets=[dict(name="Dados", data=rows)])

