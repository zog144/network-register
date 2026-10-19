# Reconciliation, evidence and durable operation

## Tri-state capability and trusted evidence

Provider support, caller authorization and readiness are distinct states. A matching DNS name and public IP alone do not permit mutation; publisher evidence must be authenticated and fresh, and the zone must remain under the reviewed authority. Stale/missing/contradictory observations stop that binding rather than treating it as empty desired state.

## Prepare before provider side effects

The shared engine freezes intended operation, owner/binding and connection revisions, record evidence, plan and request identity before external writes. Lost provider responses require reconciliation by the **same** durable operation and exact provider ID. A retry may only proceed under the engine's documented idempotence rules after re-observation; browser refresh or controller restart must not fabricate a new mutation.

## Safe uncertain-write recovery and deletion verification

The shared `DnsEngine` never automatically redispatches a write once dispatch
has been recorded. Bounded, provider-authorized reads may prove its exact
effect; otherwise the operation remains uncertain or conflicted for explicit
operator resolution. An owned delete ID disappearing is not enough for
success if another A/CNAME/DNAME/NS record now claims the hostname or a
conflicting parent delegation exists. That is a conflict, not proof of an
unpublished hostname. Unrelated TXT records are not deleted.

The older Cloudflare compatibility paths (`DnsRecords` and
`operations.ensure_a`) also persist a write-ahead `applying` marker.
After a timeout, crash or failed result save, the same desired record can be
finalized by an exact provider observation without repeating the mutation.
Absent, stale, changed or ambiguous observations **must not** trigger another
POST/PATCH/DELETE. They fail closed pending inspection and manual recovery;
do not erase the state directory to force a retry. Previously recorded owned
IDs disappearing unexpectedly likewise constitute drift, not permission to
recreate a record.

## Read-only reconciliation preview (schema 1)

The shared engine exposes `DnsEngine.preview(actor, owner_id, binding_id,
resource_id, desired, desired_revision, *, delete=False)`. The caller supplies
the same trusted, validated desired `RecordSnapshot` and monotonically
managed desired revision used for planning. Explicit unpublication requires
`desired=None, delete=True`; missing host observations never imply deletion.
The authorized caller may serialize the returned immutable
`ReconciliationPreview` with `.to_dict()` for a station-access inspection
surface. There is no browser-accessible mutation or unauthenticated CLI.

Example with an already-configured engine, authorized actor, binding and host:

```python
from zog.network_register.models import RecordSnapshot

desired = RecordSnapshot("one.hosts.example.com", "8.8.8.8", 300)
preview = engine.preview(
    "admin", "owner", "binding", host_uuid, desired, 12
)
payload = preview.to_dict()
# outcome: "candidate" | "no-op" | "blocked"
# proposed_action: "create" | "update" | "delete" | "none"
```

Schema 1 returns `provider`, `zone_name`, `hostname`, scope revisions,
`desired_revision`, `desired`, `last_applied`, `outcome`,
`proposed_action`, `reason`, `authorized`, `observed_count`,
`observed`, and `read_only=True`. Observations contain only normalized
record identity, type, public A address, TTL, proxy flag and whether the
record **exactly** matches persisted owned state. Raw provider comments,
credential references, response bodies, secret material and arbitrary
provider error text are not returned. At most 20 relevant A/CNAME/DNAME/NS
records at the exact hostname are included; `observed_count` records the
total. `observed_count=None` means no provider inventory was checked, **not**
that DNS is empty. TXT records are ignored for A-write conflicts.

Outcomes and safety contract:

- `candidate` is a **non-binding suggestion**. No request ID, reservation,
  pending operation or dispatch marker is created. Actual execution must use
  a **new** `plan → prepare → apply` lifecycle with its full revalidation.
- `no-op / already-matches` means exact persisted ownership matches the
  current provider inventory. `no-op / not-managed` for explicit deletion
  means there is no owned target to inspect; it is not proof of DNS absence.
- `blocked / unmanaged-record` rejects foreign records, even those with
  identical values. `owned-record-drift` rejects changed ID, marker,
  address, TTL or proxy flag, without calling the drift-blocking planner.
- `blocked / pending-operation`, `connection-not-ready`,
  `binding-not-ready`, `rename-not-supported` and `plan-validation`
  explain local constraints without asking the provider to write.
- `blocked / publication-<code>`, `inspection-<code>` and
  `provider-<code>` distinguish fail-closed authorization, authority and
  provider read failures. `scope-changed` covers changed ledger state or
  another operation during the provider read.

`authorized=True` means the checked publication and inspection gates
permitted **this read**; it does not promise the provider will accept a later
write. `authorized=False` means a gate denied this inspection.
`authorized=None` means the check was skipped due to an earlier blocker.
Caller/owner authorization failures raise `NetworkError('permission')`
rather than leaking preview contents. The gate is checked both before and
after network IO; connection/binding/owned state and pending operations are
re-read after provider inventory to avoid presenting stale candidates.

Preview reads provider inventory, not public authoritative DNS propagation.
It does not store observations, repair drift, release reservations, revoke
credentials, buy a domain, or prove host enrollment/inventory itself.
Station-access supplies that trusted policy and independently authorizes
the user-facing view. The two-provider source interface does not imply
deployment of a new central writer.

## Central integration boundary

Station-access owns user authorization, vault records, requested DNS assignments and the central worker scheduler. Network-register owns the provider and ledger contracts. Host-discover contributes signed host observations, not DNS write permissions. The older example host-discover reconciler is historical and cannot silently replace a currently selected central writer.

## Retained contracts and evidence

- [SHARED-FOUNDATION.md](../SHARED-FOUNDATION.md)
- [AUTHORITY-LIFECYCLE.md](../AUTHORITY-LIFECYCLE.md)
- [DNS-COLLECTOR.md](../DNS-COLLECTOR.md)
- [RECONCILER-HANDOFF.md](../RECONCILER-HANDOFF.md)

Exact schemas, chronological acceptance reports and live provider status remain separately verifiable. The synthesis does not turn prior source-only implementation into a deployed or authorized production service.
