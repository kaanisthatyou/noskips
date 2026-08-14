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
  el.textContent = text;
  el.className = `msg${kind ? ` ${kind}` : ""}`;
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
