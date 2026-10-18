# TruthLM / ORL Web

The independently deployable public service behind `truthlm.com`. TruthLM is a thought assistant
for students and researchers, not an answer engine: it publishes weekly investigations that show how
a question was scoped, what the evidence shows, which numbers were reproduced, where experts
disagree, and what remains open. It is deliberately not a social network: there are no public
profiles, feeds, comments, or votes.

## Access model

TruthLM has two access levels:

1. **Read.** Every investigation, the method, the archive, and the public RSS feed are open to
   everyone without an account.
2. **Subscribe and receive.** Subscribers receive new investigations by email and choose the domains
   and cited researchers they follow. While `ORL_WEB_ACCESS_MODE=invite`, people join a waitlist and
   an administrator approves addresses in batches; approval starts the subscription. Set the mode to
   `open` when anyone may subscribe by signing in with their email.

The editorial team chooses the questions. At launch only editors and administrators submit them, and
the team publishes at most one investigation per research domain each week after a manual review.
The service covers seven domains by default: Biology, Chemistry, Economics, Finance, Mathematics,
Physics, and Statistics.

The service hosts the publication experience, the waitlist and subscriber list, email delivery,
question review, research-readiness labels, and sanitized Core metrics. It never imports ORL Core,
opens the Core catalog, or connects to its vector store.

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
`Biology,Chemistry,Economics,Finance,Mathematics,Physics,Statistics`); add a domain only when the
consortium has an expert for it. The browser receives an opaque, revocable server-side session in an HttpOnly, Secure,
SameSite cookie; state-changing browser requests also require a session-bound CSRF token. Only
token hashes are persisted. Configure initial elevated accounts with `ORL_WEB_ADMIN_EMAILS` and
`ORL_WEB_EDITOR_EMAILS`; later role changes should be made through controlled administration.

ORL Core and trusted operational clients continue to authenticate with signed bearer tokens
containing `sub`, `role`, `iss`, and `aud` claims. Supported roles are `user`, `moderator`, `editor`,
`admin`, and `service`. Browser identities remain inside Web and are never included in Core research
requests.

Public pages:

- `/` explains TruthLM as a thought assistant, presents the two access levels, and lists the latest
  investigations. While access is invite-only it carries the waitlist form.
- `/join` is the standalone waitlist page (or, in `open` mode, the subscribe page).
- `/research` provides a searchable archive of published investigations.
- `/research/{slug}` renders the findings with their open questions and limitations, the structured
  research record, evidence map, and bibliography, plus share links (LinkedIn, X, Bluesky, Facebook,
  Reddit, email, copy link, native share) and Open Graph/Twitter card metadata.
- `/method` presents the seven questions with prompts readers can apply themselves and the public
  record.
- `/feeds/research.xml` is the public RSS 2.0 feed for every published investigation.
- `/unsubscribe/{user_id}/{signature}` is the signed link every research email carries; it stops
  research emails without signing in and accepts one-click unsubscribe requests from mail providers.
- `/login` requests a passwordless sign-in link without revealing whether an account exists.
- `/docs` exposes the API reference.

Subscriber and staff pages:

- `/subscriptions` lets a subscriber turn research emails off or on, follow all research or selected
  domains and cited researchers, and create or rotate a private RSS URL that uses the same interests.
- `/questions` (editors and administrators) submits research questions, lists approved questions by
  domain with their cluster IDs, and shows your submissions' moderation state.
- `/moderation` is the review console for moderators and administrators: approve, attach, or decline
  pending questions; resolve flags; and, for administrators, approve waitlist requests in batches and
  invite addresses directly.
- `/editor` is the editorial workspace: review and publish drafts, retract or correct publications,
  and email new research to subscribers.

## Weekly workflow

1. Someone joins the waitlist at `/join`. An administrator approves the address in `/moderation` (or
   invites it directly). Approval creates the subscriber's account, which follows all weekly research
   by default, and emails a welcome notice with a sign-in link and an unsubscribe link.
2. An editor or administrator submits a question at `/questions` with an `Idempotency-Key` header,
   optionally suggesting one of the configured domains.
3. A moderator approves it into a new question cluster with a domain, attaches it to an existing
   cluster, or declines it with a reason the submitter sees. Approval returns the cluster ID.
4. An editor records a manual readiness assessment when needed.
5. The operator runs ORL Core on the question and builds the publication bundle with
   `--cluster-id <cluster ID>`, so the investigation carries the question's domain.
6. ORL Core submits the checksummed `publication-bundle` to `POST /v1/admin/publications`. The service
   validates all evidence references and requires passed citation-support, originality, copyright,
   equation, and quantitative gates before creating a draft.
7. After the manual review, an editor publishes the draft with
   `POST /v1/admin/publications/{bundle_id}/publish`. Only then does it appear on public pages, the
   RSS feed, and `GET /v1/articles`. Publishing never emails anyone by itself.
8. Once the week's investigations are published (at most one per domain), an editor presses
   **Email new research to subscribers** in `/editor`. That repeats
   `POST /v1/admin/deliveries/run` until no subscribers remain: each subscriber receives one email
   listing the new investigations that match their interests, never the same investigation twice.
   `GET /v1/admin/deliveries` reports subscribers, sent, failed, and interrupted deliveries.
9. A corrected bundle increments `revision`, identifies `supersedes_bundle_id`, and explains the
   correction. Publishing it supersedes the prior public revision without deleting it, and it is not
   emailed again. Editors may reject drafts or retract the current publication only with an audited
   reason; a retracted investigation is never emailed.

A service or administrator can also import a checksummed Core metrics snapshot. Public clients read
only the latest persisted snapshot.

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
  CSRF proofs, service JWTs, and the unsubscribe links in emails already sent.
- Development `console` delivery writes sign-in URLs and research email subjects to the
  `orl_web.auth` logger. Never use it in production. Production validation requires `smtp`, a host,
  a from address, PostgreSQL, and HTTPS.
- SMTP credentials belong in the deployment secret store. Database backups contain email addresses
  and credential hashes and must be handled as sensitive data.
- Personal RSS URLs are shown only when created or rotated. Reverse proxies and analytics must redact
  `/feeds/personal/*` paths because the URL contains the reader credential. The database retains only
  a hash, and revocation or rotation invalidates the prior URL immediately.

## Email delivery operations

- Send through an email provider's SMTP endpoint (for example Amazon SES, Postmark, or Resend) with
  SPF, DKIM, and DMARC configured for the sender domain. Research emails carry `List-Unsubscribe` and
  one-click `List-Unsubscribe-Post` headers, which Gmail and Yahoo expect from bulk senders.
- Approving waitlist addresses in batches warms a new sending domain gradually.
- `ORL_WEB_DELIVERY_BATCH_SIZE` (default 50) caps the subscribers emailed per run. A failed email is
  retried on later runs, at most three attempts in total. A delivery interrupted mid-send stays
  `sending` and is never retried automatically, so nobody is emailed twice; check it with
  `GET /v1/admin/deliveries` and the provider's logs.
