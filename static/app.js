/* ============ noskips frontend ============ */

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- state ----
let now = null;            // last /api/now snapshot
let trackKey = "";         // artist:::album:::title of the loaded track
let sel = { n: null, mod: "just" };
let shelfDirty = true;     // refetch library next time the shelf opens

// -------------------------------------------------------------- helpers ----
const fmt = (s) => {
  s = Math.max(0, Math.floor(s));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

const modWord = (mod) => (mod === "light" ? t("mod_light") : t("mod_strong"));
const labelOf = (n, mod) => (mod === "just" ? `${n}` : `${modWord(mod)} ${n}`);
const valueOf = (n, mod) =>
  Math.round((n + (mod === "light" ? -1 / 3 : mod === "strong" ? 1 / 3 : 0)) * 100) / 100;

// ------------------------------------------------------------------ i18n ----
const I18N = {
  en: {
    tab_now: "now", tab_shelf: "shelf", tab_settings: "settings",
    tab_hint: "tap again to tuck the widget away",
    min_title: "minimize", close_title: "close",
    prev_title: "previous", playpause_title: "play / pause", next_title: "next",
    empty_now_big: "nothing spinning",
    empty_now_small: "put a record on in spotify & it shows up here ♪",
    rate_track: "rate this track", edit_suffix: " · edit",
    pick_number: "pick a number…",
    mod_light: "light", mod_just: "just", mod_strong: "strong",
    note_placeholder: "scribble a note… (why this number?)",
    stamp_it: "✦ stamp it", restamp_it: "✦ re-stamp it",
    stamped_avg: "✦ stamped — album avg {avg}",
    stamp_rated: "RATED",
    shelf_empty_big: "bare shelves",
    shelf_empty_small: "no verdicts yet — go judge something",
    single_album: "(single)",
    tracks_rated: "{count} track(s) rated",
    album_avg_line: "{artist} — album avg {avg}",
    remove_rating: "remove rating",
    settings_lang_label: "language",
    settings_theme_label: "color theme",
    settings_account_label: "account",
    settings_skin_label: "tucked-away look",
    kind_video: "a video — this one stays on this pc",
    shelf_videos_label: "videos · kept on this pc",
    videos_rated: "{count} video(s) rated",
    listen_on: "listening", listen_off: "listen to the sound",
    listen_hint: "reads what your speakers are playing, so the bars are real and every stamp keeps a trace of the moment. off by default.",
    priv_public: "shared", priv_public_off: "private",
    priv_note: "note shared", priv_note_off: "note private",
    acct_signed_out: "not signed in — everything stays on this pc",
    acct_pair: "link this pc",
    acct_pairing: "code {code} — finish in your browser",
    acct_cancel: "cancel",
    acct_signout: "sign out",
    acct_as: "signed in as @{handle}",
    acct_no_handle: "signed in — claim a handle on the site",
    acct_sync_on: "syncing", acct_sync_off: "sync paused",
    acct_unsent: "{n} waiting to send",
    acct_synced: "all sent",
    shared_first: "nobody has stamped this — be the first press ✦",
    shared_avg: "{count} verdicts · avg {avg}",
    shared_first_by: "first pressed by @{handle}",
  },
  tr: {
    tab_now: "şimdi", tab_shelf: "raf", tab_settings: "ayarlar",
    tab_hint: "widget'ı gizlemek için tekrar dokun",
    min_title: "küçült", close_title: "kapat",
    prev_title: "önceki", playpause_title: "oynat / duraklat", next_title: "sonraki",
    empty_now_big: "hiçbir şey çalmıyor",
    empty_now_small: "spotify'da bir şey çal, burada görünsün ♪",
    rate_track: "bu parçayı puanla", edit_suffix: " · düzenle",
    pick_number: "bir sayı seç…",
    mod_light: "hafif", mod_just: "tam", mod_strong: "güçlü",
    note_placeholder: "bir not karala… (neden bu sayı?)",
    stamp_it: "✦ damgala", restamp_it: "✦ yeniden damgala",
    stamped_avg: "✦ damgalandı — albüm ort. {avg}",
    stamp_rated: "PUANLANDI",
    shelf_empty_big: "raflar boş",
    shelf_empty_small: "henüz hüküm yok — git bir şeyi yargıla",
    single_album: "(tekli)",
    tracks_rated: "{count} parça puanlandı",
    album_avg_line: "{artist} — albüm ort. {avg}",
    remove_rating: "puanı kaldır",
    settings_lang_label: "dil",
    settings_theme_label: "renk teması",
    settings_account_label: "hesap",
    settings_skin_label: "gizli görünüm",
    kind_video: "video — bu bilgisayarda kalır",
    shelf_videos_label: "videolar · bu bilgisayarda",
    videos_rated: "{count} video puanlandı",
    listen_on: "dinliyor", listen_off: "sesi dinle",
    listen_hint: "hoparlörden çıkanı okur; çubuklar gerçek olur ve her damga o anın izini saklar. varsayılan olarak kapalı.",
    priv_public: "paylaşımda", priv_public_off: "gizli",
    priv_note: "not paylaşımda", priv_note_off: "not gizli",
    acct_signed_out: "giriş yapılmadı — her şey bu bilgisayarda kalıyor",
    acct_pair: "bu bilgisayarı bağla",
    acct_pairing: "kod {code} — tarayıcında tamamla",
    acct_cancel: "iptal",
    acct_signout: "çıkış yap",
    acct_as: "@{handle} olarak girildi",
    acct_no_handle: "girildi — sitede bir kullanıcı adı al",
    acct_sync_on: "eşitleniyor", acct_sync_off: "eşitleme duraklatıldı",
    acct_unsent: "{n} tanesi gönderilmeyi bekliyor",
    acct_synced: "hepsi gönderildi",
    shared_first: "bunu kimse damgalamamış — ilk baskı sen ol ✦",
    shared_avg: "{count} hüküm · ort. {avg}",
    shared_first_by: "ilk baskı: @{handle}",
  },
  es: {
    tab_now: "ahora", tab_shelf: "estante", tab_settings: "ajustes",
    tab_hint: "toca de nuevo para ocultar el widget",
    min_title: "minimizar", close_title: "cerrar",
    prev_title: "anterior", playpause_title: "reproducir / pausar", next_title: "siguiente",
    empty_now_big: "nada sonando",
    empty_now_small: "pon algo en spotify y aparecerá aquí ♪",
    rate_track: "califica esta canción", edit_suffix: " · editar",
    pick_number: "elige un número…",
    mod_light: "suave", mod_just: "justo", mod_strong: "fuerte",
    note_placeholder: "escribe una nota… (¿por qué este número?)",
    stamp_it: "✦ sellarlo", restamp_it: "✦ volver a sellarlo",
    stamped_avg: "✦ sellado — promedio del álbum {avg}",
    stamp_rated: "SELLADO",
    shelf_empty_big: "estantes vacíos",
    shelf_empty_small: "aún sin veredictos — ve a juzgar algo",
    single_album: "(sencillo)",
    tracks_rated: "{count} canción(es) calificada(s)",
    album_avg_line: "{artist} — promedio del álbum {avg}",
    remove_rating: "eliminar calificación",
    settings_lang_label: "idioma",
    settings_theme_label: "tema de color",
    settings_account_label: "cuenta",
    settings_skin_label: "aspecto recogido",
    kind_video: "un vídeo — este se queda en este pc",
    shelf_videos_label: "vídeos · guardados en este pc",
    videos_rated: "{count} vídeo(s) calificado(s)",
    listen_on: "escuchando", listen_off: "escuchar el sonido",
    listen_hint: "lee lo que suena en tus altavoces, así las barras son reales y cada sello guarda un rastro del momento. desactivado por defecto.",
    priv_public: "compartido", priv_public_off: "privado",
    priv_note: "nota compartida", priv_note_off: "nota privada",
    acct_signed_out: "sin sesión — todo se queda en este pc",
    acct_pair: "vincular este pc",
    acct_pairing: "código {code} — termina en tu navegador",
    acct_cancel: "cancelar",
    acct_signout: "cerrar sesión",
    acct_as: "conectado como @{handle}",
    acct_no_handle: "conectado — elige un usuario en el sitio",
    acct_sync_on: "sincronizando", acct_sync_off: "sincronización en pausa",
    acct_unsent: "{n} por enviar",
    acct_synced: "todo enviado",
    shared_first: "nadie ha sellado esto — sé la primera prensa ✦",
    shared_avg: "{count} veredictos · promedio {avg}",
    shared_first_by: "primera prensa de @{handle}",
  },
  ja: {
    tab_now: "再生中", tab_shelf: "棚", tab_settings: "設定",
    tab_hint: "もう一度タップしてウィジェットを隠す",
    min_title: "最小化", close_title: "閉じる",
    prev_title: "前へ", playpause_title: "再生 / 一時停止", next_title: "次へ",
    empty_now_big: "何も再生されていません",
    empty_now_small: "Spotifyで何か再生すると、ここに表示されます ♪",
    rate_track: "この曲を評価する", edit_suffix: "・編集",
    pick_number: "数字を選んでください…",
    mod_light: "弱め", mod_just: "ちょうど", mod_strong: "強め",
    note_placeholder: "メモを書く…（なぜこの数字？）",
    stamp_it: "✦ 評価する", restamp_it: "✦ 再評価する",
    stamped_avg: "✦ 評価完了 — アルバム平均 {avg}",
    stamp_rated: "評価済み",
    shelf_empty_big: "棚は空です",
    shelf_empty_small: "まだ評価がありません — 何か評価しに行こう",
    single_album: "（シングル）",
    tracks_rated: "{count}曲評価済み",
    album_avg_line: "{artist} — アルバム平均 {avg}",
    remove_rating: "評価を削除",
    settings_lang_label: "言語",
    settings_theme_label: "カラーテーマ",
    settings_account_label: "アカウント",
    settings_skin_label: "折りたたみ時の見た目",
    kind_video: "動画 — これはこのPCに残ります",
    shelf_videos_label: "動画・このPCに保存",
    videos_rated: "{count}本の動画を評価済み",
    listen_on: "聴いています", listen_off: "音を聴く",
    listen_hint: "スピーカーの音を読み取ります。バーが本物になり、評価にはその瞬間の波形が残ります。既定はオフです。",
    priv_public: "共有中", priv_public_off: "非公開",
    priv_note: "メモも共有", priv_note_off: "メモは非公開",
    acct_signed_out: "未ログイン — すべてこのPCの中だけです",
    acct_pair: "このPCを連携する",
    acct_pairing: "コード {code} — ブラウザで完了してください",
    acct_cancel: "キャンセル",
    acct_signout: "ログアウト",
    acct_as: "@{handle} としてログイン中",
    acct_no_handle: "ログイン済み — サイトでハンドルを取得してください",
    acct_sync_on: "同期中", acct_sync_off: "同期を一時停止中",
    acct_unsent: "{n}件が送信待ち",
    acct_synced: "すべて送信済み",
    shared_first: "まだ誰も評価していません — 最初の一枚になろう ✦",
    shared_avg: "{count}件の評価・平均 {avg}",
    shared_first_by: "最初の評価: @{handle}",
  },
  zh: {
    tab_now: "正在播放", tab_shelf: "唱片架", tab_settings: "设置",
    tab_hint: "再次点击以收起小组件",
    min_title: "最小化", close_title: "关闭",
    prev_title: "上一首", playpause_title: "播放 / 暂停", next_title: "下一首",
    empty_now_big: "没有正在播放的内容",
    empty_now_small: "在spotify播放点什么，就会显示在这里 ♪",
    rate_track: "为这首歌评分", edit_suffix: " · 编辑",
    pick_number: "选择一个数字…",
    mod_light: "偏轻", mod_just: "刚好", mod_strong: "偏强",
    note_placeholder: "写点笔记…（为什么打这个分？）",
    stamp_it: "✦ 盖章", restamp_it: "✦ 重新盖章",
    stamped_avg: "✦ 已盖章 — 专辑均分 {avg}",
    stamp_rated: "已评分",
    shelf_empty_big: "空空如也",
    shelf_empty_small: "还没有评价 — 去评一评吧",
    single_album: "（单曲）",
    tracks_rated: "已评{count}首",
    album_avg_line: "{artist} — 专辑均分 {avg}",
    remove_rating: "删除评分",
    settings_lang_label: "语言",
    settings_theme_label: "配色主题",
    settings_account_label: "账号",
    settings_skin_label: "收起时的样子",
    kind_video: "视频 — 这条只留在本机",
    shelf_videos_label: "视频 · 保存在本机",
    videos_rated: "已评{count}个视频",
    listen_on: "正在聆听", listen_off: "聆听声音",
    listen_hint: "读取扬声器正在播放的声音，让波形是真实的，并为每次盖章留下当时的痕迹。默认关闭。",
    priv_public: "已共享", priv_public_off: "私密",
    priv_note: "笔记已共享", priv_note_off: "笔记私密",
    acct_signed_out: "未登录 — 所有内容都留在这台电脑上",
    acct_pair: "关联这台电脑",
    acct_pairing: "验证码 {code} — 请在浏览器中完成",
    acct_cancel: "取消",
    acct_signout: "退出登录",
    acct_as: "已登录为 @{handle}",
    acct_no_handle: "已登录 — 请在网站上认领一个用户名",
    acct_sync_on: "同步中", acct_sync_off: "同步已暂停",
    acct_unsent: "{n} 条待发送",
    acct_synced: "已全部发送",
    shared_first: "还没有人评过这首 — 来当第一个 ✦",
    shared_avg: "{count} 条评价 · 均分 {avg}",
    shared_first_by: "首评：@{handle}",
  },
};

// prefs moved from the rateify_* keys when the app was renamed; read the old
// key once so an upgrading user keeps their language and theme
function pref(name, fallback) {
  return (
    localStorage.getItem(`noskips_${name}`) ??
    localStorage.getItem(`rateify_${name}`) ??
    fallback
  );
}
const setPref = (name, value) => localStorage.setItem(`noskips_${name}`, value);

let lang = pref("lang", "en");

function t(key, params) {
  let s = (I18N[lang] && I18N[lang][key]) ?? I18N.en[key] ?? key;
  if (params) for (const k in params) s = s.replace(`{${k}}`, params[k]);
  return s;
}

function applyI18n() {
  document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  document.querySelectorAll("[data-i18n-title]").forEach((el) => (el.title = t(el.dataset.i18nTitle)));
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => (el.placeholder = t(el.dataset.i18nPlaceholder)));
  document.querySelectorAll(".lang-pill").forEach((p) => p.classList.toggle("on", p.dataset.lang === lang));
}

function setLang(l) {
  lang = l;
  setPref("lang", l);
  applyI18n();
  renderRating();
  renderAccount();
  renderListening();
  renderShared();
  resetRating(now && now.saved);
  openPanel = null;
  if (!shelfDirty) loadShelf();
}

document.querySelectorAll(".lang-pill").forEach((p) =>
  p.addEventListener("click", () => setLang(p.dataset.lang))
);

// ---------------------------------------------------------------- theme ----
const THEMES = ["classic", "noir", "mint", "berry", "ocean"];
let theme = pref("theme", "classic");

function setTheme(name) {
  theme = name;
  setPref("theme", name);
  document.body.classList.remove(...THEMES.map((n) => `theme-${n}`));
  document.body.classList.add(`theme-${name}`);
  document.querySelectorAll(".swatch").forEach((s) => s.classList.toggle("on", s.dataset.theme === name));
}

document.querySelectorAll(".swatch").forEach((s) =>
  s.addEventListener("click", () => setTheme(s.dataset.theme))
);

setTheme(theme);
applyI18n();

// ---------------------------------------------------- tucked-away skins ----
// Four ways for the mini bar to show a song. Each builds its DOM once in
// setSkin() and is then updated per frame from drawProgress(), so nothing
// allocates in the animation loop.
const SKINS = ["spool", "groove", "hiss", "ticker"];
let skin = pref("skin", "spool");
let spectrum = [];      // last frame from /api/spectrum
let spectrumTap = null; // the EventSource, open only while something needs it

const SKIN_HTML = {
  // a mini cassette: tape winds from the left hub to the right as it plays
  spool: `<span class="sk-spool">
      <i class="hub left"></i><i class="tape"></i><i class="hub right"></i>
    </span>`,
  // a tiny record; the tonearm tracks inward exactly as far as you've listened
  groove: `<span class="sk-groove"><i class="disc"></i><i class="arm"></i></span>`,
  // sixteen bands of whatever is actually coming out of the speakers
  hiss: `<span class="sk-hiss">${'<i></i>'.repeat(16)}</span>`,
  // the title, typed onto a strip of receipt paper feeding out of the bar
  ticker: `<span class="sk-ticker"><i class="strip"><b></b></i></span>`,
};

function setSkin(name) {
  skin = SKINS.includes(name) ? name : "spool";
  setPref("skin", skin);
  const box = $("mini-skin");
  box.className = `mini-skin skin-${skin}`;
  box.innerHTML = SKIN_HTML[skin];
  document.querySelectorAll(".skinbtn").forEach((b) => b.classList.toggle("on", b.dataset.skin === skin));
  tapSpectrum();
}

document.querySelectorAll(".skinbtn").forEach((b) =>
  b.addEventListener("click", () => setSkin(b.dataset.skin))
);

// Only hold the stream open while something is actually drawing it — an idle
// EventSource is a thread on the widget's tiny Flask server for no reason.
function tapSpectrum() {
  const wanted = skin === "hiss";
  if (wanted && !spectrumTap) {
    spectrumTap = new EventSource("/api/spectrum");
    spectrumTap.onmessage = (e) => {
      try {
        spectrum = JSON.parse(e.data);
      } catch {
        spectrum = [];
      }
    };
    spectrumTap.onerror = () => {
      /* the widget carries on regardless; bars just stop moving */
    };
  } else if (!wanted && spectrumTap) {
    spectrumTap.close();
    spectrumTap = null;
    spectrum = [];
  }
}

function drawSkin(progress, playing) {
  const box = $("mini-skin");
  if (!box.firstElementChild) return;

  if (skin === "spool") {
    // both hubs turn while playing; the tape thickens as the song winds on
    const spin = playing ? (Date.now() / 1000) * 220 : 0;
    box.style.setProperty("--spin", `${spin}deg`);
    box.style.setProperty("--wound", progress.toFixed(3));
  } else if (skin === "groove") {
    // the arm swings from the rim (-18°) toward the label (+16°)
    box.style.setProperty("--arm", `${-18 + progress * 34}deg`);
    box.style.setProperty("--spin", `${playing ? (Date.now() / 1000) * 200 : 0}deg`);
  } else if (skin === "hiss") {
    const bars = box.querySelectorAll("i");
    bars.forEach((bar, i) => {
      const value = spectrum[i] ?? 0;
      bar.style.height = `${6 + value * 20}px`;
    });
  } else if (skin === "ticker") {
    box.style.setProperty("--fed", `${(progress * 100).toFixed(1)}%`);
    const strip = box.querySelector("b");
    const text = (now && now.title) || "";
    if (strip.textContent !== text) strip.textContent = text;
  }
}

// ---------------------------------------------------------- listening ----
let listening = { enabled: false, available: false };

async function loadListening() {
  try {
    listening = await (await fetch("/api/visual")).json();
  } catch {
    return;
  }
  renderListening();
}

function renderListening() {
  const box = $("listen");
  if (!box) return;
  box.innerHTML = "";

  const button = document.createElement("button");
  button.className = `acct-btn${listening.enabled ? " on" : ""}`;
  button.textContent = listening.enabled ? t("listen_on") : t("listen_off");
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      listening = await (
        await fetch("/api/visual", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ on: !listening.enabled }),
        })
      ).json();
    } catch {
      /* leave the last known state up */
    }
    renderListening();
  });
  box.appendChild(button);

  const note = document.createElement("p");
  note.className = "acct-note";
  note.textContent = listening.enabled && listening.error
    ? listening.error
    : t("listen_hint");
  box.appendChild(note);
  fitWindow();
}

// -------------------------------------------------------------- account ----
// The widget is happy signed out forever; this whole section is opt-in, and
// until it's used the app opens no connections at all.
let acct = { signed_in: false, sync_on: false, unsent: 0, pairing: null };
let acctTimer = null;

async function loadAccount() {
  try {
    acct = await (await fetch("/api/account")).json();
  } catch {
    return; // the local server blinked; leave the last known state up
  }
  renderAccount();
  renderPrivacy();
  // watch closely while a pairing is in flight, idle the rest of the time
  clearInterval(acctTimer);
  acctTimer = setInterval(loadAccount, acct.pairing ? 2000 : 30000);
}

async function accountPost(url, body) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const out = await res.json();
    if (out.sync) acct = out.sync;
    if (out.error) acct = { ...acct, last_error: out.error };
  } catch {
    /* offline is a normal state here, not an error worth shouting about */
  }
  renderAccount();
  renderPrivacy();
  clearInterval(acctTimer);
  acctTimer = setInterval(loadAccount, acct.pairing ? 2000 : 30000);
}

function renderAccount() {
  const box = $("account");
  if (!box) return;
  box.innerHTML = "";

  const line = (cls, text) => {
    const p = document.createElement("p");
    p.className = cls;
    p.textContent = text;
    box.appendChild(p);
  };
  const button = (text, fn, cls) => {
    const b = document.createElement("button");
    b.className = "acct-btn" + (cls ? ` ${cls}` : "");
    b.textContent = text;
    b.addEventListener("click", fn);
    box.appendChild(b);
  };

  if (acct.pairing) {
    line("acct-code", acct.pairing.code);
    line("acct-note", t("acct_pairing", { code: acct.pairing.code }));
    button(t("acct_cancel"), () => accountPost("/api/account/cancel"));
  } else if (!acct.signed_in) {
    line("acct-note", t("acct_signed_out"));
    button(t("acct_pair"), () => accountPost("/api/account/pair"), "go");
  } else {
    line("acct-who", acct.handle ? t("acct_as", { handle: acct.handle }) : t("acct_no_handle"));
    button(
      acct.sync_on ? t("acct_sync_on") : t("acct_sync_off"),
      () => accountPost("/api/account/sync", { on: !acct.sync_on }),
      acct.sync_on ? "on" : ""
    );
    line("acct-note", acct.unsent ? t("acct_unsent", { n: acct.unsent }) : t("acct_synced"));
    button(t("acct_signout"), () => accountPost("/api/account/signout"));
  }
  if (acct.last_error) line("acct-err", acct.last_error);
  fitWindow();
}

// ------------------------------------------------------ per-rating privacy ----
let priv = { public: true, notePublic: true };

function renderPrivacy() {
  const box = $("privacy");
  // nothing to decide about sharing when nothing is being shared
  box.hidden = !(acct.signed_in && acct.sync_on);
  const pub = $("priv-public");
  const note = $("priv-note");
  pub.classList.toggle("on", priv.public);
  pub.textContent = priv.public ? t("priv_public") : t("priv_public_off");
  note.classList.toggle("on", priv.notePublic);
  note.textContent = priv.notePublic ? t("priv_note") : t("priv_note_off");
  note.disabled = !priv.public;
}

$("priv-public").addEventListener("click", () => {
  priv.public = !priv.public;
  if (!priv.public) priv.notePublic = false; // a private verdict can't have a public note
  renderPrivacy();
});
$("priv-note").addEventListener("click", () => {
  if (!priv.public) return;
  priv.notePublic = !priv.notePublic;
  renderPrivacy();
});

// label for an already-stored numeric value (used on the shelf)
const prettyAvg = (v) => (v == null ? "–" : (Math.round(v * 10) / 10).toFixed(1));

// ------------------------------------------------- tabs + window fitting ----
let collapsed = false;

// ask the native window to hug the content (no-op in a plain browser)
function fitWindow() {
  if (!window.pywebview) return;
  const w = collapsed ? 250 : 420;
  const h = collapsed
    ? 40
    : Math.min(Math.max(document.body.scrollHeight + 6, 280), 920);
  window.pywebview.api.resize(w, h);
}

function setCollapsed(c) {
  collapsed = c;
  document.body.classList.toggle("collapsed", c);
  fitWindow();
}

$("mini-now").addEventListener("click", () => setCollapsed(false));

document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    if (tab.classList.contains("active")) {
      setCollapsed(!collapsed); // tap the open tab again to tuck the widget away
      return;
    }
    setCollapsed(false);
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const view = tab.dataset.view;
    $("view-now").hidden = view !== "now";
    $("view-shelf").hidden = view !== "shelf";
    $("view-settings").hidden = view !== "settings";
    if (view === "shelf" && shelfDirty) loadShelf();
    fitWindow();
  })
);

// -------------------------------------------------------- rating drawer ----
let savedLabel = null; // label of the stored rating for the current track

function updateDrawerLabel() {
  const open = !$("rating-zone").hidden;
  $("drawer-toggle").textContent =
    (savedLabel ? `✎ ${savedLabel}${t("edit_suffix")}` : `✎ ${t("rate_track")}`) +
    (open ? " ▴" : " ▾");
}

$("drawer-toggle").addEventListener("click", () => {
  $("rating-zone").hidden = !$("rating-zone").hidden;
  updateDrawerLabel();
  fitWindow();
});

// ------------------------------------------------------------ rating UI ----
const pillsBox = $("pills");
for (let n = 1; n <= 10; n++) {
  const b = document.createElement("button");
  b.className = "pill";
  b.textContent = n;
  b.addEventListener("click", () => {
    sel.n = n;
    if (n === 10 && sel.mod === "strong") sel.mod = "just"; // scale tops out at 10
    renderRating();
  });
  pillsBox.appendChild(b);
}

document.querySelectorAll(".mod").forEach((m) =>
  m.addEventListener("click", () => {
    if (m.disabled) return;
    sel.mod = m.dataset.mod;
    renderRating();
  })
);

function renderRating() {
  [...pillsBox.children].forEach((p, i) => p.classList.toggle("on", i + 1 === sel.n));
  document.querySelectorAll(".mod").forEach((m) => {
    m.classList.toggle("active", m.dataset.mod === sel.mod);
    m.disabled = m.dataset.mod === "strong" && sel.n === 10;
  });
  if (sel.n == null) {
    $("r-label").textContent = t("pick_number");
    $("r-value").textContent = "";
  } else {
    $("r-label").textContent = labelOf(sel.n, sel.mod);
    $("r-value").textContent = `(${valueOf(sel.n, sel.mod)})`;
  }
}

function resetRating(saved) {
  if (saved) {
    // reverse the stored value back into pill + modifier
    const v = saved.value;
    const n = Math.round(v);
    sel.n = Math.min(10, Math.max(1, n));
    sel.mod = v < n - 0.1 ? "light" : v > n + 0.1 ? "strong" : "just";
    $("note").value = saved.note || "";
    $("stamp").hidden = false;
    // ratings from before the social layer have no flags; sharing is the default
    priv = { public: saved.public !== false, notePublic: saved.notePublic !== false };
  } else {
    sel = { n: null, mod: "just" };
    $("note").value = "";
    $("stamp").hidden = true;
    priv = { public: true, notePublic: true };
  }
  renderPrivacy();
  const btn = $("save");
  btn.classList.remove("saved");
  btn.textContent = saved ? t("restamp_it") : t("stamp_it");
  savedLabel = saved ? saved.label : null;
  updateDrawerLabel();
  renderRating();
}

// ---------------------------------------------------------------- save ----
$("save").addEventListener("click", async () => {
  const btn = $("save");
  if (!now || !now.active) return;
  if (sel.n == null) {
    btn.classList.remove("nope");
    void btn.offsetWidth; // restart the shake
    btn.classList.add("nope");
    return;
  }
  btn.disabled = true;
  try {
    const res = await fetch("/api/rate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        artist: now.artist,
        album: now.album,
        title: now.title,
        value: valueOf(sel.n, sel.mod),
        label: labelOf(sel.n, sel.mod),
        note: $("note").value,
        public: priv.public,
        notePublic: priv.notePublic,
        kind: now.kind,
      }),
    });
    const out = await res.json();
    if (out.ok) {
      if (out.sync) {
        acct = out.sync;
        renderAccount();
      }
      shelfDirty = true;
      const stamp = $("stamp");
      stamp.hidden = true;
      void stamp.offsetWidth; // replay slam animation
      stamp.hidden = false;
      btn.classList.add("saved");
      btn.textContent = t("stamped_avg", { avg: prettyAvg(out.albumAvg) });
      savedLabel = labelOf(sel.n, sel.mod);
      updateDrawerLabel();
    }
  } finally {
    btn.disabled = false;
  }
});

// ------------------------------------------------------------- controls ----
document.querySelectorAll(".ctl").forEach((b) =>
  b.addEventListener("click", () => {
    fetch("/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: b.dataset.act }),
    });
    // optimistic flip so the vinyl, icon and clock react instantly
    if (b.dataset.act === "playpause" && now && now.active) {
      now.position = clock.pos + (clock.playing ? Date.now() / 1000 - clock.at : 0);
      now.ts = Date.now() / 1000;
      now.playing = !now.playing;
      renderNow();
    }
    setTimeout(pollNow, 350); // then confirm against reality
  })
);

// ----------------------------------------------------------- now playing ----
async function pollNow() {
  try {
    const res = await fetch("/api/now");
    now = await res.json();
  } catch {
    now = { active: false };
  }
  renderNow();
}

function renderNow() {
  const card = $("now-card");
  const empty = $("now-empty");
  const active = !!(now && now.active);
  const mini = $("mini-now");
  mini.classList.toggle("has-track", active);
  mini.classList.toggle("playing", active && now.playing);
  if (active) {
    $("mini-title").textContent = now.title;
    $("mini-artist").textContent = now.artist;
    const miniCover = $("mini-cover-sm");
    const wantMini = now.cover || "";
    if (miniCover.dataset.src !== wantMini) {
      miniCover.dataset.src = wantMini;
      miniCover.src = wantMini;
    }
  }
  if (!now || !now.active) {
    card.hidden = true;
    empty.hidden = false;
    return;
  }
  card.hidden = false;
  empty.hidden = true;

  const key = `${now.artist}:::${now.album}:::${now.title}`;
  if (key !== trackKey) {
    trackKey = key;
    $("t-title").textContent = now.title;
    $("t-artist").textContent = now.artist;
    $("t-album").textContent = now.album;
    resetRating(now.saved);
    fitWindow(); // title height can change between tracks
  }

  const cover = $("cover");
  const want = now.cover || "";
  if (cover.dataset.src !== want) {
    cover.dataset.src = want;
    cover.src = want;
  }

  renderKind();
  renderShared();

  $("vinyl").classList.toggle("out", now.playing);
  card.classList.toggle("playing", now.playing);
  // NB: the `hidden` attribute is ignored on inline <svg>, use display
  $("icon-play").style.display = now.playing ? "none" : "";
  $("icon-pause").style.display = now.playing ? "" : "none";

  syncClock();
}

// videos are rated exactly like songs — this just says where the verdict will
// land, so nobody is surprised that it didn't reach their profile
function renderKind() {
  const el = $("kind-line");
  const isVideo = now && now.kind === "video";
  const card = $("now-card");
  card.classList.toggle("is-video", !!isVideo);
  if (!isVideo) {
    if (!el.hidden) {
      el.hidden = true;
      fitWindow();
    }
    return;
  }
  const wasHidden = el.hidden;
  el.hidden = false;
  const text = t("kind_video");
  if (el.textContent !== text) el.textContent = text;
  if (wasHidden) fitWindow();
}

// what everyone else made of this track. absent until sync is on and the
// answer has arrived, so the layout never jumps around waiting for a network
function renderShared() {
  const el = $("shared-line");
  const s = now && now.shared;
  if (!s) {
    if (!el.hidden) {
      el.hidden = true;
      fitWindow();
    }
    return;
  }
  const wasHidden = el.hidden;
  el.hidden = false;
  el.classList.toggle("first", !s.exists);

  let text;
  if (!s.exists) {
    // the good moment: nobody in the world has stamped this one
    text = t("shared_first");
  } else {
    text = t("shared_avg", { count: s.count, avg: prettyAvg(s.average) });
    if (s.first_press_by) text += ` · ${t("shared_first_by", { handle: s.first_press_by })}`;
  }
  if (el.textContent !== text) el.textContent = text;
  if (wasHidden) fitWindow();
}

// ------------------------------------------------------- smooth progress ----
// Spotify only reports its position to Windows every few seconds, so raw
// polls jump backwards. Keep a local clock and only resync on real events
// (track change, play/pause, or a seek that drifts it > 3s).
const clock = { key: "", pos: 0, at: 0, playing: false, duration: 0 };

function syncClock() {
  const t = Date.now() / 1000;
  let serverPos = now.position + (now.playing ? t - now.ts : 0);
  if (now.duration) serverPos = Math.min(serverPos, now.duration);
  const localPos = clock.pos + (clock.playing ? t - clock.at : 0);
  if (
    clock.key !== trackKey ||
    clock.playing !== now.playing ||
    Math.abs(serverPos - localPos) > 3
  ) {
    clock.pos = serverPos;
    clock.at = t;
  }
  clock.key = trackKey;
  clock.playing = now.playing;
  clock.duration = now.duration || 0;
}

// drive the bar every frame so it glides instead of ticking
function drawProgress() {
  if (now && now.active && clock.duration) {
    let pos = clock.pos + (clock.playing ? Date.now() / 1000 - clock.at : 0);
    pos = Math.min(pos, clock.duration);
    const progress = pos / clock.duration;
    $("p-fill").style.width = `${progress * 100}%`;
    const cur = fmt(pos);
    if ($("p-cur").textContent !== cur) $("p-cur").textContent = cur;
    const dur = fmt(clock.duration);
    if ($("p-dur").textContent !== dur) $("p-dur").textContent = dur;
    // the mini bar is driven by the same clock, so it never drifts from the bar
    if (collapsed) drawSkin(progress, clock.playing);
  }
  requestAnimationFrame(drawProgress);
}
requestAnimationFrame(drawProgress);

// ---------------------------------------------------------------- shelf ----
function albumCard(a) {
  const video = a.kind === "video";
  const card = document.createElement("div");
  card.className = `album-card${video ? " video-card" : ""}`;
  card.innerHTML = `
    <div class="album-cover-wrap">
      <span class="avg-badge">${prettyAvg(a.avg)}</span>
      ${
        a.cover
          ? `<img class="album-cover" src="${a.cover}" alt="" loading="lazy">`
          : `<div class="album-cover placeholder">${video ? "▶" : "♪"}</div>`
      }
    </div>
    <p class="album-name"></p>
    <p class="album-artist"></p>
    <p class="album-count"></p>`;
  // a video has no album, so its channel carries the card instead
  card.querySelector(".album-name").textContent =
    a.album || (video ? a.artist : t("single_album"));
  card.querySelector(".album-artist").textContent = video && !a.album ? "" : a.artist;
  card.querySelector(".album-count").textContent = t(
    video ? "videos_rated" : "tracks_rated",
    { count: a.count }
  );
  card.addEventListener("click", () => toggleTracks(card, a));
  return card;
}

function fillGrid(grid, albums) {
  grid.innerHTML = "";
  albums.forEach((a) => grid.appendChild(albumCard(a)));
}

async function loadShelf() {
  shelfDirty = false;
  const res = await fetch("/api/library");
  const { albums, videos = [] } = await res.json();

  fillGrid($("shelf-grid"), albums);
  fillGrid($("videos-grid"), videos);
  // the videos shelf only exists once there's something on it
  $("videos-block").hidden = videos.length === 0;
  $("shelf-empty").hidden = albums.length > 0 || videos.length > 0;

  fitWindow();
}

let openPanel = null;
function toggleTracks(card, a) {
  if (openPanel) {
    // the kind is part of the identity: a song and a video can share a name
    const wasThis = openPanel.dataset.for === `${a.kind}:::${a.artist}:::${a.album}`;
    openPanel.remove();
    openPanel = null;
    if (wasThis) {
      fitWindow();
      return;
    }
  }
  const panel = document.createElement("div");
  panel.className = "album-tracks";
  panel.dataset.for = `${a.kind}:::${a.artist}:::${a.album}`;
  panel.innerHTML = `<h3></h3><p class="sub"></p>`;
  panel.querySelector("h3").textContent = a.album || t("single_album");
  panel.querySelector(".sub").textContent = t("album_avg_line", { artist: a.artist, avg: prettyAvg(a.avg) });

  a.tracks.forEach((trk) => {
    const row = document.createElement("div");
    row.className = "trk";
    row.innerHTML = `
      <span class="trk-title"></span>
      <span class="trk-label"></span>
      <button class="trk-del">✕</button>`;
    row.querySelector(".trk-title").textContent = trk.title;
    row.querySelector(".trk-label").textContent = trk.label;
    row.querySelector(".trk-del").title = t("remove_rating");
    row.querySelector(".trk-del").addEventListener("click", async (e) => {
      e.stopPropagation();
      await fetch("/api/rate", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          artist: a.artist,
          album: a.album,
          title: trk.title,
          kind: a.kind,
        }),
      });
      shelfDirty = true;
      trackKey = ""; // force the now-view to reload saved state
      loadShelf();
    });
    panel.appendChild(row);
    if (trk.note) {
      const note = document.createElement("p");
      note.className = "trk-note";
      note.textContent = `“${trk.note}”`;
      panel.appendChild(note);
    }
    const date = document.createElement("p");
    date.className = "trk-date";
    date.textContent = trk.date.slice(0, 10);
    panel.appendChild(date);
  });

  panel.addEventListener("click", (e) => e.stopPropagation());
  card.after(panel);
  openPanel = panel;
  fitWindow();
}

// ------------------------------------------------------- widget window ----
// pywebview announces itself after load; only then show the ✕ / — buttons
window.addEventListener("pywebviewready", () => {
  document.body.classList.add("webview");
  $("win-close").addEventListener("click", () => window.pywebview.api.close());
  $("win-min").addEventListener("click", () => window.pywebview.api.minimize());
  fitWindow();
  setTimeout(fitWindow, 700); // refit once fonts/cover have settled
});

// ----------------------------------------------------------------- boot ----
renderRating();
renderPrivacy();
setSkin(skin);
loadAccount();
loadListening();
pollNow();
setInterval(pollNow, 1000);
if (location.hash === "#shelf")
  document.querySelector('.tab[data-view="shelf"]').click();
if (location.hash === "#settings")
  document.querySelector('.tab[data-view="settings"]').click();
if (location.hash === "#rate") {
  $("rating-zone").hidden = false;
  updateDrawerLabel();
}
