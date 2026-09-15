import { test } from "node:test";
import assert from "node:assert/strict";
import { stripCells } from "../js/strip.js";

test("one cell per recorded day, oldest first", () => {
  const cells = stripCells("LLN");
  assert.equal(cells.length, 90);
  assert.deepEqual(cells.slice(-3).map((c) => c.level), ["ok", "ok", "hard"]);
});

test("the last cell is today", () => {
  const cells = stripCells("LLN");
  assert.equal(cells.at(-1).offsetFromToday, 0);
  assert.equal(cells.at(-3).offsetFromToday, 2);
});

test("a short history is left-padded with no-data so every strip aligns", () => {
  const cells = stripCells("L", 5);
  assert.equal(cells.length, 5);
  assert.deepEqual(cells.map((c) => c.level), ["nodata", "nodata", "nodata", "nodata", "ok"]);
});

test("an empty history is all no-data, not all failure", () => {
  const cells = stripCells("", 3);
  assert.ok(cells.every((c) => c.level === "nodata"));
});

test("a history longer than the window keeps the most recent days", () => {
  const cells = stripCells("NNNLLL", 3);
  assert.ok(cells.every((c) => c.level === "ok"));
});

test("each cell carries its exact state so colour is never the only carrier", () => {
  assert.equal(stripCells("A", 1)[0].state, "auth_required");
  assert.equal(stripCells(".", 1)[0].state, null);
});

test("a gap inside the history keeps day offsets honest", () => {
  // The pipeline fills days it did not run with ".", so position is day offset.
  const cells = stripCells("L.....L", 7);
  assert.equal(cells.at(-1).offsetFromToday, 0);
  assert.equal(cells[0].offsetFromToday, 6);
  assert.equal(cells[0].level, "ok");
  assert.ok(cells.slice(1, 6).every((c) => c.level === "nodata"));
});
