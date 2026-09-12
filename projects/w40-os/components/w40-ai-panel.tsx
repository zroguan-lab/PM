"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { Bot, ChevronLeft, ChevronRight, Send } from "lucide-react";
import { aiActions, aiActionsByPath } from "@/lib/mock/ui";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/shared/empty-state";
import { cn } from "@/lib/utils";

export function W40AIPanel() {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();
  const actions = aiActionsByPath[pathname as keyof typeof aiActionsByPath] ?? aiActions.default;

  return (
    <aside className={cn("ai-panel", collapsed && "ai-panel-collapsed")}>
      <div className="ai-header">
        <div className="ai-title"><Bot size={18} /><span>W40 AI</span>{!collapsed && <small><i /> READY</small>}</div>
        <Button variant="ghost" size="icon" aria-label={collapsed ? "展开 W40 AI" : "折叠 W40 AI"} onClick={() => setCollapsed((value) => !value)}>
          {collapsed ? <ChevronLeft size={17} /> : <ChevronRight size={17} />}
        </Button>
      </div>
      {!collapsed && (
        <div className="ai-content">
          <p className="eyebrow">CONTEXT ACTIONS</p>
          <div className="ai-actions">{actions.map((action) => <Button variant="outline" size="sm" key={action}>{action}</Button>)}</div>
          <EmptyState className="ai-empty" icon={<Bot size={24} />} title="AI 功能将在后续阶段接入" description="当前仅展示界面与占位交互" />
          <div className="ai-input"><input aria-label="W40 AI 输入" placeholder="询问当前页面…" disabled /><Button size="icon" aria-label="发送" disabled><Send size={16} /></Button></div>
        </div>
      )}
    </aside>
  );
}
