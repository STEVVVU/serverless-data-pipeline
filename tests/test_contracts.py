"""SDK boundary contract tests: no emulator or cloud calls are made."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from google.api_core.exceptions import Conflict
from pipeline import fetch_object, load, transform, validate_rows


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.rows = transform(Path('sample.csv').read_text())

    @patch.dict(os.environ, {'BACKEND': 'firestore', 'GCS_BUCKET': 'bucket'})
    @patch('google.cloud.storage.Client')
    def test_storage_generation_bound_download(self, client):
        blob = client.return_value.bucket.return_value.blob.return_value
        blob.size, blob.generation = 3, 17
        blob.download_as_bytes.return_value = b'csv'
        self.assertEqual(fetch_object('sales.csv'), 'csv')
        blob.download_as_bytes.assert_called_once_with(if_generation_match=17, raw_download=True)

    @patch.dict(os.environ, {'BACKEND': 'firestore', 'FIRESTORE_COLLECTION': 'orders'})
    @patch('google.cloud.firestore.Client')
    def test_firestore_create_and_duplicate(self, client):
        document = client.return_value.collection.return_value.document.return_value
        document.create.side_effect = [None, Conflict('duplicate')]
        self.assertEqual(load(self.rows), {'accepted': 2})
        self.assertEqual(document.create.call_count, 2)
        client.return_value.collection.assert_called_with('orders')

    def test_load_rejects_forged_money(self):
        for bad in (float('nan'), 'NaN', '1.001', '999999999999999'):
            row = {**self.rows[0], 'revenue': bad}
            with self.assertRaises(ValueError):
                validate_rows([row])
        with self.assertRaises(ValueError):
            validate_rows([{**self.rows[0], 'margin': '1'}])


if __name__ == '__main__':
    unittest.main()
