"""Systemd templates are staging-only and never install the quarantined timer."""
import json
from pathlib import Path
import tempfile
import unittest

from zog.network_register.worker_units import (
    UnitSelectionError, render_units, stage_units,
)


SELECTION = {
    "schema": 1,
    "python": "/opt/zog/station/venv/bin/python",
    "working_directory": "/opt/zog/station/app",
    "environment_file": "/state/station/config/worker.env",
    "state_directory": "/state/station/dns-controller",
    "receipt_directory": "/state/station/dns-worker-runs",
    "service_user": "zog-station",
    "service_group": "zog-station",
}


class UnitTests(unittest.TestCase):
    def test_rendered_inspect_is_default_and_distinct_from_legacy(self):
        result = render_units(SELECTION)
        self.assertEqual(set(result), {
            "zog-shared-dns-worker.service", "zog-shared-dns-worker.timer"})
        unit = result["zog-shared-dns-worker.service"]
        timer = result["zog-shared-dns-worker.timer"]
        self.assertIn("User=zog-station", unit)
        self.assertIn("Group=zog-station", unit)
        self.assertIn("EnvironmentFile=/state/station/config/worker.env", unit)
        self.assertIn("ReadWritePaths=/state/station/dns-controller /state/station/dns-worker-runs", unit)
        self.assertIn("zog.network_register.scheduled_worker --receipt-dir", unit)
        self.assertNotIn("--apply", unit)
        self.assertNotIn("ExecStart=/opt/station-access/", unit)
        self.assertNotIn("User=station-access", unit)
        self.assertNotIn("\n[Install]", unit)
        self.assertIn("Unit=zog-shared-dns-worker.service", timer)
        self.assertNotIn("Unit=host-dns-reconcile.service", timer)
        self.assertIn("OnUnitInactiveSec=5min", timer)

    def test_apply_requires_explicit_mode_selection(self):
        unit = render_units(SELECTION, mode="apply")["zog-shared-dns-worker.service"]
        self.assertIn("--apply", unit)
        self.assertEqual(unit.count("--apply"), 1)
        with self.assertRaises(UnitSelectionError):
            render_units(SELECTION, mode="migrate")

    def test_no_newlines_shell_expansions_or_forged_service_identity(self):
        for key, bad in (
            ("python", "/usr/bin/python\nExecStart=/bin/sh"),
            ("environment_file", "/tmp/worker env"),
            ("receipt_directory", "/state/station/../other"),
            ("service_user", "root; echo fake"),
            ("service_group", "%i"),
        ):
            selection = dict(SELECTION, **{key: bad})
            with self.subTest(key=key), self.assertRaises(UnitSelectionError):
                render_units(selection)
        with self.assertRaises(UnitSelectionError):
            render_units(dict(SELECTION, token="secret"))

    def test_stage_creates_only_reviewable_files_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            result = stage_units(SELECTION, root)
            self.assertFalse(result["installed"])
            self.assertFalse(result["enabled"])
            self.assertEqual(result["mode"], "inspect")
            self.assertEqual(set(x.name for x in root.iterdir()),
                             set(result["files_sha256"]))
            for entry in root.iterdir():
                self.assertEqual(entry.stat().st_mode & 0o777, 0o600)
            first = (root / "zog-shared-dns-worker.service").read_text()
            with self.assertRaises(UnitSelectionError):
                stage_units(SELECTION, root, mode="apply")
            self.assertEqual((root / "zog-shared-dns-worker.service").read_text(), first)

    def test_symlink_or_insecure_staging_folder_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            alias = root / "symlink"
            alias.symlink_to(root, target_is_directory=True)
            with self.assertRaises(UnitSelectionError):
                stage_units(SELECTION, alias)
            root.chmod(0o755)
            with self.assertRaises(UnitSelectionError):
                stage_units(SELECTION, root)


if __name__ == "__main__":
    unittest.main()
