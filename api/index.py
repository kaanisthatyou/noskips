"""Vercel entrypoint.

Vercel's Python runtime looks for a WSGI/ASGI callable named ``app`` in this
file and turns the whole thing into one serverless function; vercel.json then
rewrites every path to it, so Flask keeps doing its own routing.

The module-level ``create_app()`` runs once per cold start, not per request —
which is why db.py uses NullPool and Neon's pooled connection string. See the
note there before "optimizing" this into a persistent pool.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.factory import create_app  # noqa: E402

app = create_app()
