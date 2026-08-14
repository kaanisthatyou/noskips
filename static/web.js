/* ============ noskips on the web ============
 *
 * Deliberately small and dependency-free. The pages themselves are rendered
 * server-side and work without this file; everything here is the interactive
 * layer on top, talking to the same /v1 API the widget uses. One
 * implementation of signing up, one of claiming a name.
 */

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  let data = {};
  try {
    data = await res.json();
  } catch {
    /* a proxy error page, or an empty body — treated as a failure below */
  }
  return { ok: res.ok, status: res.status, data };
}

function say(el, text, kind) {
  if (!el) return;
  // remember what the element was wearing, so tagging it good/bad doesn't
  // strip the class that positions it
  if (el.dataset.base === undefined) el.dataset.base = el.className;
  el.textContent = text;
  el.className = `${el.dataset.base}${kind ? ` ${kind}` : ""}`;
}

// ------------------------------------------------------------ sign in / up ----
const authForm = $("auth-form");
if (authForm) {
  const msg = $("auth-msg");
  authForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const signup = authForm.dataset.mode === "signup";
    const button = authForm.querySelector("button");
    button.disabled = true;
    say(msg, "…");

    const { ok, data } = await api(`/v1/auth/${signup ? "signup" : "login"}`, {
      method: "POST",
      body: { email: $("email").value, password: $("password").value },
    });
    button.disabled = false;

    if (!ok) return say(msg, data.error || "that didn't work", "bad");
    if (signup && !data.me) {
      // the deliberately identical answer for an address that already exists
      return say(msg, "check your email to finish signing up.", "good");
    }
    location.href = data.me && !data.me.handle ? "/welcome" : authForm.dataset.next || "/";
  });
}

const forgot = $("forgot");
if (forgot) {
  forgot.addEventListener("click", async (e) => {
    e.preventDefault();
    const email = $("email").value;
    if (!email) return say($("auth-msg"), "type your email above first", "bad");
    await api("/v1/auth/forgot", { method: "POST", body: { email } });
    say($("auth-msg"), "if that address has an account, a reset link is on its way.", "good");
  });
}

// ---------------------------------------------------------------- handles ----
const handleForm = $("handle-form");
if (handleForm) {
  const input = $("handle");
  const msg = $("handle-msg");
  let checking;

  input.addEventListener("input", () => {
    clearTimeout(checking);
    const wanted = input.value.trim();
    if (wanted.length < 3) return say(msg, "");
    checking = setTimeout(async () => {
      const { data } = await api(`/v1/handle/available?handle=${encodeURIComponent(wanted)}`);
      if (data.available) say(msg, `@${wanted} is free ✦`, "good");
      else say(msg, data.suggestion ? `${data.reason} — @${data.suggestion} is free` : data.reason, "bad");
    }, 250);
  });

  handleForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const { ok, data } = await api("/v1/handle/claim", {
      method: "POST",
      body: { handle: input.value.trim() },
    });
    if (!ok) return say(msg, data.error || "that didn't work", "bad");
    location.href = handleForm.dataset.next || `/@${data.me.handle}`;
  });
}

// -------------------------------------------------------- verify / reset ----
const tokenCard = $("token-card");
if (tokenCard) {
  const msg = $("token-msg");
  const token = tokenCard.dataset.token;

  if (tokenCard.dataset.purpose === "verify") {
    (async () => {
      if (!token) return say(msg, "that link is missing its token.", "bad");
      const { ok, data } = await api("/v1/auth/verify", { method: "POST", body: { token } });
      if (!ok) return say(msg, data.error || "that link has expired.", "bad");
      say(msg, "confirmed ✦ taking you in…", "good");
      setTimeout(() => (location.href = data.me.handle ? "/feed" : "/welcome"), 900);
    })();
  }

  const resetForm = $("reset-form");
  if (resetForm) {
    resetForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const { ok, data } = await api("/v1/auth/reset", {
        method: "POST",
        body: { token, password: $("password").value },
      });
      if (!ok) return say(msg, data.error || "that didn't work", "bad");
      say(msg, "done ✦", "good");
      setTimeout(() => (location.href = data.me.handle ? "/feed" : "/welcome"), 700);
    });
  }
}

// --------------------------------------------------------------- settings ----
const profileForm = $("profile-form");
if (profileForm) {
  const msg = $("settings-msg");
  profileForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const { ok, data } = await api("/v1/me", {
      method: "PATCH",
      body: {
        display_name: $("display_name").value,
        bio: $("bio").value,
        is_private: $("is_private").checked,
        notes_private_default: $("notes_private_default").checked,
      },
    });
    say(msg, ok ? "saved ✦" : data.error || "that didn't work", ok ? "good" : "bad");
  });
}

document.querySelectorAll(".revoke-btn").forEach((button) =>
  button.addEventListener("click", async () => {
    button.disabled = true;
    const { ok } = await api(`/v1/devices/${button.dataset.device}`, { method: "DELETE" });
    if (ok) button.closest(".row").remove();
    else button.disabled = false;
  })
);

const signout = $("signout-btn");
if (signout) {
  signout.addEventListener("click", async () => {
    await api("/v1/auth/logout", { method: "POST" });
    location.href = "/";
  });
}

const del = $("delete-btn");
if (del) {
  del.addEventListener("click", async () => {
    // typing the handle is the confirmation; the server insists on it too
    const handle = prompt("this cannot be undone. type your handle to confirm:");
    if (!handle) return;
    const { ok, data } = await api("/v1/account", {
      method: "DELETE",
      body: { confirm: handle.replace(/^@/, "") },
    });
    if (!ok) return say($("danger-msg"), data.error || "that didn't match", "bad");
    location.href = "/";
  });
}

// ----------------------------------------------------------------- social ----
const followBtn = $("follow-btn");
if (followBtn) {
  followBtn.addEventListener("click", async () => {
    const following = followBtn.dataset.following === "true";
    followBtn.disabled = true;
    const { ok } = await api(`/v1/follow/${followBtn.dataset.handle}`, {
      method: following ? "DELETE" : "POST",
    });
    followBtn.disabled = false;
    if (!ok) return;
    followBtn.dataset.following = String(!following);
    followBtn.textContent = following ? "follow" : "following";
    followBtn.classList.toggle("on", !following);
  });
}

document.querySelectorAll(".report-btn").forEach((button) =>
  button.addEventListener("click", async () => {
    const reason = prompt("what's wrong with this one?");
    if (!reason) return;
    const { ok, data } = await api("/v1/report", {
      method: "POST",
      body: { rating_id: button.dataset.rating, reason },
    });
    button.textContent = ok ? "reported" : data.error || "couldn't file that";
    button.disabled = true;
  })
);

document.querySelectorAll(".cosign-btn").forEach((button) =>
  button.addEventListener("click", async () => {
    const done = button.classList.contains("on");
    button.disabled = true;
    const { ok, data } = await api(`/v1/cosign/${button.dataset.rating}`, {
      method: done ? "DELETE" : "POST",
    });
    button.disabled = false;
    if (!ok) return;
    button.classList.toggle("on", !done);
    button.textContent = done ? "cosign" : `cosigned · ${data.count}`;
  })
);

// ------------------------------------------------------------ stamping ----
// The widget's scale, on the web: ten pills and a light/just/strong modifier.
// A verdict entered here is the same object as one stamped in the widget, so
// the arithmetic has to match app.js exactly — light is −1/3, strong is +1/3.

const modOffset = { light: -1 / 3, just: 0, strong: 1 / 3 };
const valueOf = (n, mod) => Math.round((n + modOffset[mod]) * 100) / 100;
const labelOf = (n, mod) => (mod === "just" ? `${n}` : `${mod} ${n}`);

function readBack(value) {
  // reverse a stored value into pill + modifier, so restamping starts where
  // the reader actually left off rather than at a blank control
  const n = Math.min(10, Math.max(1, Math.round(value)));
  return { n, mod: value < n - 0.1 ? "light" : value > n + 0.1 ? "strong" : "just" };
}

function setUpStamp(form) {
  const state = form.dataset.value
    ? readBack(parseFloat(form.dataset.value))
    : { n: null, mod: "just" };
  const standalone = form.dataset.standalone === "true";
  const reading = form.querySelector(".stamp-reading");
  const msg = form.querySelector(".stamp-msg");

  function render() {
    form.querySelectorAll(".pill").forEach((p) =>
      p.classList.toggle("on", Number(p.dataset.n) === state.n)
    );
    form.querySelectorAll(".mod").forEach((m) => {
      m.classList.toggle("active", m.dataset.mod === state.mod);
      // the scale tops out at 10; there is no stronger than the top
      m.disabled = m.dataset.mod === "strong" && state.n === 10;
    });
    reading.textContent =
      state.n == null ? "pick a number" : `${labelOf(state.n, state.mod)} (${valueOf(state.n, state.mod)})`;
  }

  form.querySelectorAll(".pill").forEach((p) =>
    p.addEventListener("click", () => {
      state.n = Number(p.dataset.n);
      if (state.n === 10 && state.mod === "strong") state.mod = "just";
      render();
    })
  );

  form.querySelectorAll(".mod").forEach((m) =>
    m.addEventListener("click", () => {
      if (m.disabled) return;
      state.mod = m.dataset.mod;
      render();
    })
  );

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.n == null) return say(msg, "pick a number first", "bad");

    // the standalone page carries the track in its own fields; a row on an
    // album page already knows exactly which song it is
    const what = standalone
      ? {
          artist: $("s-artist").value.trim(),
          album: $("s-album").value.trim(),
          title: $("s-title").value.trim(),
        }
      : { artist: form.dataset.artist, album: form.dataset.album, title: form.dataset.title };

    if (!what.title) return say(msg, "a song needs a title", "bad");

    const save = form.querySelector(".stamp-save");
    save.disabled = true;
    say(msg, "…");

    const { ok, data } = await api("/v1/sync", {
      method: "POST",
      body: {
        ops: [
          {
            op: "rate",
            ...what,
            value: valueOf(state.n, state.mod),
            label: labelOf(state.n, state.mod),
            note: form.querySelector(".stamp-note").value.trim(),
            is_public: form.querySelector(".stamp-public").checked,
            note_public: form.querySelector(".stamp-note-public").checked,
            // keep the widget's revision, not one past it: whichever verdict
            // was written last should win, and the server settles ties by time
            rev: Number(form.dataset.rev || 1),
          },
        ],
      },
    });
    save.disabled = false;

    if (!ok) return say(msg, data.error || "that didn't work", "bad");
    const result = (data.results || [])[0] || {};
    if (result.status !== "stored") {
      return say(msg, result.error || "the server already has a newer verdict", "bad");
    }

    if (standalone) {
      say(msg, result.first_press ? "first press ✦ taking you there…" : "stamped ✦", "good");
      return setTimeout(() => (location.href = `/album/${result.album_key}`), 700);
    }

    say(msg, result.first_press ? "first press ✦" : "stamped ✦", "good");
    save.textContent = "restamp it";

    // the row above now says something different about the world
    const slot = form.closest(".stamp-slot");
    const row = slot.previousElementSibling;
    if (row) {
      row.querySelector(".t-avg").textContent = Number(result.average).toFixed(1);
      row.querySelector(".t-count").textContent =
        `${result.count} verdict${result.count === 1 ? "" : "s"}`;
      const toggle = row.querySelector(".stamp-toggle");
      if (toggle) toggle.textContent = `yours · ${valueOf(state.n, state.mod).toFixed(1)}`;
    }
  });

  render();
}

document.querySelectorAll(".stamp-control").forEach(setUpStamp);

document.querySelectorAll(".stamp-toggle").forEach((button) =>
  button.addEventListener("click", () => {
    const slot = $(button.dataset.for);
    const form = slot.querySelector(".stamp-control");
    form.hidden = !form.hidden;
  })
);
