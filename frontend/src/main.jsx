import React from "react";
import { createRoot } from "react-dom/client";
import { ClerkProvider } from "@clerk/clerk-react";
import * as Sentry from "@sentry/react";
import App from "../prototype.jsx";
import AuthGate from "../components/AuthGate.jsx";

const PUBLISHABLE = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY || "";
const SENTRY_DSN = import.meta.env.VITE_SENTRY_DSN_FRONTEND || "";

if (SENTRY_DSN) {
  Sentry.init({
    dsn: SENTRY_DSN,
    environment: import.meta.env.VITE_APP_ENV || "production",
    tracesSampleRate: 0.1,
  });
}

const tree = PUBLISHABLE ? (
  <ClerkProvider publishableKey={PUBLISHABLE} afterSignOutUrl="/">
    <AuthGate>
      <App />
    </AuthGate>
  </ClerkProvider>
) : (
  <App />
);

createRoot(document.getElementById("root")).render(tree);
