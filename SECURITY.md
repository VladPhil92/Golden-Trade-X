# Security Policy

Golden Trade X handles trading execution, account state and operational telemetry. Security defects can therefore become financial-risk defects and are treated with the same priority as correctness failures.

## Supported versions

Only the current `main` branch and the latest published release are supported for security fixes. Historical tags are immutable evidence and may remain vulnerable; upgrade rather than patching an old deployment in place.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that exposes credentials, enables unauthorized execution, bypasses risk controls or could facilitate account compromise.

Prefer GitHub Private Vulnerability Reporting when it is enabled for this repository. If that channel is unavailable, contact the maintainer through the public project contact listed in `README.md` and clearly mark the message `SECURITY — Golden Trade X` without including live credentials.

Include, where possible:

- affected commit/tag;
- affected file/module;
- reproducible steps or minimal proof of concept;
- expected vs actual behavior;
- impact assessment;
- whether any secret may have been exposed.

Never send real broker passwords, API keys, Telegram tokens or private keys in a report. Redact them and rotate any credential suspected of exposure.

## Security invariants

- No tracked `.env` or live credential material.
- GitHub Actions use least-privilege permissions.
- Trading/runtime code must fail closed when authorization, ownership or broker execution state is ambiguous.
- Dependency and secret-scanning gates are blocking for integration.
- Production credentials must be injected at runtime and must not be embedded in `.mq5`, `.mqh`, Python, workflow or config files.
- Security findings that can affect execution, risk state or metrics are P0 and block feature work.

## Disclosure and remediation

The maintainer will validate the report, prepare a focused fix with regression coverage, verify CI/MetaEditor where applicable, and document the remediation without publishing exploit-enabling secrets. A vulnerability is not considered resolved solely because a credential was deleted from the current tree; exposed credentials must also be rotated and repository history assessed.
