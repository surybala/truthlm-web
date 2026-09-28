# ORL Web - implemented milestone

## Service boundary

- **WEB-ARCH-001** ORL Web shall run as an independently packaged service and shall not import ORL Core code or access Core persistence.
- **WEB-CONTRACT-001** Imported Core artifacts and emitted research requests shall satisfy vendored v1 JSON Schemas, and checksummed artifacts shall be verified before persistence.

## Questions and moderation

- **WEB-Q-001** Question submission shall require an authenticated user, enforce input and per-user rate limits, retain the original text, and support idempotent replay.
- **WEB-Q-002** The question queue shall be visible only to signed-in members, grouped by research domain and ranked within each domain by current-cycle votes, and shall support search, domain and readiness filtering, cycle status, and viewer-specific vote state without conflating votes with research readiness.
- **WEB-Q-003** An authenticated user shall be able to inspect their submission moderation history and idempotently report a public question for moderator review with a bounded reason.
- **WEB-Q-004** A moderator shall be able to list pending submissions and reported questions, then resolve or dismiss each report exactly once with an audited reason.
- **WEB-Q-005** A moderator shall be able to reject a pending submission, approve it into a new cluster, or attach it to an existing open cluster with a recorded reason and immutable audit event. No submission is visible to other members before approval, and a rejection reason is shown to its submitter.
- **WEB-Q-006** Every approved question shall belong to one research domain from the configured list: submitters may suggest a domain, moderators assign it when approving a new cluster, attached submissions inherit their cluster's domain, and unknown domains are rejected.
- **WEB-MOD-001** Moderators and administrators shall have a role-gated review console to approve, attach, or decline pending questions and to resolve reports; administrators shall additionally manage invitation requests, members, and weekly cycles there. Hiding a control is never the authorization decision.

## Voting and cycles

- **WEB-DATA-002** Votes shall target question clusters and enforce at most one active vote per eligible user, cluster, and weekly cycle.
- **WEB-VOTE-005** Vote creation and removal shall be idempotent and transactionally update the authoritative database and audit trail.
- **WEB-CYCLE-001** Freezing a weekly cycle shall atomically store one reproducible per-domain vote snapshot and select at most one winner per research domain: the open question with the most votes (at least one), then the earliest creation time and stable ID. Each winner is stored under a database uniqueness constraint and emits a schema-valid research request.
- **WEB-CYCLE-002** A manual winner override shall require an authorized actor and reason, replace the selection of at most one question per domain, and be retained in the immutable audit trail and vote snapshot.

## Readiness and metrics

- **WEB-READY-001** Editors shall be able to record a schema-valid, versioned manual readiness assessment without exposing user identity to Core.
- **WEB-METRIC-001** Web shall persist only schema-valid, checksum-verified immutable Core metrics snapshots and publicly serve the latest snapshot with its timestamp and definitions.

## Publication and public experience

- **WEB-UI-001** The public home, method, archive, and article pages shall present TruthLM as a thought assistant for students and researchers rather than a quick-answer service, present the research method as the questions an investigation asks, make published investigations browsable without authentication, and never show the members' question queue or vote counts to the public.
- **WEB-UI-002** Published investigations shall be shareable without third-party scripts: every article page shall declare its canonical URL and Open Graph and Twitter card metadata and offer share links for common social networks and email, plus copy-link and native device sharing.
- **WEB-UI-003** The reader view of every published investigation shall surface its open questions and material limitations beside the findings, so an article ends in further inquiry rather than a final verdict.
- **WEB-PUB-001** Web shall idempotently accept a publication bundle as a draft only after schema, checksum, citation-reference, research-review, originality, copyright, citation-support, equation, and quantitative gates pass; editorial approval shall be a separate authenticated action.
- **WEB-PUB-002** Published scientific prose shall be rendered deterministically from the accepted bundle without model rewriting or executable source HTML.
- **WEB-PUB-003** Corrections and retractions shall retain immutable bundle revisions, a stable canonical URL, visible public history, and an audited editorial reason.
- **WEB-PUB-004** Every published article shall expose a structured research record containing scope, methodology, expert perspectives, research actions, claim evidence, disagreements, computations, limitations, and open questions rather than hidden model chain-of-thought.
- **WEB-PUB-005** The default public record shall present a six-to-ten-stage Research journey in reader language, with the signed granular event count retained as a secondary technical audit note. Web shall deterministically derive the journey for valid legacy bundles that predate the field and shall add the Web-owned editorial publication stage.
- **WEB-EDIT-001** Authorized editors shall be able to inspect draft content, gates, methodology, and limitations and then publish or reject a revision through an authenticated editorial queue.
- **WEB-FEED-001** Web shall expose a standards-valid, cacheable public RSS feed containing only current published investigations, stable article URLs, publication timestamps, domain categories, and cited researcher metadata.
- **WEB-SUB-001** Authenticated users shall be able to follow all weekly research or any combination of normalized domains and cited researchers; a personal feed shall include a publication once when any selected interest matches.
- **WEB-SUB-002** Personal RSS access shall use a high-entropy credential stored only as a hash and shall support immediate rotation and revocation without using the browser session in an RSS reader.

## Membership and access

- **WEB-ACCESS-001** While the access mode is `invite`, sign-in links shall be issued and honored only for addresses that are approved, bootstrap-elevated, or held by an elevated account. Every other address receives the same neutral response, and a revoked address stays blocked in every access mode except bootstrap elevation.
- **WEB-ACCESS-002** Anyone shall be able to request an invitation with a bounded email, name, role, discipline, and note. The response shall be identical for new, pending, approved, and revoked addresses, never overwrite an existing request, and be globally rate-limited.
- **WEB-ACCESS-003** Administrators shall be able to list requests and approve, decline, revoke, or directly invite an address with an audited reason. Revocation shall revoke the member's active browser sessions; approval shall notify the address by email, and a delivery failure shall not roll back the decision.

## Security and operations

- **WEB-AUTH-001** Browser authentication shall use rate-limited, short-lived, single-use email links and opaque server-side sessions whose raw credentials are never persisted.
- **WEB-AUTH-002** Browser sessions shall be revocable, carried in HttpOnly SameSite cookies, and require a session-bound CSRF proof for state-changing requests while preserving signed bearer authentication for service clients.
- **WEB-SEC-001** Question and vote mutations shall require valid authentication, bounded input, eligibility checks, rate limits, and audit events.
- **WEB-SEC-002** Moderator, editor, administrator, and service operations shall be separated by signed role claims, and sensitive mutations shall emit immutable audit events.
- **WEB-OPS-001** The PostgreSQL-oriented schema shall be reproducibly installable through a versioned migration with database and application protections for immutable records.
- **WEB-OPS-002** The service and its migrations shall load local configuration from the project's `.env` file without overriding variables already set in the environment, and the test suite shall neither read that file nor inherit `ORL_WEB_*` variables from the developer's shell.

## Authentication and question-queue design

### Trust boundaries

Public browser users authenticate directly with ORL Web. Their email address, session, submission
history, votes, and reports remain in the Web database. ORL Core receives only a selected cluster ID,
canonical question, revision, cycle, and idempotency key. Core and trusted operational clients retain
the signed bearer-token path; browser sessions do not replace service authentication.

### Passwordless authentication

1. `POST /v1/auth/magic-link` accepts a normalized email and a same-origin return path. It always
   returns the same accepted response after validation, including when the per-email hourly limit is
   exhausted.
2. Web generates at least 256 bits of randomness. Only a SHA-256 token hash is stored. The delivered
   URL is HTTPS in production, expires after 15 minutes by default, and is valid once.
3. `GET /auth/verify` locks and consumes the token, creates or resolves the Web user, and creates an
   opaque session. The response redirects immediately so the login token does not remain in the
   destination URL.
4. The session cookie is HttpOnly, SameSite=Lax, path-scoped to `/`, and Secure in production. The
   database stores only its SHA-256 hash, expiry, revocation time, and ownership metadata.
5. A CSRF proof is deterministically bound to the raw session with HMAC-SHA256 and the service
   secret. Same-origin JavaScript obtains it from `GET /v1/auth/session`; every unsafe request made
   with cookie authentication must supply it in `X-CSRF-Token`. Bearer requests do not use browser
   CSRF protection.
6. `POST /v1/auth/logout` revokes the session in the database, records an audit event, and clears the
   cookie. Expired, revoked, missing-user, malformed, or replayed credentials fail closed.

SMTP is the required production delivery adapter. Console delivery exists only for local
development. Production startup rejects SQLite, HTTP base URLs, the development signing secret, or
missing SMTP configuration. Elevated bootstrap email lists apply only when a user is first created.

### Member queue behavior

`GET /v1/questions` requires a signed-in member and returns open or selected clusters, their
canonical text, research domain, tags, cycle-scoped vote totals, rank within the domain, readiness
assessment, and a viewer-specific `viewer_has_voted` boolean. Votes and readiness are rendered as
independent signals. The queue supports local text search, domain filtering, and readiness filtering
without changing server truth. The public never sees the queue or vote counts: published
investigations are the only public output of the question process.

Authenticated users may submit bounded questions with an idempotency key, toggle one vote per
cluster in the active weekly cycle, read their own submission and moderation history, and submit one
idempotent report per question. Reports contain a controlled reason and bounded optional detail;
they produce immutable audit events but never alter vote totals. Before submission, the browser
offers lexical duplicate guidance against the current public queue. This is advisory only: manual
moderation remains authoritative until semantic clustering is implemented.

### Operational invariants

- Email addresses are personally identifiable data. Backups, logs, and database access must be
  protected accordingly. Raw session credentials must never be logged.
- The only intentional raw magic-link exposure is the development console mailer. It is prohibited
  by production configuration validation.
- Role checks are server-side on every privileged endpoint. Hiding an editor control is not an
  authorization decision.
- Rate-limit counters are authoritative database records in this milestone. Multi-instance
  deployments therefore share limits without process-local state.
- Login and question responses avoid executable user content; dynamic queue content is inserted with
  DOM `textContent`, and the site Content Security Policy disallows inline script execution.

## Research feed and subscription design

### Feed semantics

`GET /feeds/research.xml` is the canonical public feed and requires no account. It emits at most the
100 most recent current `published` articles in reverse publication order. Draft, rejected,
superseded, and retracted revisions are excluded. A corrected published revision keeps its canonical
article URL and updates the item represented by that permalink.

RSS items contain the article title, public summary, canonical URL, publication date, moderator-
assigned cluster tags as categories, and authors from the bundle citation records as Dublin Core
creators. Feed content is deterministic and XML-escaped. `ETag` and five-minute public cache headers
allow readers and edge caches to avoid transferring unchanged content.

### Interest taxonomy and matching

Subscription dimensions come from the public scientific record rather than a parallel profiling
system:

- `all` follows every weekly published investigation.
- `domain` values match normalized tags on the question cluster that produced an investigation.
- `researcher` values match normalized author names in that investigation's citations.

Normalization applies Unicode NFKC, whitespace folding, and case-insensitive comparison. A personal
feed uses OR semantics across its preferences and emits each matching article once. Users may add a
value before it appears in the published option list so a feed can begin matching future work.

### Personal feed access

A signed-in user manages preferences at `/subscriptions`. `POST /v1/subscriptions/feed-token`
creates or rotates a 256-bit opaque feed credential. Only its SHA-256 hash is persisted. The raw URL
is returned once for transfer into an RSS reader; it cannot be recovered later. Rotation deletes the
old credential before issuing the new one, and revocation invalidates it immediately.

Personal feeds expose only already-public article metadata, but the URL can reveal a user's selected
interests. It must be treated as a secret by application logs, analytics, reverse proxies, support
tools, and users. Browser session cookies are never accepted as a substitute for a personal feed
credential. Feed polling updates `last_used_at` at most once per day to avoid a write on every poll.

## Positioning, membership, and domain design

### Positioning

TruthLM is a thought assistant, not an answer engine. The public pages speak to students,
researchers, and curious readers and say plainly that the site is the wrong place for a quick answer.
The method is presented as the sequence of questions an investigation must answer (scope, standard
of evidence, what the literature shows, whether the numbers reproduce, where experts disagree, what
would change the conclusion, and what to investigate next) so readers can apply it themselves.
Article pages keep the open questions and limitations beside the findings.

The site is deliberately not a social network: there are no public profiles, followers, feeds of
member activity, comments, or public vote counts. Members interact only by asking questions and
upvoting approved ones; everyone else reads published investigations and the method.

### Invite-only access

`ORL_WEB_ACCESS_MODE=invite` (the default) gates browser sign-in. An address may sign in when it is in
the bootstrap admin or editor list, has an approved access record, or belongs to an account with an
elevated role. `open` admits every address except revoked ones, so access can be widened without a
code change. Sign-in requests for other addresses receive the standard neutral response and no mail.
The verify step repeats the check, so an access decision made after a link was sent still applies.

`POST /v1/access-requests` is public. It stores a pending request (email, name, optional role,
discipline, and note) only when the address has no record, and always returns the same accepted
message; existing records are never overwritten, so nobody can alter another person's request or
learn whether an address is known. A global hourly cap bounds moderation-queue flooding and fails
with `429` without revealing anything about individual addresses.

Administrators decide requests through `POST /v1/admin/access-requests/{id}/decision` with
`approve`, `decline`, or `revoke` and a reason, or add a trusted address directly through
`POST /v1/admin/access`. Valid transitions are pending → approved or declined, declined → approved,
approved → revoked, and revoked → approved; repeating the current state is an idempotent replay.
Revocation revokes every active browser session of the matching account. Approval commits first and
then emails a sign-in pointer; the response reports whether delivery succeeded. Accounts that existed
before invite-only access were grandfathered as approved by the migration and can be revoked.

### Domains and weekly selection

`ORL_WEB_DOMAINS` lists the research domains TruthLM currently covers (default Economics, Finance,
Mathematics, Statistics). Only listed domains are accepted, so members cannot ask for research in a
field the consortium has no expert for. A submitter may suggest a domain; the moderator's choice at
approval is authoritative. Clusters created before domains existed form an `unassigned` group.

Freezing a cycle ranks open clusters within each domain by votes, then creation time, then ID, and
selects the leader of every domain whose leader has at least one vote. An administrator may override
at most one selection per domain with a reason. Each selection is stored in `cycle_selections`, which
is unique per cycle and domain and per cycle and cluster, and yields its own research request with
`request_id` `weekly-{cycle}-{domain}`. Selected clusters leave the open queue.

### Sharing

Article pages declare a canonical URL and Open Graph and Twitter card metadata built from the
published title, summary, and publication time. Share controls are plain links to LinkedIn, X,
Bluesky, Facebook, Reddit, and email, plus copy-link and the Web Share API where the device offers it.
No third-party script, pixel, or embed is loaded, and the Content Security Policy is unchanged.
