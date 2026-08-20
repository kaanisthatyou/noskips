"""The widget's half of syncing.

Three promises shape every line of this file:

1. **The rate button never waits on the network.** Rating writes to the local
   JSON and appends to an outbox; a background thread deals with the internet on
   its own time. Offline, the queue simply grows.
2. **Nothing leaves the machine until you ask.** No token, no sync toggle, no
   traffic — not even the read that fetches what other people thought, because
   asking "what does the world think of this track?" tells the world what you're
   playing.
3. **The local file stays the source of truth.** `data/ratings.json` keeps its
   shape and remains grep-able and portable. The server is a copy, not the
   original.

State lives in two small files next to it:

    data/session.json   device token, handle, whether sync is on
    data/outbox.json    ops waiting to go out
"""

import json
import os
import platform
import secrets
import threading
import time
from datetime import datetime, timezone

import requests

from server.envcompat import env
from server.resolve import identify

# The deploy, and what every downloaded exe will talk to — nobody who installs
# it sets RATEIFY_SERVER, so this literal is the shipped behaviour. The host is
# still the old project name: the rename to rateify stopped at the code, because
# renaming the Vercel project changes this hostname and the Google and Discord
# OAuth redirect URIs are registered against it. Change the project, update both
# consoles, then change this line — in that order, before building a release.
DEFAULT_SERVER = env("SERVER", "https://noskips-navy.vercel.app")

TICK = 2.0  # seconds between worker passes
DRAIN_EVERY = 10  # ticks — so a batch goes out about every 20s
SHARED_TTL = 900  # seconds to trust a cached community average
HTTP_TIMEOUT = 10


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def _write_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic: a crash mid-write can't corrupt the queue


class SyncEngine:
    def __init__(self, data_dir, base_url=None, app_version="0", library_provider=None):
        self.base_url = (base_url or DEFAULT_SERVER).rstrip("/")
        self.app_version = app_version
        # called once, just after pairing, to lift an existing shelf up to the
        # account. ratings.json belongs to app.py, so it hands us a reader
        # rather than us reaching into its file.
        self.library_provider = library_provider
        self.session_file = data_dir / "session.json"
        self.outbox_file = data_dir / "outbox.json"

        self._lock = threading.Lock()
        self._session = _read_json(self.session_file, {})
        self._outbox = _read_json(self.outbox_file, [])
        self._shared = {}  # work_key -> (fetched_at, payload or None)
        self._wanted = None  # work_key the UI is currently showing
        self._pairing = None  # {nonce, code, url, started}
        self._last_error = None
        self._last_sync = self._session.get("last_sync")
        self._http = requests.Session()
        self._http.headers["User-Agent"] = f"rateify/{app_version}"

    # ------------------------------------------------------------ session ----

    @property
    def token(self):
        return self._session.get("device_token")

    @property
    def signed_in(self):
        return bool(self.token)

    @property
    def enabled(self):
        """Signed in is not the same as syncing. You can pair and still keep
        everything local until you say otherwise."""
        return self.signed_in and self._session.get("sync_on", True)

    def _save_session(self):
        _write_json(self.session_file, self._session)

    def status(self):
        with self._lock:
            return {
                "signed_in": self.signed_in,
                "sync_on": self.enabled,
                "handle": self._session.get("handle"),
                "unsent": len(self._outbox),
                "last_sync": self._last_sync,
                "last_error": self._last_error,
                "pairing": (
                    {"code": self._pairing["code"], "url": self._pairing["url"]}
                    if self._pairing
                    else None
                ),
                "server": self.base_url,
            }

    def set_enabled(self, on):
        with self._lock:
            self._session["sync_on"] = bool(on)
            self._save_session()

    def sign_out(self):
        """Forget the account. Ratings stay — they're yours and they're local."""
        with self._lock:
            token = self.token
            self._session = {}
            self._outbox = []
            self._shared.clear()
            self._pairing = None
            self._save_session()
            _write_json(self.outbox_file, [])
        if token:
            try:  # best effort; being offline must not stop you signing out
                self._post("/v1/pair/unlink", {}, token=token)
            except requests.RequestException:
                pass

    # -------------------------------------------------------------- pairing ----

    def begin_pairing(self):
        nonce = secrets.token_urlsafe(32)
        body = {
            "device_nonce": nonce,
            "device_name": platform.node() or "a windows pc",
            "app_version": self.app_version,
        }
        data = self._post("/v1/pair/start", body)
        with self._lock:
            self._pairing = {
                "nonce": nonce,
                "code": data["code"],
                "url": data["url"],
                "started": time.time(),
            }
            self._last_error = None
        return {"code": data["code"], "url": data["url"]}

    def cancel_pairing(self):
        with self._lock:
            self._pairing = None

    def _poll_pairing(self):
        with self._lock:
            pairing = dict(self._pairing) if self._pairing else None
        if pairing is None:
            return
        if time.time() - pairing["started"] > 600:
            with self._lock:
                self._pairing = None
                self._last_error = "that code expired — try again"
            return

        data = self._post("/v1/pair/poll", {"device_nonce": pairing["nonce"]})
        if data.get("pending", True):
            return

        token = data["device_token"]
        with self._lock:
            self._session["device_token"] = token
            self._session.setdefault("sync_on", True)
            self._pairing = None
            self._save_session()
        self._refresh_handle()
        self._backfill()

    def _backfill(self):
        """Lift the shelf they already have up to the freshly linked account.

        Every rating made before signing in — which for most people is all of
        them — goes out as an ordinary op. Provenance is deliberately *not*
        'live': we genuinely can't prove we watched those play, and the whole
        value of that mark is that it's never claimed loosely.
        """
        if self.library_provider is None:
            return
        try:
            ops = self.library_provider()
        except Exception as exc:
            return self._log(exc)
        for op in ops:
            self.enqueue({**op, "provenance": "web"})

    def _refresh_handle(self):
        try:
            me = self._get("/v1/me")["me"]
        except (requests.RequestException, KeyError, ValueError):
            return
        with self._lock:
            self._session["handle"] = me.get("handle")
            self._session["needs_handle"] = me.get("needs_handle", False)
            self._save_session()

    # --------------------------------------------------------------- outbox ----

    def enqueue(self, op):
        """Queue an op and return immediately. Called on the request thread, so
        it does no I/O beyond one small local write.

        A signed-out widget queues nothing at all — there's no account for it to
        go to, and letting the outbox shadow the entire library for someone who
        never signs in would be a second copy of their shelf for no reason.
        Signing in backfills instead.
        """
        if not self.signed_in:
            return
        with self._lock:
            key = (op.get("artist"), op.get("album"), op.get("title"))
            # only the newest verdict per track matters; drop any it supersedes
            self._outbox = [
                o for o in self._outbox
                if (o.get("artist"), o.get("album"), o.get("title")) != key
            ]
            self._outbox.append(op)
            _write_json(self.outbox_file, self._outbox)
            # our own opinion changed, so the cached community figure is stale
            ident = identify(op.get("artist", ""), op.get("album", ""), op.get("title", ""))
            self._shared.pop(ident.work_key, None)

    def _drain(self):
        with self._lock:
            if not self._outbox or not self.enabled:
                return
            batch = self._outbox[:200]

        try:
            data = self._post("/v1/sync", {"ops": batch})
        except requests.RequestException as exc:
            with self._lock:
                self._last_error = "offline — your ratings are queued"
            return self._log(exc)

        sent = {(o.get("artist"), o.get("album"), o.get("title")) for o in batch}
        with self._lock:
            # every answered op is finished, including rejections: a malformed
            # op will never succeed, and retrying it forever would wedge the queue
            self._outbox = [
                o for o in self._outbox
                if (o.get("artist"), o.get("album"), o.get("title")) not in sent
            ]
            _write_json(self.outbox_file, self._outbox)
            self._last_sync = _now_iso()
            self._last_error = None
            self._session["last_sync"] = self._last_sync
            self._save_session()
            for result in data.get("results", []):
                if result.get("work_key"):
                    self._shared[result["work_key"]] = (
                        time.time(),
                        {
                            "average": result.get("average"),
                            "count": result.get("count"),
                            "exists": True,
                        },
                    )

    # --------------------------------------------------------------- shared ----

    def shared_for(self, artist, album, title):
        """What everyone else thought — from cache, never blocking.

        Returns None when we don't know yet (or aren't allowed to ask), and the
        UI simply doesn't show a community line until we do.
        """
        if not self.enabled or not title:
            return None
        key = identify(artist, album, title).work_key
        with self._lock:
            self._wanted = key
            hit = self._shared.get(key)
        if hit and time.time() - hit[0] < SHARED_TTL:
            return hit[1]
        return None

    def _fetch_shared(self):
        with self._lock:
            key = self._wanted
            hit = self._shared.get(key) if key else None
        if not key or not self.enabled:
            return
        if hit and time.time() - hit[0] < SHARED_TTL:
            return

        try:
            response = self._http.get(
                f"{self.base_url}/v1/works/{key}",
                headers=self._auth_headers(),
                timeout=HTTP_TIMEOUT,
            )
            if response.status_code == 404:
                # nobody has ever rated this — the good case
                payload = {"exists": False, "first_press": True}
            else:
                response.raise_for_status()
                work = response.json()["work"]
                payload = {
                    "exists": True,
                    "average": work["average"],
                    "count": work["count"],
                    "first_press_by": (work.get("first_press") or {}).get("handle"),
                }
        except (requests.RequestException, KeyError, ValueError) as exc:
            return self._log(exc)

        with self._lock:
            self._shared[key] = (time.time(), payload)

    # ----------------------------------------------------------------- http ----

    def _auth_headers(self, token=None):
        token = token or self.token
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _post(self, path, body, token=None):
        response = self._http.post(
            f"{self.base_url}{path}",
            json=body,
            headers=self._auth_headers(token),
            timeout=HTTP_TIMEOUT,
        )
        if response.status_code == 401 and self.signed_in:
            self._handle_revoked()
        response.raise_for_status()
        return response.json()

    def _get(self, path):
        response = self._http.get(
            f"{self.base_url}{path}", headers=self._auth_headers(), timeout=HTTP_TIMEOUT
        )
        if response.status_code == 401 and self.signed_in:
            self._handle_revoked()
        response.raise_for_status()
        return response.json()

    def _handle_revoked(self):
        """The device was revoked from the web. Forget the token, keep the
        queue — they may pair again and everything still goes out."""
        with self._lock:
            self._session.pop("device_token", None)
            self._session.pop("handle", None)
            self._last_error = "this device was unlinked"
            self._save_session()

    def _log(self, exc):
        # the widget has no console in the frozen build; failures are surfaced
        # through status() instead, and this stays quiet on purpose
        return None

    # --------------------------------------------------------------- worker ----

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="rateify-sync").start()
        return self

    def _loop(self):
        ticks = 0
        while True:
            try:
                if self._pairing is not None:
                    self._poll_pairing()
                elif self.enabled:
                    self._fetch_shared()
                    if ticks % DRAIN_EVERY == 0:
                        self._drain()
            except Exception as exc:  # a sync problem must never kill the widget
                self._log(exc)
            ticks += 1
            time.sleep(TICK)
