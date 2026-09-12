"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, FileText, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { contentIdeas, contents } from "@/lib/mock/contents";
import { getContentSourceLabel, getEntityLabel, getSourcePath } from "@/lib/mock/selectors";
import type { Content } from "@/lib/types";
import { PageHeader } from "@/components/shared/page-header";
import { SectionHeader } from "@/components/shared/section-header";
import { StatusBadge } from "@/components/shared/status-badge";

const CONTENT_STORAGE_KEY = "w40.create.contents.v2";

export function ContentWorkspace() {
  const [documents, setDocuments] = useState<Content[]>([...contents]);
  const [activeId, setActiveId] = useState(contents[0].id);
  const [saveState, setSaveState] = useState("LOCAL DRAFT");
  const activeDocument = documents.find((document) => document.id === activeId) ?? documents[0];
  const publishedDocuments = documents.filter((document) => document.status === "PUBLISHED");
  const sourcePath = getSourcePath(activeDocument.sourceType);
  const sourceLabel = getEntityLabel(activeDocument.sourceType, activeDocument.sourceId);

  useEffect(() => {
    const restore = window.setTimeout(() => {
      try {
        const saved = localStorage.getItem(CONTENT_STORAGE_KEY);
        if (saved) setDocuments(JSON.parse(saved));
      } catch {
        setDocuments([...contents]);
      }
    }, 0);
    return () => window.clearTimeout(restore);
  }, []);

  useEffect(() => {
    const autosave = window.setTimeout(() => {
      localStorage.setItem(CONTENT_STORAGE_KEY, JSON.stringify(documents));
      setSaveState("AUTOSAVED");
    }, 500);
    return () => window.clearTimeout(autosave);
  }, [documents]);

  const wordCount = useMemo(() => activeDocument.body.trim().length, [activeDocument.body]);

  function updateActive(patch: Partial<Content>) {
    setDocuments((current) => current.map((document) => document.id === activeId ? { ...document, ...patch, updatedAt: "JUST NOW" } : document));
    setSaveState("SAVING");
  }

  function saveDraft() {
    updateActive({ status: "DRAFT" });
    setSaveState("SAVED");
  }

  function markPublished() {
    updateActive({ status: "PUBLISHED", publishedAt: "2026-09-10 11:30" });
    setSaveState("PUBLISHED");
  }

  function openIdea(idea: (typeof contentIdeas)[number]) {
    const existing = documents.find((document) => document.title === idea.title);
    if (existing) {
      setActiveId(existing.id);
      return;
    }
    const next: Content = {
      id: idea.id,
      title: idea.title,
      body: "## 核心观点\n\n在这里开始整理你的判断。",
      sourceType: idea.sourceType,
      sourceId: idea.sourceId,
      createdAt: "2026-09-11",
      updatedAt: "JUST NOW",
      status: "DRAFT",
    };
    setDocuments((current) => [next, ...current]);
    setActiveId(next.id);
  }

  return (
    <section className="create-page">
      <PageHeader className="create-heading" eyebrow="CREATE" title="内容" subtitle="哪些研究和投资认知值得输出？" updatedAt={<span>{saveState}</span>} />

      <div className="create-layout">
        <aside className="content-sidebar">
          <section aria-labelledby="drafts-heading">
            <SectionHeader variant="compact" eyebrow="DRAFTS" title="草稿" id="drafts-heading" action={<span>{documents.length}</span>} />
            <div className="document-list">
              {documents.slice(0, 5).map((document) => (
                <button key={document.id} className={cn("document-item", document.id === activeId && "document-item-active")} onClick={() => setActiveId(document.id)}>
                  <strong>{document.title}</strong><span><b>{getContentSourceLabel(document.sourceType)}</b><time>{document.updatedAt}</time><StatusBadge tone={document.status === "PUBLISHED" ? "published" : "draft"}>{document.status}</StatusBadge></span>
                </button>
              ))}
            </div>
          </section>

          <section aria-labelledby="ideas-heading">
            <SectionHeader variant="compact" eyebrow="IDEAS" title="选题池" id="ideas-heading" action={<span>5</span>} />
            <div className="idea-list">
              {contentIdeas.map((idea) => <button key={idea.id} onClick={() => openIdea(idea)}><strong>{idea.title}</strong><span><b>{getContentSourceLabel(idea.sourceType)}</b><em>{idea.tag}</em></span></button>)}
            </div>
          </section>

          <section aria-labelledby="published-heading">
            <SectionHeader variant="compact" eyebrow="PUBLISHED" title="已发布" id="published-heading" action={<span>{publishedDocuments.length}</span>} />
            <div className="published-list">
              {publishedDocuments.map((document) => <button key={document.id} onClick={() => setActiveId(document.id)}><strong>{document.title}</strong><span>{document.publishedAt} · {getContentSourceLabel(document.sourceType)}</span></button>)}
            </div>
          </section>
        </aside>

        <main className="content-editor" aria-label="当前编辑器">
          <header className="editor-toolbar">
            <div><FileText size={14} /><span>{activeDocument.status}</span><i /> <span>{wordCount} 字符</span></div>
            <div><Button variant="outline" size="sm" onClick={saveDraft}><Save size={13} />保存草稿</Button><Button size="sm" onClick={markPublished}><Check size={13} />标记已发布</Button></div>
          </header>
          <input className="editor-title" aria-label="内容标题" value={activeDocument.title} onChange={(event) => updateActive({ title: event.target.value })} />
          <textarea className="editor-body" aria-label="内容正文" value={activeDocument.body} onChange={(event) => updateActive({ body: event.target.value })} spellCheck={false} />
          <footer className="editor-source">
            <span>SOURCE</span><strong>{sourceLabel} / {getContentSourceLabel(activeDocument.sourceType)}</strong>
            {sourcePath && <Link href={sourcePath}>{activeDocument.sourceType === "Asset" ? "查看投资页" : "查看研究页"}<ArrowRight size={12} /></Link>}
          </footer>
        </main>
      </div>
    </section>
  );
}
