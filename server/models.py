"""The shared world's schema.

Design notes worth keeping in your head while reading:

* **There is no catalog.** No table of songs seeded from anywhere. A ``Work``
  row comes into existence only inside the transaction that stores its first
  rating, and it is deleted again when its last rating goes. That is the one
  rule the whole product is built on, and it lives in store.py.

* **Portable types only** — ``Uuid``, ``JSON``, no CITEXT, no server-side
  triggers. Postgres in production, SQLite in the tests, same DDL. Case
  insensitivity is done with explicit ``*_ci`` columns instead of collations so
  both engines agree on what "already taken" means.

* **Aggregates are denormalized** onto ``Work`` (``rating_count`` /
  ``rating_sum``) and maintained in the same transaction as the rating itself,
  so an album page is one indexed read rather than a scan.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid():
    return uuid.uuid4()


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ------------------------------------------------------------------ people ----


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)

    # handle_ci is the uniqueness authority; handle keeps the casing they chose
    handle: Mapped[str | None] = mapped_column(String(20))
    handle_ci: Mapped[str | None] = mapped_column(String(20), unique=True)
    handle_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    display_name: Mapped[str | None] = mapped_column(String(40))
    bio: Mapped[str | None] = mapped_column(String(200))
    # the avatar is generated from this, so there are no uploads to moderate
    avatar_seed: Mapped[str] = mapped_column(String(32), default=lambda: uuid.uuid4().hex[:16])

    # nullable: an account created purely through Google/Discord has no password
    email: Mapped[str | None] = mapped_column(String(254))
    email_ci: Mapped[str | None] = mapped_column(String(254), unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(String(255))

    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    notes_private_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    identities: Mapped[list["Identity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    devices: Mapped[list["Device"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    ratings: Mapped[list["Rating"]] = relationship(back_populates="user")

    @property
    def is_verified(self):
        return self.email_verified_at is not None or bool(self.identities)


class Identity(Base):
    """A linked Google or Discord account."""

    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("provider", "provider_uid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(16))  # 'google' | 'discord'
    provider_uid: Mapped[str] = mapped_column(String(64))
    email_at_provider: Mapped[str | None] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="identities")


class EmailToken(Base):
    """Single-use verification / password-reset tokens. Only the hash is kept,
    so a database leak doesn't hand out account takeovers."""

    __tablename__ = "email_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(16))  # 'verify' | 'reset'
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ----------------------------------------------------------------- devices ----


class Device(Base):
    """A paired widget. The token is opaque and stored hashed; the exe holds the
    only copy of the plaintext, and the user can revoke any device from the web."""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str | None] = mapped_column(String(60))
    app_version: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="devices")


class Pairing(Base):
    """A short-lived code shown in the widget and typed/clicked in the browser.

    This is what keeps OAuth secrets out of the exe entirely: the login happens
    in a real browser, and the widget only ever learns the resulting token.
    """

    __tablename__ = "pairings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    device_nonce_hash: Mapped[str] = mapped_column(String(64))
    device_name: Mapped[str | None] = mapped_column(String(60))
    app_version: Mapped[str | None] = mapped_column(String(20))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # the issued token, held exactly once for the widget's next poll
    device_token: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ------------------------------------------------------------------- works ----


class Work(Base):
    """One song, as agreed on by everyone who has rated it.

    Created only by store.upsert_rating; destroyed by store.delete_rating when
    the last rating goes. Nothing else may insert into this table.
    """

    __tablename__ = "works"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    work_key: Mapped[str] = mapped_column(String(20), unique=True)
    album_key: Mapped[str] = mapped_column(String(20), index=True)

    # normalized, for matching
    norm_artist: Mapped[str] = mapped_column(String(300))
    norm_album: Mapped[str] = mapped_column(String(300))
    norm_title: Mapped[str] = mapped_column(String(300))
    # as first seen, for showing to humans
    display_artist: Mapped[str] = mapped_column(String(300))
    display_album: Mapped[str] = mapped_column(String(300))
    display_title: Mapped[str] = mapped_column(String(300))
    feat: Mapped[list | None] = mapped_column(JSON)

    # filled in later by the MusicBrainz resolver; never required
    mbid_recording: Mapped[str | None] = mapped_column(String(36), index=True)
    mbid_release_group: Mapped[str | None] = mapped_column(String(36))
    cover_url: Mapped[str | None] = mapped_column(String(300))
    pending_resolution: Mapped[bool] = mapped_column(Boolean, default=True)
    # when two works turn out to be the same recording, the loser points here
    merged_into: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("works.id"))

    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    rating_sum: Mapped[float] = mapped_column(Numeric(10, 2), default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ratings: Mapped[list["Rating"]] = relationship(
        back_populates="work", cascade="all, delete-orphan"
    )

    @property
    def average(self):
        return round(float(self.rating_sum) / self.rating_count, 2) if self.rating_count else None


class Rating(Base):
    """One person's verdict on one song."""

    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "work_id"),
        Index("ix_ratings_user_recent", "user_id", "rated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"))

    # the widget's scale: 1..10 shifted by -1/3, 0 or +1/3 for light/just/strong
    value: Mapped[float] = mapped_column(Numeric(4, 2))
    label: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    # 240-point amplitude envelope frozen at the moment of stamping (base64)
    trace: Mapped[str | None] = mapped_column(Text)

    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    note_public: Mapped[bool] = mapped_column(Boolean, default=True)
    # 'live'  — stamped in the widget while the track was actually playing
    # 'web'   — entered from memory on the site
    provenance: Mapped[str] = mapped_column(String(8), default="web")
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))

    # the client's monotonic revision for this track, for last-write-wins sync
    rev: Mapped[int] = mapped_column(Integer, default=1)
    rated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="ratings")
    work: Mapped[Work] = relationship(back_populates="ratings")
    cosigns: Mapped[list["Cosign"]] = relationship(
        back_populates="rating", cascade="all, delete-orphan"
    )


# ------------------------------------------------------------------ social ----


class Cosign(Base):
    """You countersign someone else's stamp. The only reaction there is."""

    __tablename__ = "cosigns"
    __table_args__ = (UniqueConstraint("user_id", "rating_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rating_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ratings.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    rating: Mapped[Rating] = relationship(back_populates="cosigns")


class Follow(Base):
    __tablename__ = "follows"
    __table_args__ = (UniqueConstraint("follower_id", "followee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    follower_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    followee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Block(Base):
    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("blocker_id", "blocked_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    blocker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    blocked_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RateLimit(Base):
    """A fixed-window counter, in the database on purpose.

    Serverless means every request may run in a fresh process, so an in-memory
    limiter would reset constantly and protect nothing. Redis would work and
    would also be the only paid thing in the stack — a tiny table costs nothing
    and is plenty at this scale.
    """

    __tablename__ = "rate_limits"
    __table_args__ = (UniqueConstraint("bucket", "window_start"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    bucket: Mapped[str] = mapped_column(String(160), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(Integer, default=0)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    reporter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    target_rating_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ratings.id", ondelete="CASCADE")
    )
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
