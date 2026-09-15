import { load } from "./data.js";
import { DEFAULT_QUERY, AUTH_NONE, apply, facets, toHash, fromHash } from "./filter.js";
import { renderRows } from "./table.js";
import { renderMosaic, updateMosaic, summarise } from "./mosaic.js";
import { corrections } from "./corrections.js";
import { LEVEL_LABEL } from "./levels.js";

const $ = (id) => document.getElementById(id);

/* ---- theme ------------------------------------------------------------ */

function initTheme() {
  const btn = $("theme");
  const stored = (() => {
    try { return localStorage.getItem("theme"); } catch { return null; }
  })();
  if (stored) document.documentElement.dataset.theme = stored;

  const label = () => {
    const dark = document.documentElement.dataset.theme === "dark"
      || (!document.documentElement.dataset.theme
          && window.matchMedia("(prefers-color-scheme: dark)").matches);
    btn.textContent = dark ? "Light" : "Dark";
    return dark;
  };
  label();

  btn.addEventListener("click", () => {
    const dark = label();
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", document.documentElement.dataset.theme); } catch { /* private mode */ }
    label();
  });
}

/* ---- controls --------------------------------------------------------- */

function option(value, text) {
  const o = document.createElement("option");
  o.value = value;
  o.textContent = text;
  return o;
}

function fillControls(entries) {
  const f = facets(entries);

  $("category").append(option("", "Any"), ...f.categories.map((c) => option(c, c)));
  $("auth").append(
    option("", "Any"),
    option(AUTH_NONE, "No key needed"),
    ...f.auths.map((a) => option(a, a))
  );
  $("cors").append(option("", "Any"), option("yes", "Yes"), option("no", "No"), option("unknown", "Unknown"));
  $("sort").append(
    option("reliability", "Most reliable"),
    option("name", "Name"),
    option("speed", "Fastest")
  );
}

function readQuery() {
  return {
    text: $("q").value,
    category: $("category").value,
    auth: $("auth").value,
    cors: $("cors").value,
    sort: $("sort").value,
    https: $("https").checked,
    hideBroken: $("hideBroken").checked,
  };
}

function writeQuery(q) {
  $("q").value = q.text;
  $("category").value = q.category;
  $("auth").value = q.auth;
  $("cors").value = q.cors;
  $("sort").value = q.sort;
  $("https").checked = q.https === true || q.https === "true";
  $("hideBroken").checked = q.hideBroken === true || q.hideBroken === "true";
}

/* ---- corrections ------------------------------------------------------ */

function renderCorrections(entries) {
  const { httpsDowngrade, deadLink, corsUnconfirmed } = corrections(entries);
  const el = $("corrections");
  el.replaceChildren();

  const h2 = document.createElement("h2");
  h2.textContent = "Where the list disagrees with reality";
  const lede = document.createElement("p");
  lede.textContent =
    "The upstream README records what someone believed when they added an entry. "
    + "These are the places our measurements say otherwise. Strength of evidence varies, "
    + "and it is marked.";
  el.append(h2, lede);

  const group = (title, blurb, items, render, caveat) => {
    const g = document.createElement("section");
    g.className = "group";
    const h3 = document.createElement("h3");
    h3.textContent = `${title} — ${items.length}`;
    const p = document.createElement("p");
    p.textContent = blurb;
    g.append(h3, p);
    if (caveat) {
      const c = document.createElement("p");
      c.className = "group__caveat";
      c.textContent = caveat;
      g.append(c);
    }
    if (!items.length) {
      const none = document.createElement("p");
      none.textContent = "Nothing here yet.";
      g.append(none);
    } else {
      const ol = document.createElement("ol");
      for (const e of items.slice(0, 40)) ol.append(render(e));
      g.append(ol);
      if (items.length > 40) {
        const more = document.createElement("p");
        more.textContent = `…and ${items.length - 40} more.`;
        g.append(more);
      }
    }
    el.append(g);
  };

  const li = (main, detail) => {
    const l = document.createElement("li");
    l.append(document.createTextNode(main));
    if (detail) {
      const s = document.createElement("span");
      s.className = "mono";
      s.textContent = ` ${detail}`;
      l.append(s);
    }
    return l;
  };

  group(
    "Documented as HTTPS, redirects to HTTP",
    "Strong evidence and directly actionable: the entry claims HTTPS, but following it ends on an insecure URL.",
    httpsDowngrade,
    (e) => li(e.name, `→ ${e.final_url}`)
  );

  group(
    "Link has been dead for three days or more",
    "Confirmed by the same flap filter the pipeline uses. A single bad day is never listed here — a transient outage is not a finding.",
    deadLink,
    (e) => li(e.name, `${e.state} · ${e.failing_streak}d`)
  );

  group(
    "Documented as CORS-enabled, no header observed",
    "A lead to check, not a correction to submit.",
    corsUnconfirmed,
    (e) => li(e.name, e.url),
    "We request each entry's documentation page, not its API endpoint. Plenty of "
    + "services send CORS headers on the API while the docs page does not, so a "
    + "missing header here does not prove the README wrong. Verify against the "
    + "actual endpoint before reporting any of these upstream."
  );
}

/* ---- boot ------------------------------------------------------------- */

async function main() {
  initTheme();

  let data;
  try {
    data = await load();
  } catch (err) {
    $("headline").textContent = "Could not load the data";
    $("when").textContent = String(err.message || err);
    return;
  }

  const { entries, generated } = data;
  const s = summarise(entries, generated);

  $("headline").textContent = s.headline;
  const when = $("when");
  when.textContent = s.stale
    ? `${s.when} — the pipeline has not published since then`
    : s.when;
  when.classList.toggle("is-stale", s.stale);

  const detail = $("detail");
  detail.innerHTML =
    `<b>${s.answered.toLocaleString()}</b> answered · `
    + `<b>${s.broken.toLocaleString()}</b> did not · `
    + `<b>${s.pct}%</b> of the list is broken`;

  const legend = $("legend");
  for (const [level, text] of Object.entries(LEVEL_LABEL)) {
    const li = document.createElement("li");
    const i = document.createElement("i");
    i.style.background = `var(--${level})`;
    li.append(i, document.createTextNode(text));
    legend.append(li);
  }

  fillControls(entries);
  renderMosaic($("mosaic"), entries);
  renderCorrections(entries);

  const draw = (q, pushHash) => {
    const visible = apply(entries, q);
    renderRows($("rows"), visible, q);
    updateMosaic(new Set(visible.map((e) => e.id)));
    $("count").textContent =
      `Showing ${visible.length.toLocaleString()} of ${entries.length.toLocaleString()}`;
    if (pushHash) {
      const h = toHash(q);
      history.replaceState(null, "", h || window.location.pathname);
    }
  };

  const initial = fromHash(window.location.hash);
  writeQuery(initial);
  draw(initial, false);

  let timer;
  const onChange = () => {
    clearTimeout(timer);
    timer = setTimeout(() => draw(readQuery(), true), 90);
  };
  for (const id of ["q", "category", "auth", "cors", "sort", "https", "hideBroken"]) {
    $(id).addEventListener("input", onChange);
  }

  window.addEventListener("hashchange", () => {
    const q = fromHash(window.location.hash);
    writeQuery(q);
    draw(q, false);
  });
}

main();
