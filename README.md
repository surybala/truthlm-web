# TruthLM / ORL Web

The independently deployable public service behind `truthlm.com`. TruthLM is a thought assistant
for students and researchers, not an answer engine: it publishes weekly investigations that show how
a question was scoped, what the evidence shows, which numbers were reproduced, where experts
disagree, and what remains open. Anyone can read the investigations and the method. During early
access, only invited members can submit questions (each reviewed by a person before anyone else sees
it) and upvote approved questions within each research domain. It is deliberately not a social
network: there are no public profiles, feeds, comments, or public vote counts.

The service hosts the publication experience, the invite-only membership list, question review,
manual grouping, weekly per-domain selection, research-readiness labels, and sanitized Core
metrics. It never imports ORL Core, opens the Core catalog, or connects to its vector store.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # then set ORL_WEB_ADMIN_EMAILS to your address
docker compose up -d postgres
alembic upgrade head
uvicorn orl_web.app:app --reload
```

The server and `alembic` load `orl-web/.env` automatically, whatever the working directory.
Variables already set in the shell or deployment environment win over the file, and settings are
read at startup, so restart the server after editing it. Set `ORL_WEB_DOTENV=0` to ignore the file.
Container images do not include `.env`; production configuration comes from the deployment
environment and its secret store. The test suite never reads `.env` and clears `ORL_WEB_*`
variables inherited from your shell.

Production requires PostgreSQL, an HTTPS `ORL_WEB_BASE_URL`, SMTP delivery, and a non-default JWT
secret of at least 32 characters. Members authenticate with a short-lived, single-use email link.
`ORL_WEB_ACCESS_MODE=invite` (the default) sends links only to approved addresses, bootstrap
admins/editors, and elevated accounts; set it to `open` to admit everyone except revoked addresses.
`ORL_WEB_DOMAINS` lists the research domains questions may belong to (default
`Economics,Finance,Mathematics,Statistics`); add a domain only when the consortium has an expert for
it. The browser receives an opaque, revocable server-side session in an HttpOnly, Secure,
SameSite cookie; state-changing browser requests also require a session-bound CSRF token. Only
token hashes are persisted. Configure initial elevated accounts with `ORL_WEB_ADMIN_EMAILS` and
`ORL_WEB_EDITOR_EMAILS`; later role changes should be made through controlled administration.

ORL Core and trusted operational clients continue to authenticate with signed bearer tokens
containing `sub`, `role`, `iss`, and `aud` claims. Supported roles are `user`, `moderator`, `editor`,
`admin`, and `service`. Browser identities remain inside Web and are never included in Core research
requests.

Public pages:

- `/` explains TruthLM as a thought assistant for students and researchers, presents the method as
  seven questions, lists the latest investigations, describes how questions are chosen, and hosts
  the invitation request form.
- `/join` is the standalone invitation request page.
- `/research` provides a searchable archive of published investigations.
- `/research/{slug}` renders the findings with their open questions and limitations, the structured
  research record, evidence map, and bibliography, plus share links (LinkedIn, X, Bluesky, Facebook,
  Reddit, email, copy link, native share) and Open Graph/Twitter card metadata.
- `/method` presents the seven questions with prompts readers can apply themselves, the public
  record, and how questions are selected.

Member pages:

- `/questions` (members only) provides question submission with review guidance and an optional
  domain, the queue grouped by domain and ranked by upvotes, readiness filtering, duplicate hints,
  review decisions with reviewer notes, and question flagging.
- `/subscriptions` lets a signed-in user follow all research or selected domains and cited
  researchers, then create or rotate a private RSS URL.
- `/moderation` is the review console for moderators and administrators: approve, attach, or decline
  pending questions; resolve flags; and, for administrators, decide invitation requests, invite
  addresses directly, and open or close weekly cycles.
- `/feeds/research.xml` is the public RSS 2.0 feed for every published investigation. Personal feed
  URLs are issued from the subscriptions page and can be polled without a browser session.
- `/login` requests a passwordless sign-in link without revealing whether an account exists.
- `/editor` loads the editorial queue for an editor or administrator browser session.
- `/docs` exposes the API reference.

## Initial workflow

1. A visitor requests an invitation at `/join` (or an administrator invites an address directly).
   An administrator approves it in `/moderation`; the person is emailed a sign-in pointer.
2. A member submits a question with an `Idempotency-Key` header, optionally suggesting a domain.
3. A moderator approves it into a new cluster with a domain, attaches it to an existing cluster, or
   declines it with a reason the member sees (for example, questions a lookup can answer).
4. An administrator opens a weekly cycle; members upvote approved questions.
5. An editor records a manual readiness assessment when needed.
6. An administrator closes the cycle. The service stores a per-domain vote snapshot, selects the
   most-upvoted question in each domain (at least one upvote, overrides need a reason), and emits one
   validated research-request payload per selection for ORL Core.
7. A service or administrator imports a checksummed Core metrics snapshot. Public clients read only
   the latest persisted snapshot.
8. ORL Core submits a checksummed `publication-bundle` to `POST /v1/admin/publications`. The service
   validates all evidence references and requires passed citation-support, originality, copyright,
   equation, and quantitative gates before creating a draft.
9. An editor or administrator publishes the reviewed draft with
   `POST /v1/admin/publications/{bundle_id}/publish`. Only then does it appear on public pages and in
   `GET /v1/articles`.
10. A corrected bundle increments `revision`, identifies `supersedes_bundle_id`, and explains the
   correction. Publishing it supersedes the prior public revision without deleting it. Editors may
   reject drafts or retract the current publication only with an audited reason.

Publication bundles contain an answer and a structured public research record: scope, assumptions,
methodology, expert contributions, chronological research actions, claim-to-source mappings,
disagreements, computations, limitations, and open questions. The site deliberately does not expose
private prompts or hidden token-by-token chain-of-thought. It publishes the inspectable scientific
record needed to reproduce, challenge, and extend the work.

Run `pytest` for the independent requirement, API, contract, and migration suite.

## Authentication operations

- Invitation decisions are audited without copying the email address into the audit record.
  Revoking access revokes the member's browser sessions immediately. The migration that introduced
  invite-only access grandfathered existing accounts as approved; review them in `/moderation`.

- Magic links expire after `ORL_WEB_MAGIC_LINK_MINUTES`, are consumed transactionally, and are
  rate-limited per normalized email address. Responses remain neutral after the limit is reached.
- Sessions expire after `ORL_WEB_SESSION_DAYS`. Sign-out revokes the server record immediately and
  clears the cookie. Rotate `ORL_WEB_JWT_SECRET` only with a planned invalidation of existing browser
  CSRF proofs and service JWTs.
- Development `console` delivery writes the sign-in URL to the `orl_web.auth` logger. Never use it in
  production. Production validation requires `smtp`, a host, a from address, PostgreSQL, and HTTPS.
- SMTP credentials belong in the deployment secret store. Database backups contain email addresses
  and credential hashes and must be handled as sensitive data.
- Personal RSS URLs are shown only when created or rotated. Reverse proxies and analytics must redact
  `/feeds/personal/*` paths because the URL contains the reader credential. The database retains only
  a hash, and revocation or rotation invalidates the prior URL immediately.
