"""The v1 API.

Versioned in the path because the widget is an installed exe: an old copy on
someone's laptop must keep working long after the site has moved on. Breaking
this surface means breaking software you can't update.
"""

from flask import Blueprint

bp = Blueprint("api", __name__, url_prefix="/v1")

from . import (  # noqa: E402,F401
    auth_api,
    internal_api,
    pair_api,
    read_api,
    social_api,
    sync_api,
)
