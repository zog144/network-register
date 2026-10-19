# Adoption, cutover and uncertain-provider recovery

## Exact old record adoption

Moving from a legacy DNS writer to the shared engine is explicit. An administrator freezes the old writer, reviews each record's canonical name, owner, type, address, TTL, proxied flag, exact provider ID and recognized operation marker, then imports the binding without performing a provider write. A matching value with a foreign/unknown marker is **not** proof of ownership.

## Single-writer transition

The new durable owner state and credentials must be initialized before activation, and the original writer must be disabled/fenced. Do not run two reconciliation controllers over the same names. Missing ledger, wrong selection or uncertain provider result blocks publication instead of recreating state. Read-only recovery and provider inspection may identify the known operation, but not erase an ownership conflict.

## Revisions survive reuse

Name release, provider deletion and host archival are separate operations. Historical allocation generation, tombstones, audit and completed receipts remain after release; old queued commands cannot reclaim a reused name. Exact current actor and connection revisions control resumption.

## Retained contracts and evidence

- [ADOPTION-CUTOVER.md](../ADOPTION-CUTOVER.md)
- [NAME-LIFECYCLE.md](../NAME-LIFECYCLE.md)
- [RECONCILER-HANDOFF.md](../RECONCILER-HANDOFF.md)

Exact schemas, chronological acceptance reports and live provider status remain separately verifiable. The synthesis does not turn prior source-only implementation into a deployed or authorized production service.
