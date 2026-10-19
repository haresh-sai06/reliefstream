"""Fuzzy location dedup helpers."""
from storage import normalize_location, location_similarity, is_duplicate_extracted
from models import ExtractedFields


def test_normalize_expands_abbreviations():
    assert "street" in normalize_location("Ganapathy 4th st")
    assert normalize_location("Ganapathy 4th st") == normalize_location("Ganapathy 4th street")


def test_conflicting_street_numbers_low_similarity():
    assert location_similarity("Ganapathy 4th street", "Ganapathy 2nd street") < 0.75


def test_containment_overlong_llm_location():
    short = "Puliyakulam 2nd main"
    long = "Puliyakulam 2nd main opposite hospital, 8 kids in ground floor school building"
    assert location_similarity(short, long) >= 0.75


def test_latin_fold_tamil_transliteration():
    a = "சிங்காநல்லூர் aiyer street 3rd cross"
    b = "Singanallur Aiyer street 3rd cross"
    assert location_similarity(a, b) >= 0.75


def test_short_area_name_does_not_match_all_streets():
    assert location_similarity("Peelamedu", "Peelamedu Hope College") < 0.75


def test_is_duplicate_same_incident():
    a = ExtractedFields(location="Vadavalli Manikaran temple", urgency="low",
                        request_type="shelter", confidence=0.9, parseable=True)
    b = ExtractedFields(location="Vadavalli Manikaran temple", urgency="high",
                        request_type="food", confidence=0.9, parseable=True)
    assert is_duplicate_extracted(a, b)
