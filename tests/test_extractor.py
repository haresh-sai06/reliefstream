"""Unit tests for the LLM extractor's parsing and safety post-validation (LLM is mocked)."""
import json
from types import SimpleNamespace

import pytest

import extractor


def _fake_response(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def mock_llm(monkeypatch):
    def install(content=None, exc=None):
        def create(**kwargs):
            if exc:
                raise exc
            return _fake_response(content)
        monkeypatch.setattr(extractor._client.chat.completions, "create", create)
    return install


def test_clean_json_strips_code_fences():
    assert extractor._clean_json('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_clean_json_extracts_object_from_prose():
    assert json.loads(extractor._clean_json('Sure! {"a": 2} hope it helps')) == {"a": 2}


def test_extract_happy_path(mock_llm):
    mock_llm(json.dumps({
        "location": "Ganapathy 4th street", "urgency": "immediate", "request_type": "rescue",
        "people_count": 4, "contact": "98765-43210", "confidence": 0.9, "parseable": True,
    }))
    r = extractor.extract("Family of 4 stranded ...")
    assert r.parseable and r.people_count == 4 and r.urgency == "immediate"


def test_extract_forces_unparseable_when_location_missing(mock_llm):
    mock_llm(json.dumps({"location": None, "urgency": "high", "request_type": "rescue",
                         "confidence": 0.95, "parseable": True}))
    r = extractor.extract("help pls")
    assert r.parseable is False
    assert r.notes


def test_extract_forces_unparseable_on_low_confidence(mock_llm):
    mock_llm(json.dumps({"location": "Peelamedu", "urgency": "high", "request_type": "rescue",
                         "confidence": 0.2, "parseable": True}))
    assert extractor.extract("x y z").parseable is False


def test_malformed_json_goes_to_unparseable_pile(mock_llm):
    mock_llm("not json at all")
    r = extractor.extract("garbage")
    assert r.parseable is False and r.confidence == 0.0


def test_schema_violation_goes_to_unparseable_pile(mock_llm):
    mock_llm(json.dumps({"urgency": "apocalyptic", "request_type": "rescue"}))
    assert extractor.extract("x").parseable is False


def test_llm_outage_never_raises(mock_llm):
    mock_llm(exc=RuntimeError("connection refused"))
    r = extractor.extract("anything")
    assert r.parseable is False and "failed" in r.notes
