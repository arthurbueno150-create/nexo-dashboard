import csv
import io
import unittest
from decimal import Decimal
from pathlib import Path

from nexo.charts import chart_geometry
from nexo.engine import (Filters, Mapping, Rules, analyze, date_value, detect_header,
                         export_csv, filter_rows, infer_mapping, number_value, prepare, sort_rows)
from nexo.imports import import_book, read_book

SAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'nexo-dados-ficticios.xlsx'


class EngineTests(unittest.TestCase):
    def test_number_formats_and_invalid_values(self):
        for raw, expected in [('R$ 1.234,56', '1234.56'), ('1,234.56', '1234.56'),
                              ('(25,50)', '-25.50'), ('12%', '.12'), ('1.234', '1234'),
                              ('1,234', '1.234'), (0, '0')]:
            with self.subTest(raw=raw):
                self.assertEqual(number_value(raw), Decimal(expected))
        for raw in [True, None, '', 'abc', float('inf'), float('nan'), '1,2,3']:
            self.assertIsNone(number_value(raw))

    def test_calendar_validation(self):
        self.assertEqual(date_value('29/02/2024'), '2024-02-29')
        for value in ['29/02/2025', '31/04/2026', '2026-13-01', '45000']:
            self.assertIsNone(date_value(value))

    def test_header_and_identifiers(self):
        matrix = [['Relatório'], [], ['SKU', 'Categoria', 'Valor'],
                  ['0001', 'Áudio', '12,50'], ['0002', 'Vídeo', '30,00']]
        data = prepare(matrix, detect_header(matrix))
        self.assertEqual(data.header, 2)
        self.assertEqual(data.columns[0].kind, 'text')
        self.assertEqual(data.rows[0][0], '0001')
        self.assertEqual(infer_mapping(data).metric, 2)
        self.assertEqual([c.name for c in prepare([['A', 'A', None], [1, 2, 3]]).columns], ['A', 'A (2)', 'Coluna 3'])

    def test_cleaning_is_reversible(self):
        matrix = [['Nome', 'Valor'], [' João ', 10], ['João', 10], [None, None], ['Ana', None]]
        clean = prepare(matrix, rules=Rules(True, True))
        self.assertEqual((len(clean.rows), clean.removed, clean.duplicates, clean.empty_rows, clean.missing), (2, 1, 1, 1, 1))
        self.assertEqual(len(prepare(matrix, rules=Rules(False, False)).rows), 3)
        self.assertEqual(matrix[1][0], ' João ')

    def test_finance_signed_and_unclassified(self):
        data = prepare([['Data', 'Categoria', 'Tipo', 'Valor'],
                        ['2026-01-01', 'A', 'Receita', '.10'],
                        ['2026-01-02', 'A', 'Despesa', '-0,20'],
                        ['inválida', 'B', 'Outro', '9'],
                        ['2026-01-04', 'B', 'Receita', 'erro']])
        # Force metric to also exercise a column with more than 20% invalid values.
        mapping = Mapping(metric=3, group=1, date=0, type=2, mode='finance', currency=True)
        data.rows[0][3] = '0,10'
        result = analyze(data.rows, mapping)
        self.assertEqual(result['balance'], Decimal('-.10'))
        self.assertEqual((result['invalid'], result['unclassified'], result['undated']), (1, 1, 1))
        result = analyze([[10], [-3]], Mapping(metric=0, mode='finance'))
        self.assertEqual((result['income'], result['expense'], result['balance']), (10, 3, 7))

    def test_filters_sorting_and_export(self):
        data = prepare([['Data', 'Categoria', 'Valor'], ['2026-01-01', 'Áudio', 10],
                        ['2026-02-01', 'Áudio', 2], ['2026-02-15', 'Vídeo', 30]])
        mapping = infer_mapping(data)
        selected = filter_rows(data, mapping, Filters(search='audio', start='2026-02-01', end='2026-02-28'))
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0][2], 2)
        self.assertEqual([r[2] for r in sort_rows(data.rows, data.columns, 2)], [2, 10, 30])
        self.assertEqual(len(filter_rows(data, mapping, Filters(category='Vídeo'))), 1)
        injected = prepare([['=header', 'Valor'], ['=SUM(A1)', -2], ['+cmd', 3], ['@item', 4]])
        exported = list(csv.reader(io.StringIO(export_csv(injected.columns, injected.rows).lstrip('\ufeff')), delimiter=';'))
        self.assertEqual(exported[0][0], "'=header")
        self.assertEqual(exported[1], ["'=SUM(A1)", '-2'])
        self.assertEqual(exported[2][0], "'+cmd")

    def test_text_only_and_negative_charts(self):
        data = prepare([['Equipe', 'Nome'], ['A', 'Ana'], ['B', 'João']])
        mapping = infer_mapping(data)
        self.assertEqual(mapping.metric, -1)
        self.assertEqual(sum(x['value'] for x in analyze(data.rows, mapping)['groups']), 2)
        mapping = Mapping(metric=1, group=0)
        geometry = chart_geometry(analyze([['A', -20], ['B', 10]], mapping), mapping)
        self.assertTrue(all(bar['height'] >= 0 for bar in geometry['bars']))
        self.assertTrue(chart_geometry(analyze([], mapping), mapping)['empty'])


class ImportTests(unittest.TestCase):
    def test_real_workbook_financial_totals_and_cleanup(self):
        book = read_book(SAMPLE.read_bytes(), SAMPLE.name)
        self.assertEqual([s['name'] for s in book['sheets']], ['Finanças', 'Vendas', 'Estoque'])
        matrix = book['sheets'][0]['data']
        for deduplicate, count, expense, balance in [(False, 74, 60774, 28326), (True, 72, 55689, 33411)]:
            data = prepare(matrix, detect_header(matrix), Rules(True, deduplicate))
            result = analyze(data.rows, infer_mapping(data))
            self.assertEqual((result['count'], result['income'], result['expense'], result['balance']), (count, 89100, expense, balance))
            self.assertEqual(data.duplicates, 2)
        sales = prepare(book['sheets'][1]['data'])
        result = analyze(sales.rows, infer_mapping(sales))
        self.assertEqual(len(sales.rows), 36)
        self.assertEqual(result['invalid'], 0)
        self.assertGreater(result['total'], 0)
        stock = prepare(book['sheets'][2]['data'])
        self.assertEqual(len(stock.rows), 20)
        self.assertEqual(stock.columns[0].kind, 'text')
        self.assertTrue(str(stock.rows[0][0]).startswith('0'))

    def test_delimiters_encodings_and_quotes(self):
        for payload, name in [('Produto;Valor\nÁudio;12,50'.encode('cp1252'), 'a.csv'),
                              ('Produto\tValor\nÁudio\t12,50'.encode(), 'a.tsv'),
                              ('Produto,Valor\n"Áudio, pro","12,50"'.encode('utf-8-sig'), 'a.csv')]:
            data = prepare(read_book(payload, name)['sheets'][0]['data'])
            self.assertEqual(analyze(data.rows, infer_mapping(data))['total'], Decimal('12.50'))
        book = read_book(b'Nome;Valor\n"linha\nseguinte";12', 'a.csv')
        self.assertEqual(len(book['sheets'][0]['data']), 2)

    def test_invalid_and_oversized_inputs(self):
        for payload, name in [(b'', 'a.csv'), (b'a;b\n"unterminated', 'a.csv'),
                              (b'not a workbook', 'a.xlsx'), (b'not a workbook', 'a.xls'),
                              (b'abc', 'a.exe'), (b'a;' * 201, 'a.csv')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                read_book(payload, name)

    def test_isolated_process_and_timeout(self):
        self.assertEqual(import_book(b'Nome;Valor\nAna;12', 'a.csv')['sheets'][0]['data'][1], ['Ana', '12'])
        with self.assertRaises(ValueError):
            import_book(b'invalid', 'a.xlsx')
        with self.assertRaisesRegex(ValueError, 'segundos'):
            import_book(b'Nome;Valor\nAna;12', 'a.csv', timeout=0)


if __name__ == '__main__':
    unittest.main()
