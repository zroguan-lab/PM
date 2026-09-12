import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type PageHeaderProps = {
  eyebrow: string;
  title: string;
  subtitle: string;
  updatedAt?: ReactNode;
  actions?: ReactNode;
  className?: string;
};

export function PageHeader({ eyebrow, title, subtitle, updatedAt, actions, className }: PageHeaderProps) {
  const aside = actions ?? updatedAt;

  return (
    <header className={cn("workspace-page-header", className)}>
      <div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{subtitle}</p></div>
      {aside}
    </header>
  );
}
