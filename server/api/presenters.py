"""Turning models into JSON.

The only interesting rule in here is that privacy is applied at serialization
time, in one place: a note marked private is stripped for everyone except its
author, and a private profile answers with just enough to say "this exists but
isn't yours to read". Scattering that logic across handlers is how a social app
leaks the one note somebody really didn't want public.
"""


def _iso(dt):
    return dt.isoformat() if dt else None


def user_brief(user):
    if user is None:
        return None
    return {
        "handle": user.handle,
        "display_name": user.display_name or user.handle,
        "avatar_seed": user.avatar_seed,
    }


def me(user, device=None):
    return {
        "id": str(user.id),
        "handle": user.handle,
        "display_name": user.display_name,
        "bio": user.bio,
        "avatar_seed": user.avatar_seed,
        "email": user.email,
        "email_verified": user.email_verified_at is not None,
        "is_private": user.is_private,
        "notes_private_default": user.notes_private_default,
        "needs_handle": not user.handle_ci,
        "created_at": _iso(user.created_at),
        "device": {"id": str(device.id), "name": device.name} if device else None,
    }


def work(w, first_presser=None, viewer_rating=None):
    return {
        "work_key": w.work_key,
        "album_key": w.album_key,
        "artist": w.display_artist,
        "album": w.display_album,
        "title": w.display_title,
        "feat": w.feat or [],
        "cover_url": w.cover_url,
        "average": w.average,
        "count": w.rating_count,
        "first_press": user_brief(first_presser),
        "yours": rating(viewer_rating, viewer=viewer_rating.user if viewer_rating else None)
        if viewer_rating
        else None,
    }


def rating(r, viewer=None, include_work=False):
    """One verdict. ``viewer`` is the person reading, so we know whether the
    note is theirs to see."""
    if r is None:
        return None
    mine = viewer is not None and r.user_id == viewer.id
    show_note = r.note_public or mine

    out = {
        "id": str(r.id),
        "value": float(r.value),
        "label": r.label,
        "note": r.note if show_note else None,
        "note_hidden": bool(r.note and not show_note),
        "trace": r.trace,
        "live": r.provenance == "live",
        "rated_at": _iso(r.rated_at),
        "cosigns": len(r.cosigns),
        "by": user_brief(r.user),
        "mine": mine,
    }
    if include_work and r.work is not None:
        out["work"] = {
            "work_key": r.work.work_key,
            "album_key": r.work.album_key,
            "artist": r.work.display_artist,
            "album": r.work.display_album,
            "title": r.work.display_title,
            "cover_url": r.work.cover_url,
            "average": r.work.average,
            "count": r.work.rating_count,
        }
    return out


def profile(user, stats, viewer=None, visible=True):
    out = {
        "handle": user.handle,
        "display_name": user.display_name or user.handle,
        "bio": user.bio,
        "avatar_seed": user.avatar_seed,
        "joined": _iso(user.created_at),
        "is_private": user.is_private,
        "visible": visible,
        "is_you": viewer is not None and viewer.id == user.id,
    }
    if visible:
        out.update(stats)
    return out
