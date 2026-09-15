import { levelOfChar, CHAR_STATE, STATE_LABEL } from "./levels.js";

export const WINDOW = 90;

// Left-pad rather than right-pad: every strip must end on today, so a column
// means the same date in every row. Short histories are young entries, not
// failing ones. The pipeline fills days it did not run with ".", so position
// really is day offset — that was not true before the September 2026 outage
// exposed it.
export function stripCells(history, window = WINDOW) {
  const recent = (history || "").slice(-window);
  const padded = ".".repeat(Math.max(0, window - recent.length)) + recent;
  return [...padded].map((ch, i) => ({
    level: levelOfChar(ch),
    state: CHAR_STATE[ch] || null,
    offsetFromToday: padded.length - 1 - i,
  }));
}

export function renderStrip(history) {
  const wrap = document.createElement("div");
  wrap.className = "strip";
  wrap.setAttribute("role", "img");

  const cells = stripCells(history);
  const measured = cells.filter((c) => c.level !== "nodata");
  const ok = measured.filter((c) => c.level === "ok" || c.level === "gated").length;
  wrap.setAttribute(
    "aria-label",
    measured.length
      ? `Answered on ${ok} of the last ${measured.length} days probed`
      : "Not probed yet"
  );

  for (const cell of cells) {
    const el = document.createElement("span");
    el.className = `cell cell--${cell.level}`;
    if (cell.state) {
      const when = cell.offsetFromToday === 0 ? "today" : `${cell.offsetFromToday} days ago`;
      el.title = `${STATE_LABEL[cell.state]} — ${when}`;
    }
    wrap.append(el);
  }
  return wrap;
}
