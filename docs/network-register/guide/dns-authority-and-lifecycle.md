# DNS authority and name lifecycle

## Separate ownership from observed DNS bytes

Network-register implements provider-agnostic DNS state and durable ownership. An enrolled Host UUID, a reserved canonical child name, an authorized DNS zone/binding, desired publication revision and a provider record ID are independent identities. A mutable host display label or self-reported address cannot by itself assign DNS ownership.

## Evidence before publication

An external privileged evidence collector must authenticate accepted signed host identity, fresh AWS inventory agreement, public address and provider-zone authority. A typed value delivered by browser JSON is not evidence that those checks occurred. Selected zone nameservers and current provider credentials require explicit authority/connection checks; unsupported or conflicting evidence blocks publication.

## Reserve, publish, unpublish, release

Name reservation is a reviewed provider-read operation with durable allocation and receipt. Publication is a separate plan/prepare/apply operation guarded by current evidence and revisions. Unpublish records explicit absence intent **without releasing the name**. Release requires verified provider absence and exact ownership, while preserving tombstones and audit history. Fresh allocations start beyond old revision floors.

## Retained contracts and evidence

- [AUTHORITY-LIFECYCLE.md](../AUTHORITY-LIFECYCLE.md)
- [NAME-LIFECYCLE.md](../NAME-LIFECYCLE.md)
- [HOST-DISCOVER-DNS-DESIGN.md](../HOST-DISCOVER-DNS-DESIGN.md)

Exact schemas, chronological acceptance reports and live provider status remain separately verifiable. The synthesis does not turn prior source-only implementation into a deployed or authorized production service.
