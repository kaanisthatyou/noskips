# Tasks — social v2  *(all six done, 2026-08-18)*

Six independent pieces, in the order they unblock each other. T3 is the spine:
T4 and T6 both read the numbers it records, so it lands first.

---

## T1 ✔ — provider glyphs on the auth buttons

`continue with google` / `continue with discord` currently read as plain text
buttons. Put the provider's mark on the **right** edge of each, after the label.

* Touches: `templates/login.html`, `templates/link.html`, `zine.css`.
* Inline SVG, `currentColor`, no network fetch — the site ships no third-party
  requests and a CDN'd brand icon would be the first one.


**Done:** `_macros.html:oauth_button` + `provider_mark`; used by login and link. Inline SVG, no third-party request.

## T2 ✔ — discord mark beside the discord username on a profile

If the shelf's owner signed in with Discord, show their Discord name on the
profile with the same mark next to it.

* The name isn't stored today — `Identity` keeps `provider_uid` and
  `email_at_provider` only. Needs a `username_at_provider` column, captured in
  `oauth.profile()`, plus a migration.
* Only for a Discord identity; Google links stay invisible on the profile.


**Done:** `identities.username_at_provider`, captured in `oauth.profile()`, refreshed on every sign-in and never cleared. Shown by the `discord_name()` template global.

## T3 ✔ — listening time, measured honestly

When a verdict is stamped, record how much of *that* track was actually heard.

* **Cap is the song's own length.** You cannot bank more than 100% of a track.
* **A rewind must not pay twice.** Re-hearing the same 30 seconds does not add
  30 seconds. So the measure is *coverage of distinct parts of the song*, not
  wall-clock time with the player open.
* Implementation: a one-second-per-slot bitmap over the track's duration,
  fed by the poller that already runs every second in `app.py`. Marking a slot
  twice is a no-op, which is exactly the rewind rule, for free.
* Forward seeks don't count as heard. A continuous run between two polls does
  (that's jitter, not a skip).
* Carries to the server on the existing sync op → two new `Rating` columns:
  `listened_ms` and `coverage`.
* A restamp keeps the **larger** of the two figures — the most of that song the
  person has ever demonstrably sat through.


**Done:** `audio.Listen` (one slot per second) → `app.py` poller → sync op → `ratings.listened_ms` / `ratings.coverage`.

## T4 ✔ — stylized achievements

Badges, in the zine's own language (rubber stamps, not game trophies).
Separate from, and shown alongside, the daily / weekly / monthly / all-time
listening totals.

* Derived on read from ratings + T3's numbers. Nothing new stored, so a badge
  can never disagree with the shelf it's printed on.
* Tiers so they keep meaning something past the first week.


**Done:** `listening.BADGES` — seven badges, tiered, derived on read. Shown on the profile under the rolling day/week/month/all-time totals.

## T5 ✔ — the score stamp is too weak

`10.0` and a `10.` sitting inside a thin circle. It should read as something
pressed into the page — the object the whole product is named after.

* Touches `.score` in `zine.css`; the markup in `_macros.html` stays as it is
  wherever possible.


**Done:** `.score` in `zine.css`: two rings, an off-register second impression, a heavier press on a ten.

## T6 ✔ — leaderboards, two boards

1. **Time listened** — total, from T3.
2. **Stamps** — how many verdicts they've given.

Board 2 only counts a verdict where the person heard **more than 80% of the
song** (80% of its *distinct* length — see T3, a rewind can't get you there).

**This threshold is not stated anywhere in the UI.** No "80%" in a label, a
tooltip, a help page, or an API field name a reader would meet. The board says
"stamps" and means it; the bar is enforced quietly in the query.

Private shelves, banned and deleted accounts stay off both boards.


**Done:** `/leaderboard` + `/v1/leaderboard`. The bar lives once, in `listening._QUALIFYING_COVERAGE`, and a test asserts it never reaches a response.


---

## Not done here, on purpose

* **The production database has not been migrated.** `alembic upgrade head`
  against Neon is a change to live data and is the owner's call, not something
  to slip into a feature branch. Until it runs, the deploy will 500 on any page
  touching the new columns.
* **A verdict stamped on the website can never reach the stamps board.** The
  site has no playhead to watch, so its coverage is zero by construction. That
  follows from the rule as specified rather than contradicting it, and the
  board's page says where the numbers come from — but it does mean the board is
  a widget-users' board.
