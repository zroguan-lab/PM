import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type StatusTone = "positive" | "negative" | "neutral" | "warning" | "draft" | "published" | "upcoming" | "muted";

export function StatusBadge({ tone, children, className }: { tone: StatusTone; children: ReactNode; className?: string }) {
  return <span className={cn("status-badge", `status-${tone}`, className)}>{children}</span>;
}
