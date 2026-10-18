# ORL Web - implemented milestone

## Service boundary

- **WEB-ARCH-001** ORL Web shall run as an independently packaged service and shall not import ORL Core code or access Core persistence.
- **WEB-CONTRACT-001** Imported Core artifacts and recorded readiness assessments shall satisfy vendored v1 JSON Schemas, and checksummed artifacts shall be verified before persistence.

## Questions and moderation

- **WEB-Q-001** Question submission shall require an editor or administrator, enforce input and per-user rate limits, retain the original text, and support idempotent replay.
- **WEB-Q-002** The question list shall be visible only to signed-in members, never to the public, grouped by research domain in configured order and listed oldest first within each domain with its status and readiness. The question workspace page shall be available only to editors and administrators; other members are sent to their subscriptions.
- **WEB-Q-003** An authenticated user shall be able to inspect their submission moderation history and idempotently report a public question for moderator review with a bounded reason.
- **WEB-Q-004** A moderator shall be able to list pending submissions and reported questions, then resolve or dismiss each report exactly once with an audited reason.
- **WEB-Q-005** A moderator shall be able to reject a pending submission, approve it into a new cluster, or attach it to an existing open cluster with a recorded reason and immutable audit event. No submission is visible to other members before approval, and a rejection reason is shown to its submitter.
- **WEB-Q-006** Every approved question shall belong to one research domain from the configured list: submitters may suggest a domain, moderators assign it when approving a new cluster, attached submissions inherit their cluster's domain, and unknown domains are rejected.
- **WEB-MOD-001** Moderators and administrators shall have a role-gated review console to approve, attach, or decline pending questions and to resolve reports; administrators shall additionally manage invitation requests and members there. Hiding a control is never the authorization decision.

## Readiness and metrics

- **WEB-READY-001** Editors shall be able to record a schema-valid, versioned manual readiness assessment without exposing user identity to Core.
- **WEB-METRIC-001** Web shall persist only schema-valid, checksum-verified immutable Core metrics snapshots and publicly serve the latest snapshot with its timestamp and definitions.

## Publication and public experience

- **WEB-UI-001** The public home, method, archive, and article pages shall present TruthLM as a thought assistant for students and researchers rather than a quick-answer service; the home page shall present exactly two access levels: reading every investigation and the method without an account, and an email subscription to new investigations that begins on the waitlist while access is invite-only; the method shall present the questions an investigation asks; published investigations shall remain browsable without authentication; and the public shall never see the question list or member data.
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

## Email delivery

- **WEB-MAIL-001** Approving or directly inviting an address, and a first sign-in while access is open, shall make the address an email subscriber: its member account is created if absent with the role its bootstrap lists grant, it follows all weekly research by default, and the approval notice carries a sign-in link and an unsubscribe link.
- **WEB-MAIL-002** An editor, administrator, or service client shall be able to run an email delivery that sends each eligible subscriber at most one email listing every current published investigation that matches the subscriber's interests, was first published after the subscriber's current email subscription began, and was never emailed to that subscriber before. Eligible subscribers have a non-revoked account with access and have not unsubscribed. No investigation is emailed to the same subscriber twice, including after a correction, and retracted investigations are never sent.
- **WEB-MAIL-003** Delivery runs shall be bounded and resumable: a run emails at most the configured or requested number of subscribers, records each delivery as sent, failed, or skipped with its attempt count, retries a failed delivery at most three times in total, never resends a delivery whose send was interrupted, and reports how many subscribers remain. Delivery status and the run action shall be available only to editors, administrators, and service clients.
- **WEB-MAIL-004** Every research email shall carry a visible unsubscribe link plus `List-Unsubscribe` and one-click `List-Unsubscribe-Post` headers, signed for that subscriber. Using the link stops further deliveries without signing in, reveals no account details, and rejects invalid signatures. A signed-in member shall be able to turn email delivery off and on from the subscriptions page.

## Membership and access

- **WEB-ACCESS-001** While the access mode is `invite`, sign-in links shall be issued and honored only for addresses that are approved, bootstrap-elevated, or held by an elevated account. Every other address receives the same neutral response, and a revoked address stays blocked in every access mode except bootstrap elevation.
- **WEB-ACCESS-002** Anyone shall be able to request an invitation with a bounded email, name, role, discipline, and note. The response shall be identical for new, pending, approved, and revoked addresses, never overwrite an existing request, and be globally rate-limited.
- **WEB-ACCESS-003** Administrators shall be able to list requests and approve, decline, revoke, or directly invite an address with an audited reason. Revocation shall revoke the member's active browser sessions; approval shall notify the address by email, and a delivery failure shall not roll back the decision.

## Security and operations

- **WEB-AUTH-001** Browser authentication shall use rate-limited, short-lived, single-use email links and opaque server-side sessions whose raw credentials are never persisted.
- **WEB-AUTH-002** Browser sessions shall be revocable, carried in HttpOnly SameSite cookies, and require a session-bound CSRF proof for state-changing requests while preserving signed bearer authentication for service clients.
- **WEB-SEC-001** Question mutations shall require valid authentication, bounded input, role checks, rate limits, and audit events.
- **WEB-SEC-002** Moderator, editor, administrator, and service operations shall be separated by signed role claims, and sensitive mutations shall emit immutable audit events.
- **WEB-OPS-001** The PostgreSQL-oriented schema shall be reproducibly installable through a versioned migration with database and application protections for immutable records.
- **WEB-OPS-002** The service and its migrations shall load local configuration from the project's `.env` file without overriding variables already set in the environment, and the test suite shall neither read that file nor inherit `ORL_WEB_*` variables from the developer's shell.

## Access model

TruthLM has two access levels:

1. **Read.** Every published investigation, the method, the archive, and the public RSS feed are
   open to everyone without an account.
2. **Subscribe and receive.** A subscriber receives new investigations by email and can choose the
   domains and cited researchers they follow. While `ORL_WEB_ACCESS_MODE=invite`, people join a
   waitlist and administrators approve addresses gradually; approval is what starts the
   subscription. Switching to `open` lets anyone subscribe by signing in with their email.

There is no paid tier and no member voting. The owners choose the research questions: at launch only
editors and administrators submit questions, and the editorial team publishes at most one
investigation per research domain each week after a manual review.

## Authentication and question workflow

### Trust boundaries

Public browser users authenticate directly with ORL Web. Their email address, session, submission
history, subscriptions, deliveries, and reports remain in the Web database. ORL Core receives only a
question cluster ID, canonical question, and revision, which an operator passes to a Core run. Core
and trusted operational clients retain the signed bearer-token path; browser sessions do not replace
service authentication.

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

### Question workflow

An editor or administrator submits a question at `/questions` with an optional suggested domain. A
moderator or administrator approves it in the review console, choosing the final wording and domain
(or attaching it to an existing open question). The approval returns the cluster ID that the
operator passes to `orl platform publication build --cluster-id`, so the published investigation
inherits the question's domain for feeds and email matching.

`GET /v1/questions` requires a signed-in member and returns open or selected clusters with their
canonical text, research domain, tags, status, and readiness assessment, grouped by domain in the
configured order and oldest first within each domain. The public never sees the list. Members may
report a question they can see; reports produce immutable audit events and are resolved in the
review console.

### Operational invariants

- Email addresses are personally identifiable data. Backups, logs, and database access must be
  protected accordingly. Raw session credentials must never be logged.
- The only intentional raw magic-link exposure is the development console mailer. It is prohibited
  by production configuration validation.
- Role checks are server-side on every privileged endpoint. Hiding an editor control is not an
  authorization decision.
- Rate-limit counters are authoritative database records in this milestone. Multi-instance
  deployments therefore share limits without process-local state.
- Login and question responses avoid executable user content; dynamic content is inserted with DOM
  `textContent`, and the site Content Security Policy disallows inline script execution.

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
feed and an email delivery use OR semantics across the subscriber's preferences and include each
matching article once. Users may add a value before it appears in the published option list so their
subscription can begin matching future work.

### Personal feed access

A signed-in user manages preferences at `/subscriptions`. `POST /v1/subscriptions/feed-token`
creates or rotates a 256-bit opaque feed credential. Only its SHA-256 hash is persisted. The raw URL
is returned once for transfer into an RSS reader; it cannot be recovered later. Rotation deletes the
old credential before issuing the new one, and revocation invalidates it immediately.

Personal feeds expose only already-public article metadata, but the URL can reveal a user's selected
interests. It must be treated as a secret by application logs, analytics, reverse proxies, support
tools, and users. Browser session cookies are never accepted as a substitute for a personal feed
credential. Feed polling updates `last_used_at` at most once per day to avoid a write on every poll.

## Email delivery design

### Subscribers

A subscriber is a member account with an email address. Approving a waitlist request or inviting an
address directly creates the account immediately, so approved people receive research without ever
signing in; in `open` mode the first sign-in creates it. New accounts follow `all` weekly research,
and the member can narrow that to domains or researchers at `/subscriptions`. Bootstrap admin and
editor addresses keep their elevated role when an approval creates their account. Each delivery run
also creates accounts for approved addresses that predate this rule.

A subscriber is eligible while their address still has access (approved, elevated, or any
non-revoked address in `open` mode) and `email_opt_out_at` is empty.

### Runs

`POST /v1/admin/deliveries/run` (editor, administrator, or service) performs one bounded run:

1. **Queue.** For each eligible subscriber, add one `email_deliveries` row per current published
   investigation that matches their interests, was first published at or after the subscriber's
   current email subscription began (`email_subscribed_at`: account creation, or the moment they
   last turned email back on), and has no row for that subscriber yet. A returning subscriber is
   therefore not sent what was published while they were unsubscribed. `(user_id, article_id)` is unique, so a
   corrected revision, which keeps its article, is never queued twice.
2. **Send.** Pick at most `limit` subscribers (default `ORL_WEB_DELIVERY_BATCH_SIZE`, 50) with
   pending rows or failed rows below three attempts. Rows for a subscriber who unsubscribed or lost
   access, or for an investigation that is no longer published, become `skipped`. The remaining rows
   are committed as `sending` with an incremented attempt count before the email is handed to the
   mailer, then become `sent` or `failed`. One email lists all of a subscriber's rows.
3. **Report.** The response counts queued rows, emails sent, emails failed, skipped rows, and the
   subscribers that still have deliverable rows. Editors repeat the run until nothing remains.

A crash between handing an email to the mailer and recording the outcome leaves rows in `sending`.
Those rows are never retried automatically, so a subscriber is never emailed twice for the same
investigation; editors can inspect them in `GET /v1/admin/deliveries`.

The editorial workspace shows the delivery status and runs deliveries in batches until none remain.
Publishing does not email anyone by itself, so the editorial team can publish the week's
investigations and send one email containing them.

### Messages and unsubscribe

Each research email lists the new investigations with their domains, summary, and canonical URL,
explains that investigations are researched by AI agents and reviewed by a person before
publication, links to `/subscriptions` to change interests, and carries an unsubscribe link. The link
is `/unsubscribe/{user_id}/{signature}`, where the signature is an HMAC-SHA256 of the user ID under the
service secret; rotating the secret invalidates previously sent links. `GET` shows a confirmation
page, and `POST` (including the RFC 8058 one-click request a mail provider sends) sets
`email_opt_out_at` and records an audit event. Invalid signatures receive the same not-found page.
`PUT /v1/subscriptions/email` lets a signed-in member turn delivery off or back on.

Production delivery should use an email provider's SMTP endpoint with SPF, DKIM, and DMARC
configured for the sending domain. Approving waitlist addresses in batches also warms the sending
domain gradually.

## Positioning and domains

### Positioning

TruthLM is a thought assistant, not an answer engine. The public pages speak to students,
researchers, and curious readers and say plainly that the site is the wrong place for a quick answer.
The method is presented as the sequence of questions an investigation must answer (scope, standard
of evidence, what the literature shows, whether the numbers reproduce, where experts disagree, what
would change the conclusion, and what to investigate next) so readers can apply it themselves.
Article pages keep the open questions and limitations beside the findings.

The site is deliberately not a social network: there are no public profiles, followers, feeds of
member activity, comments, votes, or public counts of members.

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
then emails a welcome notice with a sign-in link and an unsubscribe link; the response reports
whether delivery succeeded. Accounts that existed before invite-only access were grandfathered as
approved by the migration and can be revoked.

### Domains and cadence

`ORL_WEB_DOMAINS` lists the research domains TruthLM covers. The default is the seven domains ORL
Core has experts for: Biology, Chemistry, Economics, Finance, Mathematics, Physics, and Statistics.
Only listed domains are accepted. A submitter may suggest a domain; the moderator's choice at
approval is authoritative. Clusters created before domains existed form an `unassigned` group.

The editorial cadence is at most one investigation per domain per week, reviewed manually before
publication. Subscribers who follow everything receive up to seven investigations in one weekly
email when the editors run a single delivery after publishing the week's work.

### Sharing

Article pages declare a canonical URL and Open Graph and Twitter card metadata built from the
published title, summary, and publication time. Share controls are plain links to LinkedIn, X,
Bluesky, Facebook, Reddit, and email, plus copy-link and the Web Share API where the device offers it.
No third-party script, pixel, or embed is loaded, and the Content Security Policy is unchanged.
