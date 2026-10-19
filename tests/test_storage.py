"""Storage + dedup tests against a temporary SQLite file."""
import pytest

import storage
from models import ExtractedFields


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "t.db"))
    storage.init_db()


def _ext(**kw):
    base = dict(location="Ganapathy 4th street", urgency="immediate", request_type="rescue",
                confidence=0.9, parseable=True)
    base.update(kw)
    return ExtractedFields(**base)


def test_new_request_is_inserted():
    r, is_new = storage.upsert_request("a", "paste", None, _ext())
    assert is_new and r.status == "new" and r.duplicate_count == 1


def test_same_location_type_urgency_is_deduplicated():
    a, _ = storage.upsert_request("msg one", "paste", None, _ext())
    b, is_new = storage.upsert_request("msg two (forward)", "whatsapp", None, _ext(location="  GANAPATHY 4th Street "))
    assert not is_new and a.id == b.id and b.duplicate_count == 2


def test_unparseable_uses_normalised_text_fingerprint():
    bad = ExtractedFields(parseable=False)
    a, _ = storage.upsert_request("Test message, please ignore!", "paste", None, bad)
    b, is_new = storage.upsert_request("test   message please IGNORE", "paste", None, bad)
    assert not is_new and a.id == b.id
    assert a.status == "unparseable"


def test_workflow_claim_resolve_and_stats():
    r, _ = storage.upsert_request("a", "paste", None, _ext())
    assert storage.claim_request(r.id, "Asha").status == "claimed"
    done = storage.resolve_request(r.id, "Asha", "helped", "boat reached")
    assert done.status == "resolved" and "[helped]" in done.resolved_note
    s = storage.stats()
    assert s["total"] == 1 and s["resolved"] == 1


def test_triage_only_moves_unparseable():
    r, _ = storage.upsert_request("hmm", "paste", None, ExtractedFields(parseable=False))
    assert storage.triage_unparseable(r.id, "Ops", "human-triaged").status == "triaged"
