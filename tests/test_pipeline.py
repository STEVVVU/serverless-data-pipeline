import unittest
from pathlib import Path
from pipeline import transform


class TransformTests(unittest.TestCase):
    def setUp(self):
        self.csv = Path('sample.csv').read_text()

    def test_transform_and_duplicate(self):
        rows = transform(self.csv)
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]['priority'], rows[0]['days'], rows[0]['margin']), ('High', 2, '0.4'))

    def test_invalid_priority_and_header(self):
        with self.assertRaises(ValueError):
            transform(self.csv.replace(',H,', ',X,'))
        with self.assertRaises(ValueError):
            transform(self.csv.replace('Region,', 'Bad,'))

    def test_non_string_csv_rejected(self):
        for value in (17, None, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                transform(value)

    def test_zero_revenue(self):
        rows = transform(self.csv.replace('20.00,12.00,8.00', '0.00,12.00,8.00'))
        self.assertIsNone(rows[0]['margin'])


if __name__ == '__main__':
    unittest.main()
