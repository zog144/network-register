# Cloudflare planner and executor — network-register 0.6.0

Version 0.7.0 extends this engine to native Porkbun DNS; see
[PORKBUN-WRITES.md](PORKBUN-WRITES.md). The migration and integration limitations
below still apply. The record inspection validator now also preserves service labels.

Built from unstable cafcfad0ed0420414718c596074f1895fc30a6d5. This pass supplies
the next library layer over the shared foundation. No station-access pin was
updated, no running service was deployed, and no live provider operation was run.

## Delivered

`DnsEngine` plans owned DNS-only A creates/updates/deletes and executes saved
operations. `CloudflareDns` implements the DNS adapter with injected SecretResolver
and HttpTransport. CloudflareTransport verifies TLS, fixes the API host, rejects
redirects, limits response size and never retries a request. The adapter exposes
no purchase, registrar or zone-creation route. Existing legacy APIs/CLI remain
unchanged and still do not acquire the new engine's guarantees automatically.

Records, zones and errors use Cloudflare's documented v4 contract. GET zone checks
the exact selected account and ID; inventory is paginated explicitly and validated.
Unknown record types and unrelated wildcard records remain inspectable. Writes
use a unique nonsecret operation marker in `comment`, proxied=false and an explicit
effective TTL (minimum 300 seconds here). No Cloudflare idempotency header is assumed.
The adapter resolves the pinned credential reference, not arbitrary replacement keys.
HTTP 200 with success=false is failure; transport/5xx/malformed mutation responses
remain uncertain. Provider error bodies never become public errors or saved events.

## Workflow

Trusted application code supplies all authorization and publication policies:

```python
from zog.network_register.engine import DnsEngine
from zog.network_register.models import RecordSnapshot

engine = DnsEngine(ledger, publication_gate, secret_resolver)
desired = RecordSnapshot('worker.hosts.example.com', '8.8.8.8', 300)  # illustrative
plan = engine.plan(actor, owner_id, binding_id, host_uuid, desired, desired_revision=1)
if plan is not None:
    operation = ledger.prepare(actor, request_id, plan)
    operation = engine.apply(actor, owner_id, request_id, operation['revision'])
```

Do not copy the illustrative address into production. Supply the host's verified
public address. A plan is a detached immutable intent, not an execution or continuing
authorization. Persist/reuse its request ID and plan for duplicate requests. `plan`
may return None for unchanged desired state, producing zero provider mutations.
Deletion requires `desired=None, delete=True`; it is never inferred from a missed
heartbeat. DNS rename and adoption are not implemented.

`apply` advances a single saved operation and returns its durable state. On
`verifying` (or prepared with a preflight retry), a scheduler must wait until
`next_check_at` before calling again with the latest operation revision. No sleeping
or background worker is embedded in the library. `inspect_operation` reads local
evidence. Terminal duplicates return their saved result without provider calls.
An uncertain/conflicted operation stays blocked; no implicit resolution or replay.

## Required policy gate

PublicationGate.check(connection, binding, resource_id, desired, action, desired_revision) must
return None on success or raise a sanitized NetworkError. There is deliberately
no default implementation. A false return is rejected. Actions are:

- `inspect`: verify current authority for the selected domain/prefix, including
  delegation (desired_revision is None). API account access and an active zone alone do not prove authority.
- `publish`: additionally verify enrolled resource identity, matching inventory
  address and evidence no older than five minutes, plus current desired revision.
- `unpublish`: verify explicit removal intent and ownership authorization. A stale
  heartbeat is not removal intent.

The engine calls this gate before planning/reading and rechecks it after preflight
reads immediately before durable dispatch. The application Authorizer is checked
on scope reads and every transition, with an additional dispatch permission check.
Current connection/binding revisions and the saved credential reference must match.
Revocation/rotation therefore cannot silently substitute authority into old intent.
As with all remote APIs, authorization or manual DNS changes may still race a request
after the final local check. This pass does not claim a distributed transaction.

## Ownership and three-way comparison

Plans compare desired, stored last-applied and current provider snapshots. Stored
record ID and last operation marker must match. An external address, TTL, proxy,
marker or ID change, or manual deletion, blocks the binding instead of being repaired.
Matching the newly desired value does not excuse a change from last-applied state.

An existing unowned A record is not adopted, even if its address matches. Extra A,
CNAME/NS conflicts and delegated/CNAME ancestors block the name. Unrelated TXT and
other records remain untouched. Writes address only the owned ID, never an RRset.
Successful deletes retain the name reservation and operation evidence.

The planner marks detected drift as a blocked binding. Executor conflicts remain
unresolved operations, which block all subsequent mutation plans/preparations for
that binding. Operator resolution and adoption tools are deliberately deferred.

## Durable dispatch and recovery

One nonexpiring OS worker lock spans planning or execution; short SQLite transactions
protect metadata. No database transaction spans provider HTTP. A future Django
StateStore must supply the same worker_lock and durable transactional semantics.

Preflight reads compare current records immediately before dispatch. The dispatch
state commits before HTTP. Returned create/update IDs are saved as response evidence,
then a complete authorized inventory verifies exact name/content/TTL/proxy/marker/ID.
Only this comparison can mark the operation succeeded. A delete succeeds only when
its owned ID is absent from a complete authorized listing. A 404, forbidden lookup,
missing page or malformed response cannot prove absence.

On restart, a saved dispatching operation becomes verification-only. An empty listing
after a lost create response is never treated as permission to create again. An
unchanged update after timeout also remains unresolved. This executor conservatively
does **not replay mutations automatically**, including 429/5xx responses. Existing
foundation retry-wait metadata is not dispatched by this executor; automatic proven-
unapplied mutation retries need a later explicit implementation.

There are at most five preflight attempts and five verification attempts, with
counters committed before reads so a crash cannot reset the budget. Retry dates are
persisted; jitter is 1–60 seconds and a longer Retry-After wins. A pre-dispatch read
failure can safely end as failed because no mutation was attempted. A dispatched
outcome that cannot be verified becomes uncertain and blocks the binding. After
five attempts, further automatic verification also stops; operator recovery is a
later workflow. Unexpected exceptions preserve dispatch evidence and escape.

Success means **provider-applied and reread**, not globally propagated DNS or verified
authoritative answers. Propagation checking, shared provider rate scheduling and
broader authority implementation are not included here.

## Compatibility and remaining work

Version 0.5 ledger state opens without a schema rebuild. New optional marker,
response-ID, counters and due-time fields are additive. Existing managed records
without an ownership marker cannot be silently migrated: planning blocks them.
Legacy DnsRecords JSON is never imported or inferred from matching DNS values.
The version 0.6 engine is a library API; the existing CLI remains the legacy path.

Station-access needs no upgrade for this release. Continue the present pinned
controller until explicit migration, application authorization/evidence/delegation
gates, operation UI and integration acceptance are implemented. Never enable both
writers for the same scope. This pass does not claim full NR-001 compliance.

Next work includes Porkbun writes through this engine's contract, authority and
credential lifecycle implementation, explicit migration/adoption/conflict recovery,
and station-access integration. Registrar exclusions are enforced by the new adapter;
legacy registrar CLI removal remains part of the later transition.

## Verification

evidence/cloudflare-executor-tests.txt (dated private test evidence; results apply only to the stated source/test revision) records 101 passing tests: 56 previous and
45 new. Coverage includes fixtures through the real adapter, pagination, unknown
types, HTTP-200 errors, secret redaction, scope checks, manual drift, extra records,
lost create/update/delete responses, post-write divergence, delayed visibility,
storage failure after success, process exit after dispatch before HTTP, no replay
after 72 hours, authorization changes, locks, durable retry budgets and Retry-After.
All provider interactions in this pass were mocks/fixtures. No live DNS acceptance
or purchases were performed.

Official API contracts checked 2026-09-29:

- https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/create/
- https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/edit/
- https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/delete/
- https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/list/
- https://developers.cloudflare.com/api/resources/zones/methods/get/
