"""The widget's half of the pairing dance. The browser's half lives in
server/web/pair_routes.py, because that's where a human can see the address bar.
"""

from datetime import timedelta

from flask import current_app, g, jsonify, request

from ..auth import pairing
from ..security import ApiError, rate_limit, require_user
from . import bp


@bp.post("/pair/start")
def pair_start():
    rate_limit(g.db, "pair_start", limit=10, per=timedelta(minutes=10))
    data = request.get_json(silent=True) or {}
    try:
        code = pairing.start(
            g.db,
            data.get("device_nonce"),
            device_name=data.get("device_name"),
            app_version=data.get("app_version"),
        )
    except pairing.PairingError as exc:
        raise ApiError(str(exc), 400, "pair_failed")

    base = current_app.config["BASE_URL"]
    return jsonify(
        ok=True,
        code=pairing.format_code(code),
        url=f"{base}/link?code={code}",
        expires_in=int(pairing.PAIRING_TTL.total_seconds()),
    )


@bp.post("/pair/poll")
def pair_poll():
    # polled every couple of seconds by design, so the ceiling is generous
    rate_limit(g.db, "pair_poll", limit=400, per=timedelta(minutes=10))
    token = pairing.poll(g.db, (request.get_json(silent=True) or {}).get("device_nonce"))
    if token is None:
        return jsonify(ok=True, pending=True)
    return jsonify(ok=True, pending=False, device_token=token)


@bp.delete("/devices/<device_id>")
@require_user
def revoke_device(device_id):
    """Unlink a device from the web — including one you've lost, which is the
    whole reason this isn't only available to the device itself."""
    from ..models import Device
    from ..security import as_uuid

    key = as_uuid(device_id)
    device = g.db.get(Device, key) if key else None
    if device is None or device.user_id != g.user.id:
        raise ApiError("no such device", 404, "not_found")
    pairing.revoke(g.db, device)
    return jsonify(ok=True)


@bp.post("/pair/unlink")
@require_user
def unlink_this_device():
    """Called by a widget that wants to forget itself. Revoking someone else's
    device is done from the web settings page, not from an exe."""
    from ..security import current_device

    device = current_device(g.db)
    if device is None:
        raise ApiError("this isn't a paired device", 400, "not_a_device")
    pairing.revoke(g.db, device)
    return jsonify(ok=True)
