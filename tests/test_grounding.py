"""Deterministic extraction guards. No model and no network."""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from extractor import ground_to_source
from models import ExtractedFields


def extracted(**changes):
    values = dict(location='Ganapathy street', urgency='immediate', request_type='rescue',
                  confidence=0.9, parseable=True, contact='9876543210')
    values.update(changes)
    return ExtractedFields(**values)


class GroundingTests(unittest.TestCase):
    def test_invented_phone_place_and_coordinates_are_dropped(self):
        raw = 'Family stranded near Ganapathy street contact 9876543210'
        result = ground_to_source(
            extracted(location='Anna Nagar tower', contact='9000000000', lat=11.0168, lon=76.9558),
            raw,
        )
        self.assertIsNone(result.contact)
        self.assertIsNone(result.location)
        self.assertIsNone(result.lat)
        self.assertIsNone(result.lon)
        self.assertFalse(result.parseable)
        self.assertIn('not grounded', result.notes)

    def test_phone_punctuation_and_place_from_the_message_are_kept(self):
        raw = 'Family stranded near Ganapathy street contact 98765-43210'
        result = ground_to_source(extracted(), raw)
        self.assertEqual(result.contact, '9876543210')
        self.assertEqual(result.location, 'Ganapathy street')
        self.assertTrue(result.parseable)

    def test_short_hallucinated_place_is_dropped(self):
        raw = 'Need a boat near the kovil'
        result = ground_to_source(extracted(location='Pune'), raw)
        self.assertIsNone(result.location)
        self.assertFalse(result.parseable)

    def test_status_update_is_not_treated_as_a_request(self):
        raw = ('Water levels reducing in Sundakkamuthur area, our team already '
               'helped 8 families, can move to next area')
        result = ground_to_source(
            extracted(location='Sundakkamuthur area', urgency='low', request_type='other'),
            raw,
        )
        self.assertEqual(result.location, 'Sundakkamuthur area')
        self.assertFalse(result.parseable)
        self.assertIn('does not read as a request', result.notes)

    def test_tamil_text_is_not_blocked_for_missing_english_cues(self):
        raw = 'சிங்காநல்லூர் aiyer street 3rd cross ல water level 5 feet'
        result = ground_to_source(extracted(location='சிங்காநல்லூர் aiyer street'), raw)
        self.assertTrue(result.parseable)


class CorpusLabelTests(unittest.TestCase):
    def test_safety_labels_match_the_checked_in_corpus(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / 'tests' / 'run_corpus_eval.py').read_text(encoding='utf-8')
        labels = ast.literal_eval(script.split('NOT_A_REQUEST = ', 1)[1].split('\n}\n', 1)[0] + '\n}')
        corpus = {
            line.strip() for line in (root / 'sample_data' / 'rescue_messages.txt').read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.startswith('#')
        }
        missing = set(labels) - corpus
        self.assertEqual(missing, set())
        self.assertGreater(len(corpus - set(labels)), 0)
