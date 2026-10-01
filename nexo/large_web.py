"""Uploads em partes, um leitor por vez e arquivos temporários por sessão."""
from __future__ import annotations

import atexit
import json
import multiprocessing
import os
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from flask import Blueprint, Response, abort, g, jsonify, render_template, request, session

from .large_data import FORMATS, MAX_DB, connect, csv_chunks, progress, selection, worker

CHUNK = 4 * 1024 * 1024
MAX_UPLOAD = 250 * 1024 * 1024
TTL = 1800
TIMEOUT = 900


@dataclass
class Job:
    id: str
    owner: str
    folder: Path
    name: str
    size: int
    header: int | None
    received: int = 0
    state: str = 'uploading'
    touched: float = field(default_factory=time.monotonic)
    started: float = 0
    process: object = None
    lock: object = field(default_factory=threading.RLock)

    @property
    def source(self):
        return self.folder / ('source' + Path(self.name).suffix.lower())

    def refresh(self):
        if self.state != 'processing':
            return
        if time.monotonic() - self.started > TIMEOUT:
            self.process.terminate()
            self.process.join(timeout=3)
            progress(self.folder, state='failed', rows=0, message='Tempo de processamento excedido (15 minutos). Divida o arquivo ou use CSV.')
        if not self.process.is_alive():
            self.process.join(timeout=0)
            try:
                result = json.loads((self.folder / 'progress.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                result = {}
            self.state = result.get('state', 'failed')
            if self.state == 'processing' or self.state not in {'ready', 'failed'}:
                self.state = 'failed'
            if self.state == 'failed':
                progress(self.folder, state='failed', rows=0, message=result.get('message') if result.get('state') == 'failed' else 'O leitor atingiu os recursos disponíveis. Tente CSV ou divida o arquivo.')
                self.source.unlink(missing_ok=True)
                (self.folder / 'data.sqlite').unlink(missing_ok=True)

    def snapshot(self):
        self.refresh()
        result = dict(state=self.state, rows=0, message='Enviando arquivo…')
        if self.state != 'uploading':
            try:
                result.update(json.loads((self.folder / 'progress.json').read_text(encoding='utf-8')))
            except (OSError, ValueError):
                pass
        result.update(id=self.id, name=self.name, received=self.received, size=self.size)
        return result


class Manager:
    def __init__(self, root=None):
        self.root = Path(tempfile.mkdtemp(prefix='nexo-large-', dir=root)).resolve()
        self.jobs = {}
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.reap, daemon=True)
        self.thread.start()
        atexit.register(self.close)

    def remove(self, job):
        with job.lock:
            if job.process is not None and job.process.is_alive():
                job.process.terminate()
                job.process.join(timeout=3)
            # Diretórios gerados pelo servidor; nunca caminhos fornecidos pelo cliente.
            if job.folder.resolve().parent != self.root:
                raise RuntimeError('Diretório temporário inválido.')
            shutil.rmtree(job.folder, ignore_errors=True)
            job.state = 'deleted'
            self.jobs.pop(job.id, None)

    def reap(self):
        while not self.stopped.wait(30):
            self.cleanup()

    def cleanup(self):
        with self.lock:
            for job in list(self.jobs.values()):
                if not job.lock.acquire(blocking=False):
                    continue
                try:
                    job.refresh()
                    if time.monotonic() - job.touched > TTL:
                        self.remove(job)
                finally:
                    job.lock.release()

    def clear_owner(self, owner):
        with self.lock:
            for job in list(self.jobs.values()):
                if job.owner == owner:
                    self.remove(job)

    def close(self):
        self.stopped.set()
        with self.lock:
            for job in list(self.jobs.values()):
                self.remove(job)
            try:
                self.root.rmdir()
            except OSError:
                pass


def register(app):
    manager = Manager(app.config.get('LARGE_TEMP_ROOT'))
    app.extensions['large_manager'] = manager
    bp = Blueprint('large', __name__)

    def owned(identifier):
        with manager.lock:
            job = manager.jobs.get(identifier)
            if job is None or job.owner != session.get('sid'):
                abort(404, 'Importação indisponível. A sessão pode ter expirado ou o servidor reiniciado.')
            job.touched = time.monotonic()
            return job

    @bp.get('/large')
    def index():
        with manager.lock:
            jobs = [j.snapshot() for j in manager.jobs.values() if j.owner == session['sid']]
        return render_template('large.html', csrf=g.state.csrf, jobs=jobs, max_mb=MAX_UPLOAD // 1024**2)

    @bp.post('/large/start')
    def start():
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            abort(400, 'Dados de upload inválidos.')
        name = Path(str(data.get('name', '')).replace('\\', '/')).name[:180]
        size = data.get('size')
        header = data.get('header')
        if Path(name).suffix.lower() not in FORMATS:
            abort(400, 'Formato não suportado. Use CSV, TSV, XLSX, XLSM, XLTX, XLTM, XLS, XLSB ou ODS.')
        if type(size) is not int or not 0 < size <= MAX_UPLOAD:
            abort(400, 'O modo de arquivos grandes aceita até 250 MB por arquivo.')
        if header is not None and (type(header) is not int or not 0 <= header < 30):
            abort(400, 'Cabeçalho inválido: escolha uma linha de 1 a 30.')
        with manager.lock:
            active = [j for j in manager.jobs.values() if j.owner == session['sid']]
            if any(j.state in {'uploading', 'processing'} for j in active):
                abort(409, 'Aguarde ou cancele a importação atual.')
            for job in active:
                if job.state == 'failed':
                    manager.remove(job)
            if len(manager.jobs) >= 3:
                abort(503, 'Os espaços temporários estão ocupados. Descarte uma importação ou tente mais tarde.')
            reserved = sum(MAX_DB + j.size - sum(p.stat().st_size for p in j.folder.iterdir() if p.is_file()) for j in manager.jobs.values())
            if shutil.disk_usage(manager.root).free - reserved < MAX_DB + size + 128 * 1024 * 1024:
                abort(503, 'Espaço temporário insuficiente. Descarte uma importação ou tente mais tarde.')
            identifier = secrets.token_hex(16)
            folder = manager.root / identifier
            folder.mkdir()
            job = Job(identifier, session['sid'], folder, name, size, header)
            job.source.touch()
            manager.jobs[identifier] = job
            return jsonify(job.snapshot()), 201

    @bp.post('/large/<identifier>/chunk')
    def chunk(identifier):
        job = owned(identifier)
        try:
            offset = int(request.args.get('offset', '-1'))
        except ValueError:
            abort(400, 'Posição de envio inválida.')
        if request.content_length is None or not 0 < request.content_length <= CHUNK:
            abort(413, 'Cada parte do envio deve ter até 4 MB.')
        with job.lock:
            if job.state != 'uploading' or offset != job.received:
                abort(409, 'O envio mudou. Consulte o progresso antes de continuar.')
            if job.received + request.content_length > job.size:
                abort(413, 'O envio excede o tamanho informado.')
            payload = request.stream.read(CHUNK + 1)
            if len(payload) != request.content_length:
                abort(400, 'Parte incompleta. Envie novamente.')
            try:
                with job.source.open('ab') as output:
                    output.write(payload)
            except OSError:
                # Volta à posição confirmada caso o sistema tenha gravado só uma parte.
                try:
                    with job.source.open('r+b') as output:
                        output.truncate(job.received)
                except OSError:
                    pass
                abort(503, 'Não há espaço para continuar o envio. Descarte-o e tente um arquivo menor.')
            job.received += len(payload)
            return jsonify(job.snapshot())

    @bp.post('/large/<identifier>/finish')
    def finish(identifier):
        job = owned(identifier)
        with manager.lock, job.lock:
            for other in manager.jobs.values():
                other.refresh()
            if job.state != 'uploading' or job.received != job.size:
                abort(409, 'O envio ainda não está completo ou já foi processado.')
            if any(j.state == 'processing' for j in manager.jobs.values()):
                abort(409, 'Outro arquivo está sendo processado. Aguarde e clique em Processar envio.')
            job.process = multiprocessing.get_context('spawn').Process(target=worker, args=(str(job.folder), job.name, job.header), daemon=True)
            job.started = time.monotonic()
            progress(job.folder, state='processing', rows=0, message='Preparando a leitura…')
            try:
                job.process.start()
            except Exception:
                abort(503, 'Não foi possível iniciar o leitor. Tente novamente.')
            job.state = 'processing'
            return jsonify(job.snapshot()), 202

    @bp.get('/large/<identifier>/status')
    def status(identifier):
        job = owned(identifier)
        with job.lock:
            return jsonify(job.snapshot())

    @bp.post('/large/<identifier>/cancel')
    def cancel(identifier):
        job = owned(identifier)
        with manager.lock:
            manager.remove(job)
        return jsonify(state='deleted')

    @bp.get('/large/<identifier>/data')
    def data(identifier):
        job = owned(identifier)
        with job.lock:
            job.refresh()
            if job.state != 'ready':
                abort(409, 'A importação ainda não está pronta.')
            try:
                with connect(job.folder) as db:
                    values = selection(db, request.args)
            except (sqlite3.Error, ValueError):
                abort(400, 'Consulta inválida ou demorada demais. Reduza os filtros e tente novamente.')
            finally:
                if 'db' in locals():
                    db.close()
            return render_template('large_data.html', job=job, values=values, csrf=g.state.csrf)

    @bp.get('/large/<identifier>/export')
    def export(identifier):
        job = owned(identifier)
        with job.lock:
            job.refresh()
            if job.state != 'ready':
                abort(409, 'A importação ainda não está pronta.')
            db = connect(job.folder)
            try:
                values = selection(db, request.args)
            except (sqlite3.Error, ValueError):
                abort(400, 'Filtros inválidos ou consulta demorada demais.')
            finally:
                db.close()
        def generate():
            with job.lock:
                if job.state != 'ready':
                    return
                database = connect(job.folder)
                try:
                    yield from csv_chunks(database, values)
                finally:
                    database.close()
        return Response(generate(), content_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="nexo-arquivo-grande.csv"'})

    @bp.errorhandler(400)
    @bp.errorhandler(404)
    @bp.errorhandler(409)
    @bp.errorhandler(413)
    @bp.errorhandler(503)
    def error(exc):
        if request.method == 'POST' or request.path.endswith('/status'):
            return jsonify(error=exc.description), exc.code
        return render_template('error.html', message=exc.description), exc.code

    app.register_blueprint(bp)
