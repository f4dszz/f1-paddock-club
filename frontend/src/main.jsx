import React from "react";
import { createRoot } from "react-dom/client";
import { ClerkProvider } from "@clerk/clerk-react";
import * as Sentry from "@sentry/react";
import App from "../prototype.jsx";
import AuthGate from "../components/AuthGate.jsx";
import { ErrorBoundary, ErrorFallback } from "../components/ErrorBoundary.jsx";

const PUBLISHABLE = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY || "";
const SENTRY_DSN = import.meta.env.VITE_SENTRY_DSN_FRONTEND || "";

// BS-08 — strip auth credentials before any event leaves the browser.
// The WS auth token rides in the URL query string (?token=/&demo_token=), so
// request URLs and breadcrumbs can capture a live Clerk JWT. We scrub those
// query params and drop request URLs from outgoing Sentry events.
//
// KNOWN LIMITATION (BS-08): the deeper fix is to move the WS token out of the
// URL into the Sec-WebSocket-Protocol subprotocol (or a short-lived ticket).
// That is a handshake rewrite (backend + frontend) and is intentionally NOT
// done here per the targeted-fix rule; this scrubber is the mitigation.
const TOKEN_QS = /([?&](?:demo_)?token)=[^&#]*/gi;
function scrubUrl(url) {
  if (typeof url !== "string") return url;
  return url.replace(TOKEN_QS, "$1=***");
}
function sentryBeforeSend(event) {
  try {
    if (event.request) {
      // Do not send the raw request URL (may contain the token query param).
      if (event.request.url) event.request.url = scrubUrl(event.request.url);
      if (event.request.query_string) event.request.query_string = "***";
    }
    if (Array.isArray(event.breadcrumbs)) {
      for (const b of event.breadcrumbs) {
        if (b?.data?.url) b.data.url = scrubUrl(b.data.url);
        if (typeof b?.message === "string") b.message = scrubUrl(b.message);
      }
    }
  } catch {
    // Never let scrubbing throw and lose the safety property.
  }
  return event;
}

if (SENTRY_DSN) {
  Sentry.init({
    dsn: SENTRY_DSN,
    environment: import.meta.env.VITE_APP_ENV || "production",
    tracesSampleRate: 0.1,
    sendDefaultPii: false,
    beforeSend: sentryBeforeSend,
    beforeBreadcrumb(breadcrumb) {
      if (breadcrumb?.data?.url) breadcrumb.data.url = scrubUrl(breadcrumb.data.url);
      return breadcrumb;
    },
  });
}

// frontend-completeness-5 — global handlers so async failures outside a
// try/catch are surfaced/reported instead of silently dropped. When Sentry is
// configured it captures; otherwise we at least log to the console.
if (typeof window !== "undefined") {
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event?.reason;
    if (SENTRY_DSN) Sentry.captureException(reason ?? new Error("unhandledrejection"));
    // eslint-disable-next-line no-console
    console.error("[unhandledrejection]", reason);
  });
  window.addEventListener("error", (event) => {
    if (SENTRY_DSN && event?.error) Sentry.captureException(event.error);
    // eslint-disable-next-line no-console
    console.error("[window.error]", event?.message || event?.error || event);
  });
}

// frontend-completeness-1 — prefer Sentry's boundary (reports render errors)
// when a DSN is set, else fall back to the custom class boundary so the
// no-DSN build still shows a recovery card instead of a blank screen.
function withBoundary(node) {
  if (SENTRY_DSN) {
    return (
      <Sentry.ErrorBoundary fallback={<ErrorFallback />}>
        {node}
      </Sentry.ErrorBoundary>
    );
  }
  return <ErrorBoundary>{node}</ErrorBoundary>;
}

const inner = PUBLISHABLE ? (
  <ClerkProvider publishableKey={PUBLISHABLE} afterSignOutUrl="/">
    <AuthGate>
      <App />
    </AuthGate>
  </ClerkProvider>
) : (
  <App />
);

createRoot(document.getElementById("root")).render(withBoundary(inner));
