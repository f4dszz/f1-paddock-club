import { UserButton } from "@clerk/clerk-react";

export default function UserMenu() {
  return (
    <span data-testid="user-menu" style={{ display: "inline-flex", alignItems: "center" }}>
      <UserButton afterSignOutUrl="/" appearance={{ elements: { avatarBox: { width: 28, height: 28 } } }} />
    </span>
  );
}
