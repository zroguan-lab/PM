import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type SectionHeaderProps = {
  eyebrow: string;
  title: string;
  id?: string;
  action?: ReactNode;
  variant?: "card" | "document" | "compact";
  className?: string;
};

export function SectionHeader({ eyebrow, title, id, action, variant = "card", className }: SectionHeaderProps) {
  return (
    <header className={cn("shared-section-header", `shared-section-${variant}`, variant === "card" && "section-heading", className)}>
      <div><p className="eyebrow">{eyebrow}</p><h2 id={id}>{title}</h2></div>
      {action}
    </header>
  );
}
