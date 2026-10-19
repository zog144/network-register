# Native Porkbun DNS writes — network-register 0.7.0

Based on unstable 292e1865d1294546a6fe910167faf7f92e2f48b6. This pass adds a
PorkbunDns adapter to the existing shared DnsEngine. No live provider requests with
user credentials, purchases, funding operations, DNS changes or deployments were
performed. Official API documentation was read; execution tests use local fixtures.

## Implemented scope

- Existing accessible domain-backed native Porkbun DNS; the zone ID is its canonical
  domain name. No generic zone creation or deletion is exposed.
- Create DNS-only A records; edit/delete by exact owned numeric record ID.
- Same durable operation ledger, name reservations, three-way comparison, host UUIDs,
  external authority/evidence gate and revision checks as the Cloudflare engine.
- Header authentication with X-API-Key and X-Secret-API-Key from an injected vault
  resolver. References, not credentials, are saved in plans and operations.
- Fixed HTTPS API host, redirect refusal, bounded response size, sanitized errors,
  no adapter retries and an explicit read/write endpoint allowlist.

The allowlist includes domain/listAll, dns/preflight, dns/retrieve, dns/create,
dns/edit by ID and dns/delete by ID only. It excludes all registrar mutations,
funding, nameserver changes, proxy management and name/type bulk replacements.
Existing PorkbunClient and porkbun-* CLI commands remain the read-only onboarding
interface. New writes are a library feature and are not automatically enabled in
station-access.

## Representation and verification

Write inputs are canonical full host names. The adapter enforces zone membership
and converts them to relative Porkbun input names: one.hosts.example.com in
example.com becomes one.hosts. Apex/wildcard/unsupported record writes are rejected.
The planned TTL must be at least 600 seconds. Set it explicitly; no provider default
or TTL=0 is used. Accounts with a higher effective minimum need an explicit matching
desired TTL; silent provider clamping fails verification and blocks further writes.

Porkbun numeric record IDs are exposed as strings. Read results normalize numeric TTL
strings to integers and notes to the engine's marker/comment field. Unknown types,
wildcards and service labels such as _acme-challenge are preserved for inspection;
unrelated records remain untouched. The shared/Cloudflare inspection path was fixed
to accept service labels too, without relaxing host A-record write validation.

An update success has no returned record object, so the adapter reports the requested
ID, and the executor separately rereads the inventory. No write response alone is
accepted as proof of completion. Missing create-response IDs and lost responses are
resolved using complete authorized reads and the saved marker/content/scope.

## Native authority checks and warnings

Porkbun retains a DNS zone even if another provider serves the domain. API success
therefore does not imply active DNS authority. Before dispatch, get_zone requires a
matching domain in dns/preflight and an explicit successful nameservers-ours check.
An absent/ambiguous check blocks. DNS inventory must explicitly report
cloudflare=disabled; unknown or enabled proxy state is outside this adapter's scope.

These provider checks supplement, and do not replace, the required PublicationGate
which verifies parent delegation, authoritative evidence and fresh host/inventory
identity/address evidence. The account_ref is an operator-defined stable account
label; Porkbun does not return a verified account identifier through these reads.
Connection discovery alone does not grant management or prove write permission.

Any nonempty warnings on a successful write produce a ProviderWriteWarning. The
engine records a conflict, retaining a returned create ID when available. It never
declares success merely because the stored record matches after that warning.
The write may already have happened; conflict is not rollback. Raw warning strings
are excluded from the operation record and public exception to avoid leaking data.
The unresolved operation blocks the binding for operator review. A lost response
still relies on current authority checks and the explicit verification budget.

## Idempotency and recovery

Every POST includes the operation's saved step_key as Idempotency-Key. Relative
name, TTL, address and operation notes produce a deterministic business payload.
The same operation therefore retains both key and payload across retries. The
provider documents a 24-hour replay window; this is not an indefinite guarantee.

The shared executor remains conservative: it automatically repeats reads only,
never mutations. A dispatched timeout, 5xx or missing listing is verified and then
left uncertain if unresolved. It does not repeat a create either within the provider
window or after it expires. Tests cover elapsed 25/49 hours. A direct adapter retry
fixture demonstrates identical headers/body and one simulated provider creation;
this does not introduce automatic replay into DnsEngine.

Read attempts and retry times remain durable and bounded. Longer Retry-After values
are honored. Revocation, unexpected exceptions or storage failure retain the existing
operation evidence. Success means provider-applied and reread, not globally propagated
DNS. Automatic conflict resolution and post-budget verification remain future work.

## Integration

Construct a ready, explicitly verified Connection(provider='porkbun') and ZoneBinding
with zone_id=zone_name=the selected domain. Store the user's API pair under an immutable
credential reference. SecretResolver.resolve returns {'api_key': ..., 'secret_key': ...}.
DnsEngine now selects the proper adapter from the connection provider; the normal
plan/prepare/apply workflow from CLOUDFLARE-EXECUTOR.md is unchanged.

Supply the same non-permissive Authorizer and PublicationGate contracts. Never mark a
binding ready just because credentials save, domain listing, ping or preflight succeeds.
The adapter does not supply the independent authoritative resolver or cloud verifier.
Do not direct existing Cloudflare binding state at Porkbun; create an explicitly
authorized new binding, then follow a future explicit migration workflow.

No station-access upgrade is needed now. It remains pinned to the existing controller.
Migration/adoption, authority and credential lifecycle implementation, operator recovery,
station-access UI/controller wiring and live acceptance are still outstanding.

## Validation

See evidence/porkbun-write-tests.txt (dated private test evidence; results apply only to the stated source/test revision): 131 tests pass (101 previous plus 30 new).
Coverage includes a complete engine-to-adapter HTTP fixture lifecycle, notes/ID/TTL
translation, account-minimum mismatch, service records, pagination, forbidden routes,
header-only authentication, stable idempotency payloads, lost responses, expiration,
manual drift, wrong authority, proxy state, warnings after applied writes, missing
records/IDs, HTTP-200 errors, 429/5xx handling and secret redaction.

No sandbox or production account acceptance was performed. When a suitable domain is
available, use a separately authorized test prefix and recorded test IDs. Account
funding is not a requirement for these fixture tests, and no purchase is part of this pass.

Official contract checked 2026-09-29:

- https://porkbun.com/api/json/v3/spec (v3.44)
- https://porkbun.com/llms/dns
- https://porkbun.com/llms/domain

## Explicit first-record initialization (0.11.1)

`zog.network_register.initialization.initialize_porkbun_a` supports an operator-requested
first A record before a newly registered native Porkbun zone serves its SOA.
It is a separate library operation, never a fallback inside normal reconciliation.
The caller supplies an authorized ledger connection/binding, trusted EvidenceGate,
DnsAuthorityCollector, credential resolver, and the exact host intent.

Requirements: the exact four supported Porkbun nameservers must be pinned and
confirmed directly at every discovered parent nameserver; the domain must appear
in the authenticated account; editable native DNS inventory must be empty;
approved enrollment, fresh signed host evidence and matching AWS inventory must
pass the existing host policy. Existing names and nonempty zones are not adopted.

The operation pins its exact inputs and uses the normal durable operation ledger,
ownership marker and idempotency key. Lost responses are inspected, never blindly
redispatched. Repeated calls address the same operation; changed intent is rejected.
Keep the ledger for later explicit adoption/migration and cleanup. Do not delete its
state or recreate it to retry. Provider warnings remain a conflict requiring review.

A `succeeded` result means only provider-applied. Query SOA and A responses from all
nameservers afterward, and pass the normal authority gate before enabling ongoing
reconciliation. This operation does not configure station-access multi-provider
assignments or make a second destination appear in its host UI.

## Porkbun managed backend and accepted-warning recovery (0.12.0)

The `cloudflare` flag alone does not identify an externally moved domain: Porkbun
can report `enabled` while its own nameservers remain authoritative. The adapter
accepts either known flag value, requires `nameservers-ours` preflight for enabled
responses, retains the external delegation/SOA gate, and rejects explicit
per-record proxying. It continues to use Porkbun credentials and `/dns/*` routes;
it never selects the Cloudflare adapter or queues a domain move. Initialization
still requires an empty, initially native inventory and remains explicit.

`DnsEngine.recover_accepted(actor, owner, request_id, expected_revision)` resolves
an accepted-write conflict using provider reads only. It requires an existing
response record ID, unchanged scope/credentials/revisions/host intent, current
DNS authority, and an exact ID, ownership marker and desired record match. It
records success in the existing ledger rather than creating a replacement record.
Mismatched or missing records remain conflicts. This is an explicit operator
recovery operation, never an automatic mutation retry.
