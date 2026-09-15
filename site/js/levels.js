// The ten probe states collapse to four ordered levels. Ten hues would be
// unreadable and indefensible under colour-vision deficiency, and would encode
// a false claim — that all ten states are peers. They are not: auth_required
// means the domain is alive and gatekeeping, which belongs nowhere near
// dns_failure. The exact state always travels as text, so colour is never the
// only carrier.
export const LEVELS = ["ok", "gated", "transient", "hard"];

const STATE_LEVEL = {
  live: "ok",
  auth_required: "gated",
  rate_limited: "gated",
  client_error: "gated",
  server_error: "transient",
  timeout: "transient",
  not_found: "hard",
  dns_failure: "hard",
  unreachable: "hard",
  tls_invalid: "hard",
};

export const CHAR_STATE = {
  L: "live", A: "auth_required", R: "rate_limited", C: "client_error",
  N: "not_found", S: "server_error", T: "tls_invalid", D: "dns_failure",
  U: "unreachable", X: "timeout",
};

export const STATE_LABEL = {
  live: "Answered",
  auth_required: "Needs a key",
  rate_limited: "Rate limited",
  client_error: "Refused the request",
  not_found: "Page is gone",
  server_error: "Server error",
  timeout: "Timed out",
  tls_invalid: "Certificate problem",
  dns_failure: "Domain does not resolve",
  unreachable: "Nothing listening",
};

export const LEVEL_LABEL = {
  ok: "Answered",
  gated: "Alive, but gated",
  transient: "Failing, often recovers",
  hard: "Failing, usually permanent",
  nodata: "Not probed",
};

// A state this build has never heard of is a later schema, not a healthy API.
// Failing towards "transient" keeps it visible without asserting it is dead.
export function levelOf(state) {
  return STATE_LEVEL[state] || "transient";
}

export function levelOfChar(ch) {
  if (ch === ".") return "nodata";
  const state = CHAR_STATE[ch];
  return state ? levelOf(state) : "nodata";
}
