"""Following, cosigning, and the moderation floor.

The moderation pieces ship alongside the social pieces on purpose. A social app
that can follow and post before it can block and report is a problem waiting for
its first bad week.
"""

from datetime import timedelta

from flask import g, jsonify, request
from sqlalchemy import select

from ..models import Block, Cosign, Follow, Rating, Report
from ..security import ApiError, as_uuid, rate_limit, require_handle
from . import bp
from .read_api import _blocked_between, _find_user


# --------------------------------------------------------------- following ----


@bp.post("/follow/<handle>")
@require_handle
def follow(handle):
    rate_limit(g.db, "follow", limit=60, per=timedelta(hours=1), key=str(g.user.id))
    target = _find_user(handle)
    if target.id == g.user.id:
        raise ApiError("you already know what you think", 400, "self_follow")
    if _blocked_between(target, g.user):
        raise ApiError("no such person", 404, "not_found")

    existing = g.db.scalar(
        select(Follow).where(Follow.follower_id == g.user.id, Follow.followee_id == target.id)
    )
    if existing is None:
        g.db.add(Follow(follower_id=g.user.id, followee_id=target.id))
        g.db.flush()
    return jsonify(ok=True, following=True)


@bp.delete("/follow/<handle>")
@require_handle
def unfollow(handle):
    target = _find_user(handle)
    existing = g.db.scalar(
        select(Follow).where(Follow.follower_id == g.user.id, Follow.followee_id == target.id)
    )
    if existing is not None:
        g.db.delete(existing)
        g.db.flush()
    return jsonify(ok=True, following=False)


# ---------------------------------------------------------------- cosigns ----


def _rating_or_404(rating_id):
    key = as_uuid(rating_id)
    rating = g.db.get(Rating, key) if key else None
    if rating is None or not rating.is_public:
        raise ApiError("no such verdict", 404, "not_found")
    return rating


@bp.post("/cosign/<rating_id>")
@require_handle
def cosign(rating_id):
    rate_limit(g.db, "cosign", limit=200, per=timedelta(hours=1), key=str(g.user.id))
    rating = _rating_or_404(rating_id)
    if rating.user_id == g.user.id:
        raise ApiError("cosigning yourself doesn't count", 400, "self_cosign")
    if _blocked_between(rating.user, g.user):
        raise ApiError("no such verdict", 404, "not_found")

    existing = g.db.scalar(
        select(Cosign).where(Cosign.user_id == g.user.id, Cosign.rating_id == rating.id)
    )
    if existing is None:
        g.db.add(Cosign(user_id=g.user.id, rating_id=rating.id))
        g.db.flush()
    return jsonify(ok=True, cosigned=True, count=len(rating.cosigns))


@bp.delete("/cosign/<rating_id>")
@require_handle
def uncosign(rating_id):
    rating = _rating_or_404(rating_id)
    existing = g.db.scalar(
        select(Cosign).where(Cosign.user_id == g.user.id, Cosign.rating_id == rating.id)
    )
    if existing is not None:
        g.db.delete(existing)
        g.db.flush()
    return jsonify(ok=True, cosigned=False, count=len(rating.cosigns))


# ------------------------------------------------------------- moderation ----


@bp.post("/block/<handle>")
@require_handle
def block(handle):
    target = _find_user(handle)
    if target.id == g.user.id:
        raise ApiError("you can't block yourself", 400, "self_block")

    existing = g.db.scalar(
        select(Block).where(Block.blocker_id == g.user.id, Block.blocked_id == target.id)
    )
    if existing is None:
        g.db.add(Block(blocker_id=g.user.id, blocked_id=target.id))
    # blocking also severs any follow in either direction
    for follow_row in g.db.scalars(
        select(Follow).where(
            ((Follow.follower_id == g.user.id) & (Follow.followee_id == target.id))
            | ((Follow.follower_id == target.id) & (Follow.followee_id == g.user.id))
        )
    ):
        g.db.delete(follow_row)
    g.db.flush()
    return jsonify(ok=True, blocked=True)


@bp.delete("/block/<handle>")
@require_handle
def unblock(handle):
    target = _find_user(handle)
    existing = g.db.scalar(
        select(Block).where(Block.blocker_id == g.user.id, Block.blocked_id == target.id)
    )
    if existing is not None:
        g.db.delete(existing)
        g.db.flush()
    return jsonify(ok=True, blocked=False)


@bp.post("/report")
@require_handle
def report():
    rate_limit(g.db, "report", limit=20, per=timedelta(hours=1), key=str(g.user.id))
    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()[:500]
    if not reason:
        raise ApiError("say what's wrong with it", 400, "reason_required")

    target_rating = target_user = None
    if data.get("rating_id"):
        target_rating = _rating_or_404(data["rating_id"]).id
    elif data.get("handle"):
        target_user = _find_user(data["handle"]).id
    else:
        raise ApiError("report a verdict or a person", 400, "target_required")

    g.db.add(
        Report(
            reporter_id=g.user.id,
            target_rating_id=target_rating,
            target_user_id=target_user,
            reason=reason,
        )
    )
    g.db.flush()
    return jsonify(ok=True, filed=True)
