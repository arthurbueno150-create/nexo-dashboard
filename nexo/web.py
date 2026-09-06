"""Aplicação Flask: sessões isoladas, importação, filtros e exportações."""
from __future__ import annotations

import hmac
import io
import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

from flask import Flask, Request, Response, abort, g, redirect, render_template, request, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from .charts import chart_geometry
from .engine import (Filters, Mapping, Rules, analyze, category_name, date_value, demo_book, detect_header, empty, export_csv, filter_rows, format_number, infer_mapping, number_value, prepare, sort_rows)
from .imports import MAX_FILE, import_book

ROOT = Path(__file__).resolve().parent.parent
VIEWS = {"overview": "Visão geral", "data": "Explorar dados", "quality": "Qualidade dos dados", "rules": "Automações"}
SESSION_TTL = 7200


class MemoryRequest(Request):
    """Mantém uploads limitados em memória, inclusive no parser multipart."""

    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        return io.BytesIO()


@dataclass
class State:
    book: dict = field(default_factory=demo_book)
    sheet: int = 0
    header: int = 0
    rules: Rules = field(default_factory=Rules)
    mapping: Mapping | None = None
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    touched: float = field(default_factory=time.monotonic)
    message: str = ""
    error: str = ""
    revision: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)

    def dataset(self):
        return prepare(self.book["sheets"][self.sheet]["data"], self.header, self.rules)


def create_app(test_config=None):
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    app.request_class = MemoryRequest
    app.config.update(
        SECRET_KEY=os.environ.get("NEXO_SECRET_KEY") or secrets.token_hex(32),
        MAX_CONTENT_LENGTH=MAX_FILE + 1024 * 1024,
        MAX_FORM_MEMORY_SIZE=256 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("NEXO_SECURE_COOKIE") == "1",
        TRUSTED_HOSTS=os.environ.get("NEXO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(","),
        IMPORT_ISOLATED=True,
        MAX_SESSIONS=16,
    )
    if test_config:
        app.config.update(test_config)
    states, states_lock = {}, threading.RLock()
    app.extensions["nexo_states"] = states
    app.jinja_env.filters["number"] = format_number
    app.jinja_env.globals.update(empty=empty, number_value=number_value, views=VIEWS)

    @app.before_request
    def load_state():
        if request.endpoint in {None, "static", "health"} or request.method == "OPTIONS":
            return
        now = time.monotonic()
        with states_lock:
            for key in list(states):
                if now - states[key].touched > SESSION_TTL:
                    states.pop(key)
            identifier = session.get("sid")
            if identifier not in states:
                if len(states) >= app.config["MAX_SESSIONS"]:
                    abort(503, "Limite de sessões ativas. Tente novamente mais tarde.")
                identifier = secrets.token_urlsafe(32)
                session.clear()
                session["sid"] = identifier
                states[identifier] = State()
            g.state = states[identifier]
            g.state.touched = now
        if request.method == "POST":
            token = request.form.get("csrf", "")
            if not hmac.compare_digest(token, g.state.csrf):
                abort(400, "A sessão mudou. Recarregue a página e tente novamente.")

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'"
        if not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def integer(value, default=-1):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def current_view():
        value = request.values.get("view", "overview")
        return value if value in VIEWS else "overview"

    def filters_from_request():
        filters = Filters(*(request.args.get(k, "")[:500] for k in ("search", "category", "start", "end")))
        if filters.start and date_value(filters.start) != filters.start or filters.end and date_value(filters.end) != filters.end:
            abort(400, "Informe um intervalo de datas válido.")
        if filters.start and filters.end and filters.start > filters.end:
            abort(400, "A data inicial deve vir antes da data final.")
        return filters

    def context():
        state = g.state
        data = state.dataset()
        mapping = state.mapping or infer_mapping(data)
        filters = filters_from_request()
        rows = filter_rows(data, mapping, filters)
        order = integer(request.args.get("sort"))
        descending = request.args.get("desc") == "1"
        rows = sort_rows(rows, data.columns, order, descending)
        result = analyze(rows, mapping)
        pages = max(1, (len(rows) + 11) // 12)
        page = min(max(1, integer(request.args.get("page"), 1)), pages)
        metric = data.columns[mapping.metric].name if mapping.metric >= 0 else "Registros"
        group = data.columns[mapping.group].name if mapping.group >= 0 else "Categoria"
        if mapping.mode == "finance":
            kpis = [("Receitas", format_number(result["income"], mapping.currency), "Entradas classificadas", "mint", "↗"),
                    ("Despesas", format_number(result["expense"], mapping.currency), "Saídas classificadas", "orange", "↙"),
                    ("Saldo do período", format_number(result["balance"], mapping.currency), "Receitas menos despesas", "purple", "∿"),
                    ("Registros analisados", format_number(len(rows)), "Na seleção atual", "blue", "▦")]
        else:
            kpis = [(f"Total · {metric}", format_number(result["total"], mapping.currency) if mapping.metric >= 0 else format_number(len(rows)), "Na seleção atual", "mint", "∿"),
                    ("Média por registro" if mapping.metric >= 0 else "Colunas", format_number(result["average"], mapping.currency) if mapping.metric >= 0 else str(len(data.columns)), "Valores numéricos válidos" if mapping.metric >= 0 else "Detectadas na planilha", "purple", "↗"),
                    ("Categorias", str(len(result["groups"])), group, "orange", "◫"),
                    ("Registros analisados", format_number(len(rows)), "Na seleção atual", "blue", "▦")]
        def link(**changes):
            params = request.args.to_dict()
            params.update(changes)
            return url_for("index", **{k: v for k, v in params.items() if v is not None})
        return dict(state=state, data=data, mapping=mapping, filters=filters, result=result, rows=rows, visible_rows=rows[(page-1)*12:page*12], page=page, pages=pages, order=order, descending=descending,
                    view=current_view(), view_name=VIEWS[current_view()], kpis=kpis, metric=metric, group=group, categories=sorted({category_name(row, mapping) for row in data.rows}, key=str.casefold),
                    chart=chart_geometry(result, mapping), link=link, row_start=(page-1)*12+1 if rows else 0, row_end=min(page*12, len(rows)), configured=request.args.get("configure") == "1",
                    filter_args=asdict(filters), active_filters=any(asdict(filters).values()))

    @app.get("/")
    def index():
        with g.state.lock:
            values = context()
            response = render_template("dashboard.html", **values)
            g.state.message = g.state.error = ""
            return response

    @app.post("/upload")
    def upload():
        state = g.state
        files = request.files.getlist("file")
        if len(files) != 1 or not files[0].filename:
            state.error = "Escolha um arquivo por importação."
            return redirect(url_for("index"))
        source = files[0]
        payload = source.stream.read(MAX_FILE + 1)
        with state.lock:
            revision = state.revision
        try:
            if app.config["IMPORT_ISOLATED"]:
                book = import_book(payload, source.filename)
            else:
                from .imports import read_book
                book = read_book(payload, source.filename)
            with states_lock:
                cells = sum(len(row) for s in book["sheets"] for row in s["data"])
                others = sum(len(row) for other in states.values() if other is not state for s in other.book["sheets"] for row in s["data"])
                if cells + others > 2_000_000:
                    raise ValueError("A capacidade de memória das sessões foi atingida. Encerre outra sessão e tente novamente.")
                with state.lock:
                    if state.revision != revision:
                        raise ValueError("A sessão mudou durante a importação. Tente importar novamente.")
                    old = state.dataset()
                    header = detect_header(book["sheets"][0]["data"])
                    data = prepare(book["sheets"][0]["data"], header, state.rules)
                    compatible = [c.name for c in old.columns] == [c.name for c in data.columns]
                    mapping = state.mapping or infer_mapping(old) if compatible else None
                    state.book, state.sheet, state.header, state.mapping = book, 0, header, mapping
                    state.revision += 1
                    state.message = f"Importação concluída. {len(data.rows)} registros analisados."
        except ValueError as exc:
            state.error = str(exc)
        return redirect(url_for("index"))

    @app.post("/sheet")
    def change_sheet():
        with g.state.lock:
            index = integer(request.form.get("sheet"))
            if not 0 <= index < len(g.state.book["sheets"]):
                abort(400, "Aba inválida.")
            g.state.sheet = index
            g.state.header = detect_header(g.state.book["sheets"][index]["data"])
            g.state.mapping = None
            g.state.revision += 1
        return redirect(url_for("index", view=current_view()))

    @app.post("/demo")
    def demo():
        try:
            book = demo_book(request.form.get("kind", ""))
        except ValueError:
            abort(400, "Exemplo inválido.")
        with g.state.lock:
            g.state.book = book
            g.state.sheet = g.state.header = 0
            g.state.mapping = None
            g.state.revision += 1
            g.state.message = "Exemplo carregado. Os dados são fictícios."
        return redirect(url_for("index"))

    @app.post("/rules")
    def change_rules():
        with g.state.lock:
            g.state.rules = Rules(request.form.get("trim") == "on", request.form.get("deduplicate") == "on")
            g.state.revision += 1
            g.state.message = "Regras aplicadas. Os indicadores foram recalculados."
        return redirect(url_for("index", view="rules"))

    @app.post("/configure")
    def configure():
        with g.state.lock:
            state = g.state
            header = integer(request.form.get("header"), 0)
            try:
                data = prepare(state.book["sheets"][state.sheet]["data"], header, state.rules)
            except ValueError as exc:
                abort(400, str(exc))
            if header != state.header:
                mapping = infer_mapping(data)
            else:
                choices = {}
                for key in ("metric", "group", "date", "type"):
                    value = integer(request.form.get(key))
                    if not -1 <= value < len(data.columns):
                        abort(400, "Coluna inválida.")
                    choices[key] = value
                mode = request.form.get("mode")
                if mode not in {"finance", "general"}:
                    abort(400, "Tipo de análise inválido.")
                mapping = Mapping(**choices, mode=mode, currency=request.form.get("currency") == "on")
            state.header, state.mapping = header, mapping
            state.revision += 1
            state.message = "Configuração atualizada."
        return redirect(url_for("index", view=current_view(), configure=1))

    @app.get("/export/csv")
    def csv_download():
        with g.state.lock:
            values = context()
            output = export_csv(values["data"].columns, values["rows"])
        return Response(output, content_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="nexo-dados-filtrados.csv"'})

    @app.get("/export/json")
    def json_download():
        with g.state.lock:
            values = context()
            output = dict(source=g.state.book["name"], sheet=g.state.book["sheets"][g.state.sheet]["name"], demo=bool(g.state.book.get("demo")),
                          mapping=asdict(values["mapping"]), filters=asdict(values["filters"]), rules=asdict(g.state.rules), summary=values["result"],
                          quality=dict(missing=values["data"].missing, duplicates=values["data"].duplicates, removed=values["data"].removed, completeness=values["data"].completeness))
        # Decimais como strings preservam a precisão para outros programas.
        return Response(json.dumps(output, default=str, ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="nexo-relatorio.json"'})

    @app.get("/api/summary")
    def summary():
        with g.state.lock:
            values = context()
            result = values["result"]
            response = {key: str(value) if isinstance(value, Decimal) else value for key, value in result.items() if key not in {"timeline", "groups"}}
            response["mode"] = values["mapping"].mode
            return response

    @app.post("/clear")
    def clear():
        with states_lock:
            states.pop(session.get("sid"), None)
        session.clear()
        return redirect(url_for("index"))

    @app.get("/health")
    def health():
        return {"status": "ok", "language": "Python", "version": "2.0.0"}

    @app.errorhandler(RequestEntityTooLarge)
    def oversized(_error):
        return render_template("error.html", message="Arquivo muito grande. O limite é de 15 MB."), 413

    @app.errorhandler(400)
    @app.errorhandler(503)
    def bad_request(error):
        return render_template("error.html", message=error.description), error.code

    return app
