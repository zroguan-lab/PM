import type { ReactNode } from "react";

export function MainWorkspace({ children }: { children: ReactNode }) {
  return <main className="main-workspace">{children}</main>;
}
