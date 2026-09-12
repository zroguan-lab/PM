import type { ReactNode } from "react";
import { CommandBar } from "@/components/command-bar";
import { LeftNav } from "@/components/left-nav";
import { MainWorkspace } from "@/components/main-workspace";
import { W40AIPanel } from "@/components/w40-ai-panel";

export function AppShell({ children }: { children: ReactNode }) {
  return <div className="app-shell"><LeftNav /><CommandBar /><MainWorkspace>{children}</MainWorkspace><W40AIPanel /></div>;
}
