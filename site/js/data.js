const CATALOG = "./data/catalog.json";
const STATUS = "./data/status.json";

async function getJson(fetchImpl, url) {
  const res = await fetchImpl(url);
  if (!res.ok) throw new Error(`Could not load ${url} (HTTP ${res.status})`);
  return res.json();
}

// The catalogue is the source of truth for what exists. An entry with no status
// row is kept and rendered as unmeasured rather than silently vanishing — the
// alternative hides entries precisely when something has gone wrong upstream.
export async function load(fetchImpl = fetch) {
  const [catalog, status] = await Promise.all([
    getJson(fetchImpl, CATALOG),
    getJson(fetchImpl, STATUS),
  ]);

  const byId = new Map(status.entries.map((s) => [s.id, s]));
  const entries = catalog.entries.map((c) => {
    const s = byId.get(c.id) || {};
    return { ...c, ...s, history: s.history || "" };
  });

  return { generated: status.generated || catalog.generated, entries };
}
