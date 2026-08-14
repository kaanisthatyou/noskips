"""What the download section offers, and where it points.

Deliberately a committed table rather than a call to the GitHub releases API.
The front page must not depend on GitHub being up, and it must not spend a
serverless cold start on an outbound HTTP request before it can render — a
marketing page that is sometimes slow and occasionally blank is worse than one
whose version number is updated by hand at release time.

So: bump this alongside ``__version__`` in app.py and ``MyAppVersion`` in
installer.iss. docs/RELEASING.md lists all three in one place.
"""

import os

VERSION = "2.0.0"

# Sizes are the real bytes of the built artifacts, shown so nobody is surprised
# by a 30MB download on a hotel connection.
ARTIFACTS = [
    {
        "kind": "installer",
        "name": f"noskips-Setup-{VERSION}.exe",
        "bytes": 32_860_015,
        "blurb": "per-user installer, no admin needed",
    },
    {
        "kind": "portable",
        "name": f"noskips-{VERSION}-portable.zip",
        "bytes": 30_506_788,
        "blurb": "unzip and run, nothing written outside the folder",
    },
]

# The repo moves when it gets renamed, and the links have to move with it
# rather than quietly 404 — see docs/NEXT.md.
REPO = os.environ.get("GITHUB_REPO", "kaanisthatyou/noskips")


def _mb(size):
    return f"{size / 1_000_000:.1f}MB"


def latest():
    """The current release, ready to render."""
    base = f"https://github.com/{REPO}/releases/download/v{VERSION}"
    return {
        "version": VERSION,
        "repo": REPO,
        "repo_url": f"https://github.com/{REPO}",
        "artifacts": [
            {**a, "url": f"{base}/{a['name']}", "size": _mb(a["bytes"])} for a in ARTIFACTS
        ],
    }
