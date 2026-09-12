"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarDays, ChartNoAxesCombined, FileText, FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";

const navigation = [
  { href: "/today", label: "TODAY", caption: "今日", icon: CalendarDays },
  { href: "/invest", label: "INVEST", caption: "投资", icon: ChartNoAxesCombined },
  { href: "/research", label: "RESEARCH", caption: "研究", icon: FlaskConical },
  { href: "/create", label: "CREATE", caption: "内容", icon: FileText },
] as const;

export function LeftNav() {
  const pathname = usePathname();

  return (
    <aside className="left-nav">
      <div className="brand">
        <span>W40 / OS</span>
        <small>PERSONAL INVESTMENT SYSTEM</small>
      </div>
      <nav aria-label="一级导航" className="nav-list">
        {navigation.map(({ href, label, caption, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link key={href} href={href} className={cn("nav-item", active && "nav-item-active")} aria-current={active ? "page" : undefined}>
              <Icon size={17} strokeWidth={1.7} />
              <span><strong>{label}</strong><small>{caption}</small></span>
            </Link>
          );
        })}
      </nav>
      <div className="system-status"><i /> SYSTEM ONLINE</div>
    </aside>
  );
}
