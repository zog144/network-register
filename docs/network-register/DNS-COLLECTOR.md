# DNS authority collector — 0.9.0

`DnsAuthorityCollector` supplies real DNS observations to the 0.8.0 EvidenceGate.
Install the optional DNS dependency with `pip install '.[dns]'`; dnspython 2.8.0
was used for fixture acceptance. Existing provider/legacy APIs remain compatible.

```python
from zog.network_register.dns_authority import DnsAuthorityCollector
collector = DnsAuthorityCollector()
evidence = collector.authority(connection, binding)
```

This performs DNS reads, not provider writes. A trusted application combines the
collector with its host evidence source and supplies that source to `EvidenceGate`.
No credentials enter DNS queries. The station-access companion pass provides that
adapter plus a read-only readiness command; it does not migrate the live controller.

## What is checked

The configured recursive resolver bootstraps the closest enclosing parent zone's
nameservers and resolves nameserver addresses. Queries use absolute names without
search-suffix expansion. The collector directly queries every discovered parent
server for its SOA and the selected child's delegation. Every parent must return
a referral with exactly the binding's explicitly selected nameserver set.

It then directly queries every pinned authoritative server for the zone SOA and
NS evidence at every label boundary between the zone and managed prefix. Each
answer must be authoritative for the exact zone. An NS referral/answer, CNAME,
DNAME, wrong-zone SOA, missing negative SOA, lame server, contradictory delegation,
malformed/truncated response, or unavailable server blocks evidence. NXDOMAIN
with the bound zone's authoritative SOA can establish an unshadowed prefix.

Queries use nonrecursive TCP with validated DNS responses. Only public unicast
server addresses are queried; aliases and nonpublic addresses are rejected.
Alternate server addresses are attempted only after transport failure, not after
contradictory evidence. Defaults: three seconds per query, 45 seconds total, 128
queries, at most 16 servers per set and eight addresses per server. Large or slow
configurations fail closed rather than silently skipping checks. No background
retry or cache is introduced. Returned timestamps conservatively precede the
queries they cover; EvidenceGate enforces the existing 300-second freshness limit.

## Trust and deliberate limits

This is DNS authority observation, not legal ownership proof or DNSSEC validation.
The recursive resolver is a trusted bootstrap dependency; use a resolver appropriate
for the deployment's threat model. Direct DNS TCP is not encrypted/authenticated
transport. A server hosting both parent and child may answer from the child apex
instead of exposing a parent referral; this collector rejects that ambiguous case.
It does not infer the parent delegation from the child's own NS answer.

The collector checks zone-to-prefix boundaries. Provider record inspection in the
engine remains necessary for exact managed names and ownership conflicts. The
collector does not claim authoritative visibility of a newly written A record.
No provider asset discovery, adoption, nameserver change, or zone creation occurs.

## Verification

191 network-register tests passed, including 24 wire-message collector fixtures.
They exercise delegation disagreement, aliases, prefix delegation, negative answers,
wrong SOA, non-authoritative answers, private/multicast destinations, budgets,
timeouts/address fallback, malformed responses and sanitized errors. Existing
ledger, lifecycle, Cloudflare and Porkbun tests remain passing. No live DNS or
provider acceptance is claimed. See evidence/dns-collector-tests.txt (dated private test evidence; results apply only to the stated source/test revision).

Protocol/API references: [RFC 1034](https://www.rfc-editor.org/rfc/rfc1034.html),
[dnspython query support](https://dnspython.readthedocs.io/en/stable/query.html),
[resolver API](https://dnspython.readthedocs.io/en/stable/resolver-class.html).
