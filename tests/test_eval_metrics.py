"""Tests for the eval harness's scoring functions."""
from pathlib import Path

import run_eval

DATA = Path(__file__).resolve().parents[1] / "eval" / "labeled_messages.jsonl"


def test_location_match_token_overlap():
    assert run_eval.location_match("near Ganapathy 4th street opp petrol pump", "Ganapathy 4th street")
    assert not run_eval.location_match("Peelamedu", "Ganapathy 4th street")


def test_score_field_handles_acceptable_alternatives_and_nulls():
    assert run_eval.score_field("urgency", "high", ["immediate", "high"]) == (1, 0, 0)
    assert run_eval.score_field("urgency", "low", ["immediate", "high"]) == (0, 1, 1)
    assert run_eval.score_field("people_count", None, [1, None]) == (0, 0, 0)
    assert run_eval.score_field("people_count", None, 4) == (0, 0, 1)
    assert run_eval.score_field("contact", "+91 98765 43210".replace("+91 ", ""), "98765-43210") == (1, 0, 0)


def test_prf():
    assert run_eval.prf(1, 1, 0)["precision"] == 0.5


def test_dataset_is_well_formed():
    rows = run_eval.load(DATA)
    assert len(rows) >= 40
    assert len({r["id"] for r in rows}) == len(rows)
    for r in rows:
        assert set(r["gold"]) == {"parseable", "location", "urgency", "request_type", "people_count", "contact"}


def test_oracle_extractor_scores_perfect_extraction():
    res = run_eval.evaluate(run_eval.load(DATA), run_eval.gold_extractor)
    assert res["extraction_micro"]["f1"] == 1.0
    assert res["actionable_classification"]["f1"] == 1.0
