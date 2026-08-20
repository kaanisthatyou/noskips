# The rateify server

The widget is offline-first and works forever with none of this running. The
server is what it talks to *when you ask it to*: accounts, handles, profiles,
and the shared index of verdicts.

## Run it locally

```
pip install -r server/requirements.txt
cp .env.example .env          # nothing needs filling in to start
python -m alembic upgrade head
flask --app server.factory:create_app run --debug
```

That gives you a working install on SQLite with verification emails printed to
the console — no Postgres, no Google project, no SMTP account. Sign-in buttons
for Google and Discord appear only once their credentials are in the
environment, so a bare checkout is fully usable.

```
python -m pytest tests/ -q
```

209 tests, ~40 seconds, no network and no database server.

## The one rule

A song has no entry in the shared world until a human rates it.

There is no catalog table and no importer. A `works` row is created *only*
inside the transaction that stores its first rating, and it is deleted again
when the last rating goes. `GET /v1/works/<key>` answers **404** for anything
nobody has rated — not an empty object with a zero in it — and the widget turns
that 404 into "be the first press".

All of it lives in `server/store.py`, and `tests/test_store.py` is the proof.

## Track identity

`server/resolve.py` is the load-bearing module. The same song reaches us as
`Currents / Let It Happen`, `Currents (Deluxe) / Let It Happen - 2015 Remaster`
and `Currents [Explicit] / Let It Happen`; key the index on raw strings and it
shatters into singletons where every average is computed over one person.

Two keys come out of it:

- `work_key` — artist + title. Deliberately **not** album, so a song collects
  one pile of verdicts across the single, the album and the greatest-hits.
- `album_key` — artist + album, for grouping the shelf and album pages.

Edition noise (remaster, deluxe, explicit, mono) is stripped because it
describes the same performance. `live`, `acoustic`, `demo` and `remix` are
never stripped, because they describe a different one.

`tests/test_resolve.py` is the specification — a table of pairs that must merge
and pairs that must stay apart. **Adding a rule without adding a case there is
how the shared index quietly rots.**

## How the widget signs in

The exe holds no secrets. It delegates the login to a real browser:

```
widget   POST /v1/pair/start {nonce}   -> a 6-character code + a URL
widget   opens that URL in the browser
person   logs in normally, sees the device named, approves it
widget   POST /v1/pair/poll  {nonce}   -> its own device token
```

The code is useless without the nonce, so a guessed or phished code can't hand
the token to an attacker's widget — but a victim could still be talked into
approving a device that isn't theirs, which is why `/link` is an explicit form
with a warning rather than a one-click link. Tokens are stored hashed and are
revocable per device.

## Deploying free

Everything here is $0:

| | |
|---|---|
| App | Vercel Hobby — `vercel.json` + `api/index.py`, one serverless function |
| Database | Neon free tier — use the **pooled** connection string (`-pooler` in the host) |
| Email | Gmail SMTP + an app password, 500/day, no domain needed |
| Domain | `*.vercel.app` until you want a real one (`.app` ~$15/yr; avoid `.fm`, ~$100/yr) |

### Neon, step by step

1. **neon.tech** → sign in with GitHub → **Create project**. Name it `rateify`,
   pick the region nearest your Vercel region, leave the Postgres version at the
   default. The free tier needs no card.
2. On the project dashboard, **Connection string**. Two things to get right:
   - the **Connection pooling** toggle must be **on** — the host then has
     `-pooler` in it. This is not a nicety: `server/db.py` uses `NullPool`
     because a serverless process can't reuse connections, so PgBouncer on
     Neon's side is doing all the pooling. The direct string will exhaust
     connections under any real traffic.
   - copy the **psql / URI** form, not the `psql "..."` command line.

   You want something shaped like:

   ```
   postgresql://neondb_owner:XXXX@ep-something-a1b2c3-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```

3. **You don't have to fix the scheme by hand.** Neon hands out `postgresql://`,
   which SQLAlchemy resolves to psycopg **2** — and what's installed here is
   psycopg **3**. `normalize_database_url` in `server/db.py` rewrites it to
   `postgresql+psycopg://`, and `server/migrations/env.py` uses the same helper
   so migrations and the app can never resolve different drivers. Paste the URL
   exactly as Neon gives it to you.

4. **Migrate once, from your machine.** PowerShell:

   ```powershell
   $env:DATABASE_URL = "postgresql://...-pooler.../neondb?sslmode=require"
   pip install -r server/requirements.txt
   python -m alembic upgrade head
   ```

   Expect `Running upgrade -> 4cd2a8fc4580, initial schema` and then the rate-limit
   revision. Re-running is safe; it's a no-op once they're applied.

5. **Check it took**, rather than trusting it:

   ```powershell
   python -c "from server.db import engine; from sqlalchemy import text; print(engine().connect().execute(text('select count(*) from users')).scalar())"
   ```

   `0` is the right answer. `relation "users" does not exist` means step 4
   ran against SQLite because `DATABASE_URL` wasn't set in that shell.

6. **Put the same string in Vercel** — Project → Settings → Environment
   Variables → `DATABASE_URL`, ticked for Production (and Preview, if you want
   previews to work). Environment variables are read at cold start, so
   **redeploy after adding it**; setting it on a live project changes nothing
   until the next deployment.

Then set `SECRET_KEY` and `BASE_URL` the same way.

> If you'd rather not manage the string at all: Vercel's Marketplace has a Neon
> integration that provisions the database and sets `DATABASE_URL` on the
> project for you. It's the same Neon free tier. Check the variable it sets is
> the pooled host before relying on it.

Two things to know:

- **Vercel Hobby is non-commercial** under its terms. If this ever earns money,
  the same app moves to Fly.io for about $5/month.
- **Serverless has no long-lived connections.** `server/db.py` uses `NullPool`
  deliberately and leans on Neon's PgBouncer. Don't "optimize" that into a
  persistent pool.

## Moderation

Ships with the social features rather than after them, because a social app
without them becomes someone else's problem within a week.

- `/admin` — the report queue. Access is by handle from the `ADMIN_HANDLES`
  environment variable (comma-separated), so there's no "make me an admin" code
  path to find a bug in. It answers **404**, not 403, to everyone else.
- Actions are dismiss, hide the verdict (it stays theirs, it just leaves every
  public surface), and ban. An admin can't be banned through the queue —
  otherwise one retaliatory report is a self-inflicted lockout.
- `RATEIFY_READ_ONLY=1` is the kill switch: every write stops, everything stays
  readable. The thing you want at 2am when you'd rather freeze the site than
  take it down.

## Link previews

`server/web/og.py` draws profile and album cards with Pillow — real paper
colour, real Special Elite, the average stamped crooked. They respect the same
privacy rules as the pages: a private shelf has no card, and a song nobody
rated has nothing to preview.

Pillow is imported softly. Without it the pages simply omit their `og:image`
rather than 500.

## The MusicBrainz pass

`server/musicbrainz.py` is the second pass that catches what normalization
can't — "Mr. Brightside" vs "Mister Brightside" — by asking MusicBrainz for a
real recording MBID and merging works that turn out to be the same recording.

Three rules, in order of how badly they'd hurt to get wrong:

- **Resolution is never a gate.** A work with no MBID is a perfectly normal
  work. MusicBrainz being down changes nothing.
- **Never on the write path.** A sync batch can carry 200 ops; at one request
  per second that would be a three-minute HTTP request. It runs from cron
  instead — a deliberate departure from the original plan's "resolve inline
  with a 2s timeout".
- **One request per second, with a contactable User-Agent.** Their stated
  limit and the condition of using it.

Because Vercel Hobby only fires cron once a day, the schedule lives in
`.github/workflows/resolve.yml` and runs every fifteen minutes (also free). It
POSTs to `/v1/internal/resolve` with `RESOLVER_TOKEN`; set that as both a
Vercel env var and a repo secret, along with `RATEIFY_URL`.

Cover art is *linked* from the Cover Art Archive, never copied — and checked
with a HEAD first, so a missing cover is a clean placeholder rather than a
broken image. We never host artwork: the widget's local cache is Spotify's and
uploading it isn't ours to do.

The genuinely dangerous part is merging, because moving ratings between works
runs into `UNIQUE(user_id, work_id)` whenever one person rated both spellings.
`merge_works` always deletes the loser's row and transplants its values onto
the survivor rather than moving the row across — moving first puts two rows in
one slot for as long as the flush takes, which the database refuses outright.
`tests/test_musicbrainz.py` covers that case specifically.

## Still to come

The website (`docs/WEBSITE.md`) is planned and deliberately not built.
