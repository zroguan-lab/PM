import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function EmptyState({ icon, title, description, className }: { icon?: ReactNode; title: string; description?: string; className?: string }) {
  return <div className={cn("empty-state", className)}>{icon}<p>{title}</p>{description && <span>{description}</span>}</div>;
}
