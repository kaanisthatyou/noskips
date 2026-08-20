# What's left

Handoff note. Branch `rateify-social`, 297 tests green, nothing pushed. Phases
0–5 are built and verified — including the website, which was previously
planned-only. What remains is almost entirely **credentials and your machine**:
the code no longer has a hole in it that I can close without your accounts.

---

## 1. Blocked on you — accounts and secrets

None of this can be done without your credentials. All free.

**The site is up: https://noskips-navy.vercel.app.** Neon is provisioned through
the Vercel Marketplace, the schema is migrated, and `SECRET_KEY` and `BASE_URL`
are set on the project. What is left below is sign-in, mail and the cron.

| Service | What for | Lands in | |
|---|---|---|---|
| [neon.tech](https://neon.tech) | Postgres — pooled string (`-pooler` in the host) | `DATABASE_URL` | **done** |
| [vercel.com](https://vercel.com) | the deploy | — | **done** |
| Google Cloud → Credentials → OAuth client (Web) | redirect `https://noskips-navy.vercel.app/auth/google/callback` | `GOOGLE_CLIENT_ID` / `_SECRET` | |
| discord.com/developers → OAuth2 | redirect `https://noskips-navy.vercel.app/auth/discord/callback` | `DISCORD_CLIENT_ID` / `_SECRET` | |
| Google account → Security → App passwords | 500 mails/day, no domain needed | `SMTP_USER` / `SMTP_PASSWORD`, `EMAIL_BACKEND=smtp` | |

Still to set: `ADMIN_HANDLES=kaan`, `RESOLVER_TOKEN`, `MUSICBRAINZ_CONTACT`,
`DISCORD_INVITE`. Full list with comments in `.env.example`.

The Marketplace integration provisions `DATABASE_URL` **sensitive**, meaning
Vercel will not show it back to you — not in `vercel env pull`, not in the
dashboard. To migrate again, read the string from the Neon console (Vercel →
Storage → rateify → Open in Neon), then:

```
DATABASE_URL=<neon pooled url> python -m alembic upgrade head
```

**Two GitHub repo secrets** for the cron (`.github/workflows/resolve.yml`):
`RATEIFY_URL` and `RESOLVER_TOKEN`. Without them the resolver never runs, so
cover art stays blank, duplicate spellings never merge, and — since the same
tick now does the housekeeping — spent rate-limit rows never get pruned.

**The one that would have bitten you — settled.** The widget's fallback pointed
at a bare `*.vercel.app` name that was already taken by somebody else. The
deploy lives at `https://noskips-navy.vercel.app` and `sync.py` now ships that.
That hostname keeps the pre-rename project name on purpose: renaming the Vercel
project rewrites the URL, and the Google and Discord OAuth redirect URIs point
at it, so sign-in breaks until both consoles are updated to match.

```python
DEFAULT_SERVER = os.environ.get("RATEIFY_SERVER", "https://noskips-navy.vercel.app")
```

`RATEIFY_SERVER` still overrides it, but only on a machine where somebody sets
it — and nobody who downloads the exe will. **When a real domain is bought,
change that literal before building the release**, not after: ship it stale and
every download pairs against nothing, silently, and the only fix is a new
release.

**`GITHUB_REPO` is fine as it is.** It defaults to `kaanisthatyou/rateify` and
the repo now really is called that, so the download buttons resolve.

---

## 2. Real gaps in the code

None outstanding. The three that were listed here are built:

- **Rating from the web** — every track row on `/album/<key>` carries the same
  1–10 + light/just/strong control the widget has, and `/stamp` lets you first-
  press anything from memory. Both post one op to `/v1/sync` and are marked
  `web`, never `live`; only a paired widget can claim the live mark.
- **Finding things** — `/search` over artist, record and title (query folded
  through the same normalizer the index was built with, so a pasted "— 2015
  Remaster" still lands), plus people by handle. `/recent` is the public list.
  The search box sits in the chrome of every page.
- **The landing page** — `/` is the real one now: hero, the one rule, the
  trace, a ticker that hides itself below 25 verdicts, downloads, Discord, and
  a plain-language `/privacy`. `docs/WEBSITE.md` is the spec it was built from.

Two things you should know about how they behave:

- **A web verdict doesn't come back down to the widget.** Sync is one-way —
  the widget pushes its outbox up and pulls community averages down, but never
  pulls your own ratings back into `ratings.json`. So something you stamp on
  the site lives on the server only. The web control deliberately sends the
  widget's *existing* revision rather than one past it, so whichever verdict
  was written last wins and a later widget stamp is never silently dropped.
- **Rate-limit rows are keyed by IP** and are now pruned to an hour by the
  resolver cron (`prune_rate_limits`). The `/privacy` page says an hour — if
  you ever remove the cron, that sentence stops being true.

---

## 3. Built but never exercised

Written and unit-tested, but never run against the real thing because it needs
credentials I don't have:

- **Google and Discord sign-in.** The redirect flow, token exchange and profile
  mapping are untested end-to-end. The account-linking logic *is* tested,
  including the case where an unverified provider email must not take over an
  existing account.
- **Real email.** Everything ran on the console backend. SMTP delivery,
  deliverability and link formatting in a real client are unverified.
- **Postgres.** All 297 tests run on SQLite. The models stick to portable types
  and the migrations apply cleanly, but nothing has touched Neon. Search uses
  `LIKE` with an escaped needle, which behaves the same on both — but it is a
  sequential scan, so if the index ever gets big, that's the first thing to
  reach for an index for (`pg_trgm` on the `norm_*` columns).
- **The MusicBrainz cron.** `resolve_pending` is tested with a stubbed HTTP
  layer; no live MusicBrainz call has ever been made. Watch the first run —
  their rate limit is strict and the User-Agent must identify you.

### YouTube classification

I verified `Spotify.exe` → `MediaPlaybackType.MUSIC` against a live session.
I never got a live **browser** session, so the fallback for players reporting
`UNKNOWN` is untested against real YouTube.

To check: play a video, then

```
python -c "import app,time; time.sleep(2); print(app.app.test_client().get('/api/now').get_json())"
```

If it lands on the music shelf, send me the `source` and `kind` values and the
fallback in `media_kind.py` can be tightened.

---

## 4. Before anyone else sees it

1. **Seed the index.** An empty social product looks dead, and the landing
   page's ticker stays hidden below 25 verdicts — which is the honest signal,
   not a bug to work around. Pair your widget and your 11 albums (143 tracks)
   backfill automatically, then keep rating.
2. **Staff the moderation queue.** `/admin` and the `RATEIFY_READ_ONLY` kill
   switch both work, but only if `ADMIN_HANDLES` is set on the deploy.
3. **The three screenshots the landing page wants.** `static/shots/README.md`
   lists exactly what each one should show; the page removes any `<img>` whose
   file is missing, so it degrades quietly rather than breaking — but the hero
   is a wall of text without them, and the trace GIF is the one that travels.
4. **Trademark check** on "rateify" — I searched apps, domains and handles and
   found it clear, but I did not check USPTO/EUIPO. Ten minutes, worth it
   before it goes on anything permanent.
5. ~~Re-shoot the README screenshots.~~ Done — both now show the real widget.

---

## 5. Housekeeping

- ~~Push the branch.~~ Done — `rateify-social` and `main` both track origin.
- ~~Rename the GitHub repo.~~ Done — it is `kaanisthatyou/rateify`, which is
  what `GITHUB_REPO` already defaults to, so nothing needs setting.
- **Installer vs your library.** `rateify-Setup-2.0.0.exe` installs to
  `%LOCALAPPDATA%\Programs\rateify` and starts with an **empty shelf** — the
  library that matters lives next to the exe in the repo root. Copy
  `data\ratings.json` (and `covers\`) across by hand, or keep running the exe
  from the repo root. Note both builds bind port 7700, so whichever starts
  second just opens a browser onto the first.

---

## 6. Deliberate deferrals — not bugs

- **No comments on verdicts.** The note *is* the comment; comments would mean
  real moderation infrastructure.
- **Cover art is blank until the resolver runs.** `cover_url` is only filled by
  the MusicBrainz pass.
- **The trace needs listening switched on**, which is off by default. No
  capture, no trace — an invented one would make the honest ones worthless.
- **A work belongs to the album it was first seen on.** A track on both an album
  and a compilation groups under whichever arrived first.
- **Search is substring, not fuzzy.** A typo finds nothing. Trigram search is a
  Postgres extension away if it turns out to matter, but guessing at what
  somebody meant is how you end up recommending things.
- **Rate limiting is fixed-window**, so up to 2× the limit can slip through
  across a boundary. Fine for stopping scripted abuse.
- **Vercel Hobby is non-commercial** under its terms. If this ever earns money,
  the same app moves to Fly.io for ~$5/mo.
- **Avoid `.fm`** (~$100/yr). `.app` is ~$15, or stay on `*.vercel.app`.
