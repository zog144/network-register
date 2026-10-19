# Third-party notices — network-register development source

The Zog-owned network-register source is licensed **BSD-3-Clause OR
GPL-3.0-only**. The full grant and license texts are in LICENSE and LICENSES/.
No upstream provider's code or website, acquired account domain, private API
key, live DNS state or downloaded runtime dependencies are relicensed here.

The optional `dns` dependency installs dnspython 2.8+ (ISC license);
dependency bytes and installed transitive packages are separate and must be
reviewed against the actual build/install manifest before redistribution.
Cloudflare and Porkbun are external DNS/registrar providers accessed through
their APIs; their third-party terms and hosted data are not bundled software.
The optional host-deploy adapter requires separately supplied compatible Zog
host-deploy source, not a bundled wheel.

This source-only publication does not authorize domain purchase, A-record
changes, secret distribution, live DNS reconciliation, or rootfs/image delivery.
