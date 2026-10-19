# Public source migration and provider safety

Public source publication transfers **only** reviewed Git source files.
Historical `recovery/` files contain actual account, region, host, DNS, zone
and request identities, and remain in the private archival repository. The
prebuilt host-deploy wheel is also excluded and must be rebuilt independently.

This repository's unit CI must operate with mocked Cloudflare/Porkbun provider
clients, temporary state and no credential variables; no network-enabled test,
domain purchase, DNS write, AWS provision or background reconciler is an
acceptance requirement for the first public source push.

Future live acceptance is a separate operator-authorized gate requiring exact
provider account ownership, allowed zone, tested inventory/IP/host evidence,
durable transaction recovery, and negative tests for conflicting/manual DNS
changes. Do not infer authority from source publication or old recovery state.

Public source CI must compile/test without secrets or privileged host execution,
check retained first-party rights and source packaging, and verify an exact
clean-history Git tree. The new public `unstable` branch must be approved
separately; public `main` promotion is a later reviewed operation.
