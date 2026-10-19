# Shared foundation — network-register 0.5.0

Historical foundation-pass scope. Version 0.6.0 adds the optional Cloudflare
planner/executor described in [CLOUDFLARE-EXECUTOR.md](CLOUDFLARE-EXECUTOR.md).
The existing station-access controller is still not migrated to this engine.

Implements the first shared foundation pass toward NR-001. No provider API calls,
live DNS changes, purchases, deployment or existing-state migration were performed
for this pass. This is not yet the complete NR-001 reconciler.

## Delivered boundaries

`contracts.py` defines DnsProvider, RegistrarReader, optional ZoneProvisioner,
HttpTransport, SecretResolver, Authorizer and StateStore protocols. Adapters own
HTTP/name/pagination translation; the future engine owns planning, verification
and retry decisions; station-access owns HTTP authorization, vault, persistent
integration records and scheduling. Neither hosts nor operations receive secrets.

Capability has independent supported/authorized/ready tri-state values and a safe
reason. Ready requires both supported and authorized. NetworkError categories are
authentication, permission, validation, conflict, not-found, rate-limit, transient,
uncertain, storage and unsupported. Messages never include raw provider errors;
adapters must sanitize provider codes/request IDs before supplying optional metadata.
Syntax validation alone is not secret redaction. Existing adapter errors are not
yet converted to this contract.

`models.py` supplies immutable validated Connection, ZoneBinding, RecordSnapshot,
ManagedRecord and Plan DTOs. DNS names normalize to IDNA lowercase without a final
dot. Only public IPv4, non-wildcard DNS-only A writes are represented. Prefixes are
strictly below a zone, and plans target one label beneath a binding's prefix.
Connection account references are explicit, including an operator-defined stable
Porkbun account reference (not an inferred account identity).

`OperationLedger` persists versioned JSON operation models: immutable plan, actor,
owner, request ID/hash, binding/connection IDs, credential reference, before/after
snapshots and intended record ID, operation marker/step key, mutable state/revision,
timestamps, retry time and an append-only transition event list. Returned dictionaries
are detached snapshots; changing them does not change stored state. Store writes
are trusted internal infrastructure, not an application API for bypassing the ledger.

## Durable semantics

- Explicit initialization: `SqliteStateStore(path, create=True)` refuses an existing
  file. Normal opening uses `SqliteStateStore(path)` and refuses missing, empty,
  corrupt or unknown-schema state. A later missing database is never recreated.
- SQLite FULL synchronous transactions serialize comparisons and updates. Intent,
  name reservation and operation creation commit together. The reference store is
  for a local Linux filesystem, not NFS or a distributed deployment.
- `put_connection` / `put_binding` compare expected revisions; identity/scope fields
  cannot be changed in place. New revisions are exactly previous + 1. Overlapping
  active prefixes are conservatively rejected across connections/providers/owners.
- Connections/bindings start unverified/discovered. A trusted integrator may mark
  ready only after target-resource and authority checks. The ledger itself performs
  no delegation checks and does not turn discovery into authorization.
- `prepare(actor, request_id, plan)` rechecks authorization, ready state, exact
  connection/binding revisions, scope and provider TTL policy (minimum 300 for
  Cloudflare; 600 for Porkbun). It performs no provider IO. A Plan is already-computed
  intent, not a claim that the provider currently matches its before snapshot.
- Owner + request ID deduplicates identical canonical plan payloads, including after
  completion. Reusing that key with different payload conflicts. Only one unresolved
  operation per binding is admitted; newer desired revisions cannot replace it.
- All operations and reservations are retained indefinitely in this pass, satisfying
  the minimum 48-hour window without pruning unresolved evidence. Retention tooling
  is deferred. Desired revisions must advance for each new operation on a resource.
- Exact owned record IDs and last-applied snapshots are required for update/delete.
  Only verified successful creates enter the managed-record store. There is no
  adoption or legacy import API in this pass. A delete keeps ownership history and
  the name reservation; the same resource can explicitly create again later.

## State transitions and recovery contract

| From | Allowed next states |
| --- | --- |
| prepared | dispatching, cancelled, conflict, failed |
| dispatching | verifying, uncertain |
| verifying | succeeded, retry-wait, conflict, uncertain |
| retry-wait | dispatching, cancelled, failed, conflict |
| uncertain | verifying |
| succeeded / failed / cancelled / conflict | None |

Conflict is retained and blocks the binding; operator resolution is deferred, not
silently implemented as an unlock. Uncertain operations can only return to
verification. Dispatched work cannot be cancelled or declared failed without first
resolving its outcome. A dispatch transition is durably committed before HTTP.

Every transition compares the operation revision and checks the current actor's
authorization. Dispatch additionally rechecks connection/binding readiness and
their saved revisions/credential reference. Rotation thus blocks old undispatched
intent rather than silently substituting a new secret. Read-only verification and
local inspection can remain available after revocation when the authorizer permits.

The transition API is **trusted-worker-only**, never a browser endpoint. Its proof
arguments represent comparisons that the future executor must actually perform:

- `matched`: intended content, marker, scope and record ID verified; successful
  create/update requires a record ID, and update cannot change it.
- `absent`: an owned delete ID is absent in an authorized provider lookup.
- `unapplied`: dispatch is proven to have made no change; required before retry-wait,
  together with a future retry timestamp. Dispatch before that timestamp is rejected.

The ledger cannot authenticate a caller-supplied proof. It enforces transition
structure, not provider truth. The future executor must hold the OS `worker_lock()`
across dispatch/verification and serialize per binding; metadata transactions alone
must never be treated as a provider mutation lock. Do not hold a DB transaction
around network IO. Authorizer callbacks must be local and bounded.

## station-access integration handoff

Keep the current installed dependency and existing APIs pinned until the new engine
is ready. This release is additive: Client, PorkbunClient, DnsRecords, existing CLI
commands and their on-disk JSON state formats are unchanged. The existing controller
does **not** acquire the new ledger guarantees simply by upgrading the package.

1. Supply owner/object-scoped Authorizer, encrypted-vault SecretResolver and either
   the reference local store or a Django-backed StateStore with equivalent atomic
   transaction semantics. Authorize reads as well as prepare/configure/transition.
2. Persist Connection and ZoneBinding with explicit account, selected zone and prefix.
   Credential refs must name immutable vault revisions; never contain key material.
   Do not mark ready from ping/domain listing alone. No automatic credential fallback
   may turn a disconnected binding back into a writable connection.
3. Keep browser API methods separate from internal transition methods. Future plan
   review and apply APIs should use request IDs and expected revisions. Operations
   expose local status/evidence, not secrets or raw provider errors.
4. Migrate existing assignments explicitly using preserved account, zone, record ID,
   resource identity and last-applied evidence. Do not manufacture ownership from
   matching names, addresses or comments. No automatic migration is shipped here.
5. Continue using the legacy controller until the executor, migration and integration
   acceptance tests land. Never run legacy and new writers on the same binding.

Minimal preparation (no DNS calls):

```python
from zog.network_register.store import SqliteStateStore
from zog.network_register.ledger import OperationLedger
from zog.network_register.models import Connection, ZoneBinding, Plan, RecordSnapshot

# actor_authorizer is supplied by the authenticated application.
store = SqliteStateStore('/protected/state/network-register.sqlite', create=True)
ledger = OperationLedger(store, actor_authorizer)
ledger.put_connection('admin', Connection(
    'cf', 'owner', 'cloudflare', 'account-reference', 'vault:credential:1'), 0)
# Starts discovered; trusted authority checks must precede ready state revisions.
ledger.put_binding('admin', ZoneBinding(
    'hosts', 'owner', 'cf', 'provider-zone-id', 'example.com', 'hosts.example.com'), 0)
```

## Remaining work

The provider-neutral planner, adapter implementations of these protocols, injected
transport/secret use in those adapters, public apply CLI, provider executor, real
three-way drift checks, post-write verification, retry classification/backoff,
Porkbun writes/idempotency replay, authority checks, credential rotation validation,
explicit adoption/migration, zone provisioning recovery and station-access UI
integration remain subsequent passes. Legacy purchase commands also remain exposed;
the full baseline's registrar restrictions are not yet enforced on the legacy CLI.

## Verification

See evidence/shared-foundation-tests.txt (dated private test evidence; results apply only to the stated source/test revision): 56 tests pass (27 existing + 29 new).
New coverage includes concurrent duplicate preparation, owner checks, stale
revisions, scope/TTL validation, revocation/rotation before dispatch, unresolved
binding blocking, exact ownership, deletion reservation, retry proof/time gates,
missing/unknown state, rollback, process exit before commit and after durable
dispatch, OS writer contention, and retention beyond 48 hours. No live provider
acceptance or station-access deployment is claimed.
