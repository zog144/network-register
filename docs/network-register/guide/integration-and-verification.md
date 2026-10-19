# Integration and verification

## Owners and interfaces

The reusable DnsEngine/connection/provider layer is installed under the single Zog namespace and consumed by station-access's reviewed central controller. Host-discover supplies signed host evidence; EC2 inventory and approved Host identity are independent checks. The shared provider library does not automatically make old Cloudflare-only station code a two-provider writer.

## Verification ladder

Unit fixtures can prove canonical DNS record representation, credential redaction, journal replay, provider response validation, stale-evidence rejection and state transitions. Independent read-only domain checks can confirm provider connectivity. A live write test on an explicitly owned disposable record must separately verify create, update, unpublish, release, wrong-owner refusal and recovery after a lost response.

## Backups and release

Preserve provider connection revisions, ownership ledger, request receipts, station registry configuration and encrypted vault keyring as a coordinated recovery set. After a version change, identify current provider capability and selected worker explicitly before claiming activation. Old provider-specific historical notes remain as evidence, not live readiness claims.

## Retained contracts and evidence

- [SHARED-FOUNDATION.md](../SHARED-FOUNDATION.md)
- [PORKBUN-WRITES.md](../PORKBUN-WRITES.md)
- [CLOUDFLARE-EXECUTOR.md](../CLOUDFLARE-EXECUTOR.md)
- [ADOPTION-CUTOVER.md](../ADOPTION-CUTOVER.md)

Exact schemas, chronological acceptance reports and live provider status remain separately verifiable. The synthesis does not turn prior source-only implementation into a deployed or authorized production service.
