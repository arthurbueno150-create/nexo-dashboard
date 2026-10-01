import csv
import io
import json
import re
import sqlite3
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from nexo.large_data import build_database, connect, csv_chunks, selection, zip_check
from nexo.large_web import CHUNK, MAX_UPLOAD
from nexo.web import create_app


class DiskModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def build(self, payload, name='data.csv', header=0):
        (self.root / ('source' + Path(name).suffix)).write_bytes(payload)
        build_database(self.root, name, header)
        return json.loads((self.root / 'progress.json').read_text(encoding='utf-8'))

    def test_query_precision_filter_export_and_all_rows(self):
        content = 'Categoria;Valor;Codigo\n' + ''.join(f'{"Áudio" if i % 2 == 0 else "Vídeo"};0,10;{i:06d}\n' for i in range(100_001))
        self.assertEqual(self.build(content.encode())['state'], 'ready')
        self.assertFalse((self.root / 'source.csv').exists())
        db = connect(self.root)
        try:
            values = selection(db, {'metric':'1', 'search':'audio', 'page':'2'})
            self.assertEqual((values['count'], values['total'], values['average']), (50_001, '5000.10', '0.10'))
            self.assertEqual(len(values['rows']), 50)
            self.assertEqual(values['rows'][0][-1], '000100')
            exported = ''.join(csv_chunks(db, values))
            rows = list(csv.reader(io.StringIO(exported.lstrip('\ufeff')), delimiter=';'))
            self.assertEqual(len(rows), 50_002)
            self.assertEqual(rows[-1][-1], '100000')
            with self.assertRaises(ValueError):
                selection(db, {'metric':'999'})
        finally:
            db.close()

    def test_csv_formula_neutralization_and_missing_values(self):
        self.build(b'Nome;Valor\n=cmd;2\n@other;\n')
        db = connect(self.root)
        try:
            values = selection(db, {'metric':'1'})
            exported = ''.join(csv_chunks(db, values))
            self.assertIn("'=cmd", exported)
            self.assertIn("'@other", exported)
            self.assertEqual(values['valid'], 1)
        finally:
            db.close()

    def test_xlsx_xlsm_templates_multisheet_and_dates(self):
        from datetime import date
        for extension in ('.xlsx', '.xlsm', '.xltx', '.xltm'):
            with self.subTest(extension=extension):
                dbpath = self.root / 'data.sqlite'
                dbpath.unlink(missing_ok=True)
                book = Workbook()
                book.active.title = 'Primeira'
                book.active.append(['Data', 'Valor'])
                book.active.append([date(2026, 10, 1), 2.5])
                book.create_sheet('Segunda').append(['Item', 'Quantidade'])
                book['Segunda'].append(['A', 3])
                payload = io.BytesIO()
                book.save(payload)
                self.assertEqual(self.build(payload.getvalue(), 'data'+extension)['state'], 'ready')
                db = connect(self.root)
                try:
                    values = selection(db, {})
                    self.assertEqual(len(values['sheets']), 2)
                    self.assertEqual(values['rows'][0], ['2026-10-01', 2.5])
                finally:
                    db.close()

    def test_ods_repetitions_multisheet_and_empty_padding(self):
        xml = '''<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:spreadsheet>
        <table:table table:name="Dados"><table:table-row><table:table-cell><text:p>Valor</text:p></table:table-cell></table:table-row><table:table-row table:number-rows-repeated="3"><table:table-cell office:value-type="float" office:value="2.5"/><table:table-cell table:number-columns-repeated="1023"/></table:table-row><table:table-row table:number-rows-repeated="1048570"><table:table-cell/></table:table-row></table:table>
        <table:table table:name="Outra"><table:table-row><table:table-cell><text:p>Nome</text:p></table:table-cell></table:table-row><table:table-row><table:table-cell><text:p>Ana</text:p></table:table-cell></table:table-row></table:table>
        </office:spreadsheet></office:body></office:document-content>'''
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr('content.xml', xml)
        self.assertEqual(self.build(payload.getvalue(), 'test.ods')['state'], 'ready')
        db = connect(self.root)
        try:
            values = selection(db, {'metric':'0'})
            self.assertEqual((values['count'], values['total']), (3, '7.5'))
            self.assertEqual(len(values['sheets']), 2)
        finally:
            db.close()

    def test_limits_and_invalid_files_fail_without_partial_database(self):
        for payload, extension in [(b'bad', '.xlsx'), (b'', '.csv'), (b'a\n"broken', '.csv'), (b'a;'*201+b'\nb;'*201, '.csv')]:
            with self.subTest(extension=extension):
                result = self.build(payload, 'test'+extension)
                self.assertEqual(result['state'], 'failed')
                self.assertFalse((self.root / 'data.sqlite').exists())
                self.assertFalse((self.root / ('source'+extension)).exists())
        with patch('nexo.large_data.MAX_ROWS', 1):
            self.assertEqual(self.build(b'A\n1\n2')['state'], 'failed')

    def test_legacy_xls_fixture(self):
        path = Path(__file__).parent / 'fixtures' / 'small.xls'
        self.assertEqual(self.build(path.read_bytes(), 'small.xls')['state'], 'ready')
        db = connect(self.root)
        try:
            values = selection(db, {'metric':'1'})
            self.assertEqual(values['total'], '12.5')
            self.assertEqual(values['rows'][0][0], '0001')
        finally:
            db.close()

    def test_real_xlsb_fixture(self):
        path = Path(__file__).parent / 'fixtures' / 'pandas-test1.xlsb'
        result = self.build(path.read_bytes(), 'data.xlsb')
        self.assertEqual(result['state'], 'ready', result)
        db = connect(self.root)
        try:
            values = selection(db, {})
            self.assertEqual(values['count'], 7)
            self.assertEqual(len(values['sheet']['columns']), 5)
        finally:
            db.close()


class LargeUploadTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING':True, 'SECRET_KEY':'test-only'})
        self.client = self.app.test_client()
        html = self.client.get('/large').get_data(as_text=True)
        self.csrf = re.search(r'data-csrf="([^"]+)"', html).group(1)

    def tearDown(self):
        self.app.extensions['large_manager'].close()

    def post(self, url, **kwargs):
        return self.client.post(url, headers={'X-CSRF-Token':self.csrf}, **kwargs)

    def start(self, size, name='test.csv'):
        response = self.post('/large/start', json={'name':name, 'size':size, 'header':0})
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.json['id']

    def test_chunk_integrity_csrf_isolation_and_cancel(self):
        self.assertEqual(self.client.post('/large/start', json={'size':12,'name':'test.csv'}).status_code, 400)
        identifier = self.start(12)
        self.assertEqual(self.post(f'/large/{identifier}/chunk?offset=1', data=b'a').status_code, 409)
        self.assertEqual(self.post(f'/large/{identifier}/finish').status_code, 409)
        self.assertEqual(self.post(f'/large/{identifier}/chunk?offset=0', data=b'x'*13).status_code, 413)
        self.assertEqual(self.post(f'/large/{identifier}/chunk?offset=0', data=b'a'*6).json['received'], 6)
        self.assertEqual(self.post(f'/large/{identifier}/chunk?offset=0', data=b'b'*6).status_code, 409)
        other = self.app.test_client()
        self.assertEqual(other.get(f'/large/{identifier}/status').status_code, 404)
        job = self.app.extensions['large_manager'].jobs[identifier]
        self.assertEqual(job.source.read_bytes(), b'a'*6)
        self.assertEqual(self.post(f'/large/{identifier}/cancel').status_code, 200)
        self.assertFalse(job.folder.exists())

    def test_limits_quota_and_clear(self):
        self.assertEqual(self.post('/large/start', json={'name':'test.csv','size':MAX_UPLOAD+1}).status_code, 400)
        self.assertEqual(self.post('/large/start', json={'name':'test.exe','size':10}).status_code, 400)
        identifier = self.start(20)
        self.assertEqual(self.post('/large/start', json={'name':'test.csv','size':10}).status_code, 409)
        self.assertEqual(self.post(f'/large/{identifier}/chunk?offset=0', data=b'x'*(CHUNK+1)).status_code, 413)
        self.post('/clear')
        self.assertEqual(len(self.app.extensions['large_manager'].jobs), 0)

    def test_worker_and_original_dashboard_remains_available(self):
        payload = b'Categoria;Valor\nA;2\nB;3\n'
        identifier = self.start(len(payload))
        self.post(f'/large/{identifier}/chunk?offset=0', data=payload)
        self.assertEqual(self.post(f'/large/{identifier}/finish').status_code, 202)
        deadline = time.monotonic()+30
        while time.monotonic()<deadline:
            result = self.client.get(f'/large/{identifier}/status').json
            if result['state'] != 'processing':
                break
            time.sleep(.1)
        self.assertEqual(result['state'], 'ready', result)
        self.assertEqual(self.client.get(f'/large/{identifier}/data?metric=1').status_code, 200)
        export = self.client.get(f'/large/{identifier}/export?group=0&category=B')
        self.assertIn('"B";"3"', export.get_data(as_text=True))
        self.assertNotIn('"A";"2"', export.get_data(as_text=True))
        self.assertEqual(self.client.get('/api/summary').json['count'], 128)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_expired_upload_removed_by_cleanup(self):
        identifier = self.start(12)
        manager = self.app.extensions['large_manager']
        job = manager.jobs[identifier]
        job.touched -= 1801
        manager.cleanup()
        self.assertFalse(job.folder.exists())
        self.assertEqual(self.client.get(f'/large/{identifier}/status').status_code, 404)

    def test_failed_import_keeps_previous_ready_file(self):
        def finish_payload(payload):
            identifier = self.start(len(payload))
            self.post(f'/large/{identifier}/chunk?offset=0', data=payload)
            self.post(f'/large/{identifier}/finish')
            deadline = time.monotonic()+30
            while time.monotonic()<deadline:
                state = self.client.get(f'/large/{identifier}/status').json['state']
                if state != 'processing':
                    return identifier, state
                time.sleep(.1)
            self.fail('Worker did not finish')
        first, state = finish_payload(b'Nome;Valor\nAna;12')
        self.assertEqual(state, 'ready')
        second, state = finish_payload(b'Nome;Valor\n"invalid')
        self.assertEqual(state, 'failed')
        self.assertEqual(self.client.get(f'/large/{first}/data').status_code, 200)
        self.assertEqual(self.client.get(f'/large/{second}/data').status_code, 409)


if __name__ == '__main__':
    unittest.main()
