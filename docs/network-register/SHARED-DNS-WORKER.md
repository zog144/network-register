# Supported shared DNS scheduled worker and timer

**Status: source candidate only — not installed, enabled or authorized for live provider writes.** Owners: network-register Regular (worker and packaging), station-access Regular (consumer API), network-register/host-deploy Work (native acceptance).

The legacy host-dns-reconcile.service and host-dns-reconcile.timer remain quarantined, non-installable text fixtures under station-access/docs/station-access/legacy/noninstallable/. **Never restore or enable them.**

## Shared controller and trust contract

The scheduled entry point is zog.network_register.scheduled_worker. It does not call the generic station-access reconcile_host_dns command, whose legacy mode can still write. Instead, it imports the installed, reviewed station-access implementation and holds dns_reconcile.controller_lock(config, modes=("shared", "paused")) across **both** primary dns_shared.reconcile_locked and dns_destinations.reconcile_all. The shared writer must be stage=active and mode=shared; paused yields a non-mutating receipt. Legacy/frozen/absent controller, missing stable writer_lock, unknown version or foreign state blocks. It never initializes/migrates a controller.

The station-access consumer supplies protected controller.json/controller.lock inode, schema-1 SqliteStateStore and operation ledger, current selected owner, protected credential vault references via RegistrySecretResolver, approved signed HostIdentity/beacon reports, fresh AWS inventory and authority/EvidenceGate. The worker does not accept user-supplied IP addresses, record names, credentials, host selection or private signing material. Stale, mismatched or missing evidence must block; absence of a beacon is not a delete instruction.

Source-compatibility references: station-access PR #6 c1fcb807e28915e9e39f7ec836eb6bbc7ef7a869 (protected empty controller) plus stacked PR #7 ce1eb6554d906d4216d3e6504ab7daff4e4a1c5f (original-lock adoption). They are NOT proof of installed selection. Re-attest current source pins and installed wheels before using this worker.

## Finite scheduled run

Command: python -m zog.network_register.scheduled_worker --receipt-dir /SELECTED/PROTECTED/DNS-WORKER-RUNS

Default is **inspection only** (source-approved host evidence checks and provider GET via DnsEngine.preview). Use --apply only after the operator authorizes the selected provider write scope and the deployment owner re-renders the service. The worker uses no independent writer lock: it shares station-access's durable controller.lock. Already held lock => busy receipt, no secondary dispatch. Pause/resume is performed by station-access under the same lock; resume rechecks current authority and state. An interrupted/uncertain ledger operation follows station-access recovery; it is never blindly retried by the timer.

A pre-existing, service-owned 0700 receipt directory is a deployment prerequisite. Each invocation O_EXCL creates and fsyncs a 0600 UUID.started.json **before any provider operation**, and a separate UUID.result.json on completion. A crash leaves unmatched start evidence without inventing a result. Final receipts and journald output include only schema, run identity, inspection/apply mode, UTC start/end, safe status/reason and aggregate integer counters. No raw exceptions, provider responses, tokens, host IPs or credentials are emitted by this entry point.

Exit 0: idle, succeeded, busy or paused. Exit 2: attention, blocked or failed. Exit 3: receipt-storage refusal. An unhandled abrupt termination leaves the started receipt and a failed systemd invocation. No success is claimed before the result receipt fsyncs.

## Staging-only unit packaging

The wheel includes resources systemd/zog-shared-dns-worker.service.in and .timer.in, plus the zog-shared-dns-units renderer. Unit resources are NOT installed, enabled or started by wheel installation.

An example **nonsecret** reviewed selection JSON (actual deployment must use its selected paths, identity and protected settings):

    {
      "schema": 1,
      "python": "/selected/app/venv/bin/python",
      "working_directory": "/selected/app",
      "environment_file": "/selected/state/station/worker.env",
      "state_directory": "/selected/state/station/dns-controller",
      "receipt_directory": "/selected/state/station/dns-worker-runs",
      "service_user": "selected-app",
      "service_group": "selected-app"
    }

The selection file must be mode 0600 under the selected service UID. The renderer requires an existing 0700 service-owned staging directory. Its source-only command:

    python -m zog.network_register.worker_units --selection /SELECTED/selection.json --output-directory /SELECTED/staging --mode inspect

It outputs SHA-256 for the two **staged** files with installed=false, enabled=false; it refuses replacements rather than overwriting. A separately reviewed --mode apply choice adds --apply to the selected service command. Do not install or enable from this chat.

The new oneshot service uses dynamically selected User/Group, interpreter, working directory, protected EnvironmentFile, state/receipt ReadWritePaths, finite TimeoutStartSec, systemd hardening and journal output. The timer points ONLY to zog-shared-dns-worker.service using OnBootSec, OnUnitInactiveSec and jitter. Conflicts=host-dns-reconcile.service is defense-in-depth, NOT proof the old timer is disabled.

## Native acceptance — network-register Work and station-access/host-deploy owners

1. Inspect installed package/wheel RECORD, source pins, protected controller configuration, original lock/ledger inodes, vault bindings, service UID/GID and application state mount. Confirm the legacy service/timer cannot start and there is no older writer. Native verification of the currently selected systemd version is required.
2. Stage and hash-check the new selected units. Install via the reviewed immutable application/host-deploy deployment path; create the protected receipt directory before starting a service. Confirm timer and service are initially disabled; activate *inspection-only* only on separate authorization.
3. Observe at least two timer firings and a manual invocation, including overlap (busy receipt), restart/reboot, crash between started/result, and paused/resumed controller behavior. Verify persistent ledger identity, no duplicate operation, no provider mutation, sanitized journal, retained receipts and systemd InvocationID.
4. Reject stale beacon, signed/address mismatch, missing AWS inventory, credential rotation and foreign controller state. For dry-run inspect, assert the provider was queried only through read-only preview and ledger operation/record rows did not change.
5. A separate operator-authorized test-zone or live DNS write may switch to --mode apply. Verify retained request/operation identity, provider result, idempotent repeat and recovery from an uncertain response before any production activation.
6. Report exact selected source revisions, rendered unit SHA-256, commands, service status, journal/receipt paths, boot ID and protected ledger/lock evidence reused from the earlier native station acceptance.

**Boundary:** source CI is not native acceptance. This candidate cannot run without a compatible installed station-access application, and does not itself authorize new Cloudflare/Porkbun writes, lock adoption, controller bootstrap or DNS-01 hostname/certificate grants.
