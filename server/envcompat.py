"""`RATEIFY_*` environment variables, with the pre-rename `NOSKIPS_*` names still read.

The app was called noskips until the rename, and the README told people to set
``NOSKIPS_DATA_DIR`` if they wanted their library somewhere other than next to
the exe. Anyone who did that has a shelf that exists *only* at that path — so
reading just the new name would quietly create a fresh, empty library and look
exactly like every rating being gone.

The server switches need it for the opposite reason: a deployment whose kill
switch is still set as ``NOSKIPS_READ_ONLY`` must keep stopping writes rather
than silently going writable again, which is the failure you'd discover at the
worst possible moment.

Delete this once nothing in the wild sets the old names — which for the widget
means once no installed exe still reads them, not merely once the docs stop
mentioning them.
"""

import os

PREFIX = "RATEIFY_"
LEGACY_PREFIX = "NOSKIPS_"


def env(name, default=None):
    """Read ``RATEIFY_<name>``, falling back to ``NOSKIPS_<name>``.

    Blank means unset, matching the rest of the codebase: ``.env.example``
    ships every key present with an empty value and the docs say to copy it
    verbatim, so a plain ``os.environ.get(key, default)`` hands back ``""`` for
    a key nobody ever filled in. See tests/test_env_config.py.
    """
    for prefix in (PREFIX, LEGACY_PREFIX):
        value = os.environ.get(prefix + name, "").strip()
        if value:
            return value
    return default
