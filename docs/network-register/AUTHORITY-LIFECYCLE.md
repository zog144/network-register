# Authority policy and credential lifecycle — 0.8.0

This pass implements the NR-001 library policy for trusted DNS/host evidence and
read-validated connection activation/rotation. It does not collect DNS packets,
verify beacon signatures, query AWS inventory, change the station-access dependency
pin, deploy a controller, purchase a domain, or make live DNS writes.

## Publication policy

`zog.network_register.evidence.EvidenceGate` implements the engine's publication gate.
An application supplies a privileged `EvidenceSource`; its observations must come
from trusted collectors, never arbitrary browser or beacon JSON. The source is a
trust boundary: typed evidence and timestamps alone do not authenticate an observation.

Each binding explicitly pins the selected provider zone's expected nameservers.
Discovery alone does not authorize publication. Nameserver spelling is normalized
and sets are compared without regard to order. Duplicate pins are rejected. Older
saved bindings remain readable with an empty default pin set, but the new gate
and lifecycle validator refuse to authorize them until configured explicitly.

Authority evidence must match the exact owner, connection ID/revision/credential
reference, binding ID/revision, provider zone ID/name, and managed prefix. Parent
delegation must equal the pinned set. Every pinned server must supply an
authoritative SOA for the bound zone and evidence that the managed prefix is not
shadowed by another delegation. Missing, duplicate, extra, conflicting, stale,
and future observations fail closed. Provider API zone status alone is insufficient.

All DNS observations must be no more than 300 seconds old and not in the future.
The gate rechecks their freshness after the host lookup. Publication additionally
requires the exact desired record and revision, explicit enrollment/publication,
running inventory, equal enrolled/signed/inventory cloud identity (account,
region, instance), equal desired/signed/inventory public IPv4 address, and signed
host and inventory observations within the same freshness window. Record snapshots
already constrain publication to DNS-only A records and validated TTLs.

Explicit unpublish requires a current desired revision, no desired record,
publication disabled, and an explicit unpublish decision. It does not require the
retired host to remain running. Missing heartbeats, stale evidence, or failed
inventory reads do not themselves authorize deletion. Inspection requires valid
DNS authority but does not require host evidence.

## Connection lifecycle

`zog.network_register.lifecycle.ConnectionLifecycle` provides owner-authorized,
revision-checked operations. `ReadOnlyConnectionValidator` reads the exact zone
and every records page for every non-detached binding with the candidate credential,
then checks authority for each binding. Read success does not establish write
permission. Validation never mutates provider assets.

| Operation | Local result |
| --- | --- |
| `activate(actor, owner_id, connection_id, expected_revision)` | Validates an unverified/action-required connection, atomically marks it and its bindings ready, increments revisions, and cancels undispatched work. |
| `rotate(actor, owner_id, connection_id, credential_ref, expected_revision)` | Validates a new reference against the same owner/provider/account and bound targets, then atomically switches a ready connection and cancels undispatched work. |
| `suspend(actor, owner_id, connection_id, expected_revision)` | Marks the connection revoked, blocks bindings, and cancels undispatched work without provider calls. |
| `suspend(..., disconnect=True)` | Marks the connection disconnected and detaches bindings while preserving records, reservations, operation evidence, and provider assets. |

Rotation leaves the old reference active throughout validation. The validation
receipt binds the candidate connection/revision/reference and all target snapshots;
its expiry is the earliest DNS observation expiry, not the validation start time.
The final transaction checks authorization, revisions, binding snapshots, receipt
expiry, and unresolved operations again. Concurrent revocation or binding changes
win over an obsolete validation result. Storage failure rolls back the whole switch,
operation cancellation, and audit event. Lifecycle events contain no credential value.

Activation/rotation refuse unresolved operations except prepared or retry-wait
operations known to be undispatched/proven unapplied. Suspension does not wait on
the network worker lock. It preserves dispatching/verifying/uncertain evidence;
it cannot undo an HTTP request already dispatched. It prevents subsequent work
through ready-state checks. There is no fallback to older keys, provider-side key
revocation, automatic reconnect, or automatic recovery using a revoked connection.
Keep prior vault versions and operation evidence for explicit operator recovery;
this module does not manage vault retention. Activated bindings have new revisions,
so collectors must refresh evidence before a new engine operation.

## Integration contract

Use the same trusted store, authorizer, secret resolver, and evidence source across
lifecycle operations and the engine:

```python
from zog.network_register.evidence import EvidenceGate
from zog.network_register.lifecycle import ConnectionLifecycle, ReadOnlyConnectionValidator
from zog.network_register.engine import DnsEngine

gate = EvidenceGate(trusted_evidence_source)
validator = ReadOnlyConnectionValidator(gate, secrets=secret_resolver)
lifecycle = ConnectionLifecycle(ledger, validator)
engine = DnsEngine(ledger, gate, secrets=secret_resolver)
```

`trusted_evidence_source`, `secret_resolver`, and `ledger` are application adapters,
not supplied defaults. The DNS collector must independently inspect parent delegation,
each selected authoritative server, and delegation boundaries under the managed
prefix. The host collector must authenticate enrollment and signed observations,
fetch authorized AWS inventory, and bind results to the current desired revision.
Do not accept caller-provided booleans as proof. Store stable credential references,
not secrets, in ledger objects; rotate by creating a new vault reference first.

Raw store access and `put_connection`/`put_binding` remain trusted provisioning
primitives, not browser endpoints. Integrators must route lifecycle actions through
this service and use the concrete gate for engine calls. This library does not
sandbox an application that intentionally bypasses those APIs. Existing legacy
CLI/controller flows are unchanged and do not automatically gain these checks.

## Verification and remaining work

167 fixture tests pass, including stale/future evidence, desired revision mismatch,
identity mismatch, explicit retirement, expired evidence at dispatch, all-binding
validation, failed rotation, revocation during validation, binding races, receipt
mismatch/expiry, unresolved operations, durable reopening, and transactional rollback.
See evidence/authority-lifecycle-tests.txt (dated private test evidence; results apply only to the stated source/test revision). The wheel is built and its new module
contents checked against source. No live account or DNS mutation was tested.

Next work is the trusted collector and station-access integration, with explicit
migration/adoption of existing state and operator conflict/recovery workflows.
Registrar discovery/zone provisioning and complete architecture acceptance remain
separate work. Publishing this release does not change station-access's pin.
