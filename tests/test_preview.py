"""Non-binding reconciliation preview tests. No live DNS or API credentials."""
import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from zog.network_register.contracts import NetworkError, Page
from zog.network_register.engine import DnsEngine
from zog.network_register.ledger import OperationLedger
from zog.network_register.models import Connection, RecordSnapshot, ZoneBinding
from zog.network_register.store import SqliteStateStore


RESOURCE = '12345678-1234-1234-1234-123456789abc'


class Auth:
    allowed = True

    def authorize(self, *args):
        return self.allowed


class Gate:
    denied = False

    def check(self, *args):
        if self.denied:
            raise NetworkError('permission')


class Provider:
    def __init__(self):
        self.rows = []
        self.writes = []
        self.reads = 0
        self.read_error = None
        self.on_list = None
        self.zone = dict(
            id='zone', name='example.com',
            account={'id': 'account'}, status='active')

    def get_zone(self, zone_id):
        return copy.deepcopy(self.zone)

    def list_records(self, zone_id, cursor=None):
        self.reads += 1
        if self.on_list:
            callback, self.on_list = self.on_list, None
            callback()
        if self.read_error:
            raise self.read_error
        return Page(tuple(copy.deepcopy(self.rows)))

    def create_record(self, zone_id, snapshot, *, marker, idempotency_key):
        self.writes.append('create')
        row = dict(
            id='record', name=snapshot.name, type='A',
            content=snapshot.address, ttl=snapshot.ttl,
            proxied=False, comment=marker)
        self.rows.append(row)
        return copy.deepcopy(row)

    def update_record(self, zone_id, record_id, snapshot, *, marker, idempotency_key):
        self.writes.append('update')
        row = dict(
            id=record_id, name=snapshot.name, type='A',
            content=snapshot.address, ttl=snapshot.ttl,
            proxied=False, comment=marker)
        self.rows = [row if old['id'] == record_id else old for old in self.rows]
        return copy.deepcopy(row)

    def delete_record(self, zone_id, record_id, *, idempotency_key):
        self.writes.append('delete')
        self.rows = [row for row in self.rows if row['id'] != record_id]


class PreviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = SqliteStateStore(Path(temp.name) / 'data.sqlite', create=True)
        self.auth = Auth()
        self.gate = Gate()
        self.provider = Provider()
        self.ledger = OperationLedger(self.store, self.auth, lambda: 1000)
        self.connection = Connection(
            'connection', 'owner', 'cloudflare', 'account', 'vault:1',
            status='ready')
        self.binding = ZoneBinding(
            'binding', 'owner', 'connection', 'zone',
            'example.com', 'hosts.example.com', status='ready')
        self.ledger.put_connection('admin', self.connection, 0)
        self.ledger.put_binding('admin', self.binding, 0)
        self.engine = DnsEngine(
            self.ledger, self.gate, provider_factory=lambda c: self.provider)
        self.desired = RecordSnapshot(
            'one.hosts.example.com', '8.8.8.8', 300)

    def preview(self, desired=None, *, rev=1, delete=False):
        return self.engine.preview(
            'admin', 'owner', 'binding', RESOURCE,
            None if delete else desired or self.desired, rev, delete=delete)

    def seed(self):
        plan = self.engine.plan(
            'admin', 'owner', 'binding', RESOURCE, self.desired, 1)
        row = self.ledger.prepare('admin', 'seed', plan)
        outcome = self.engine.apply('admin', 'owner', 'seed', row['revision'])
        self.assertEqual(outcome['state'], 'succeeded')
        self.assertEqual(self.provider.writes, ['create'])
        self.provider.writes.clear()
        return outcome

    def state(self):
        with self.store.transaction():
            return {
                kind: copy.deepcopy(self.store.all(kind))
                for kind in ('connection', 'binding', 'operation', 'record',
                             'reservation')}

    def test_new_record_candidate_is_read_only_and_serializable(self):
        before = self.state()
        preview = self.preview()
        self.assertEqual((preview.outcome, preview.proposed_action, preview.reason),
                         ('candidate', 'create', 'create-candidate'))
        self.assertTrue(preview.authorized)
        self.assertEqual(preview.provider, 'cloudflare')
        self.assertEqual(preview.observed_count, 0)
        self.assertEqual(preview.hostname, self.desired.name)
        self.assertEqual(self.provider.writes, [])
        self.assertEqual(self.state(), before)
        data = json.loads(json.dumps(preview.to_dict()))
        self.assertEqual(data['schema'], 1)
        self.assertTrue(data['read_only'])
        self.assertEqual(data['desired']['address'], '8.8.8.8')

    def test_existing_record_noop_and_update_candidates(self):
        self.seed()
        before = self.state()
        noop = self.preview(rev=2)
        self.assertEqual((noop.outcome, noop.proposed_action, noop.reason),
                         ('no-op', 'none', 'already-matches'))
        self.assertEqual(noop.observed_count, 1)
        self.assertTrue(noop.observed[0].matches_last_applied)
        self.assertEqual(noop.observed[0].address, '8.8.8.8')
        change = self.preview(
            replace(self.desired, address='9.9.9.9'), rev=2)
        self.assertEqual((change.outcome, change.proposed_action),
                         ('candidate', 'update'))
        self.assertEqual(self.provider.writes, [])
        self.assertEqual(self.state(), before)

    def test_delete_candidate_is_explicit_and_non_binding(self):
        self.seed()
        prior = self.state()
        proposed = self.preview(rev=2, delete=True)
        self.assertEqual((proposed.outcome, proposed.proposed_action),
                         ('candidate', 'delete'))
        self.assertIsNone(proposed.desired)
        self.assertEqual(self.state(), prior)
        self.assertEqual(self.provider.writes, [])

    def test_explicit_delete_for_unknown_resource_does_not_claim_absence(self):
        response = self.preview(delete=True)
        self.assertEqual((response.outcome, response.reason),
                         ('no-op', 'not-managed'))
        self.assertIsNone(response.observed_count)
        self.assertIsNone(response.authorized)
        self.assertEqual(self.provider.reads, 0)

    def test_foreign_record_blocks_without_poisoning_binding(self):
        self.provider.rows = [
            dict(id='foreign', name=self.desired.name, type='A',
                 content='8.8.8.8', ttl=300, proxied=False,
                 comment='secret provider note')]
        prior = self.state()
        response = self.preview()
        self.assertEqual((response.outcome, response.reason),
                         ('blocked', 'unmanaged-record'))
        self.assertEqual(response.observed_count, 1)
        self.assertFalse(response.observed[0].matches_last_applied)
        self.assertNotIn('secret provider note', json.dumps(response.to_dict()))
        self.assertEqual(self.state(), prior)
        self.assertEqual(self.provider.writes, [])

    def test_owned_record_drift_is_not_modified(self):
        self.seed()
        self.provider.rows[0]['ttl'] = 600
        prior = self.state()
        response = self.preview(rev=2)
        self.assertEqual((response.outcome, response.reason),
                         ('blocked', 'owned-record-drift'))
        self.assertEqual(self.state(), prior)
        self.assertEqual(self.provider.writes, [])

    def test_parent_alias_conflict_blocks_without_binding_side_effects(self):
        self.provider.rows = [
            dict(id='alias', name='hosts.example.com', type='CNAME',
                 content='other.example.com')]
        prior = self.state()
        response = self.preview()
        self.assertEqual((response.outcome, response.reason),
                         ('blocked', 'provider-conflict'))
        self.assertEqual(self.state(), prior)

    def test_unrelated_txt_at_name_is_not_a_conflict(self):
        self.provider.rows = [
            dict(id='txt', name=self.desired.name, type='TXT',
                 content='unrelated')]
        response = self.preview()
        self.assertEqual(response.outcome, 'candidate')
        self.assertEqual(response.observed_count, 0)

    def test_pending_operation_blocks_preview_without_provider_read(self):
        plan = self.engine.plan(
            'admin', 'owner', 'binding', RESOURCE, self.desired, 1)
        self.ledger.prepare('admin', 'pending', plan)
        before = self.state()
        reads = self.provider.reads
        response = self.preview()
        self.assertEqual((response.outcome, response.reason),
                         ('blocked', 'pending-operation'))
        self.assertIsNone(response.observed_count)
        self.assertEqual(self.provider.reads, reads)
        self.assertEqual(self.state(), before)

    def test_gate_denial_is_reported_without_inventory(self):
        self.gate.denied = True
        response = self.preview()
        self.assertEqual((response.outcome, response.reason),
                         ('blocked', 'publication-permission'))
        self.assertIs(response.authorized, False)
        self.assertEqual(self.provider.reads, 0)
        self.assertEqual(self.provider.writes, [])

    def test_denied_actor_cannot_obtain_preview_details(self):
        self.auth.allowed = False
        with self.assertRaises(NetworkError) as failure:
            self.preview()
        self.assertEqual(failure.exception.code, 'permission')
        self.assertEqual(self.provider.reads, 0)

    def test_provider_failure_cannot_look_like_empty_inventory(self):
        self.provider.read_error = NetworkError('transient')
        response = self.preview()
        self.assertEqual((response.outcome, response.reason),
                         ('blocked', 'provider-transient'))
        self.assertIsNone(response.observed_count)

    def test_wrong_zone_account_is_blocked(self):
        self.provider.zone['account']['id'] = 'foreign'
        response = self.preview()
        self.assertEqual((response.outcome, response.reason),
                         ('blocked', 'provider-conflict'))

    def test_revision_changed_during_provider_read_blocks_candidate(self):
        def change_scope():
            self.ledger.put_binding(
                'admin', replace(self.binding, revision=2), 1)
        self.provider.on_list = change_scope
        response = self.preview()
        self.assertEqual((response.outcome, response.reason),
                         ('blocked', 'scope-changed'))
        self.assertEqual(self.provider.writes, [])

    def test_gate_change_during_read_blocks_candidate(self):
        self.provider.on_list = lambda: setattr(self.gate, 'denied', True)
        response = self.preview()
        self.assertEqual((response.outcome, response.reason),
                         ('blocked', 'publication-permission'))
        self.assertEqual(self.provider.writes, [])

    def test_rename_is_blocked_not_presented_as_candidate(self):
        self.seed()
        changed = replace(self.desired, name='other.hosts.example.com')
        response = self.preview(changed, rev=2)
        self.assertEqual((response.outcome, response.reason),
                         ('blocked', 'rename-not-supported'))
        self.assertEqual(self.provider.writes, [])

    def test_missing_or_replaced_owned_record_is_drift_not_create(self):
        self.seed()
        self.provider.rows = []
        missing = self.preview(rev=2)
        self.assertEqual((missing.outcome, missing.reason),
                         ('blocked', 'owned-record-drift'))
        self.provider.rows = [
            dict(id='foreign-new', name=self.desired.name, type='A',
                 content='8.8.8.8', ttl=300, proxied=False,
                 comment='foreign')]
        replaced = self.preview(rev=2)
        self.assertEqual((replaced.outcome, replaced.reason),
                         ('blocked', 'owned-record-drift'))
        self.assertEqual(replaced.observed_count, 1)
        self.assertFalse(replaced.observed[0].matches_last_applied)
        self.assertEqual(self.provider.writes, [])

    def test_inspection_gate_refusal_is_distinct_from_provider_failure(self):
        def policy(connection, binding, resource, desired, action, revision):
            if action == 'inspect':
                raise NetworkError('permission')
        self.gate.check = policy
        response = self.preview()
        self.assertEqual((response.outcome, response.reason),
                         ('blocked', 'inspection-permission'))
        self.assertIs(response.authorized, False)
        self.assertIsNone(response.observed_count)
        self.assertEqual(self.provider.reads, 0)

    def test_delete_requires_explicit_intent(self):
        with self.assertRaises(ValueError):
            self.engine.preview(
                'admin', 'owner', 'binding', RESOURCE, None, 1)
        self.assertEqual(self.provider.reads, 0)

    def test_provider_minimum_ttl_is_enforced(self):
        response = self.preview(replace(self.desired, ttl=60))
        self.assertEqual((response.outcome, response.reason),
                         ('blocked', 'plan-validation'))
        self.assertEqual(self.provider.reads, 0)


if __name__ == '__main__':
    unittest.main()
