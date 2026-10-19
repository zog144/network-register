# Cloudflare and Porkbun provider interfaces

## Provider adapters are different

Cloudflare and Porkbun expose different zone and record mechanisms. The shared DnsEngine owns the durable plan, while provider adapters translate exact provider record identity and transport. Cloudflare supports DNS-only A create/update/delete on selected zones with fixed HTTPS transport and no unreviewed redirects. Porkbun's native DNS adapter uses domain-backed zones and numeric record IDs, with injected API-key secret resolution.

## Credentials and authority

A configured provider entry or successful read-only domain listing is not proof of registration, managed-record ownership or write authority. The selected connection version, zone ID, nameserver authority and provider-reported record set must be rechecked before write. Secrets are resolved at execution from a protected provider, not embedded in durable plans or browser responses.

## Porkbun-specific edge cases

Some native provider operations require explicit first-record initialization or warning reconciliation. An accepted provider warning is not blanket success; the engine must verify the exact intended postcondition and stored record marker before accepting a recovered operation. Old source passes did not deploy a station writer merely by implementing a library adapter.

## Retained contracts and evidence

- [CLOUDFLARE-EXECUTOR.md](../CLOUDFLARE-EXECUTOR.md)
- [PORKBUN-WRITES.md](../PORKBUN-WRITES.md)
- [PORKBUN.md](../PORKBUN.md)

Exact schemas, chronological acceptance reports and live provider status remain separately verifiable. The synthesis does not turn prior source-only implementation into a deployed or authorized production service.
