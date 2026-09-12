import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Timeline({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("timeline", className)}>{children}</div>;
}

export function TimelineRow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("timeline-row", className)}>{children}</div>;
}
