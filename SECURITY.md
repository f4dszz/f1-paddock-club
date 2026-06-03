# Security Policy

F1 Paddock Club ships real OAuth sign-in (Clerk), JWT verification, Postgres
persistence with per-identity trip isolation, and a public deploy. If you find a
security issue, please report it privately so it can be fixed before it is
disclosed publicly.

## Reporting a vulnerability

- **Email:** szding0119@gmail.com — please put `SECURITY` in the subject line.
- Alternatively, use GitHub's private
  [Report a vulnerability](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  flow from the repository's **Security** tab.

Please include:

- A description of the issue and the impact you believe it has.
- Steps to reproduce (a proof-of-concept request, payload, or sequence).
- The affected component (backend `/ws`, `/plan`, auth, persistence, frontend
  bundle, deploy config, etc.) and any relevant logs.

**Please do not** open a public GitHub issue for a security vulnerability, and
do not run automated load/abuse tests against the live deploy.

## Response expectations

This is a portfolio-stage project maintained by one person, not a funded
product with an on-call rotation. Best-effort targets:

- Acknowledge a report within **5 business days**.
- Provide an initial assessment (accepted / needs-info / not-a-vuln) within
  **10 business days**.
- For accepted issues, agree a remediation timeline with the reporter and
  coordinate public disclosure once a fix has shipped.

## Supported versions

There is a single rolling deploy from the `main` branch; there are no
long-lived release branches. Only the latest `main` (and the live deploy built
from it) is supported. Tagged releases in `CHANGELOG.md` are historical
records, not separately patched lines.

| Version            | Supported |
|--------------------|-----------|
| `main` (latest)    | ✅        |
| Older tags / forks | ❌        |

## Scope and known limitations

The deployment design (`docs/deployment-design.md`) and `CHANGELOG.md` document
the security baseline that has shipped (fail-closed auth, Clerk JWKS handling,
per-identity isolation, CORS/Origin allowlist, CSP/HSTS, rate limiting, secret
scanning). A few mitigations are intentionally targeted rather than complete and
are tracked as known limitations:

- **In-process rate limiter.** Per-IP limits live in process memory and reset on
  restart; they are not shared across multiple instances. A Redis-backed (or
  edge) limiter is the documented next step for a multi-instance deploy.
- **WebSocket credential in the query string.** The Clerk/demo token is passed
  as a `/ws` query parameter (the only mechanism a pure-browser `WebSocket`
  client has on the initial handshake). The token is scrubbed from Sentry events
  and is never logged server-side; moving it into a `Sec-WebSocket-Protocol`
  subprotocol handshake is a documented future hardening step.

If you are unsure whether something is in scope, report it anyway and we will
triage it.
