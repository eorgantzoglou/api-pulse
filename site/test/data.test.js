import { test } from "node:test";
import assert from "node:assert/strict";
import { load } from "../js/data.js";

const catalog = {
  generated: "2026-09-09", schema: 1, count: 2,
  entries: [
    { id: "a--one", name: "One", url: "https://one.example/", description: "First",
      category: "Animals", auth: "apiKey", https: true, cors: "yes" },
    { id: "a--two", name: "Two", url: "https://two.example/", description: "Second",
      category: "Weather", auth: "", https: true, cors: "no" },
  ],
};
const status = {
  generated: "2026-09-09", schema: 1,
  entries: [
    { id: "a--one", state: "live", status_code: 200, final_url: "https://one.example/",
      response_ms: 120, tls_valid: true, cors_header: "*", failing_streak: 0,
      likely_dead: false, history: "LLL" },
    { id: "a--two", state: "not_found", status_code: 404, final_url: "https://two.example/",
      response_ms: 90, tls_valid: true, cors_header: null, failing_streak: 3,
      likely_dead: true, history: "NNN" },
  ],
};

function fetchOf(map) {
  return async (url) => {
    const key = Object.keys(map).find((k) => url.includes(k));
    if (!key) return { ok: false, status: 404 };
    return { ok: true, status: 200, json: async () => map[key] };
  };
}

test("joins catalogue and status on id", async () => {
  const { entries } = await load(fetchOf({ catalog, status }));
  assert.equal(entries.length, 2);
  const one = entries.find((e) => e.id === "a--one");
  assert.equal(one.name, "One");
  assert.equal(one.state, "live");
  assert.equal(one.category, "Animals");
});

test("exposes the generated date", async () => {
  const { generated } = await load(fetchOf({ catalog, status }));
  assert.equal(generated, "2026-09-09");
});

test("an entry present in the catalogue but absent from status is kept, not dropped", async () => {
  const partial = { ...status, entries: [status.entries[0]] };
  const { entries } = await load(fetchOf({ catalog, status: partial }));
  assert.equal(entries.length, 2);
  const two = entries.find((e) => e.id === "a--two");
  assert.equal(two.state, undefined);
  assert.equal(two.history, "");
});

test("a failed fetch rejects with a message naming the file", async () => {
  const bad = async () => ({ ok: false, status: 500 });
  await assert.rejects(() => load(bad), /catalog\.json/);
});
