import { levelOf } from "./levels.js";

const DEAD_AFTER = 3;

export function corrections(entries) {
  const answered = (e) => e.state && ["ok", "gated"].includes(levelOf(e.state));

  return {
    // Claimed HTTPS, ended up on http:// after redirects. Strong evidence.
    httpsDowngrade: entries.filter(
      (e) => e.https && e.final_url && e.final_url.startsWith("http://")
    ),
    // Confirmed by the same flap filter the pipeline uses. One bad day is not a
    // finding, and submitting it upstream as one would be wrong.
    deadLink: entries.filter((e) => (e.failing_streak || 0) >= DEAD_AFTER),
    // Deliberately NOT called a mismatch: we probe the documentation URL, not
    // the API endpoint, so a missing header here does not prove the claim wrong.
    corsUnconfirmed: entries.filter((e) => e.cors === "yes" && !e.cors_header && answered(e)),
  };
}
