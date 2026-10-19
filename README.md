# network-register

**Public development source only.** The repository does not publish live registrar
accounts, DNS credentials, retained host/provisioning state or any authority to
change records. The provider integrations remain disabled unless an authorized
caller supplies its own credentials and policy. No production DNS changes were
made as part of this source migration.

**Documentation:** [Technical manual](docs/network-register/README.md) · [Source traceability](docs/network-register/TRACEABILITY.md). The manual organizes current concepts; linked detailed sources preserve exact contracts and historical evidence.

Network-register is Zog's Python library and CLI for delegated-account domain
registration and DNS management. Cloudflare and native Porkbun DNS support owned
A-record writes through the shared engine; the legacy Porkbun CLI remains read-only.
The user owns the account and pays the provider directly; the program uses the
user's scoped API authorization.

Version **0.12.0** includes [reviewed adoption and read-only recovery](docs/network-register/ADOPTION-CUTOVER.md),
extending the [bounded DNS authority collector](docs/network-register/DNS-COLLECTOR.md) and the
[authority/evidence policy and credential lifecycle](docs/network-register/AUTHORITY-LIFECYCLE.md).
It extends [Porkbun write support](docs/network-register/PORKBUN-WRITES.md) and the shared
[planner/executor with drift protection and verified recovery](docs/network-register/CLOUDFLARE-EXECUTOR.md),
built on the [shared operation ledger](docs/network-register/SHARED-FOUNDATION.md).
The new library engine requires explicit authority/evidence gates and separate state;
it does not replace the legacy station-access DNS controller automatically.
It also offers a **read-only reconciliation preview** with `DnsEngine.preview(...)`:
a non-binding, serializable explanation of desired vs. observed DNS, a candidate
create/update/delete or no-op, and explicit reasons for blocked operations.
Preview never prepares or dispatches a DNS write. See the
[preview contract and examples](docs/network-register/guide/reconciliation-and-evidence.md#read-only-reconciliation-preview-schema-1).
Existing Cloudflare/Porkbun interfaces remain compatible. The earlier
[Porkbun onboarding report](docs/network-register/PORKBUN.md) records its read-only live acceptance.

Station-access's central host-registry reconciler uses this library to maintain
owned host A records. Host-discover supplies authenticated host reports;
station-access verifies inventory and decides desired DNS state. Host-deploy
owns AWS provisioning. Network-register does not run a background worker or
verify cloud ownership itself.

This is the standalone development repository. Its Python component installs at
`zog.network_register` for local development, but public Python publication occurs
only through the aggregate `zog` distribution assembled by release-build. Station-access uses an external
immutable dependency pin; publishing here does not update that pin or any running
DNS controller.

## Install and credentials

Use Linux and Python 3.11+. Core runtime code uses the Python standard library. The optional DNS authority
collector requires dnspython: install `.[dns]` to enable it and run its tests.
From this repository:

```sh
python -m zog.network_register --help
# Optional installation provides the network-register command:
python -m pip install .
```

Supply `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` through the environment,
or a mode-0600 file outside the source tree with these labels:

```text
Account ID: YOUR_ACCOUNT_ID
API token: YOUR_TOKEN
```

Pass it with the global `--token-file /secure/cloudflare-token.txt` option.
DNS integration needs access to read the selected zone and edit its DNS records;
Registrar authorization is separate and needed only for registrar operations.
The account's registrant/contact/payment setup must be complete before purchase.
The `verify` command checks the account token endpoint; a failure there does not
by itself establish that a differently scoped DNS operation is unavailable.

## Manage an owned A record

The legacy CLI provides `a-set` and `a-remove`. New shared-engine integrations
should use the owner-bound ledger, `DnsEngine`, and `EvidenceGate` described above. Supply a registered domain with
an active zone, a fully qualified subdomain, a verified IPv4 address, and a stable
owner ID independent of mutable display labels. The names and address below are
examples; replace them with your own authorized deployment values.

```sh
network-register --token-file /secure/cloudflare-token.txt --state /var/lib/network-register a-set example.uk compiler.hosts.example.uk 192.0.2.10 --owner-id host-discover:HOST-UUID
network-register --token-file /secure/cloudflare-token.txt dns-show example.uk compiler.hosts.example.uk
network-register --token-file /secure/cloudflare-token.txt --state /var/lib/network-register a-remove example.uk compiler.hosts.example.uk --owner-id host-discover:HOST-UUID
```

Records are DNS-only (`proxied=false`). `a-set --ttl` accepts 60–86400 seconds;
the default is 60. Equal desired state makes no provider mutation. Removal is
idempotent and leaves the name reserved to its owner in local state. Unrelated,
ambiguous, differently owned or unexpectedly replaced records raise a conflict
and are preserved. There is no automatic adoption or owner-transfer operation.

The same contract is available in Python:

```python
from zog.network_register.client import Client, credentials
from zog.network_register.dns import DnsRecords

client = Client(*credentials('/secure/cloudflare-token.txt'))
dns = DnsRecords(client, 'example.uk', '/var/lib/network-register')
result = dns.ensure_a('compiler.hosts.example.uk', '192.0.2.10',
                      'host-discover:HOST-UUID', ttl=60)
```

`inspect(name)` reads exact-name records; `remove_a(name, owner_id)` removes an
owned assignment. Results include `action`, name, owner, zone and provider record.
See [the integration contract](docs/network-register/RECONCILER-HANDOFF.md) for recovery and error
handling. Older `dns-set` / `operations.ensure_a` remain compatibility APIs;
do not mix them with owner-bound `DnsRecords` on the same name.

## Registrar commands

| Command | Purpose |
| --- | --- |
| `search TERM`, `check DOMAIN...` | Query candidate domains/pricing |
| `register DOMAIN --maximum-usd AMOUNT` | Submit one guarded, billable registration attempt |
| `registration-status DOMAIN` | Inspect/recover the recorded registration outcome |
| `zones`, `zone-ensure DOMAIN` | List zones or explicitly create a pending zone |
| `verify` | Check account-token status |

`register` requires a fresh standard-tier USD quote within the supplied ceiling
and requests auto-renew disabled. That local quote check is not an atomic
provider price lock. `.uk` registrations support explicit `--registrant-type IND`
or `FIND`; use truthful account details. A zone operation does not purchase a
domain or establish public delegation.

Use one persistent `--state` directory for registration and status inspection.
The program records and synchronizes intent before purchase. A later `register`
for the same domain refuses resubmission even after an uncertain response; inspect
`registration-status` instead. There is no automatic purchase retry or force flag.
Deleting local state defeats this replay protection.

## State and source layout

`src/zog/network_register/client.py` handles the provider API and credential loading;
`src/zog/network_register/dns.py` implements owner-bound reconciliation; `src/zog/network_register/operations.py` contains registrar
and compatibility operations; `src/zog/network_register/state.py` implements local locking/durable writes.
`tests/` contains mocked provider tests.

The state directory holds `assignment-<name>.json` DNS reservations,
`registration-<domain>.json` purchase records and a local lock. Keep it on a
trusted local filesystem and back it up. After a lost mutation response, retry
DNS reconciliation with the same state so it can inspect the provider before
acting. Use one authoritative controller: this is neither distributed locking
nor provider-side compare-and-swap. Provider ownership comments are cooperation
markers, not an authorization boundary.

Historical `recovery/` state and the prebuilt `tools/host_deploy-0.9.0-py3-none-any.whl`
are intentionally excluded from this public source tree. They were not example
configuration for new deployments. The optional `host_demo` adapter requires
separately reviewed host-deploy source; it is not a DNS runtime dependency.

## Tests and current limits

```sh
python -m unittest discover -s tests -v
```

Tests cover pricing guards, uncertain purchase outcomes, durable preparation,
owner conflicts, response loss and unchanged/deleted DNS assignments. They use
mock providers and do not purchase domains or modify DNS. Historical live
acceptance evidence is retained privately and is not required or included in
this source-only public export.

The shared library engine supports Cloudflare and native Porkbun DNS-only IPv4
A records. The legacy CLI ownership path described above remains Cloudflare-only.
AAAA/CNAME writes, remote ownership transfer, and distributed controller
coordination are not implemented. DNS authority collection is available with the DNS extra; station-access provides
a companion trusted-host adapter/readiness check. Explicit ownership migration and
station-access integration of the new write controller remain separate work. The caller must verify addresses, serialize desired
revisions, and schedule retries. A failed inventory scan or missed heartbeat is
not proof that a host should lose its DNS record. CLI success returns JSON;
handled operational errors return status 1 with an error on stderr.


Private migration evidence, original source snapshots and historical live
acceptance reports are maintained separately; they are not copied into this
public source tree.
