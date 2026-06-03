// BS-14 — Vendor-neutral, no-op product-analytics seam.
//
// PRIVACY NOTE: This module is intentionally inert by default. It collects and
// sends NOTHING unless a VITE_ANALYTICS_* env var is configured at build time
// (VITE_ANALYTICS_ENABLED=1, optionally with VITE_ANALYTICS_ENDPOINT). We do
// NOT bundle any third-party analytics SDK (no GA/PostHog/Mixpanel/Plausible),
// so there are no cookies, no fingerprinting, and no cross-site beacons in the
// default build. When enabled, only the named funnel event + the small,
// explicitly-passed `props` object are sent — never free-text user input,
// auth tokens, budgets tied to identity, or PII. Callers must keep props
// coarse (e.g. {gp:"Italian GP", currency:"EUR"}), not raw form contents.
//
// The seam exists so the core funnel (calendar view -> GP select -> plan run
// -> save) has a single, swappable instrumentation point. To wire a real
// provider later, replace ONLY the body of `dispatch()` below.

const ANALYTICS_ENABLED =
  String(import.meta.env.VITE_ANALYTICS_ENABLED || "") === "1";
const ANALYTICS_ENDPOINT = import.meta.env.VITE_ANALYTICS_ENDPOINT || "";

// Swappable sink. Default: best-effort fire-and-forget beacon to a first-party
// endpoint, only when explicitly enabled. Never throws into the caller.
function dispatch(event, props) {
  if (!ANALYTICS_ENDPOINT) return; // enabled but no endpoint => still a no-op
  try {
    const body = JSON.stringify({ event, props, ts: Date.now() });
    if (typeof navigator !== "undefined" && navigator.sendBeacon) {
      navigator.sendBeacon(ANALYTICS_ENDPOINT, body);
    } else if (typeof fetch !== "undefined") {
      // keepalive lets the request outlive a page transition.
      fetch(ANALYTICS_ENDPOINT, {
        method: "POST",
        body,
        keepalive: true,
        headers: { "Content-Type": "application/json" },
      }).catch(() => {});
    }
  } catch {
    // Analytics must never break the app or surface to the user.
  }
}

/**
 * track(event, props) — record a single product-funnel event.
 * No-op unless VITE_ANALYTICS_ENABLED=1. Safe to call anywhere; never throws.
 * @param {string} event  short funnel-step name, e.g. "calendar_view"
 * @param {object} [props] small, non-PII property bag
 */
export function track(event, props = {}) {
  if (!ANALYTICS_ENABLED) return;
  if (!event || typeof event !== "string") return;
  dispatch(event, props || {});
}

export const ANALYTICS_ON = ANALYTICS_ENABLED;
