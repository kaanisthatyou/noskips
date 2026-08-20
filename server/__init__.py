"""rateify server — the shared half of the app.

The widget in ../app.py stays entirely local and offline-capable. This package
is what it talks to *when the user asks it to*: accounts, handles, profiles,
and the shared index of verdicts.
"""
