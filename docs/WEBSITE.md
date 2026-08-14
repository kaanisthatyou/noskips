# The website — plan only, not built

This is the one piece you asked to be planned and not executed. Nothing in here
exists yet. `/` currently renders a deliberate placeholder
(`server/web/templates/index.html`) that says what the product is and points at
sign-in; replacing it is the whole job below.

It lives in the same Flask app, at `/`, for the same reason everything else
does: one deploy, one stylesheet, one set of fonts. A separate Astro or Next
site would be a second thing to keep in visual step with the widget, and the
whole point is that all of this reads as one object.

## What it's for, in order

1. Get the exe onto a Windows machine.
2. Explain the one rule, because it's the most interesting thing here and
   nobody else does it.
3. Get people into the Discord.

Everything else is decoration. If a section doesn't serve one of those three,
cut it.

## Sections

**Hero.** The widget photographed floating over a real desktop — not a mockup
in a browser frame, an actual screenshot with a wallpaper behind it, because
the product's whole pitch is that it sits on top of your work. Wordmark in
Special Elite, the tagline underneath, one fat download button. No carousel, no
"trusted by", no scroll-jacking.

**"nobody has rated this yet."** The one rule, in about forty words, with a
screenshot of the first-press state in the widget. This is the section that
makes someone say *oh, that's different* — a rating site whose index only
contains songs a human actually stopped and judged. Lead with it, don't bury it
under a feature grid.

**The trace.** An animated GIF of the needle drawing the waveform while a track
plays, then the stamp landing and the trace freezing onto the verdict card.
This is the screenshot that travels, so it gets its own section and real space.
Caption it honestly: it only happens when listening is switched on.

**Live ticker.** The last ~20 public verdicts scrolling past as receipt tape,
straight off the public API. Proof of life with zero maintenance — and it will
look empty for the first week, which is a good reason to seed it by using the
thing yourself before launch. Hide the section entirely below some threshold
(say 25 verdicts) rather than showing three lonely rows.

**Download.** Both artifacts, with versions and sizes pulled from the GitHub
releases API at build time (not at request time — the marketing page must never
depend on GitHub being up):

- `noskips-Setup-x.y.z.exe` — per-user installer, no admin
- `noskips-x.y.z-portable.zip` — unzip and run

With the honest line right there rather than in a FAQ: **Windows 10/11 only,
because it reads the Windows media session. The web works everywhere.** Getting
that wrong wastes a Mac user's time and earns a bad first impression for
nothing.

**Discord.** A real section, not a footer icon. Say what the server is actually
for — first-press bragging, feature requests, weekly listening threads — because
"join our Discord" with no reason attached converts nothing. `/discord` already
exists as a permanent redirect (`server/web/pages.py`), reading its target from
the `DISCORD_INVITE` environment variable, so the invite can rotate without
breaking every link anyone has ever posted.

**Footer.** GitHub, MIT licence, and a privacy page written in plain language:
what syncs, what never leaves your machine, that covers are never uploaded,
how to export, how to delete. One page, no legalese. It's a genuine selling
point here — say it plainly and it does more work than a trust badge.

## Build notes

- **Static-render it.** The marketing page must not touch Postgres on a cold
  start. Cache the ticker's payload for a few minutes and serve the rest as
  bytes; Cloudflare in front and the database never sees the front page.
- **Reuse `static/zine.css`.** No new design language. If something needs a
  style the app doesn't have, that's a hint the section is off-brand.
- **One `og:image` for the site**, drawn by the same Pillow code as the profile
  and album cards (`server/web/og.py`) so the link preview matches everything
  else.
- **No cookie banner**, because there's nothing to consent to: no analytics, no
  third-party scripts, no fonts from a CDN. That's worth a sentence in the
  footer — it's unusual enough to be a feature.

## What I'd cut

A features grid, a testimonials section, a roadmap, a newsletter signup, and a
comparison table against Musicboard/sleevenotes/RateYourMusic. The comparison
in particular reads as insecure, and the honest version of it ("they're phone
apps where you search for an album; this catches the verdict at the second you
had it") is already the hero.

## Before it goes public

The site is the last thing to build, not the first, and there are two things
that should land before anyone is invited:

1. **Seed the index.** An empty social product looks dead. Rate a few hundred
   tracks yourself first — you already have 11 albums locally, and pairing
   backfills them automatically.
2. **Have the moderation queue staffed.** `/admin` and the `NOSKIPS_READ_ONLY`
   kill switch both exist, but they only work if `ADMIN_HANDLES` is set on the
   deploy and you actually look at the queue.
