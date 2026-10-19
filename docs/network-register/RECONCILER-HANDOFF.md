# Historical network-register 0.3.0 host-discover handoff

**Version-scoped historical Cloudflare-only integration guidance.** Version 0.3.0 exposed `zog.network_register.dns.DnsRecords` as a library/CLI, not a daemon, with Python 3.11+ standard-library dependencies and Linux filesystem locking. This is not the maintained central DNS reconciliation service's complete current provider or lifecycle contract: current support also covers Porkbun and central reconciliation decisions. Consult the [provider interfaces](guide/provider-interfaces.md), [reconciliation and evidence](guide/reconciliation-and-evidence.md), and [authority lifecycle](AUTHORITY-LIFECYCLE.md) before implementing new integrations.

## Python API

```python
from zog.network_register.client import Client, credentials
from zog.network_register.dns import DnsRecords, DnsConflict

client = Client(*credentials('/secure/cloudflare-token.txt'))
dns = DnsRecords(client, 'example.org', '/var/lib/host-discover/network-register')
owner_id = 'host-discover:' + str(host_primary_key)  # immutable, never display label
name = 'compiler-01.hosts.example.org'

result = dns.ensure_a(name, verified_public_ipv4, owner_id, ttl=60)
records = dns.inspect(name)
# On confirmed stop/termination or explicit unpublish:
result = dns.remove_a(name, owner_id)
```

Credentials file format is `Account ID: ...` and `API token: ...` on separate lines. Alternatively call `credentials()` to load CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN from the environment. Tokens stay on the controller. No credentials are bundled.

The **example.org** strings above are reserved illustrative placeholders, not an active zone or a deployment instruction. In an actual configuration, the supplied domain must be registered and have an active zone. Neither zone creation nor domain purchase belongs in the normal host reconciliation loop. Configure Zone Read and DNS Edit with scope including this zone. Runtime inspection does not require Registrar permissions. Account-token verification and policy inspection are separate permissions and need not succeed for DNS operations to work.

`ensure_a` returns a JSON-serializable object with `action` (created, updated, unchanged), `name`, `owner_id`, `zone_id`, and the Cloudflare `record`, including its `id`. `remove_a` returns action deleted or absent, and record null. Repeated equal desired state does not issue a provider mutation. `inspect` returns the list of exact-name provider records without modifying local state.

Only IPv4 A records are managed. Names must be full subdomains of the configured domain; nested names under hosts are supported without creating a separate zone. Records are DNS-only (proxied=false). TTL accepts 60–86400 seconds. Address syntax is validated; the caller must ensure the address is verified and appropriate for public publication.

## CLI

```bash
network-register --token-file /secure/cloudflare-token.txt --state /var/lib/host-discover/network-register a-set example.org compiler-01.hosts.example.org 192.0.2.10 --owner-id host-discover:123
network-register --token-file /secure/cloudflare-token.txt dns-show example.org compiler-01.hosts.example.org
network-register --token-file /secure/cloudflare-token.txt --state /var/lib/host-discover/network-register a-remove example.org compiler-01.hosts.example.org --owner-id host-discover:123
```

192.0.2.10 is an example, not a deployable host address. Successful CLI output is JSON on stdout; errors go to stderr with exit status 1. Existing `dns-set`/`operations.ensure_a` are legacy compatibility interfaces; they do not have owner-bound reservations. Do not mix them with DnsRecords on the same name. Existing legacy records are deliberately not adopted by the new interface.

## Ownership, recovery and concurrency contract

Use one persistent state directory and one authoritative controller for the domain. Keep it on a trusted local filesystem, back it up, and preserve it across deployments. Do not put state in disposable build directories. The library serializes operations with a nonblocking Linux file lock. Lock contention raises OSError/BlockingIOError: the worker should retry later.

Every assignment binds account, zone, FQDN and immutable owner ID. It records the provider record ID after creation. Names remain reserved to their original owners after removal. Changing owner or zone identity is a conflict requiring explicit operator resolution; there is no automatic transfer, force-overwrite, or reservation-release API in this pass.

Unrelated, multiple, differently owned, or unexpectedly replaced provider records cause DnsConflict and are preserved. A comment containing an owner digest supports recovery after a lost create response; it is not a security boundary. Existing records are never adopted when local assignment state is absent. A deleted owned record may be recreated if the same owner still desires it. Changes to an otherwise matching owned record's address/TTL/proxy setting are reconciled back to desired state.

Intent is durably saved before remote mutations. Timeouts or failed response saves may mean the mutation succeeded. Retry through the same DnsRecords instance configuration/state directory: it lists the exact name before deciding whether another mutation is needed. Never bypass this with a raw create retry or an empty state directory. Storage faults require restoration of storage before retrying.

This is not a distributed lock or provider-side compare-and-swap. Other controllers or humans must not concurrently edit the same managed names. Host-discover must serialize desired revisions and prevent an older queued job from applying after a newer one. A routine periodic reconciliation handles lost wakeups. This earlier library interface does not schedule retries or perform AWS verification; the current central reconciler owns decision scheduling and separately relies on the authoritative enrollment/inventory model.

## Errors and host-discover responsibilities

- DnsConflict: surface a conflict; do not overwrite or automatically adopt.
- ValueError: invalid caller input/configuration; correct it before retrying.
- CloudflareError (zog.network_register.client): API rejection or transport/response failure. Surface its sanitized message; use bounded backoff. A permission error needs configuration correction. This version exposes a message, not structured HTTP status/retry-after fields.
- OSError: local state/storage/locking failure; remote outcome may be uncertain if it occurred after the mutation.

Persist publication opt-in, unique stable DNS label, immutable owner ID, desired address/revision, applied result and last error in host-discover. Authenticate enrollment and verify EC2 identity/addresses from successful inventory. A failed scan or missed beacon is not proof of termination. Confirmed stop/termination removes owned records to avoid retaining released IPs. Keep names reserved. TTL expires resolver caches, not provider records.

A dated Cloudflare acceptance exercised provider record operations and cleanup for this historical interface; it did **not** accept the proposed host-side example reconciler. The associated evidence is retained privately and is not a prerequisite for understanding the current public provider and central reconciliation contracts.
