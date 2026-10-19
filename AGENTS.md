# Repository workflow

Develop on public unstable only after migration acceptance. Preserve concurrent
changes, exact source identities and separate private historical evidence.

## Source hygiene (user policy, 2026-10-03)

Apply the installed `zog-source-hygiene` skill before publishing. Keep original Zog
implementation in Git; retrieve external dependencies from pinned sources. Document
narrow exceptions for necessary patches, legal notices and fixtures. Do not commit
wheels, eggs, generated bundles, dependency trees or transport archives. Keep required
fixtures readable and generate payloads outside the checkout. Preserve maintained
migrations and required notices; send chat evidence/handoffs to know-file. Review the
actual outgoing file list; ignore rules alone do not remove tracked artifacts.

Use canonical host-deploy sources/pins for maintenance tools; do not restore the removed tools wheel. It is not a network-register runtime dependency.
