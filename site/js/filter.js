import { levelOf, LEVELS } from "./levels.js";

// An empty auth filter means "any". "No key needed" is a real, and the most
// commonly wanted, selection, so it gets its own sentinel rather than colliding
// with the any-value.
export const AUTH_NONE = "none";

export const DEFAULT_QUERY = {
  text: "", category: "", auth: "", https: false, cors: "",
  hideBroken: true, sort: "reliability",
};

const SORTS = new Set(["reliability", "name", "speed"]);
const BROKEN = new Set(["transient", "hard"]);

export function apply(entries, query) {
  const q = { ...DEFAULT_QUERY, ...query };
  const text = q.text.trim().toLowerCase();

  const rows = entries.filter((e) => {
    if (q.hideBroken && e.state && BROKEN.has(levelOf(e.state))) return false;
    if (q.category && e.category !== q.category) return false;
    if (q.auth && e.auth !== (q.auth === AUTH_NONE ? "" : q.auth)) return false;
    if (q.https && !e.https) return false;
    if (q.cors && e.cors !== q.cors) return false;
    if (text) {
      const hay = `${e.name} ${e.description}`.toLowerCase();
      if (!hay.includes(text)) return false;
    }
    return true;
  });

  // Decorate-sort-undecorate keeps the sort stable across engines and keeps the
  // comparator cheap: the level lookup happens once per row, not per comparison.
  const key = (e) => {
    if (q.sort === "name") return e.name.toLowerCase();
    if (q.sort === "speed") return e.response_ms == null ? Infinity : e.response_ms;
    const rank = e.state ? LEVELS.indexOf(levelOf(e.state)) : LEVELS.length;
    return rank < 0 ? LEVELS.length : rank;
  };

  return rows
    .map((e, i) => ({ e, i, k: key(e) }))
    .sort((a, b) => (a.k < b.k ? -1 : a.k > b.k ? 1 : a.i - b.i))
    .map((d) => d.e);
}

export function facets(entries) {
  const uniq = (xs) => [...new Set(xs.filter(Boolean))].sort((a, b) => a.localeCompare(b));
  return {
    categories: uniq(entries.map((e) => e.category)),
    auths: uniq(entries.map((e) => e.auth)),
  };
}

export function toHash(query) {
  const q = { ...DEFAULT_QUERY, ...query };
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v !== DEFAULT_QUERY[k]) p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `#${s}` : "";
}

export function fromHash(hash) {
  const p = new URLSearchParams((hash || "").replace(/^#/, ""));
  const q = { ...DEFAULT_QUERY };
  for (const k of Object.keys(DEFAULT_QUERY)) {
    if (!p.has(k)) continue;
    const raw = p.get(k);
    q[k] = typeof DEFAULT_QUERY[k] === "boolean" ? raw === "true" : raw;
  }
  if (!SORTS.has(q.sort)) q.sort = DEFAULT_QUERY.sort;
  return q;
}
