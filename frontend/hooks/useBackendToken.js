// Token resolution for backend HTTP + WS calls.
//
// In Clerk mode (VITE_CLERK_PUBLISHABLE_KEY set), useBackendToken returns a
// hook that pulls the current Clerk JWT via useAuth().getToken(). In demo
// mode, useDemoToken returns a stable fallback that reads VITE_DEMO_TOKEN.
//
// The two paths are SEPARATE hooks because conditionally calling useAuth()
// would break Rules of Hooks. The call site picks one based on
// import.meta.env.VITE_CLERK_PUBLISHABLE_KEY at module load, which is
// build-time constant, so the choice is stable per bundle.
import { useAuth } from "@clerk/clerk-react";
import { useCallback } from "react";

const DEMO_TOKEN = import.meta.env.VITE_DEMO_TOKEN || "";

export function useBackendToken() {
  const { isSignedIn, getToken } = useAuth();
  const fetcher = useCallback(async () => {
    if (isSignedIn) {
      try {
        const t = await getToken();
        if (t) return t;
      } catch (_) {
        // fall through to demo
      }
    }
    return DEMO_TOKEN || "";
  }, [isSignedIn, getToken]);
  return { getToken: fetcher };
}

export function useDemoToken() {
  const fetcher = useCallback(async () => DEMO_TOKEN || "", []);
  return { getToken: fetcher };
}
