# The website

> **Built.** This started as a plan-only document and is now the spec the
> landing page was built from: `server/web/templates/index.html`, with the
> download block factored into `_downloads.html` (shared with `/download`) and
> the privacy page at `privacy.html`. Where the built page departs from the
> plan it is noted inline. Keep editing this file when the page changes — it is
> the reasoning, and the reasoning is the part that's hard to reconstruct.

It lives in the same Flask app, at `/`, for the same reason everything else
does: one deploy, one stylesheet, one set of fonts.

A separate Astro or Next site would be a second thing to keep in visual step
with the widget, and the whole point is that all of this reads as one object.

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

**Download.** Both artifacts. Built as a committed table in
`server/web/releases.py` rather than a call to the GitHub releases API — same
reasoning as "not at request time", taken one step further, because a build-time
fetch still fails the day GitHub is down and you happen to redeploy. Bump it
with the version; docs/RELEASING.md names all three places. The section is also
its own page at `/download`, because a signed-in reader is redirected off `/`
to their shelf and would otherwise have no route to the exe.

- `rateify-Setup-x.y.z.exe` — per-user installer, no admin
- `rateify-x.y.z-portable.zip` — unzip and run

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

- **Download and github belong in the topbar, not only the footer.** They were
  footer-only at first, which is wrong for two different readers: a signed-in
  one is redirected off `/` and never passes the landing page's download
  section at all, and a stranger evaluating an open-source desktop app looks
  for the source before the binary. Both are in `base.html`'s nav now, so they
  are on every page.
- **Signing up is a button; signing in is a word.** The signed-out nav ends
  with `sign in` and then `start a shelf` as a `.btn small`. Five grey words in
  a row is a list, not an invitation, and the shelf is the entire reason to
  have an account. Reading stays open — profiles, albums, `/recent` and search
  need no account, because an index nobody can link into or preview isn't a
  shared index. Login gates *writing*: rating, cosigning, following, pairing.
- **Prose gets a measure; cards don't.** The 880px shell is right for a shelf
  of verdict cards and wrong for the one page that is mostly paragraphs — about
  ninety characters a line in Special Elite and nearer a hundred and thirty in
  Caveat. `.landing p` is capped in `ch` rather than px, because `ch` is
  measured in the paragraph's own font and the two faces then land near the
  same character count without two hand-tuned numbers drifting apart. Scoped by
  a `landing` class on `<main>`, set from `{% block main_class %}`.
- **Keyboard and motion, which style.css already had and this didn't.** A skip
  link (parked off-screen, not `display:none` — a hidden element isn't
  focusable), a `:focus-visible` ring, and `prefers-reduced-motion`. That last
  one matters more than it looks: `.card`'s drop-in is charming once and is
  forty rotating pieces of paper on `/recent`.
- **44px targets on small screens** by growing the box, not the type, so the
  chrome looks identical and a thumb can still hit a 13px nav link.
- **Keep Postgres off the front page.** As built: the ticker is the only thing
  on `/` that queries at all, it's cached for two minutes, and the response
  carries `Cache-Control: public, max-age=120` so a CDN absorbs the rest. The
  cache is per-process, which on serverless means it helps a warm instance and
  does nothing for a cold one — the header is what actually carries the load,
  and Redis would be the only paid thing in the stack.
  The fragment is cached as **rendered HTML, not as rows**. Caching ORM objects
  across requests appears to work, because the first render happens to load
  their relationships; the day a template touches one it didn't, it's a
  `DetachedInstanceError` in production and nowhere else.
- **Reuse `static/zine.css`.** No new design language. If something needs a
  style the app doesn't have, that's a hint the section is off-brand.
- **One `og:image` for the site**, drawn by the same Pillow code as the profile
  and album cards — `/og/site.png` in `server/web/og.py`.
- **Screenshots degrade to nothing.** Each `<img>` on the landing page removes
  itself if the file is missing, so a shot that hasn't been taken yet costs a
  picture rather than a broken page. `static/shots/README.md` says what each
  one should show.
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

Two things that should land before anyone is invited — neither is code:

1. **Seed the index.** An empty social product looks dead. Rate a few hundred
   tracks yourself first — you already have 11 albums locally, and pairing
   backfills them automatically.
2. **Have the moderation queue staffed.** `/admin` and the `RATEIFY_READ_ONLY`
   kill switch both exist, but they only work if `ADMIN_HANDLES` is set on the
   deploy and you actually look at the queue.
