import { test } from "node:test";
import assert from "node:assert/strict";
import { corrections } from "../js/corrections.js";

const E = (over) => ({
  id: "x", name: "Thing", https: true, cors: "no", state: "live",
  final_url: "https://thing.example/", cors_header: null, failing_streak: 0, ...over,
});

test("flags an entry claiming HTTPS whose final URL is http", () => {
  const rows = [E({ id: "bad", final_url: "http://thing.example/" }), E({ id: "good" })];
  assert.deepEqual(corrections(rows).httpsDowngrade.map((e) => e.id), ["bad"]);
});

test("does not flag an http downgrade on an entry that never claimed https", () => {
  const rows = [E({ https: false, final_url: "http://thing.example/" })];
  assert.equal(corrections(rows).httpsDowngrade.length, 0);
});

test("a dead link needs a confirmed streak, not one bad day", () => {
  const rows = [
    E({ id: "one", state: "not_found", failing_streak: 1 }),
    E({ id: "three", state: "not_found", failing_streak: 3 }),
  ];
  assert.deepEqual(corrections(rows).deadLink.map((e) => e.id), ["three"]);
});

test("cors mismatches are reported only for entries that answered", () => {
  const rows = [
    E({ id: "answered", cors: "yes", cors_header: null }),
    E({ id: "dead", cors: "yes", cors_header: null, state: "dns_failure" }),
  ];
  assert.deepEqual(corrections(rows).corsUnconfirmed.map((e) => e.id), ["answered"]);
});

test("an entry sending an ACAO header is not a cors mismatch", () => {
  const rows = [E({ cors: "yes", cors_header: "*" })];
  assert.equal(corrections(rows).corsUnconfirmed.length, 0);
});
