import { SignedIn, SignedOut } from "@clerk/clerk-react";
import SignInPage from "./SignInPage.jsx";

export default function AuthGate({ children }) {
  return (
    <>
      <SignedIn>{children}</SignedIn>
      <SignedOut>
        <SignInPage />
      </SignedOut>
    </>
  );
}
