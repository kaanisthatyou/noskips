# Releasing noskips

## Build the artifacts

```
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

Produces in `release/`:
- `noskips-Setup-<version>.exe` — per-user installer (no admin needed)
- `noskips-<version>-portable.zip` — unzip-and-run

Bump the version in **two places** first: `__version__` in `app.py` and
`MyAppVersion` in `installer.iss`.

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
