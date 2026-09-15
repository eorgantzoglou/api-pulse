import { test } from "node:test";
import assert from "node:assert/strict";
import { LEVELS, levelOf, levelOfChar, CHAR_STATE, STATE_LABEL } from "../js/levels.js";

test("every one of the ten states maps to a level", () => {
  const states = ["live","auth_required","rate_limited","client_error","not_found",
                  "server_error","tls_invalid","dns_failure","unreachable","timeout"];
  for (const s of states) assert.ok(LEVELS.includes(levelOf(s)), `${s} -> ${levelOf(s)}`);
});

test("the alive states are ok or gated, and nothing else is", () => {
  assert.equal(levelOf("live"), "ok");
  for (const s of ["auth_required","rate_limited","client_error"]) {
    assert.equal(levelOf(s), "gated", s);
  }
  for (const s of ["server_error","timeout"]) assert.equal(levelOf(s), "transient", s);
  for (const s of ["not_found","dns_failure","unreachable","tls_invalid"]) {
    assert.equal(levelOf(s), "hard", s);
  }
});

test("an unknown state does not throw and is not treated as healthy", () => {
  assert.notEqual(levelOf("brand_new_state_from_a_later_schema"), "ok");
});

test("the character vocabulary round-trips against the states", () => {
  assert.equal(Object.keys(CHAR_STATE).length, 10);
  assert.equal(new Set(Object.values(CHAR_STATE)).size, 10);
  for (const [ch, state] of Object.entries(CHAR_STATE)) {
    assert.equal(levelOfChar(ch), levelOf(state), ch);
  }
});

test("a no-data day is its own level, not a failure", () => {
  assert.equal(levelOfChar("."), "nodata");
  assert.notEqual(levelOfChar("."), "hard");
});

test("every state has a human label", () => {
  for (const state of Object.values(CHAR_STATE)) {
    assert.ok(STATE_LABEL[state] && STATE_LABEL[state].length > 0, state);
  }
});
