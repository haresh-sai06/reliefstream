"""API tests with FastAPI TestClient; the LLM extractor is replaced by a stub."""
import pytest
from fastapi.testclient import TestClient

from models import ExtractedFields


@pytest.fixture
def client(tmp_path, monkeypatch):
    import extractor
    import main
    import storage

    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "api.db"))

    def fake_extract(text):
        if "rooftop" in text:
            return ExtractedFields(location="Ganapathy", urgency="immediate", request_type="rescue",
                                   people_count=4, confidence=0.9, parseable=True)
        return ExtractedFields(parseable=False, notes="not a request")

    monkeypatch.setattr(extractor, "extract", fake_extract)
    with TestClient(main.app) as c:
        yield c


def test_root_lists_endpoints(client):
    assert "POST /ingest" in client.get("/").json()["endpoints"]


def test_health(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_ingest_and_list(client):
    r = client.post("/ingest", json={"text": "family on rooftop help"}).json()
    assert r["status"] == "new" and r["extracted"]["people_count"] == 4
    assert len(client.get("/requests").json()) == 1


def test_bulk_dedup_and_unparseable(client):
    body = [{"text": "family on rooftop help"}, {"text": "family on rooftop help!!"}, {"text": "nice weather"}]
    out = client.post("/ingest/bulk", json=body).json()
    assert out["processed"] == 3
    assert [x["is_new"] for x in out["results"]] == [True, False, True]
    stats = client.get("/stats").json()
    assert stats["total"] == 2 and stats["unparseable"] == 1


def test_claim_unknown_returns_404(client):
    assert client.post("/requests/nope/claim", json={"volunteer_name": "A"}).status_code == 404


def test_input_validation(client):
    assert client.post("/ingest", json={"text": "a"}).status_code == 422
