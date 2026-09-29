"""Regressões de volume: arquivos reais, processo isolado e fluxo HTTP."""
import csv
import io
import re
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from nexo.imports import MAX_FILE, read_book, import_book
from nexo.web import create_app


def csv_payload(count, delimiter=';'):
    return (delimiter.join(['Categoria', 'Valor', 'Tipo', 'Data', 'Status', 'Descricao']) + '\n'
            + ''.join(delimiter.join(['A' if i % 2 == 0 else 'B', '2', 'Receita',
                                      '2026-01-01', 'Concluido', str(i)]) + '\n'
                      for i in range(count))).encode()


def xlsx_payload(sheets):
    workbook = Workbook(write_only=True)
    for name, count, columns in sheets:
        sheet = workbook.create_sheet(name)
        sheet.append(['Valor'] + [f'Campo {i}' for i in range(1, columns)])
        for _ in range(count):
            sheet.append([2] * columns)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


class LargeImportTests(unittest.TestCase):
    def test_csv_and_tsv_accept_100000_records(self):
        for name, delimiter in [('large.csv', ';'), ('large.tsv', '\t')]:
            with self.subTest(name=name):
                book = read_book(csv_payload(100_000, delimiter), name)
                rows = book['sheets'][0]['data']
                self.assertEqual(len(rows), 100_001)
                self.assertEqual(rows[-1][-1], '99999')

    def test_xlsx_100000_records_through_isolated_process(self):
        payload = xlsx_payload([('Grande', 100_000, 10)])
        self.assertLess(len(payload), MAX_FILE)
        book = import_book(payload, 'large.xlsx')
        self.assertEqual(len(book['sheets'][0]['data']), 100_001)
        self.assertEqual(book['sheets'][0]['data'][-1], [2] * 10)

    def test_row_limit_rejects_without_truncating(self):
        with self.assertRaisesRegex(ValueError, '100.000 registros'):
            read_book(csv_payload(100_001), 'too_many.csv')

    def test_xlsx_unknown_dimensions_enforces_sheet_cell_limit(self):
        # Arquivos write-only não declaram dimensões: checar durante a leitura.
        payload = xlsx_payload([('Grande', 4, 3)])
        with patch('nexo.imports.MAX_SHEET_CELLS', 12):
            with self.assertRaisesRegex(ValueError, '12 células'):
                read_book(payload, 'too_wide.xlsx')

    def test_workbook_cell_limit_across_sheets(self):
        payload = xlsx_payload([('Primeira', 3, 2), ('Segunda', 3, 2)])
        with patch('nexo.imports.MAX_BOOK_CELLS', 12):
            with self.assertRaisesRegex(ValueError, '12 células por arquivo'):
                read_book(payload, 'many_sheets.xlsx')

    def test_large_http_upload_filter_pagination_and_export(self):
        app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'IMPORT_ISOLATED': True})
        client = app.test_client()
        html = client.get('/').get_data(as_text=True)
        csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
        response = client.post('/upload', data={
            'csrf': csrf, 'file': (io.BytesIO(csv_payload(100_000)), 'large.csv')},
            follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('100000 registros analisados', response.get_data(as_text=True))
        summary = client.get('/api/summary').json
        self.assertEqual(summary['count'], 100_000)
        self.assertEqual(summary['income'], '200000')
        self.assertEqual(client.get('/?view=data&page=8334').status_code, 200)
        query = {'category': 'B', 'page': 2}
        self.assertEqual(client.get('/api/summary', query_string=query).json['count'], 50_000)
        exported = client.get('/export/csv', query_string=query).get_data(as_text=True)
        rows = list(csv.reader(io.StringIO(exported.lstrip('\ufeff')), delimiter=';'))
        self.assertEqual(len(rows), 50_001)
        self.assertEqual(rows[-1][-1], '99999')
        # Uma importação acima do limite mantém os dados anteriores.
        response = client.post('/upload', data={
            'csrf': csrf, 'file': (io.BytesIO(csv_payload(100_001)), 'too_many.csv')},
            follow_redirects=True)
        self.assertIn('Limite por aba', response.get_data(as_text=True))
        self.assertEqual(client.get('/api/summary').json['count'], 100_000)


if __name__ == '__main__':
    unittest.main()
