import { levelOf, LEVELS, STATE_LABEL } from "./levels.js";

const cells = new Map(); // id -> element, so updates never re-query the DOM

export function renderMosaic(container, entries) {
  container.replaceChildren();
  cells.clear();

  // Ordered by level so failures cluster into a visible band rather than
  // scattering into noise. The field is built once and never rebuilt: filtering
  // dims cells instead of reflowing them, so narrowing reads as carving one
  // image rather than drawing a different one.
  const ordered = [...entries].sort((a, b) => {
    const ra = a.state ? LEVELS.indexOf(levelOf(a.state)) : LEVELS.length;
    const rb = b.state ? LEVELS.indexOf(levelOf(b.state)) : LEVELS.length;
    return ra - rb || a.name.localeCompare(b.name);
  });

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const frag = document.createDocumentFragment();

  for (const e of ordered) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = `mosaic__cell mosaic__cell--${e.state ? levelOf(e.state) : "nodata"}`;
    const label = `${e.name} — ${e.state ? STATE_LABEL[e.state] : "not probed yet"}`;
    cell.title = label;
    cell.setAttribute("aria-label", label);
    cell.addEventListener("click", () => {
      const target = document.getElementById(`row-${e.id}`);
      if (!target) return; // filtered out of the list; dimmed, not clickable-to-nowhere
      target.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
      target.focus();
    });
    cells.set(e.id, cell);
    frag.append(cell);
  }
  container.append(frag);
}

export function updateMosaic(visibleIds) {
  for (const [id, cell] of cells) {
    cell.classList.toggle("mosaic__cell--dimmed", !visibleIds.has(id));
  }
}

export function summarise(entries, generated) {
  const measured = entries.filter((e) => e.state);
  const answered = measured.filter((e) => ["ok", "gated"].includes(levelOf(e.state))).length;
  const broken = measured.length - answered;
  const days = Math.floor((Date.now() - Date.parse(generated)) / 86400000);

  return {
    headline: `${entries.length.toLocaleString()} public APIs`,
    when: days <= 1 ? "probed today" : `last probed ${generated}`,
    stale: days > 2,
    answered,
    broken,
    pct: measured.length ? ((broken / measured.length) * 100).toFixed(1) : "0.0",
  };
}
