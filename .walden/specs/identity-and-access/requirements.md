---
status: approved
approved_at: 2026-09-18T07:17:49Z
last_modified: 2026-09-18T07:17:49Z
---

# Requirements Document

## Introduction

Identity and access is the foundation every HTTP endpoint in the ERP sits on: user
accounts, password login, server-side sessions, roles with permissions, and the rule that
a user only ever reaches companies they belong to. It exists now, before the chart of
accounts gets its API, because `docs/architecture.md` §11.1 requires every endpoint to
declare and check a permission, and because anything deployed to Railway without login is
open to the internet.

Users are brought in by invitation: an administrator invites an email address, the person
receives a link, clicks it, sets their own password, and only then can log in. Nobody types
a password on someone else's behalf, and an address is proven to belong to its owner before
it reaches the books.

This feature ships the first real HTTP surface of the system: login, logout, invitation
acceptance, and "who am I". It does not add business endpoints; the chart of accounts adds
its own on top of this layer straight afterwards.

<!-- assumed: first-party email and password login with server-side sessions in a HttpOnly cookie, as approved in docs/architecture.md §2 — no OIDC, no third-party identity provider -->
<!-- assumed: sessions live in a PostgreSQL table so they can be revoked and audited, rather than being self-contained signed tokens -->
<!-- assumed: permissions are coarse strings shaped `<resource>:<action>` (e.g. `account:create`); record-level rules and field-level restrictions stay in Phase 2 -->
<!-- assumed: a single "Administrator" role ships with every permission, created by a bootstrap command; finer roles arrive with Phase 2 -->
<!-- assumed: mail goes out through a configured SMTP relay behind a Mailer interface, with a console backend in development and a recording backend in tests, so the email provider (Resend, Amazon SES, Alibaba DirectMail, anything SMTP) is deployment configuration rather than a code decision -->
<!-- assumed: invitation links carry a single-use token, expire after 7 days, and are stored hashed like session tokens -->

## Requirements

### R1 User accounts

**User Story:** As an administrator, I want to create and manage user accounts, so that only known people can use the system.

#### Acceptance Criteria

1. `R1.AC1` WHEN an administrator submits an invitation with an email address and a name, the system SHALL create the user with no password and mark them invited.
2. `R1.AC2` The system SHALL store email addresses lower-cased and trimmed.
3. `R1.AC3` IF an administrator submits an email address that another user already has, THEN the system SHALL reject it with error code `identity.duplicate_email`.
4. `R1.AC4` IF an administrator submits a value that is not a valid email address, THEN the system SHALL reject it with error code `identity.invalid_email`.
5. `R1.AC5` IF a user submits a password shorter than 12 characters when accepting an invitation or changing their password, THEN the system SHALL reject it with error code `identity.weak_password`.
6. `R1.AC6` WHEN an administrator deactivates a user, the system SHALL keep the user record and end that user's sessions.
7. `R1.AC7` IF an administrator deletes a user who appears in the audit log, THEN the system SHALL reject it with error code `identity.user_in_use`.
8. `R1.AC8` WHEN a user changes their own password with their current password, the system SHALL replace the stored hash and end their other sessions.
9. `R1.AC9` IF a user changes their password without giving the correct current password, THEN the system SHALL reject it with error code `identity.invalid_credentials`.
10. `R1.AC10` The system SHALL keep any way for one user to set another user's password out of the system, so that only the account's owner ever chooses it.

### R2 Password storage

**User Story:** As a security reviewer, I want passwords stored so they cannot be recovered, so that a database copy does not expose anyone's password.

#### Acceptance Criteria

1. `R2.AC1` The system SHALL store only an Argon2id hash of a password, never the password itself.
2. `R2.AC2` The system SHALL keep password hashes out of every API response.
3. `R2.AC3` The system SHALL keep passwords and password hashes out of logs and error messages.
4. `R2.AC4` WHEN a user logs in with a hash created under older Argon2id parameters, the system SHALL re-hash the password with the current parameters.
5. `R2.AC5` IF a stored hash cannot be parsed, THEN the system SHALL refuse the login with error code `identity.invalid_credentials`.

### R3 Login and logout

**User Story:** As a user, I want to log in and out, so that my session is mine and ends when I say so.

#### Acceptance Criteria

1. `R3.AC1` WHEN a user sends correct credentials to the login endpoint, the system SHALL create a session and return it in a `HttpOnly`, `Secure`, `SameSite=Lax` cookie.
2. `R3.AC2` WHEN a user logs in, the system SHALL record the login in the audit log.
3. `R3.AC3` IF a user sends an unknown email address or a wrong password, THEN the system SHALL reject the login with error code `identity.invalid_credentials` and the same message for both cases.
4. `R3.AC4` IF a deactivated user sends correct credentials, THEN the system SHALL reject the login with error code `identity.invalid_credentials`.
5. `R3.AC5` IF a user sends more than ten failed logins for one email address within fifteen minutes, THEN the system SHALL refuse further attempts for that email address with error code `identity.too_many_attempts`.
6. `R3.AC6` WHEN a user sends correct credentials after failed attempts, the system SHALL clear that email address's failure count.
7. `R3.AC7` WHEN a user logs out, the system SHALL end that session and reject any later request using it.
8. `R3.AC8` The system SHALL take the same amount of work for an unknown email address as for a wrong password, so neither can be told apart by timing.
9. `R3.AC9` IF an invited user who has not accepted their invitation sends a login, THEN the system SHALL reject it with error code `identity.invalid_credentials`.

### R4 Sessions

**User Story:** As a user, I want my session to identify me on every request and expire when stale, so that an abandoned browser cannot be used later.

#### Acceptance Criteria

1. `R4.AC1` WHEN a request arrives with a valid session cookie, the system SHALL identify the user it belongs to.
2. `R4.AC2` The system SHALL store a hash of the session token, not the token itself.
3. `R4.AC3` IF a request arrives with no session cookie, THEN the system SHALL refuse it with HTTP 401 and error code `identity.not_authenticated`.
4. `R4.AC4` IF a request arrives with a session token that is unknown, ended or expired, THEN the system SHALL refuse it with HTTP 401 and error code `identity.session_expired`.
5. `R4.AC5` IF a session has been idle longer than its idle limit, THEN the system SHALL treat it as expired.
6. `R4.AC6` IF a session is older than its absolute limit, THEN the system SHALL treat it as expired regardless of activity.
7. `R4.AC7` WHEN a request uses a valid session, the system SHALL record the time of last use.
8. `R4.AC8` WHEN an administrator ends another user's sessions, the system SHALL reject that user's later requests.

### R5 Roles and permissions

**User Story:** As an administrator, I want permissions granted through roles, so that what someone can do is described once and audited.

#### Acceptance Criteria

1. `R5.AC1` The system SHALL name every permission as `<resource>:<action>`.
2. `R5.AC2` WHEN an administrator grants a user a role in a company, the system SHALL give that user the role's permissions in that company only.
3. `R5.AC3` The system SHALL deny any action whose permission the user has not been granted.
4. `R5.AC4` WHEN an administrator revokes a role from a user, the system SHALL refuse that user's later requests needing the role's permissions.
5. `R5.AC5` IF an administrator grants a role that does not exist, THEN the system SHALL reject it with error code `identity.role_not_found`.
6. `R5.AC6` IF an administrator revokes the last administrator role in the system, THEN the system SHALL reject it with error code `identity.last_administrator`.
7. `R5.AC7` WHEN an administrator changes a role's permissions, the system SHALL record the change in the audit log.
8. `R5.AC8` The system SHALL ship an "Administrator" role holding every permission.

### R6 Company scoping

**User Story:** As an owner of several companies, I want each user limited to their own companies, so that one company's books are never visible to another's staff.

#### Acceptance Criteria

1. `R6.AC1` WHEN a request names a company the user holds a role in, the system SHALL carry out the request against that company.
2. `R6.AC2` IF a request names a company the user holds no role in, THEN the system SHALL refuse it with HTTP 403 and error code `identity.company_forbidden`.
3. `R6.AC3` IF a request names a company that does not exist, THEN the system SHALL refuse it with HTTP 403 and error code `identity.company_forbidden`, so that the two cases cannot be told apart.
4. `R6.AC4` WHEN a user requests their own profile, the system SHALL return only the companies they hold a role in.
5. `R6.AC5` The system SHALL check permissions per company, so a user may act in one company and not another.

### R7 Endpoint protection

**User Story:** As a security reviewer, I want every endpoint to state the permission it needs, so that no endpoint is reachable by accident.

#### Acceptance Criteria

1. `R7.AC1` The system SHALL require every endpoint to declare either the permission it needs or that it is public.
2. `R7.AC2` IF an endpoint declares neither, THEN the system SHALL fail its own start-up checks.
3. `R7.AC3` WHEN an authenticated user without the declared permission calls an endpoint, the system SHALL refuse it with HTTP 403 and error code `identity.permission_denied`.
4. `R7.AC4` WHEN an unauthenticated caller calls an endpoint that is not public, the system SHALL refuse it with HTTP 401.
5. `R7.AC5` The system SHALL treat only the login endpoint and the health endpoint as public.

### R8 Audit log

**User Story:** As an auditor, I want security events recorded permanently, so that access to the books can be reviewed after the fact.

#### Acceptance Criteria

1. `R8.AC1` WHEN a login succeeds or fails, the system SHALL append an audit record naming the email address, the outcome and the time.
2. `R8.AC2` WHEN a user, role, role grant or password changes, the system SHALL append an audit record naming the actor and the target.
3. `R8.AC3` The system SHALL keep audit records out of reach of updates and deletions.
4. `R8.AC4` The system SHALL keep passwords, password hashes and session tokens out of audit records.
5. `R8.AC5` WHEN an administrator requests the audit log for a company, the system SHALL return its records newest first.

### R9 First administrator

**User Story:** As the person installing the system, I want to create the first administrator safely, so that a fresh deployment is usable but not open.

#### Acceptance Criteria

1. `R9.AC1` WHEN an operator runs the bootstrap command on a system with no users, the system SHALL create one administrator from the given email address and password.
2. `R9.AC2` IF an operator runs the bootstrap command on a system that already has a user, THEN the system SHALL refuse it with error code `identity.already_bootstrapped`.
3. `R9.AC3` WHEN the bootstrap command runs without a password, the system SHALL generate one and print it once.
4. `R9.AC4` The system SHALL keep the bootstrap password out of the audit log.

### R10 Who am I

**User Story:** As a frontend, I want one endpoint describing the signed-in user, so that screens can be built around what that user may do.

#### Acceptance Criteria

1. `R10.AC1` WHEN an authenticated user requests their profile, the system SHALL return their id, name, email address, companies and permissions per company.
2. `R10.AC2` IF an unauthenticated caller requests the profile endpoint, THEN the system SHALL refuse it with HTTP 401.
3. `R10.AC3` The system SHALL leave the password hash and session token out of the profile response.

### R11 Invitations and email verification

**User Story:** As an invited colleague, I want a link in my email that lets me set my own password, so that my account is proven to be mine and nobody else has ever known my password.

#### Acceptance Criteria

1. `R11.AC1` WHEN an administrator invites an email address, the system SHALL send that address an email containing a single-use invitation link.
2. `R11.AC2` WHEN an invited person opens their link and submits a password, the system SHALL set that password, mark the email address verified, activate the user and consume the invitation.
3. `R11.AC3` WHEN an invitation is accepted, the system SHALL log the person in and return a session cookie.
4. `R11.AC4` The system SHALL store a hash of each invitation token, not the token itself.
5. `R11.AC5` IF an invitation link is opened more than 7 days after it was sent, THEN the system SHALL refuse it with error code `identity.invitation_expired`.
6. `R11.AC6` IF an invitation link has already been accepted, THEN the system SHALL refuse it with error code `identity.invitation_used`.
7. `R11.AC7` IF an invitation token is unknown or malformed, THEN the system SHALL refuse it with error code `identity.invitation_invalid`.
8. `R11.AC8` WHEN an administrator resends an invitation, the system SHALL make the previous link unusable and send a new one.
9. `R11.AC9` WHEN an administrator revokes an invitation, the system SHALL make its link unusable.
10. `R11.AC10` IF sending an invitation email fails, THEN the system SHALL keep the invitation and report error code `identity.invitation_email_failed` so it can be resent.
11. `R11.AC11` The system SHALL send invitation emails with both Arabic and English text.
12. `R11.AC12` The system SHALL keep invitation tokens and links out of the audit log.
13. `R11.AC13` WHEN an invitation is sent, resent, revoked or accepted, the system SHALL append an audit record naming the email address and the actor.
14. `R11.AC14` The system SHALL build invitation links from a configured public base URL.
15. `R11.AC15` WHILE no mail relay is configured, WHEN an administrator invites an email address, the system SHALL write the invitation email to the application log instead of sending it.

### R12 Cross-site request protection

**User Story:** As a security reviewer, I want cookie-authenticated requests to come only from our own application, so that another site cannot act as a signed-in user who visits it.

#### Acceptance Criteria

1. `R12.AC1` The system SHALL take the set of origins it accepts from configuration.
2. `R12.AC2` IF a request that changes state carries a session cookie and an `Origin` header that is not an accepted origin, THEN the system SHALL refuse it with HTTP 403 and error code `identity.csrf_check_failed`.
3. `R12.AC3` IF a request that changes state carries a session cookie and a `Sec-Fetch-Site` header of `cross-site`, THEN the system SHALL refuse it with HTTP 403 and error code `identity.csrf_check_failed`.
4. `R12.AC4` IF a request that changes state carries a session cookie but neither an `Origin` nor a `Sec-Fetch-Site` header, THEN the system SHALL refuse it with HTTP 403 and error code `identity.csrf_check_failed`.
5. `R12.AC5` WHEN a request that changes state carries an accepted `Origin` or a `Sec-Fetch-Site` of `same-origin`, the system SHALL process it.
6. `R12.AC6` The system SHALL apply no origin check to `GET` and `HEAD` requests.
7. `R12.AC7` The system SHALL apply the origin check to the login and invitation-acceptance endpoints as well, even though they need no session.
8. `R12.AC8` The system SHALL send every session cookie with `SameSite=Lax`, so a browser refuses cross-site sends even before the origin check.
9. `R12.AC9` WHEN the system refuses a request for a failed origin check, the system SHALL append an audit record naming the rejected origin.

## Non-Functional Requirements

- `NFR1` Security: passwords are Argon2id-hashed, session tokens and invitation tokens are stored hashed, cookies are `HttpOnly`/`Secure`/`SameSite=Lax`, cookie-authenticated writes must come from an accepted origin, and login reveals nothing about which email addresses exist (proven by `R2`, `R3.AC3`, `R3.AC8`, `R4.AC2`, `R11.AC4`, `R12`).
- `NFR2` Fail closed: an endpoint without a declared permission stops start-up rather than serving traffic (proven by `R7.AC2`).
- `NFR3` Auditability: security events are append-only and never contain secrets (proven by `R8`).
- `NFR4` Performance: identifying the caller and checking a permission takes at most two queries per request, so authorization does not dominate response time.
- `NFR5` Maintainability: other modules depend on identity only through `app.platform.identity.api` and `app.platform.access.api`, enforced by import-linter.
- `NFR6` Compatibility with Neon's pooled endpoint: authorization keeps no session-level database state, only transaction-scoped settings.

## Constraints And Dependencies

- `C1` New dependency: `argon2-cffi` for Argon2id hashing (the algorithm is already approved in `docs/architecture.md` §2; the library needs a nod).
- `C2` Sessions, users, roles, grants and audit records live in PostgreSQL 18 on Neon, added by a new Alembic migration.
- `C3` Outbound email is required for invitations. It goes through a `Mailer` interface: an SMTP backend in production (provider is deployment configuration), a log backend when no relay is configured, and a recording backend in tests. No email provider account is needed to build or test this feature.
- `C3b` Background jobs do not exist yet, so invitation emails are sent during the request and retried by resending rather than by a queue.
- `C4` TLS is terminated by the host (Railway), so the `Secure` cookie flag is set but HTTPS itself is not this feature's job.
- `C4b` The accepted origins are configuration: the local development URL plus the deployed public URL. A browser-based client on another origin would need to be added there.
- `C5` Row-level security, record rules and field-level restrictions stay in Phase 2; this feature checks permissions in the service layer.
- `C6` Local test runs stay capped at two pytest workers against the Neon `test` branch.

## Out Of Scope

- OIDC, SAML, social login and API keys for machine callers.
- Multi-factor authentication.
- Password reset by email ("forgot password") — the same token mechanism as invitations, deliberately left for a follow-up so this feature stays small; until then a locked-out user is re-invited.
- Verifying a new address when a user changes their email.
- Roles beyond the shipped Administrator role, plus record-level and field-level rules (Phase 2).
- Row-level security in PostgreSQL (Phase 2).
- Frontend login screens.
- Business endpoints for accounts, journals or entries — they arrive with the chart of accounts.
