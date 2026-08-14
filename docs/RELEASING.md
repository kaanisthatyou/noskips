# Releasing noskips

## Build the artifacts

```
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

Produces in `release/`:
- `noskips-Setup-<version>.exe` — per-user installer (no admin needed)
- `noskips-<version>-portable.zip` — unzip-and-run

Bump the version in **three places** first: `__version__` in `app.py`,
`MyAppVersion` in `installer.iss`, and `VERSION` (plus the two byte counts) in
`server/web/releases.py` — that last one is what the website's download buttons
point at, and it is a committed table rather than a call to the GitHub API so
the front page never depends on GitHub being up.

### A smaller exe

The visualiser and the trace need numpy and pyaudiowpatch. `audio.py` imports
both lazily and degrades to "not available" without them, so they can be left
out entirely:

```
$env:NOSKIPS_NO_AUDIO = "1"
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

Measured on 2.0.0: **29.3MB with, 19.5MB without**.

Note the flag has to add them to the spec's `excludes`, not merely leave them
out of `hiddenimports`. PyInstaller analyses bytecode rather than runtime
behaviour, so it finds `audio.py`'s function-level imports on its own — an
earlier version of this flag looked like it worked and shipped numpy anyway.

## Upgrading from Rateify

The installer uses a **new AppId**, so it installs alongside an existing
Rateify rather than over it. On first run the app copies
`%LOCALAPPDATA%\Programs\Rateify\data\ratings.json` and `covers\` into its own
folder (`_migrate_from_rateify` in `app.py`) and drops a
`data\.migrated-from-rateify` marker so it only ever happens once.

The old install is left completely untouched — users uninstall Rateify
themselves once they've confirmed their shelf came across.

## GitHub release

```
git tag v2.0.0
git push origin main --tags
```

Then on GitHub: *Releases → Draft a new release → choose the tag → attach both
files from `release/`*.

## Stores

- **itch.io** — best fit for the indie vibe. Create a project, upload the
  portable zip, mark it as a Windows tool. Free, no review process.
- **winget** (Microsoft's package manager) — after a GitHub release exists,
  run `wingetcreate new <url-of-Setup.exe>` and submit the generated manifest
  to https://github.com/microsoft/winget-pkgs. Free.
- **Microsoft Store** — needs a one-time ~$19 developer account and an MSIX
  package (`MSIX Packaging Tool` can wrap the installer). Only worth it if you
  want Store distribution specifically.

## Notes

- The exe stores ratings in `data/` and covers in `covers/` **next to itself**;
  the uninstaller leaves those folders alone on purpose.
- Windows only (it reads the Windows media session). The UI itself is plain
  HTML/CSS/JS, so a cross-platform port would only need a new now-playing source.
