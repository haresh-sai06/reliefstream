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


_LOC_ABBREV = {
    "st": "street", "str": "street", "rd": "road", "ave": "avenue", "av": "avenue",
    "blvd": "boulevard", "ln": "lane", "dr": "drive", "hwy": "highway",
    "opp": "opposite", "nr": "near", "ft": "feet", "no": "number",
    "bunk": "pump",  # petrol bunk ≈ petrol pump (local usage)
}

_LOC_STOP = {
    "near", "opposite", "the", "at", "in", "of", "area", "please", "help",
    "needed", "urgent", "fwd", "forwarded", "rt",
}


def normalize_location(loc: str | None) -> str:
    """Lowercase, expand abbreviations, drop stopwords/punctuation."""
    if not loc:
        return ""
    s = loc.lower().replace("&", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    toks = []
    for t in s.split():
        t = _LOC_ABBREV.get(t, t)
        if t in _LOC_STOP or not t:
            continue
        toks.append(t)
    return " ".join(toks)


def location_similarity(a: str | None, b: str | None) -> float:
    """Token Jaccard / containment on normalised locations + SequenceMatcher.

    Also compares a Latin-only fold so Tamil/English transliterations of the
    same street still match on the shared Latin tokens. Conflicting house /
    street numbers (4th vs 2nd) force the score down.
    """
    from difflib import SequenceMatcher
    na, nb = normalize_location(a), normalize_location(b)
    if not na or not nb:
        return 1.0 if (not na and not nb) else 0.0
    ta, tb = set(na.split()), set(nb.split())
    jacc = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    # containment: shorter location covered by longer (LLM often stuffs extra
    # context into location). Require >=3 tokens on the shorter side so a bare
    # area name ("Peelamedu") does not match every street in that area.
    contain = 0.0
    if ta and tb and min(len(ta), len(tb)) >= 3:
        contain = len(ta & tb) / min(len(ta), len(tb))
    ratio = SequenceMatcher(None, na, nb).ratio()
    # Latin-only fold for mixed-script pairs (Tamil place name + English street)
    def latin_tokens(s: str) -> set[str]:
        return {tok for tok in s.split() if all(ord(ch) < 128 for ch in tok)}
    la, lb = latin_tokens(na), latin_tokens(nb)
    latin_jacc = len(la & lb) / len(la | lb) if (la and lb and (la | lb)) else 0.0
    latin_contain = 0.0
    if la and lb and min(len(la), len(lb)) >= 3:
        latin_contain = len(la & lb) / min(len(la), len(lb))
    score = max(jacc, contain, ratio, latin_jacc, latin_contain)
    nums_a = {tok for tok in ta if any(ch.isdigit() for ch in tok)}
    nums_b = {tok for tok in tb if any(ch.isdigit() for ch in tok)}
    # Penalise conflicting street numbers, but not when one side's numbers are a
    # subset (over-long LLM location adding "8 kids" etc.).
    if nums_a and nums_b and nums_a != nums_b and not (nums_a < nums_b or nums_b < nums_a):
        score *= 0.4
    return score


def _urgency_compatible(a: str | None, b: str | None) -> bool:
    if not a or not b or a == "unknown" or b == "unknown":
        return True
    if a == b:
        return True
    # adjacent bands still count as the same incident for dedup
    bands = {
        frozenset({"immediate", "high"}),
        frozenset({"high", "medium"}),
        frozenset({"medium", "low"}),
    }
    return frozenset({a, b}) in bands


def _type_compatible(a: str | None, b: str | None) -> bool:
    if not a or not b or a == "unknown" or b == "unknown":
        return True
    if a == b:
        return True
    # overlapping rescue/evacuation / medical+evacuation often co-labelled
    soft = {
        frozenset({"rescue", "evacuation"}),
        frozenset({"medical", "evacuation"}),
        frozenset({"food", "rescue"}),
        frozenset({"water", "food"}),
        frozenset({"water", "shelter"}),
        frozenset({"food", "shelter"}),
        frozenset({"shelter", "evacuation"}),
    }
    return frozenset({a, b}) in soft


def is_duplicate_extracted(
    a: ExtractedFields,
    b: ExtractedFields,
    text_a: str = "",
    text_b: str = "",
    loc_threshold: float = 0.75,
) -> bool:
    """Fuzzy duplicate decision used by upsert + eval (not tuned on hold-out)."""
    # Exact normalised text fallback for unparseable forwards
    if not (a.parseable and a.location) and not (b.parseable and b.location):
        return _fingerprint(text_a, a) == _fingerprint(text_b, b)
    if not (a.parseable and a.location and b.parseable and b.location):
        return False
    sim = location_similarity(a.location, b.location)
    if sim < loc_threshold:
        return False
    if not _type_compatible(a.request_type, b.request_type):
        return False
    # Near-identical location → urgency band mismatches are usually LLM noise
    if sim >= 0.95:
        return True
    if not _urgency_compatible(a.urgency, b.urgency):
        return False
    return True


def _fingerprint(text: str, extracted: ExtractedFields) -> str:
    """Deduplication hash: normalised location + type (+ coarse urgency) if extracted."""
    if extracted.parseable and extracted.location:
        loc = normalize_location(extracted.location)
        # Drop fine urgency from the exact hash — fuzzy layer handles band matches.
        key = f"{loc}|{extracted.request_type}"
    else:
        normalized = re.sub(r"\s+", " ", text.lower())
        normalized = re.sub(r"[^\w\s]", "", normalized).strip()
        key = normalized[:200]
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


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
    """Insert if new, else increment duplicate_count. Exact fingerprint first, then fuzzy location match."""
    fp = _fingerprint(text, extracted)
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        existing = c.execute(
            'SELECT * FROM requests WHERE fingerprint = ?', (fp,)
        ).fetchone()
        if not existing and extracted.parseable and extracted.location:
            # Fuzzy scan recent actionable rows (cap keeps this O(k) per insert)
            candidates = c.execute(
                "SELECT * FROM requests WHERE status != 'unparseable' "
                "ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
            for cand in candidates:
                other = ExtractedFields(**json.loads(cand['extracted']))
                if is_duplicate_extracted(extracted, other, text, cand['original_text']):
                    existing = cand
                    fp = cand['fingerprint']
                    break
        if existing:
            c.execute(
                'UPDATE requests SET duplicate_count = duplicate_count + 1, updated_at = ? '
                'WHERE fingerprint = ?', (now, existing['fingerprint'])
            )
            row = c.execute(
                'SELECT * FROM requests WHERE fingerprint = ?', (existing['fingerprint'],)
            ).fetchone()
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
