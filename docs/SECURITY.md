# SPILLTRACE — Security Review

**Owner:** SEC · Traces: prompt §23, CON-004, NFR-007…NFR-011
**Status:** reviewed against the checklist below; findings and their resolutions recorded inline.

---

## 1. Threat model, briefly

SPILLTRACE holds investigation material that names vessels and operators. The
consequences of getting security wrong are not only technical:

* **Disclosure** — an unfinished, uncertain attribution leaking out could damage a
  vessel operator who did nothing wrong. Object-level authorisation is therefore not a
  nicety.
* **Tampering** — an altered score, geometry or timestamp destroys the evidential value
  of everything downstream. Hence checksums and run manifests on every artifact.
* **Credential theft** — Copernicus and AIS credentials are ours and are rate-limited
  and attributable; leaking them is both a cost and an integrity problem.

## 2. Checklist

| Item | Status | How |
|---|---|---|
| Authentication | Done | Email + password, Argon2id (RFC 9106 second-recommended: 64 MiB, t=3, p=4) |
| Password policy | Done | 12-character minimum enforced in `core/security.hash_password` |
| Timing side-channel on login | Done | `dummy_verify()` burns a real Argon2 verification when the email is unknown, so response time does not reveal whether an account exists |
| Session security | Done | Short-lived JWT (15 min) returned in the body; refresh token in an httpOnly, SameSite=Lax cookie scoped to `/api/v1/auth`, `Secure` in production |
| Refresh rotation | Done | Every refresh issues a new token and revokes the old; only a SHA-256 hash is stored, so a database leak yields no usable session |
| Authorization (IDOR) | Done | `CaseRepository._visibility` filters by owner in the repository, not the router, so a new endpoint cannot forget it. Unauthorised access returns **404, not 403**, so ids cannot be probed |
| Privilege separation | Done | `analyst` / `admin`; hard delete and system status are admin-only |
| Input validation | Done | Pydantic v2 at the edge; `validate_polygon` and `validate_time_window` in the domain; AOI area and window length capped |
| SQL injection | Done | SQLAlchemy Core/ORM with bound parameters throughout. No f-string SQL anywhere in `src/` |
| XSS | Done | The report escapes every interpolated value (`html.escape`); a test injects `<script>` into a case title and asserts it is escaped. The frontend is React with no `dangerouslySetInnerHTML` |
| CSRF | Mitigated | The API is token-authenticated (not cookie-authenticated) for every state-changing call; the refresh cookie is `SameSite=Lax` and is only accepted at `/api/v1/auth/refresh` |
| Secrets in the frontend | Done | The browser talks only to our API. `make audit-secrets` greps the built client bundle for credential-shaped names and fails the build; the CSP pins `connect-src` |
| Secrets in the repository | Done | `.env` is gitignored and mode 600; `.env.example` carries placeholders; `init_env.sh` generates real values with `openssl rand` |
| Secrets in logs | Done | A structlog processor redacts any field whose key contains password/secret/token/api_key/authorization/credential |
| Secrets in errors | Done | Driver messages are logged, never returned. `IntegrityError` becomes a generic 409; unhandled exceptions become a generic 500 with the type name only |
| Rate limiting | Done | 10 logins / 5 min / (IP, email); 60 refreshes / 5 min; 60 job creations / min. Fails **open** with a warning if Redis is down — losing rate limiting is bad, refusing all logins because a cache is down is worse |
| File upload | N/A | There is no user file upload. Artifacts are produced by workers and stored with a server-generated key |
| Path traversal | Done | `LocalObjectStore._path` resolves and rejects any key escaping the storage root |
| Object storage exposure | Done | The MinIO bucket is created with anonymous access **off**; downloads go through the API or a presigned URL |
| Container hardening | Done | Both images run as a non-root user; the backend image installs no compilers at runtime |
| Transport security | Deployment | HSTS is emitted when the request is HTTPS; TLS termination is the deployment's responsibility (`docs/DEPLOYMENT.md`) |
| Dependency risk | Partial | Versions are pinned with upper bounds in `pyproject.toml` and `package-lock.json`. A scheduled vulnerability scan is **not yet wired into CI** — see §4 |

## 3. Response headers

`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
`Permissions-Policy: geolocation=(), microphone=(), camera=()`, and HSTS on HTTPS.
The frontend additionally sets a CSP whose `connect-src` is `'self'` plus the configured
API origin, so the "no third-party calls" rule is enforced by the browser rather than by
convention.

## 4. Known gaps, stated plainly

1. **No dependency vulnerability scanning in CI.** `pip-audit` and `npm audit` should run
   on a schedule. Not yet wired.
2. **CSP retains `script-src 'unsafe-inline'`.** A nonce policy needs request-time
   middleware that would opt every route out of static rendering. Documented as a
   trade-off in `frontend/next.config.ts`.
3. **The SSE endpoint accepts the access token as a query parameter**, because
   `EventSource` cannot set headers. It is narrowly scoped: one read-only endpoint,
   short-lived token, ownership still checked. It does mean the token can appear in
   proxy access logs — a fetch-based streaming client would remove this and is the
   right follow-up.
4. **No audit log of who read what.** For a system holding investigation material, read
   access to a case is arguably worth recording. Not implemented.
5. **No account lockout or MFA.** Rate limiting slows credential stuffing but does not
   stop a determined attacker with a valid password.

## 5. What is enforced by test rather than by intention

* `test_disclaimers.py` — attribution responses always carry the disclaimer; generated
  prose never uses prejudicial language.
* `test_report.py::test_html_escapes_injected_content` — script injection through a case
  title is escaped.
* `test_report.py::test_html_is_self_contained` — the report makes no external request.
* `infra/scripts/audit_secrets.sh` — four checks: credential names in frontend source,
  credential names in the built bundle, `.env` tracked by git, and hard-coded
  secret-shaped literals in source.
