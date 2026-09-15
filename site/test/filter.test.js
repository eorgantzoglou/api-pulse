import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_QUERY, AUTH_NONE, apply, facets, toHash, fromHash } from "../js/filter.js";

const E = (over) => ({
  id: "x", name: "Thing", description: "does things", category: "Animals",
  auth: "", https: true, cors: "yes", state: "live", response_ms: 100,
  failing_streak: 0, likely_dead: false, history: "LLL", ...over,
});

test("hides broken entries by default", () => {
  assert.equal(DEFAULT_QUERY.hideBroken, true);
  const rows = [E({ id: "ok" }), E({ id: "bad", state: "not_found" })];
  assert.deepEqual(apply(rows, DEFAULT_QUERY).map((r) => r.id), ["ok"]);
});

test("gated entries survive hideBroken — the domain answered", () => {
  const rows = [E({ id: "key", state: "auth_required" }), E({ id: "lim", state: "rate_limited" })];
  assert.equal(apply(rows, DEFAULT_QUERY).length, 2);
});

test("turning hideBroken off shows everything", () => {
  const rows = [E({ id: "ok" }), E({ id: "bad", state: "dns_failure" })];
  assert.equal(apply(rows, { ...DEFAULT_QUERY, hideBroken: false }).length, 2);
});

test("keyword search matches name and description, case-insensitively", () => {
  const rows = [E({ id: "a", name: "Weather Co" }), E({ id: "b", description: "forecast data" })];
  assert.deepEqual(apply(rows, { ...DEFAULT_QUERY, text: "weather" }).map((r) => r.id), ["a"]);
  assert.deepEqual(apply(rows, { ...DEFAULT_QUERY, text: "FORECAST" }).map((r) => r.id), ["b"]);
});

test("filters by category, auth, https and cors", () => {
  const rows = [
    E({ id: "a", category: "Animals", auth: "apiKey", https: true, cors: "yes" }),
    E({ id: "b", category: "Weather", auth: "", https: false, cors: "no" }),
  ];
  assert.deepEqual(apply(rows, { ...DEFAULT_QUERY, category: "Weather" }).map((r) => r.id), ["b"]);
  assert.deepEqual(apply(rows, { ...DEFAULT_QUERY, auth: "apiKey" }).map((r) => r.id), ["a"]);
  assert.deepEqual(apply(rows, { ...DEFAULT_QUERY, cors: "yes" }).map((r) => r.id), ["a"]);
  assert.deepEqual(apply(rows, { ...DEFAULT_QUERY, https: true }).map((r) => r.id), ["a"]);
});

test('an auth filter of "" means any, not "no key needed"', () => {
  const rows = [E({ id: "a", auth: "apiKey" }), E({ id: "b", auth: "" })];
  assert.equal(apply(rows, DEFAULT_QUERY).length, 2);
});

test("AUTH_NONE selects only entries that need no key", () => {
  // "No key needed" is the single most common thing a developer filters for, and
  // an empty string already means "any". It needs its own sentinel or it is
  // unreachable from the UI.
  const rows = [E({ id: "key", auth: "apiKey" }), E({ id: "free", auth: "" })];
  assert.deepEqual(apply(rows, { ...DEFAULT_QUERY, auth: AUTH_NONE }).map((r) => r.id), ["free"]);
});

test("reliability sort puts healthy first and hard failures last", () => {
  const rows = [
    E({ id: "hard", state: "not_found" }),
    E({ id: "ok", state: "live" }),
    E({ id: "gated", state: "auth_required" }),
  ];
  const got = apply(rows, { ...DEFAULT_QUERY, hideBroken: false, sort: "reliability" });
  assert.deepEqual(got.map((r) => r.id), ["ok", "gated", "hard"]);
});

test("speed sort is ascending and puts unmeasured entries last", () => {
  const rows = [
    E({ id: "slow", response_ms: 900 }),
    E({ id: "none", response_ms: null }),
    E({ id: "fast", response_ms: 50 }),
  ];
  const got = apply(rows, { ...DEFAULT_QUERY, sort: "speed" });
  assert.deepEqual(got.map((r) => r.id), ["fast", "slow", "none"]);
});

test("sorting is stable for equal keys", () => {
  const rows = [E({ id: "a" }), E({ id: "b" }), E({ id: "c" })];
  assert.deepEqual(apply(rows, DEFAULT_QUERY).map((r) => r.id), ["a", "b", "c"]);
});

test("facets are sorted and de-duplicated", () => {
  const rows = [E({ category: "Weather", auth: "apiKey" }), E({ category: "Animals", auth: "apiKey" })];
  const f = facets(rows);
  assert.deepEqual(f.categories, ["Animals", "Weather"]);
  assert.deepEqual(f.auths, ["apiKey"]);
});

test("a query round-trips through the URL hash", () => {
  const q = { ...DEFAULT_QUERY, text: "weather map", category: "Weather", hideBroken: false };
  assert.deepEqual(fromHash(toHash(q)), q);
});

test("the default query produces an empty hash, and an empty hash the default query", () => {
  assert.equal(toHash(DEFAULT_QUERY), "");
  assert.deepEqual(fromHash(""), DEFAULT_QUERY);
  assert.deepEqual(fromHash("#"), DEFAULT_QUERY);
});

test("an unknown sort in the hash falls back to the default rather than throwing", () => {
  assert.equal(fromHash("#sort=nonsense").sort, DEFAULT_QUERY.sort);
});
