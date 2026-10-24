"""Synthetic storage and actual HTTP handler regressions; no model or network."""
import importlib
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import types
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from models import ExtractedFields
import storage


def fields(**changes):
    return ExtractedFields(location='Synthetic North Ward', urgency='high',
                           request_type='rescue', confidence=0.9,
                           parseable=True, **changes)


class StorageRegressionTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.db = str(Path(self.scratch.name) / 'synthetic.db')
        self.db_patch = patch.object(storage, 'DB_PATH', self.db)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        storage.init_db()

    def ingest(self, text='Household A needs rescue', source='paste', external_id=None, extracted=None):
        return storage.upsert_request(text, source, external_id, extracted or fields())

    def test_different_households_at_same_location_are_retained(self):
        first, _ = self.ingest(external_id='post-A', extracted=fields(contact='TEST-A', people_count=2))
        second, is_new = self.ingest('Household B needs rescue', external_id='post-B',
                                     extracted=fields(contact='TEST-B', people_count=7))
        self.assertTrue(is_new)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(storage.stats()['total'], 2)
        self.assertEqual(storage.get_request(second.id).extracted.contact, 'TEST-B')

    def test_external_ids_are_scoped_to_source(self):
        first, _ = self.ingest(source='channel-a', external_id='same-id')
        second, is_new = self.ingest(source='channel-b', external_id='same-id')
        self.assertTrue(is_new)
        self.assertNotEqual(first.id, second.id)

    def test_same_source_id_is_idempotent_when_message_changes(self):
        first, _ = self.ingest(source='channel-a', external_id='post-A')
        second, is_new = self.ingest('Edited message', source='channel-a', external_id='post-A')
        self.assertFalse(is_new)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.duplicate_count, 2)
        self.assertEqual(second.original_text, first.original_text)

    def test_full_message_and_punctuation_are_not_discarded(self):
        prefix = 'Synthetic shared context ' * 20
        values = [prefix + 'Unit A-1', prefix + 'Unit A1', prefix + 'Unit B-1']
        requests = [self.ingest(value)[0] for value in values]
        self.assertEqual(len({request.id for request in requests}), 3)

    def test_text_fallback_ignores_extraction_changes_and_case_spacing(self):
        first, _ = self.ingest('  Household A   needs rescue ')
        other_fields = fields().model_copy(update={'urgency': 'medium'})
        second, is_new = self.ingest('HOUSEHOLD A NEEDS RESCUE', extracted=other_fields)
        self.assertFalse(is_new)
        self.assertEqual(first.id, second.id)

    def test_text_fallback_is_scoped_to_source(self):
        first, _ = self.ingest(source='channel-a')
        second, is_new = self.ingest(source='channel-b')
        self.assertTrue(is_new)
        self.assertNotEqual(first.id, second.id)

    def test_concurrent_duplicate_ingests_create_one_request(self):
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(lambda _: self.ingest(external_id='same-post'), range(8)))
        self.assertEqual(sum(is_new for _, is_new in results), 1)
        self.assertEqual(len({request.id for request, _ in results}), 1)
        self.assertEqual(storage.get_request(results[0][0].id).duplicate_count, 8)

    def test_concurrent_claim_has_exactly_one_winner(self):
        request, _ = self.ingest()
        names = ['Synthetic A', 'Synthetic B']
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda name: storage.claim_request(request.id, name), names))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(storage.get_request(request.id).claimed_by, winners[0].claimed_by)

    def test_invalid_claim_and_repeated_triage_do_not_report_success(self):
        request, _ = self.ingest(extracted=ExtractedFields(parseable=False))
        self.assertIsNone(storage.claim_request(request.id, 'Synthetic A'))
        first = storage.triage_unparseable(request.id, 'Synthetic A', 'reviewed')
        self.assertIsNotNone(first)
        self.assertIsNone(storage.triage_unparseable(request.id, 'Synthetic B', 'overwrite'))
        self.assertEqual(storage.get_request(request.id).claimed_by, 'Synthetic A')
        self.assertIsNone(storage.claim_request('missing', 'Synthetic A'))

    def test_resolution_requires_claim_and_preserves_first_outcome(self):
        request, _ = self.ingest(extracted=ExtractedFields(parseable=False))
        self.assertIsNone(storage.resolve_request(request.id, 'Synthetic A', 'helped', 'too early'))
        storage.triage_unparseable(request.id, 'Synthetic A', 'reviewed')
        self.assertIsNone(storage.resolve_request(request.id, 'Synthetic A', 'helped', 'not claimed'))
        fresh, _ = self.ingest('Another synthetic household')
        self.assertIsNone(storage.resolve_request(fresh.id, 'Synthetic A', 'helped', 'not claimed'))
        storage.claim_request(request.id, 'Synthetic A')
        first = storage.resolve_request(request.id, 'Synthetic A', 'helped', 'original outcome')
        self.assertEqual(first.status, 'resolved')
        self.assertIsNone(storage.resolve_request(request.id, 'Synthetic B', 'wrong_info', 'overwrite'))
        self.assertEqual(storage.get_request(request.id), first)
        self.assertIsNone(storage.resolve_request('missing', 'Synthetic A', 'helped', None))

    def test_concurrent_resolutions_keep_exactly_one_outcome(self):
        request, _ = self.ingest()
        storage.claim_request(request.id, 'Synthetic A')
        attempts = [('Synthetic A', 'helped', 'first test outcome'),
                    ('Synthetic B', 'wrong_info', 'second test outcome')]
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda args: storage.resolve_request(request.id, *args), attempts))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(storage.get_request(request.id), winners[0])

    def test_legacy_migration_is_idempotent_and_preserves_all_rows(self):
        with closing(sqlite3.connect(self.db)) as connection:
            with connection:
                connection.execute('DROP TABLE request_identities')
                for index in range(2):
                    connection.execute(
                        'INSERT INTO requests (id,fingerprint,original_text,source,external_id,extracted,status,'
                        'claimed_by,duplicate_count,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (f'legacy-{index}', 'old-coarse-hash', 'Household A needs rescue', 'paste', 'post-A',
                         fields().model_dump_json(), 'claimed', f'Synthetic {index}', 4,
                         f'2026-01-0{index+1}T00:00:00', f'2026-01-0{index+1}T00:00:00'))
        storage.init_db()
        storage.init_db()
        self.assertEqual(storage.stats()['total'], 2)
        self.assertEqual(storage.get_request('legacy-1').claimed_by, 'Synthetic 1')
        repeated, is_new = self.ingest(external_id='post-A')
        self.assertFalse(is_new)
        self.assertEqual(repeated.id, 'legacy-0')
        self.assertEqual(repeated.duplicate_count, 5)
        self.assertEqual(storage.get_request('legacy-1').duplicate_count, 4)


class HTTPRegressionTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        db_patch = patch.object(storage, 'DB_PATH', str(Path(self.scratch.name) / 'http.db'))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        fake = types.ModuleType('extractor')
        fake.LLM_MODEL = 'synthetic-test'
        fake.LLM_BASE_URL = 'no-network'
        fake.extract = lambda text: ExtractedFields(parseable=False) if text == 'Ambiguous request' else fields()
        with patch.dict(sys.modules, {'extractor': fake}):
            sys.modules.pop('main', None)
            self.main = importlib.import_module('main')
        self.events = AsyncMock()
        events_patch = patch.object(self.main, '_broadcast', self.events)
        events_patch.start()
        self.addCleanup(events_patch.stop)
        from fastapi.testclient import TestClient
        self.client = TestClient(self.main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_api_retains_households_and_does_not_broadcast_failed_claim(self):
        first = self.client.post('/ingest', json={'text': 'Household A needs rescue', 'external_id': 'A'})
        second = self.client.post('/ingest', json={'text': 'Household B needs rescue', 'external_id': 'B'})
        self.assertEqual(first.status_code, 200)
        self.assertNotEqual(first.json()['id'], second.json()['id'])
        rid = first.json()['id']
        self.events.reset_mock()
        self.assertEqual(self.client.post(f'/requests/{rid}/claim', json={'volunteer_name': 'Synthetic A'}).status_code, 200)
        self.assertEqual(self.client.post(f'/requests/{rid}/claim', json={'volunteer_name': 'Synthetic B'}).status_code, 409)
        self.assertEqual(self.events.await_count, 1)
        self.assertEqual(self.events.await_args.args[0]['by'], 'Synthetic A')
        self.assertEqual(self.client.get(f'/requests/{rid}').json()['claimed_by'], 'Synthetic A')
        self.assertEqual(self.client.post('/requests/missing/claim', json={'volunteer_name': 'Synthetic B'}).status_code, 404)
        self.assertEqual(self.events.await_count, 1)

    def test_api_rejects_repeated_triage_without_success_event(self):
        request = self.client.post('/ingest', json={'text': 'Ambiguous request'}).json()
        self.events.reset_mock()
        path = f"/requests/{request['id']}/triage"
        self.assertEqual(self.client.post(path, json={'volunteer_name': 'Synthetic A'}).status_code, 200)
        self.assertEqual(self.client.post(path, json={'volunteer_name': 'Synthetic B'}).status_code, 409)
        self.assertEqual(self.events.await_count, 1)

    def test_api_rejects_invalid_resolution_and_emits_one_success_event(self):
        request = self.client.post('/ingest', json={'text': 'Household A needs rescue'}).json()
        path = f"/requests/{request['id']}/resolve"
        payload = {'volunteer_name': 'Synthetic A', 'outcome': 'helped', 'note': 'original outcome'}
        self.events.reset_mock()
        self.assertEqual(self.client.post(path, json=payload).status_code, 409)
        self.assertEqual(self.events.await_count, 0)
        self.client.post(f"/requests/{request['id']}/claim", json={'volunteer_name': 'Synthetic A'})
        self.events.reset_mock()
        first = self.client.post(path, json=payload)
        self.assertEqual(first.status_code, 200)
        payload.update(volunteer_name='Synthetic B', outcome='wrong_info', note='overwrite')
        self.assertEqual(self.client.post(path, json=payload).status_code, 409)
        self.assertEqual(self.client.get(f"/requests/{request['id']}").json(), first.json())
        self.assertEqual(self.events.await_count, 1)
        self.assertEqual(self.events.await_args.args[0]['outcome'], 'helped')
        self.assertEqual(self.client.post('/requests/missing/resolve', json=payload).status_code, 404)
        self.assertEqual(self.events.await_count, 1)


if __name__ == '__main__':
    unittest.main()
