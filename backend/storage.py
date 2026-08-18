"""SQLite persistence for ReliefStream. One file, no server, backup by cp."""
import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from models import ExtractedFields, RescueRequest

DB_PATH = os.getenv('DATABASE_PATH', 'reliefstream.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id            TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    original_text TEXT NOT NULL,
    source        TEXT NOT NULL,
    external_id   TEXT,
    extracted     TEXT NOT NULL,      -- JSON blob of ExtractedFields
    status        TEXT NOT NULL DEFAULT 'new',
    claimed_by    TEXT,
    resolved_by   TEXT,
    resolved_note TEXT,
    duplicate_count INTEGER DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fingerprint ON requests(fingerprint);
CREATE INDEX IF NOT EXISTS idx_status ON requests(status);
CREATE INDEX IF NOT EXISTS idx_created ON requests(created_at DESC);
"""


@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with _conn() as c:
        c.executescript(SCHEMA)


def _fingerprint(text: str, extracted: ExtractedFields) -> str:
    """Deduplication hash: normalized text OR (location + urgency + type) if extracted."""
    if extracted.parseable and extracted.location:
        key = f'{extracted.location.lower().strip()}|{extracted.request_type}|{extracted.urgency}'
    else:
        # Normalize whitespace + punctuation for text-only fingerprint
        normalized = re.sub(r'\s+', ' ', text.lower())
        normalized = re.sub(r'[^\w\s]', '', normalized).strip()
        key = normalized[:200]
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]


def _row_to_request(row: sqlite3.Row) -> RescueRequest:
    return RescueRequest(
        id=row['id'],
        fingerprint=row['fingerprint'],
        original_text=row['original_text'],
        source=row['source'],
        external_id=row['external_id'],
        extracted=ExtractedFields(**json.loads(row['extracted'])),
        status=row['status'],
        claimed_by=row['claimed_by'],
        resolved_by=row['resolved_by'],
        resolved_note=row['resolved_note'],
        duplicate_count=row['duplicate_count'],
        created_at=datetime.fromisoformat(row['created_at']),
        updated_at=datetime.fromisoformat(row['updated_at']),
    )


def upsert_request(text: str, source: str, external_id: Optional[str],
                    extracted: ExtractedFields) -> tuple[RescueRequest, bool]:
    """Insert if new fingerprint, else increment duplicate_count. Returns (request, is_new)."""
    fp = _fingerprint(text, extracted)
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        existing = c.execute(
            'SELECT * FROM requests WHERE fingerprint = ?', (fp,)
        ).fetchone()
        if existing:
            c.execute(
                'UPDATE requests SET duplicate_count = duplicate_count + 1, updated_at = ? '
                'WHERE fingerprint = ?', (now, fp)
            )
            row = c.execute('SELECT * FROM requests WHERE fingerprint = ?', (fp,)).fetchone()
            return _row_to_request(row), False
        rid = str(uuid.uuid4())[:12]
        status = 'unparseable' if not extracted.parseable else 'new'
        c.execute(
            'INSERT INTO requests (id, fingerprint, original_text, source, external_id, '
            'extracted, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (rid, fp, text, source, external_id,
             extracted.model_dump_json(), status, now, now)
        )
        row = c.execute('SELECT * FROM requests WHERE id = ?', (rid,)).fetchone()
        return _row_to_request(row), True


def list_requests(status: Optional[str] = None, limit: int = 500) -> list[RescueRequest]:
    with _conn() as c:
        if status:
            rows = c.execute(
                'SELECT * FROM requests WHERE status = ? ORDER BY created_at DESC LIMIT ?',
                (status, limit)
            ).fetchall()
        else:
            rows = c.execute(
                'SELECT * FROM requests ORDER BY created_at DESC LIMIT ?', (limit,)
            ).fetchall()
    return [_row_to_request(r) for r in rows]


def get_request(rid: str) -> Optional[RescueRequest]:
    with _conn() as c:
        row = c.execute('SELECT * FROM requests WHERE id = ?', (rid,)).fetchone()
    return _row_to_request(row) if row else None


def claim_request(rid: str, volunteer: str) -> Optional[RescueRequest]:
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            'UPDATE requests SET status = ?, claimed_by = ?, updated_at = ? '
            'WHERE id = ? AND status IN (?, ?)',
            ('claimed', volunteer, now, rid, 'new', 'triaged')
        )
    return get_request(rid)


def triage_unparseable(rid: str, volunteer: str, note: str) -> Optional[RescueRequest]:
    """Move an unparseable request into the actionable queue after human review."""
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            'UPDATE requests SET status = ?, claimed_by = ?, resolved_note = ?, updated_at = ? '
            'WHERE id = ? AND status = ?',
            ('triaged', volunteer, note, now, rid, 'unparseable')
        )
    return get_request(rid)


def resolve_request(rid: str, volunteer: str, outcome: str, note: Optional[str]) -> Optional[RescueRequest]:
    now = datetime.utcnow().isoformat()
    combined_note = f'[{outcome}] {note or ""}'.strip()
    with _conn() as c:
        c.execute(
            'UPDATE requests SET status = ?, resolved_by = ?, resolved_note = ?, updated_at = ? '
            'WHERE id = ?',
            ('resolved', volunteer, combined_note, now, rid)
        )
    return get_request(rid)


def stats() -> dict:
    with _conn() as c:
        total = c.execute('SELECT COUNT(*) AS n FROM requests').fetchone()['n']
        by_status = {r['status']: r['n'] for r in c.execute(
            "SELECT status, COUNT(*) AS n FROM requests GROUP BY status"
        ).fetchall()}
        rows_urg = c.execute(
            "SELECT json_extract(extracted, '$.urgency') AS u, COUNT(*) AS n "
            "FROM requests WHERE status != 'unparseable' GROUP BY u"
        ).fetchall()
        by_urgency = {r['u'] or 'unknown': r['n'] for r in rows_urg}
        rows_type = c.execute(
            "SELECT json_extract(extracted, '$.request_type') AS t, COUNT(*) AS n "
            "FROM requests WHERE status != 'unparseable' GROUP BY t"
        ).fetchall()
        by_type = {r['t'] or 'unknown': r['n'] for r in rows_type}
    return {
        'total': total,
        'new': by_status.get('new', 0),
        'triaged': by_status.get('triaged', 0),
        'claimed': by_status.get('claimed', 0),
        'resolved': by_status.get('resolved', 0),
        'unparseable': by_status.get('unparseable', 0),
        'by_urgency': by_urgency,
        'by_type': by_type,
    }
