# What's left

Handoff note. Branch `noskips-social`, four commits, 255 tests green, nothing
pushed. Phases 0–4 of the plan are built and verified; the website (Phase 5) is
planned in `docs/WEBSITE.md` and deliberately not built.

---

## 1. Blocked on you — accounts and secrets

None of this can be done without your credentials. All free.

| Service | What for | Lands in |
|---|---|---|
| [neon.tech](https://neon.tech) | Postgres — use the **pooled** string (`-pooler` in the host) | `DATABASE_URL` |
| [vercel.com](https://vercel.com) | import the repo; `vercel.json` and `api/index.py` are ready | the deploy |
| Google Cloud → Credentials → OAuth client (Web) | redirect `<url>/auth/google/callback` | `GOOGLE_CLIENT_ID` / `_SECRET` |
| discord.com/developers → OAuth2 | redirect `<url>/auth/discord/callback` | `DISCORD_CLIENT_ID` / `_SECRET` |
| Google account → Security → App passwords | 500 mails/day, no domain needed | `SMTP_USER` / `SMTP_PASSWORD`, `EMAIL_BACKEND=smtp` |

Also set: `SECRET_KEY` (`python -c "import secrets;print(secrets.token_hex(32))"`),
`BASE_URL`, `ADMIN_HANDLES=kaan`, `RESOLVER_TOKEN`, `MUSICBRAINZ_CONTACT`,
`DISCORD_INVITE`. Full list with comments in `.env.example`.

Then, once:

```
DATABASE_URL=<neon pooled url> python -m alembic upgrade head
```

**Two GitHub repo secrets** for the MusicBrainz cron
(`.github/workflows/resolve.yml`): `NOSKIPS_URL` and `RESOLVER_TOKEN`. Without
them the resolver never runs, so cover art stays blank and duplicate spellings
never merge.

**The one that will bite you:** the widget defaults to
`https://noskips.vercel.app`, which doesn't exist. After deploying, set
`NOSKIPS_SERVER` to your real URL or pairing silently fails against nothing.

---

## 2. Real gaps in the code

### You can't rate from the web

You chose "both, with provenance" — the API honours it (`POST /v1/sync` works
with a session cookie, and web ratings are correctly marked `web` rather than
`live`), but **no page has a rating control**. In practice it's widget-only
today. Album pages show what everyone thought; there's no way to add your own.

Needs: a stamp control on `/album/<key>` reusing the 1–10 + light/just/strong
scale, posting one op to `/v1/sync`.

### There is no way to find anything

No search, no browse, no "recently rated". You can only reach an album page if
somebody hands you the link. For "reaching more people" that's the biggest hole
in the web half — a profile is shareable, but the site has no front door beyond
the placeholder at `/`.

Needs: at minimum a search over `works.norm_artist` / `norm_title`, and
probably a "recent verdicts" list (which the website plan already wants for its
ticker).

### The landing page is a placeholder

`/` renders a stub (`server/web/templates/index.html`). The real one is
specified in `docs/WEBSITE.md` — that's the Phase 5 you asked me to plan and
not build.

---

## 3. Built but never exercised

These are written and unit-tested, but have never run against the real thing
because it needs credentials I don't have:

- **Google and Discord sign-in.** The redirect flow, token exchange and profile
  mapping are untested end-to-end. The account-linking logic *is* tested,
  including the case where an unverified provider email must not take over an
  existing account.
- **Real email.** Everything ran on the console backend. SMTP delivery,
  deliverability and the link formatting in a real client are unverified.
- **Postgres.** All 255 tests run on SQLite. The models stick to portable types
  and the migrations apply cleanly, but nothing has touched Neon.
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

1. **Seed the index.** An empty social product looks dead. Pair your widget and
   your 11 albums (143 tracks) backfill automatically — then keep rating.
2. **Staff the moderation queue.** `/admin` and the `NOSKIPS_READ_ONLY` kill
   switch both work, but only if `ADMIN_HANDLES` is set on the deploy.
3. **Trademark check** on "noskips" — I searched apps, domains and handles and
   found it clear, but I did not check USPTO/EUIPO. Ten minutes, worth it
   before it goes on anything permanent.
4. **Re-shoot the screenshots.** `assets/widget-now.png` and
   `assets/widget-shelf.png` still show the *rateify* wordmark, and the README
   points at them. Needs your desktop with the widget open.

---

## 5. Housekeeping

- **Push the branch.** Four commits on `noskips-social`, no remote set for it.
- **Rename the GitHub repo** to `noskips` (the local folder is still
  `Desktop/Coding/Rateify`, which is only cosmetic).
- **Two stale `Rateify.exe` copies** sit in the repo root and `dist/`. They're
  gitignored build artifacts from before the rename, and clicking one launches
  the *old* app. Worth deleting so there's nothing old to click by mistake.
  Note both old and new bind port 7700, so whichever starts second just opens a
  browser onto the first — that's the trap that makes the new build look broken.
- **Installer vs your library.** `noskips-Setup-2.0.0.exe` installs to
  `%LOCALAPPDATA%\Programs\noskips` and will start with an **empty shelf**: the
  automatic migration only looks for an *installed* Rateify, and you never
  installed one. Copy `data\ratings.json` (and `covers\`) across by hand, or
  keep running the exe from the repo root.

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
- **Rate limiting is fixed-window**, so up to 2× the limit can slip through
  across a boundary. Fine for stopping scripted abuse.
- **Vercel Hobby is non-commercial** under its terms. If this ever earns money,
  the same app moves to Fly.io for ~$5/mo.
- **Avoid `.fm`** (~$100/yr). `.app` is ~$15, or stay on `*.vercel.app`.
