# Porkbun onboarding — network-register 0.4.0

Historical onboarding report. Version 0.7.0 adds optional native DNS writes through
the shared engine; see [PORKBUN-WRITES.md](PORKBUN-WRITES.md). The original read-only
client and CLI remain unchanged.

This first adapter supports read-only credential verification, account domain listing and DNS record inspection alongside the unchanged Cloudflare registration and owner-bound A-record APIs. It has no Porkbun purchase, renewal, transfer, funding or DNS mutation endpoint.

```python
from zog.network_register.porkbun import PorkbunClient, credentials
client = PorkbunClient(*credentials('/secure/porkbun-api.txt'))
client.verify()
page = client.list_domains(start=0)
records = client.records('owned-example.com')
```

A credential file uses `API Key:` and `Secret Key:` labels; a value may follow its label on the next line. `Secret API Key:` is also accepted. Environment variables: PORKBUN_API_KEY and PORKBUN_SECRET_API_KEY. Both keys are required and must remain outside source trees.

CLI: `python -m zog.network_register --token-file /secure/porkbun-api.txt porkbun-verify`, `porkbun-domains --start 0`, and `porkbun-records owned-example.com`. These commands never construct a Cloudflare client.

The client calls the fixed HTTPS api.porkbun.com host, refuses redirects, uses 25-second timeouts and a 2 MiB response ceiling, and exposes sanitized errors without raw provider bodies. Porkbun's supported POST read endpoints are used; no automatic retries or implicit pagination occur. A page contains at most 1000 sanitized domains; next_start is supplied when a full page suggests more. Listed domains do not establish DNS authority or write access. DNS record inspection requires per-domain API access.

## Station-access compatibility

Registries already saves `{api_key, secret_key}` in its revision-bound encrypted vault. The UI now exposes Porkbun read checks, calls one bounded domain-list request, and displays at most 50 sanitized entries with a truncation indicator. Saved metadata exposes can_check=true while supported=false continues to mean the existing authoritative Cloudflare DNS controller cannot select Porkbun. Credential edits invalidate old checks. Check/save never expose keys or mutate DNS. No model migration is needed for Porkbun.

The station-access dependency snapshot contains the identical porkbun.py module. The separate network-register repository remains its source of truth; replacement of the older bundled dependency is outside this pass.

## Live acceptance 2026-09-27

User-supplied credentials authenticated successfully with /ping. /domain/listAll succeeded and returned zero domains. No domain was purchased and no DNS, payment, account or credential setting was changed. DNS record inspection is covered by fixtures only because the account has no domain. The supplied secrets were not saved to GitHub or installed in a running station.

Official references: https://porkbun.com/api/json/v3/documentation and https://porkbun.com/llms/domain and https://porkbun.com/llms/dns.

Next pass: after a user-owned domain is available, design and test owner-bound Porkbun DNS writes and explicit controller/provider binding. Do not point a Cloudflare controller's existing state at Porkbun.
