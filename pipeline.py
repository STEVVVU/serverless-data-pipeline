"""Sales transform/load/query core; local and Google Cloud backends are explicit."""
import csv
import io
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation

FIELDS = ['Region', 'Country', 'Item Type', 'Sales Channel', 'Order Priority', 'Order Date', 'Order ID', 'Ship Date', 'Units Sold', 'Unit Price', 'Unit Cost', 'Total Revenue', 'Total Cost', 'Total Profit']
MAX_BYTES = 2_000_000
MAX_ROWS = 1000


def valid_money(value: Decimal) -> bool:
    exponent = value.as_tuple().exponent
    return value.is_finite() and abs(value) <= Decimal('1000000000000') and isinstance(exponent, int) and exponent >= -2


def transform(data):
    if not isinstance(data, str):
        raise ValueError('CSV must be a string')
    if len(data.encode('utf-8')) > MAX_BYTES:
        raise ValueError('CSV exceeds size limit')
    reader = csv.DictReader(io.StringIO(data, newline=''))
    if reader.fieldnames != FIELDS:
        raise ValueError('CSV header does not match sales schema')
    result, seen = [], set()
    for index, row in enumerate(reader):
        if index >= MAX_ROWS:
            raise ValueError('CSV exceeds row limit')
        if None in row or any(not isinstance(row[k], str) or not row[k].strip() for k in FIELDS):
            raise ValueError('missing or extra field')
        order_id = row['Order ID']
        if not order_id.isascii() or not order_id.isdigit() or len(order_id) > 20:
            raise ValueError('invalid order ID')
        if order_id in seen:
            continue
        seen.add(order_id)
        try:
            priority = {'L': 'Low', 'M': 'Medium', 'H': 'High', 'C': 'Critical'}[row['Order Priority']]
            days = (datetime.strptime(row['Ship Date'], '%m/%d/%Y') - datetime.strptime(row['Order Date'], '%m/%d/%Y')).days
            units = int(row['Units Sold'])
            amounts = [Decimal(row[key]) for key in FIELDS[-5:]]
            if days < 0 or units < 0 or any(not valid_money(x) for x in amounts):
                raise ValueError('invalid numeric value')
            revenue, profit = amounts[-3], amounts[-1]
            margin = None if revenue == 0 else str(profit / revenue)
        except (KeyError, ValueError, InvalidOperation, OverflowError) as exc:
            raise ValueError('invalid sales row') from exc
        result.append({'id': order_id, 'region': row['Region'], 'country': row['Country'], 'item_type': row['Item Type'], 'channel': row['Sales Channel'], 'priority': priority, 'days': days, 'units': units, 'revenue': str(revenue), 'profit': str(profit), 'margin': margin})
    return result


def load(rows):
    validate_rows(rows)
    if os.environ.get('BACKEND', 'local') == 'firestore':
        from google.cloud import firestore
        db = firestore.Client()
        # Each document is atomic and keyed by order ID; existing records win.
        for row in rows:
            try:
                db.collection(os.environ['FIRESTORE_COLLECTION']).document(row['id']).create(row)
            except Exception as exc:
                from google.api_core.exceptions import Conflict
                if not isinstance(exc, Conflict):
                    raise
    else:
        with closing(sqlite3.connect(os.environ['SQLITE_PATH'])) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            db.executemany('INSERT OR IGNORE INTO orders VALUES (?, ?)', [(r['id'], json.dumps(r)) for r in rows])
    return {'accepted': len(rows)}


def validate_rows(rows):
    fields = {'id', 'region', 'country', 'item_type', 'channel', 'priority', 'days', 'units', 'revenue', 'profit', 'margin'}
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError('invalid records')
    for r in rows:
        if not isinstance(r, dict) or set(r) != fields or not isinstance(r['id'], str) or not r['id'].isascii() or not r['id'].isdigit() or len(r['id']) > 20:
            raise ValueError('invalid record')
        if any(not isinstance(r[k], str) or not r[k].strip() or len(r[k]) > 200 for k in ('region', 'country', 'item_type', 'channel')) or r['priority'] not in ('Low', 'Medium', 'High', 'Critical'):
            raise ValueError('invalid attributes')
        if any(type(r[k]) is not int or not 0 <= r[k] <= 1_000_000_000 for k in ('days', 'units')):
            raise ValueError('invalid integer')
        try:
            revenue, profit = (Decimal(r[k]) for k in ('revenue', 'profit'))
            if any(not isinstance(r[k], str) for k in ('revenue', 'profit')) or any(not valid_money(x) for x in (revenue, profit)):
                raise ValueError('invalid money')
            if r['margin'] != (None if revenue == 0 else str(profit / revenue)):
                raise ValueError('invalid margin')
        except (InvalidOperation, TypeError) as exc:
            raise ValueError('invalid money') from exc


def query(filters, group_by=None):
    allowed = {'region', 'country', 'item_type', 'channel', 'priority'}
    if not isinstance(filters, dict) or any(k not in allowed or not isinstance(v, str) for k, v in filters.items()):
        raise ValueError('invalid filters')
    if group_by is not None and (not isinstance(group_by, list) or len(set(group_by)) != len(group_by) or any(k not in allowed for k in group_by)):
        raise ValueError('invalid grouping')
    if os.environ.get('BACKEND', 'local') == 'firestore':
        from google.cloud import firestore
        rows = [d.to_dict() for d in firestore.Client().collection(os.environ['FIRESTORE_COLLECTION']).stream()]
    else:
        with closing(sqlite3.connect(os.environ['SQLITE_PATH'])) as db:
            rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM orders')]
    rows = [r for r in rows if all(r[k] == v for k, v in filters.items())]
    def aggregate(items):
        margins = [Decimal(r['margin']) for r in items if r['margin'] is not None]
        return {'count': len(items), 'units': sum(r['units'] for r in items), 'min_units': min((r['units'] for r in items), default=None), 'max_units': max((r['units'] for r in items), default=None), 'average_units': str(Decimal(sum(r['units'] for r in items)) / len(items)) if items else None, 'revenue': str(sum((Decimal(r['revenue']) for r in items), Decimal(0))), 'profit': str(sum((Decimal(r['profit']) for r in items), Decimal(0))), 'average_days': str(sum((Decimal(r['days']) for r in items), Decimal(0)) / len(items)) if items else None, 'average_margin': str(sum(margins, Decimal(0)) / len(margins)) if margins else None}
    if not group_by:
        return aggregate(rows)
    groups: dict[tuple, list] = {}
    for row in rows:
        key = tuple(row[k] for k in group_by)
        groups.setdefault(key, []).append(row)
    return [{**dict(zip(group_by, key)), **aggregate(items)} for key, items in sorted(groups.items())]


def fetch_object(name):
    if not isinstance(name, str) or not name or '..' in name or name.startswith('/'):
        raise ValueError('invalid object name')
    if os.environ.get('BACKEND', 'local') == 'firestore':
        from google.cloud import storage
        blob = storage.Client().bucket(os.environ['GCS_BUCKET']).blob(name)
        blob.reload()
        if blob.size > MAX_BYTES:
            raise ValueError('object exceeds size limit')
        data = blob.download_as_bytes(if_generation_match=blob.generation, raw_download=True)
        if len(data) > MAX_BYTES:
            raise ValueError('object exceeds size limit')
        return data.decode('utf-8')
    root = os.path.realpath(os.environ['OBJECT_DIR'])
    path = os.path.realpath(os.path.join(root, name))
    if os.path.commonpath([root, path]) != root:
        raise ValueError('invalid object name')
    with open(path, 'rb') as f:
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('object exceeds size limit')
    return data.decode('utf-8')
