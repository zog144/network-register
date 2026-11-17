"""Mock-only acceptance for the finite shared DNS scheduler and receipts."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import sys

from zog.network_register.contracts import NetworkError
from zog.network_register.scheduled_worker import (
    WorkerBlocked, _preview_scope, run_scheduled, station_cycle,
)


class RunReceiptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root.chmod(0o700)

    def run_worker(self, function, *, inspect_only=True, run_id=None):
        return run_scheduled(self.root, inspect_only=inspect_only,
                             operation=function, run_id=run_id)

    def test_default_inspection_and_idempotent_noop(self):
        operations = []
        def read(*, inspect_only):
            operations.append(inspect_only)
            return {"status": "idle", "counts": {}}
        first = self.run_worker(read)
        second = self.run_worker(read)
        self.assertEqual([first["status"], second["status"]], ["idle", "idle"])
        self.assertEqual(operations, [True, True])
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(len(list(self.root.glob("*.started.json"))), 2)
        self.assertEqual(len(list(self.root.glob("*.result.json"))), 2)
        for row in self.root.glob("*.json"):
            self.assertEqual(row.stat().st_mode & 0o777, 0o600)

    def test_busy_run_has_receipt_and_never_bypasses_lock(self):
        def busy(*, inspect_only):
            raise BlockingIOError("protected controller busy")
        result = self.run_worker(busy)
        self.assertEqual(result["status"], "busy")
        self.assertEqual(result["reason"], "controller-busy")
        self.assertEqual(result["counts"], {})

    def test_paused_and_resumed_do_not_dispatch_while_paused(self):
        states = iter(["paused", "succeeded", "succeeded"])
        calls = []
        def worker(*, inspect_only):
            status = next(states)
            if status == "succeeded":
                calls.append("reconciled")
            return {"status": status,
                    "counts": {"synchronized": 1} if calls and status != "paused" else {}}
        self.assertEqual(self.run_worker(worker, inspect_only=False)["status"], "paused")
        self.assertEqual(calls, [])
        self.assertEqual(self.run_worker(worker, inspect_only=False)["status"], "succeeded")
        self.assertEqual(self.run_worker(worker, inspect_only=False)["status"], "succeeded")
        self.assertEqual(calls, ["reconciled", "reconciled"])

    def test_stale_evidence_rejected_and_raw_error_never_recorded(self):
        secret = "CLOUDFLARE_API_TOKEN=should-not-log"
        def bad(*, inspect_only):
            raise RuntimeError(secret)
        outcome = self.run_worker(bad, inspect_only=False)
        self.assertEqual((outcome["status"], outcome["reason"]),
                         ("failed", "worker-failure"))
        self.assertNotIn(secret, json.dumps(outcome))
        self.assertNotIn(secret, "".join(p.read_text() for p in self.root.glob("*.json")))
        def stale(*, inspect_only):
            raise NetworkError("permission")
        outcome = self.run_worker(stale, inspect_only=False)
        self.assertEqual((outcome["status"], outcome["reason"]), ("blocked", "permission"))

    def test_attentive_results_fail_closed_on_pending_or_uncertain(self):
        def pending(*, inspect_only):
            return {"status": "attention", "counts": {"uncertain": 1}}
        result = self.run_worker(pending, inspect_only=False)
        self.assertEqual(result["status"], "attention")
        def bad(*, inspect_only):
            return {"status": "succeeded", "counts": {"uncertain": 1}}
        self.assertEqual(self.run_worker(bad, inspect_only=False)["status"], "blocked")

    def test_crash_leaves_start_receipt_for_manual_inspection(self):
        run_id = "ae18bac1-1247-4a5b-9406-3e73a22b0e61"
        def killed(*, inspect_only):
            raise KeyboardInterrupt("service killed before report")
        with self.assertRaises(KeyboardInterrupt):
            self.run_worker(killed, inspect_only=False, run_id=run_id)
        self.assertTrue((self.root / (run_id + ".started.json")).exists())
        self.assertFalse((self.root / (run_id + ".result.json")).exists())
        # Restart uses a fresh attempt identity; old incompleteness remains.
        self.assertEqual(self.run_worker(
            lambda **_: {"status": "idle", "counts": {}})["status"], "idle")
        self.assertTrue((self.root / (run_id + ".started.json")).exists())

    def test_start_receipt_failure_prevents_any_operation(self):
        calls = []
        id_value = "b11e5459-d329-44e5-9f8c-45182311ee7c"
        (self.root / (id_value + ".started.json")).write_text("older receipt")
        with self.assertRaises(FileExistsError):
            self.run_worker(lambda **_: calls.append(1), run_id=id_value)
        self.assertEqual(calls, [])
        self.assertEqual((self.root / (id_value + ".started.json")).read_text(),
                         "older receipt")

    def test_missing_or_symlinked_receipt_directory_rejects_before_dispatch(self):
        calls = []
        missing = self.root / "missing"
        with self.assertRaises(WorkerBlocked):
            run_scheduled(missing, operation=lambda **_: calls.append(1))
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(WorkerBlocked):
            run_scheduled(alias, operation=lambda **_: calls.append(1))
        self.assertFalse(calls)


class StationConsumerTests(unittest.TestCase):
    """A controlled station API stand-in; no Django dependency or provider I/O."""
    def setUp(self):
        self.state = {"writer": "shared", "stage": "active"}
        self.calls = []
        self.config = {"state_directory": "/selected/state"}
        self.legacy = False
        self.busy = False
        self.stale = False
        self.source = types.SimpleNamespace(
            use_observed_address=False, host=lambda *a: self._host(*a))
        self.gate = types.SimpleNamespace(check=lambda *a: self._check(*a))
        self.engine = types.SimpleNamespace(
            gate=self.gate, preview=lambda *a, **k: self._preview(*a, **k))
        self.selection = types.SimpleNamespace(
            connection=types.SimpleNamespace(owner_id="owner"),
            binding=types.SimpleNamespace(id="binding"),
            host_ids=("12345678-1234-1234-1234-123456789abc",))
        self.result = {"synchronized": 1}
        self.addl_result = {"unpublished": 1}

    @contextmanager
    def _lock(self, config, *, modes):
        self.calls.append("lock")
        self.assertEqual(modes, ("shared", "paused"))
        self.assertIs(config, self.config)
        if self.busy:
            raise BlockingIOError()
        if self.legacy:
            raise ValueError("legacy controller refused")
        try:
            yield Path("/selected/state")
        finally:
            self.calls.append("unlock")

    def _host(self, *args):
        self.calls.append("host-evidence")
        if self.stale:
            raise NetworkError("permission")
        return types.SimpleNamespace(
            publish_enabled=True, desired_revision=4,
            desired=types.SimpleNamespace(name="one.hosts.example.test"))

    def _check(self, *args):
        self.calls.append("evidence-gate")

    def _preview(self, *args, **kwargs):
        self.calls.append("provider-inspect")
        return types.SimpleNamespace(outcome="candidate")

    def fake_modules(self):
        module = types.ModuleType("zog.station_access.host_registry")
        module.dns_controller_lock = types.SimpleNamespace(writer_lock=lambda *_: None)
        module.dns_reconcile = types.SimpleNamespace(
            configuration=lambda: self.config, controller_lock=self._lock)
        module.dns_cutover = types.SimpleNamespace(
            controller_state=lambda _: self.state)
        module.dns_shared = types.SimpleNamespace(
            open_runtime=lambda *_: (self.selection, self.source, self.engine),
            reconcile_locked=lambda *_: self._reconcile_primary())
        module.dns_destinations = types.SimpleNamespace(
            DnsDestination=types.SimpleNamespace(
                objects=types.SimpleNamespace(filter=lambda **_: types.SimpleNamespace(
                    order_by=lambda *_: []))),
            reconcile_all=lambda *_: self._reconcile_additional())
        pkg = types.ModuleType("zog.station_access")
        pkg.__path__ = []
        module.__path__ = []
        return {"django": types.SimpleNamespace(setup=lambda: self.calls.append("setup")),
                "zog.station_access": pkg,
                "zog.station_access.host_registry": module}

    def _reconcile_primary(self):
        self.calls.append("primary-apply")
        return self.result

    def _reconcile_additional(self):
        self.calls.append("additional-apply")
        return self.addl_result

    def run_cycle(self, *, inspect_only=False):
        with patch.dict(sys.modules, self.fake_modules()):
            return station_cycle(inspect_only=inspect_only)

    def test_apply_uses_one_lock_across_primary_and_additional_destination(self):
        value = self.run_cycle()
        self.assertEqual(value, {"status": "succeeded",
                                 "counts": {"synchronized": 1, "unpublished": 1}})
        self.assertEqual(self.calls, ["setup", "lock", "primary-apply",
                                      "additional-apply", "unlock"])

    def test_inspect_only_uses_signed_evidence_and_never_calls_mutation(self):
        value = self.run_cycle(inspect_only=True)
        self.assertEqual(value["counts"], {"candidate": 1})
        self.assertIn("host-evidence", self.calls)
        self.assertIn("evidence-gate", self.calls)
        self.assertIn("provider-inspect", self.calls)
        self.assertTrue(self.source.use_observed_address)
        self.assertNotIn("primary-apply", self.calls)
        self.assertNotIn("additional-apply", self.calls)

    def test_stale_signed_host_evidence_blocks_inspect(self):
        self.stale = True
        with self.assertRaises(NetworkError):
            self.run_cycle(inspect_only=True)
        self.assertNotIn("provider-inspect", self.calls)

    def test_pause_does_not_load_provider_or_ledger_and_resume_uses_lock(self):
        self.state["writer"] = "paused"
        self.assertEqual(self.run_cycle(), {"status": "paused", "counts": {}})
        self.assertNotIn("primary-apply", self.calls)
        self.state["writer"] = "shared"
        self.calls.clear()
        self.assertEqual(self.run_cycle()["status"], "succeeded")
        self.assertIn("primary-apply", self.calls)

    def test_legacy_and_frozen_never_fall_back(self):
        self.legacy = True
        with self.assertRaises(WorkerBlocked):
            self.run_cycle()
        self.assertNotIn("primary-apply", self.calls)
        self.legacy = False
        self.state["writer"] = "frozen"
        with self.assertRaises(WorkerBlocked):
            self.run_cycle()
        self.assertNotIn("primary-apply", self.calls)

    def test_busy_scheduler_refuses_secondary_writer(self):
        self.busy = True
        with self.assertRaises(BlockingIOError):
            self.run_cycle()
        self.assertNotIn("primary-apply", self.calls)

    def test_unknown_result_is_not_reported_as_success(self):
        self.result = {"secret-or-unsupported": 1}
        with self.assertRaises(WorkerBlocked):
            self.run_cycle()
        self.assertIn("unlock", self.calls)

    def test_repeated_same_selected_state_is_idempotently_reported(self):
        first = self.run_cycle()
        second = self.run_cycle()
        self.assertEqual(first, second)
        self.assertEqual(self.calls.count("primary-apply"), 2)


if __name__ == "__main__":
    unittest.main()
