"""The browser half of device pairing, plus the landing pages for email links.

Why this is a real page with a real form rather than a one-click link: approving
a pairing hands a long-lived token to a program, so it gets an explicit,
readable confirmation naming the device — and a warning that says out loud what
the attack looks like. A GET that silently linked a device would be one crafted
link away from an account handover.
"""

from datetime import timedelta

from flask import current_app, g, redirect, render_template, request

from ..auth import pairing
from ..security import current_user, rate_limit
from . import bp


@bp.get("/link")
def link_page():
    code = pairing.parse_code(request.args.get("code"))
    ctx = {
        "code": code,
        "pretty_code": pairing.format_code(code) if code else "",
        "providers": current_app.config.get("OAUTH_PROVIDERS", []),
        "next_url": f"/link?code={code}",
        "done": False,
        "error": None,
        "pairing": None,
    }
    try:
        ctx["pairing"] = pairing.lookup(g.db, code)
    except pairing.PairingError as exc:
        ctx["error"] = str(exc)
    return render_template("link.html", **ctx)


@bp.post("/link")
def link_confirm():
    # a guessed code should not be cheap to brute-force through this page
    rate_limit(g.db, "link_confirm", limit=20, per=timedelta(minutes=10))

    code = pairing.parse_code(request.form.get("code"))
    user = current_user(g.db)
    if user is None:
        return redirect(f"/login?next=/link?code={code}")

    try:
        device = pairing.approve(g.db, code, user)
    except pairing.PairingError as exc:
        return render_template(
            "link.html", error=str(exc), code=code, pretty_code="",
            providers=[], next_url="/", done=False, pairing=None,
        )

    return render_template(
        "link.html", done=True, device_name=device.name,
        code=code, pretty_code=pairing.format_code(code), error=None,
        providers=[], next_url="/", pairing=None,
    )
