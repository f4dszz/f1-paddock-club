import { SignIn } from "@clerk/clerk-react";

export default function SignInPage() {
  return (
    <div
      data-testid="sign-in-page"
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#0a0a0a",
        padding: "24px",
      }}
    >
      <div style={{ textAlign: "center", color: "#fff" }}>
        <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>
          F1 Paddock Club
        </div>
        <div style={{ fontSize: 12, color: "#888", marginBottom: 16 }}>
          Sign in to plan and save your race weekend trips.
        </div>
        <SignIn routing="hash" />
      </div>
    </div>
  );
}
