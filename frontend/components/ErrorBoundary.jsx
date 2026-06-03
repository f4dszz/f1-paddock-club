// frontend-completeness-1 / BS-08 — App-wide error boundary.
//
// React 19 unmounts the ENTIRE tree on an uncaught render error, leaving a
// permanently blank black screen (body #0a0a0a) with no recovery. This wraps
// the app so any render throw shows a "Something went wrong — Reload" card
// instead of a blank page.
//
// main.jsx prefers Sentry.ErrorBoundary (which also reports the error to
// Sentry) when a DSN is configured; this custom class is the fallback used
// when Sentry is not initialized, so the no-DSN local/prod build still gets a
// graceful failure UI.
import { Component } from "react";

// Shared fallback UI, reused by both this class boundary and
// Sentry.ErrorBoundary in main.jsx.
export function ErrorFallback() {
  return (
    <div
      data-testid="app-error-fallback"
      role="alert"
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#0a0a0a",
        color: "#fff",
        fontFamily: "'DM Sans', sans-serif",
        padding: "24px",
        boxSizing: "border-box",
      }}
    >
      <div
        style={{
          maxWidth: 360,
          width: "100%",
          background: "#111",
          border: "1px solid #E1060044",
          borderRadius: 12,
          padding: "24px 20px",
          textAlign: "center",
        }}
      >
        <div style={{ fontSize: 28, marginBottom: 8 }}>🏁</div>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 8 }}>
          Something went wrong
        </div>
        <div style={{ fontSize: 12, color: "#888", lineHeight: 1.5, marginBottom: 18 }}>
          The page hit an unexpected error. Reloading usually fixes it.
        </div>
        <button
          type="button"
          data-testid="app-error-reload"
          onClick={() => window.location.reload()}
          style={{
            padding: "10px 18px",
            borderRadius: 8,
            border: "none",
            background: "#E10600",
            color: "#fff",
            fontSize: 13,
            fontWeight: 700,
            cursor: "pointer",
          }}
        >
          Reload
        </button>
      </div>
    </div>
  );
}

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    // Sentry (when present) is wired via main.jsx's Sentry.ErrorBoundary, so
    // this class is the no-DSN path: log so the error is not silently dropped.
    // eslint-disable-next-line no-console
    console.error("[error-boundary]", error, info?.componentStack || "");
  }

  render() {
    if (this.state.hasError) return <ErrorFallback />;
    return this.props.children;
  }
}

export default ErrorBoundary;
