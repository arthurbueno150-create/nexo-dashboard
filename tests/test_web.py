import csv
import io
import re
import unittest
from decimal import Decimal
from pathlib import Path

from nexo.web import create_app

SAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'nexo-dados-ficticios.xlsx'


class WebTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only-key', 'IMPORT_ISOLATED': False})
        self.client = self.app.test_client()
        response = self.client.get('/')
        self.csrf = re.search(r'name="csrf" value="([^"]+)"', response.get_data(as_text=True)).group(1)

    def post(self, path, data=None, **kwargs):
        return self.client.post(path, data={'csrf': self.csrf, **(data or {})}, **kwargs)

    def upload(self):
        response = self.post('/upload', {'file': (io.BytesIO(SAMPLE.read_bytes()), SAMPLE.name)}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('74 registros', response.get_data(as_text=True))

    def test_import_routes_cleanup_and_reimport(self):
        self.upload()
        self.assertEqual(self.client.get('/api/summary').json['count'], 74)
        for view in ['overview', 'data', 'quality', 'rules']:
            self.assertEqual(self.client.get('/', query_string={'view': view}).status_code, 200)
        self.assertEqual(self.client.get('/?configure=1').status_code, 200)
        self.post('/rules', {'trim': 'on', 'deduplicate': 'on'})
        summary = self.client.get('/api/summary').json
        self.assertEqual(summary['count'], 72)
        self.assertEqual(Decimal(summary['balance']), 33411)
        self.post('/upload', {'file': (io.BytesIO(SAMPLE.read_bytes()), SAMPLE.name)})
        self.assertEqual(self.client.get('/api/summary').json['count'], 72)
        self.post('/rules', {'trim': 'on'})
        self.assertEqual(self.client.get('/api/summary').json['count'], 74)
        self.post('/sheet', {'sheet': '1'})
        self.assertEqual(self.client.get('/api/summary').json['count'], 36)
        self.post('/sheet', {'sheet': '2'})
        self.assertEqual(self.client.get('/api/summary').json['count'], 20)

    def test_exports_cover_all_filtered_records(self):
        self.upload()
        query = {'search': 'Receita', 'view': 'data', 'page': 2}
        summary = self.client.get('/api/summary', query_string=query).json
        response = self.client.get('/export/csv', query_string=query)
        rows = list(csv.reader(io.StringIO(response.get_data(as_text=True).lstrip('\ufeff')), delimiter=';'))
        self.assertEqual(len(rows) - 1, summary['count'])
        self.assertGreater(summary['count'], 12)
        report = self.client.get('/export/json', query_string=query).json
        self.assertEqual(report['summary']['count'], summary['count'])
        self.assertIsInstance(report['summary']['income'], str)

    def test_errors_preserve_data_and_validate_csrf(self):
        self.upload()
        self.assertEqual(self.client.post('/clear').status_code, 400)
        self.assertEqual(self.post('/sheet', {'sheet': '999'}).status_code, 400)
        self.assertEqual(self.post('/configure', {'metric': '999', 'mode': 'general'}).status_code, 400)
        self.assertEqual(self.client.get('/?start=2026-02-30').status_code, 400)
        self.assertEqual(self.client.get('/?start=2026-05-01&end=2026-01-01').status_code, 400)
        failed = self.post('/upload', {'file': (io.BytesIO(b'bad'), 'bad.xlsx')}, follow_redirects=True)
        self.assertIn('Não foi possível', failed.get_data(as_text=True))
        self.assertEqual(self.client.get('/api/summary').json['count'], 74)

    def test_manual_mapping_and_text_only_import(self):
        self.post('/upload', {'file': (io.BytesIO(b'Item;Unidades;Preco\nA;2;10\nB;3;20'), 'data.csv')})
        self.post('/configure', {'mode': 'general', 'metric': '1', 'group': '0', 'date': '-1', 'type': '-1'})
        self.assertEqual(Decimal(self.client.get('/api/summary').json['total']), 5)
        self.post('/upload', {'file': (io.BytesIO(b'Item;Unidades;Preco\nA;4;10'), 'data.csv')})
        self.assertEqual(Decimal(self.client.get('/api/summary').json['total']), 4)
        self.post('/upload', {'file': (io.BytesIO(b'Equipe;Nome\nA;Ana\nB;Joao'), 'text.csv')})
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/api/summary').json['count'], 2)

    def test_sessions_are_isolated_and_can_be_cleared(self):
        self.upload()
        other = self.app.test_client()
        self.assertEqual(other.get('/api/summary').json['count'], 128)
        self.assertEqual(self.client.get('/api/summary').json['count'], 74)
        self.post('/clear')
        self.assertEqual(self.client.get('/api/summary').json['count'], 128)

    def test_unknown_routes_do_not_allocate_sessions(self):
        for _ in range(20):
            self.app.test_client().get('/missing-probe')
        self.assertEqual(len(self.app.extensions['nexo_states']), 1)
        self.assertEqual(self.app.test_client().get('/health').json['language'], 'Python')
        self.assertEqual(len(self.app.extensions['nexo_states']), 1)

    def test_upload_stays_in_memory_and_request_limit(self):
        with self.app.test_request_context('/upload', method='POST', data={'file': (io.BytesIO(b'x' * 600_000), 'a.csv')}):
            from flask import request
            self.assertIsInstance(request.files['file'].stream, io.BytesIO)
        self.app.config['MAX_CONTENT_LENGTH'] = 100
        response = self.post('/upload', {'file': (io.BytesIO(b'x' * 200), 'a.csv')})
        self.assertEqual(response.status_code, 413)


if __name__ == '__main__':
    unittest.main()
