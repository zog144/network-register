"""A finite, fail-closed scheduled entry point for the *shared* DNS controller.

The station-access consumer is the only owner of the protected lock, ledger,
credential resolver and signed host/AWS observations. This module never falls
back to the old legacy reconciler or creates controller state.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
import uuid

from .contracts import NetworkError


RECEIPT_SCHEMA = 1
ATTENTION_KEYS = frozenset({
    "blocked", "conflict", "uncertain", "failed", "provider_error",
    "pending_other_host", "waiting", "waiting_verification", "storage_error",
})
COUNT_KEYS = frozenset({
    "candidate", "no-op", "blocked", "synchronized", "unpublished",
    "conflict", "uncertain", "failed", "provider_error", "pending_other_host",
    "waiting", "waiting_verification", "storage_error", "backoff", "idle",
})
SAFE_CODES = frozenset({
    "permission", "conflict", "storage", "transient", "authentication",
    "rate-limit", "validation", "not-found", "unsupported", "uncertain",
})


class WorkerBlocked(RuntimeError):
    """A bounded, secret-free refusal code, not an exception body."""


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _counts(value):
    if not isinstance(value, dict):
        raise WorkerBlocked("invalid-outcome")
    clean = {}
    for name, count in value.items():
        if name not in COUNT_KEYS or type(count) is not int or count < 0:
            raise WorkerBlocked("invalid-outcome")
        clean[name] = count
    return dict(sorted(clean.items()))


def _preview_scope(selected, source, engine):
    """Read-only provider-backed previews, with fresh signed/AWS host evidence."""
    outcomes = {}
    source.use_observed_address = True
    c, b = selected.connection, selected.binding
    for resource in selected.host_ids:
        evidence = source.host(c.owner_id, b.id, resource)
        action = "publish" if evidence.publish_enabled else "unpublish"
        engine.gate.check(c, b, resource, evidence.desired, action,
                          evidence.desired_revision)
        preview = engine.preview(
            c.owner_id, c.owner_id, b.id, resource, evidence.desired,
            evidence.desired_revision, delete=evidence.desired is None)
        name = preview.outcome
        if name not in ("candidate", "no-op", "blocked"):
            raise WorkerBlocked("invalid-outcome")
        outcomes[name] = outcomes.get(name, 0) + 1
    return outcomes


def station_cycle(*, inspect_only=False):
    """Use only the installed, reviewed station-access shared-controller API.

    The controller lock spans all destinations and provider I/O. A frozen or
    legacy writer, an unmarked old lock or absent protected state cannot run.
    The station's evidence gate is responsible for stale/revoked identities.
    """
    try:
        import django
        django.setup()
        from zog.station_access.host_registry import (
            dns_controller_lock, dns_cutover, dns_destinations,
            dns_reconcile, dns_shared,
        )
    except (ImportError, RuntimeError):
        raise WorkerBlocked("station-integration-unavailable") from None

    if not callable(getattr(dns_controller_lock, "writer_lock", None)):
        raise WorkerBlocked("protected-lock-unavailable")
    config = dns_reconcile.configuration()
    if not config:
        raise WorkerBlocked("controller-not-configured")
    # The reviewed controller_lock must use dns_controller_lock.writer_lock;
    # source pinning/attestation of that station-access revision is the
    # deployment owner's responsibility.
    try:
        with dns_reconcile.controller_lock(config, modes=("shared", "paused")) as root:
            state = dns_cutover.controller_state(config)
            if state.get("stage") != "active":
                raise WorkerBlocked("controller-not-active")
            if state["writer"] == "paused":
                return {"status": "paused", "counts": {}}
            if state["writer"] != "shared":
                raise WorkerBlocked("controller-not-shared")

            if inspect_only:
                primary, source, engine = dns_shared.open_runtime(config, root)
                results = _preview_scope(primary, source, engine)
                # Every additional destination uses its own reviewed ledger,
                # and the same station-access signed-host evidence gate.
                for destination in dns_destinations.DnsDestination.objects.filter(
                        enabled=True).order_by("pk"):
                    selected, src, api = dns_destinations.runtime(destination, root)
                    for key, n in _preview_scope(selected, src, api).items():
                        results[key] = results.get(key, 0) + n
            else:
                # Never mutate the station's returned dictionary; it may be
                # retained as a projection or reused by a subsequent run.
                results = dict(dns_shared.reconcile_locked(config, root))
                for key, n in dns_destinations.reconcile_all(config, root).items():
                    results[key] = results.get(key, 0) + n
    except ValueError:
        # In particular controller_lock rejects legacy/frozen mode after flock.
        raise WorkerBlocked("controller-not-shared") from None

    counts = _counts(results)
    return {
        "status": "attention" if any(counts.get(k, 0) for k in ATTENTION_KEYS)
                  else "idle" if not any(counts.values()) else "succeeded",
        "counts": counts,
    }


def _receipt_directory(path):
    """Open an *existing* selected state directory; do not create/repair it."""
    p = Path(path)
    if not p.is_absolute():
        raise WorkerBlocked("receipt-directory-invalid")
    try:
        fd = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        st = os.fstat(fd)
        current = os.stat(p, follow_symlinks=False)
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) != 0o700
                or (st.st_dev, st.st_ino) != (current.st_dev, current.st_ino)):
            raise WorkerBlocked("receipt-directory-unsafe")
        return fd
    except OSError:
        raise WorkerBlocked("receipt-directory-unavailable") from None


def _write_receipt(dirfd, name, value):
    """Exclusive, fsync'd write; never rewrite an earlier result or error."""
    data = (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")
    fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                 0o600, dir_fd=dirfd)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
    finally:
        pass
    os.fsync(dirfd)


def run_scheduled(receipt_dir, *, inspect_only=True, operation=None,
                  run_id=None, clock=None):
    """Create a durable start + terminal receipt for every completed attempt.

    An interrupted process retains a .started.json without a .result.json.
    This never cleans up ledger operations or repeats an uncertain DNS write.
    """
    operation = operation or station_cycle
    clock = clock or _utc
    run_id = str(uuid.UUID(run_id)) if run_id is not None else str(uuid.uuid4())
    mode = "inspect" if inspect_only else "apply"
    dirfd = _receipt_directory(receipt_dir)
    try:
        started = dict(schema=RECEIPT_SCHEMA, run_id=run_id, mode=mode,
                       started_at=clock(), status="started")
        _write_receipt(dirfd, run_id + ".started.json", started)
        try:
            raw = operation(inspect_only=inspect_only)
            counts = _counts(raw["counts"])
            status = raw["status"]
            if status not in ("paused", "idle", "succeeded", "attention"):
                raise WorkerBlocked("invalid-outcome")
            if status in ("paused", "idle") and any(counts.values()):
                raise WorkerBlocked("invalid-outcome")
            if status == "succeeded" and any(counts.get(k, 0) for k in ATTENTION_KEYS):
                raise WorkerBlocked("invalid-outcome")
            if status == "attention" and not any(counts.get(k, 0) for k in ATTENTION_KEYS):
                raise WorkerBlocked("invalid-outcome")
            reason = "ok"
        except BlockingIOError:
            status, counts, reason = "busy", {}, "controller-busy"
        except WorkerBlocked as error:
            status, counts, reason = "blocked", {}, str(error)
        except NetworkError as error:
            status, counts = "blocked", {}
            reason = error.code if error.code in SAFE_CODES else "network-error"
        except Exception:
            # No raw provider errors, tokens, file paths, addresses, exception
            # string or traceback are ever written into persistent receipts.
            status, counts, reason = "failed", {}, "worker-failure"

        finished = dict(schema=RECEIPT_SCHEMA, run_id=run_id, mode=mode,
                        started_at=started["started_at"], completed_at=clock(),
                        status=status, reason=reason, counts=counts)
        _write_receipt(dirfd, run_id + ".result.json", finished)
        return finished
    finally:
        os.close(dirfd)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Finite Zog shared DNS worker; inspect-only unless --apply.")
    parser.add_argument("--receipt-dir", required=True,
                        help="Existing protected service-owned mode-0700 run receipt directory")
    parser.add_argument("--apply", action="store_true",
                        help="Dispatch only through approved shared station controller; operator-controlled")
    args = parser.parse_args(argv)
    try:
        result = run_scheduled(args.receipt_dir, inspect_only=not args.apply)
    except (WorkerBlocked, OSError, ValueError):
        # No operation is started if the durable start receipt cannot be saved.
        print(json.dumps({"status": "failed", "reason": "receipt-storage-unavailable"}),
              file=sys.stdout)
        return 3
    print(json.dumps(result, sort_keys=True), file=sys.stdout)
    return 0 if result["status"] in ("idle", "succeeded", "paused", "busy") else 2


if __name__ == "__main__":
    raise SystemExit(main())
