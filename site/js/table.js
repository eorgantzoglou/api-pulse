import { renderStrip } from "./strip.js";
import { STATE_LABEL, levelOf } from "./levels.js";

const CHUNK = 60;

function row(entry) {
  const el = document.createElement("article");
  el.className = "row";
  el.id = `row-${entry.id}`;
  el.tabIndex = -1;

  const link = document.createElement("a");
  link.className = "row__name";
  link.href = entry.url;
  link.rel = "noopener noreferrer";
  link.textContent = entry.name;

  const meta = document.createElement("p");
  meta.className = "row__meta";
  meta.textContent = entry.description;

  const side = document.createElement("div");
  side.className = "row__side";

  const level = entry.state ? levelOf(entry.state) : "nodata";
  const state = document.createElement("span");
  // The label is the carrier; the dot beside it is reinforcement, never the
  // only signal.
  state.className = `row__state row__state--${level}`;
  const dot = document.createElement("i");
  dot.setAttribute("aria-hidden", "true");
  state.append(dot, document.createTextNode(entry.state ? STATE_LABEL[entry.state] : "Not probed yet"));

  const facts = document.createElement("div");
  facts.className = "row__facts";
  const bits = [];
  if (entry.failing_streak > 0) bits.push(`failing ${entry.failing_streak}d`);
  if (entry.response_ms != null) bits.push(`${entry.response_ms} ms`);
  bits.push(entry.auth ? entry.auth : "no key");
  if (entry.cors === "yes") bits.push("CORS");
  for (const b of bits) {
    const s = document.createElement("span");
    s.className = "mono";
    s.textContent = b;
    facts.append(s);
  }

  side.append(state, facts);

  const scroll = document.createElement("div");
  scroll.className = "strip-scroll";
  scroll.append(renderStrip(entry.history));

  el.append(link, meta, side, scroll);
  return el;
}

export function renderRows(container, entries, query) {
  container.replaceChildren();

  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    const active = [
      query.text && "the search box",
      query.category && "the category",
      query.auth && "the auth filter",
      query.https && "the HTTPS filter",
      query.cors && "the CORS filter",
      query.hideBroken && "“hide broken”",
    ].filter(Boolean);
    empty.innerHTML = active.length
      ? `Nothing matches. Try relaxing <b>${active[0]}</b>.`
      : "Nothing to show.";
    container.append(empty);
    return;
  }

  let next = 0;
  const sentinel = document.createElement("div");
  sentinel.className = "sentinel";

  const paint = () => {
    const slice = entries.slice(next, next + CHUNK);
    if (!slice.length) {
      observer.disconnect();
      sentinel.remove();
      return;
    }
    const frag = document.createDocumentFragment();
    for (const e of slice) frag.append(row(e));
    container.insertBefore(frag, sentinel);
    next += slice.length;
  };

  // 1,755 rows x 90 cells is ~158,000 nodes if rendered eagerly, which janks on
  // mid-range hardware. Windowing keeps first paint fast while leaving the DOM
  // real, so Ctrl-F and screen readers still work.
  const observer = new IntersectionObserver((es) => {
    if (es.some((e) => e.isIntersecting)) paint();
  }, { rootMargin: "800px" });

  container.append(sentinel);
  paint();
  observer.observe(sentinel);
}
