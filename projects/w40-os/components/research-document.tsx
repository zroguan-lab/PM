import Link from "next/link";
import { ArrowRight, CircleDot, Clock3 } from "lucide-react";
import {
  evidence,
} from "@/lib/mock/evidence";
import {
  openResearchQuestions,
  researchQuestions,
  researchSources,
  topics,
  primaryResearchTopicId,
} from "@/lib/mock/topics";
import { getAssetsForTopic } from "@/lib/mock/selectors";
import { primaryInvestAssetId } from "@/lib/mock/assets";
import type { Evidence } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/shared/page-header";
import { SectionHeader } from "@/components/shared/section-header";
import { StatusBadge } from "@/components/shared/status-badge";

export function ResearchDocument() {
  const researchTopic = topics.find((topic) => topic.id === primaryResearchTopicId);
  if (!researchTopic) throw new Error("Research topic is missing");
  const topicQuestions = researchQuestions.filter((question) => question.topicId === researchTopic.id);
  const supportingEvidence = evidence.filter((item) => item.topicId === researchTopic.id && item.side === "support");
  const counterEvidence = evidence.filter((item) => item.topicId === researchTopic.id && item.side === "counter");
  const topicOpenQuestions = openResearchQuestions.filter((question) => question.topicId === researchTopic.id);
  const topicSources = researchSources.filter((source) => source.topicId === researchTopic.id);
  const relatedAssets = getAssetsForTopic(researchTopic.id);
  return (
    <article className="research-page">
      <PageHeader className="research-header" eyebrow="RESEARCH" title="研究" subtitle="我的判断依据是什么？" updatedAt={<div className="topic-meta"><span>CURRENT TOPIC</span><strong>{researchTopic.name}</strong><time><Clock3 size={12} />{researchTopic.updatedAt}</time></div>} />

      <section className="thesis-block" aria-labelledby="thesis-heading">
        <p className="eyebrow">THESIS</p>
        <h2 id="thesis-heading">当前 Thesis</h2>
        <blockquote>{researchTopic.thesis}</blockquote>
        <div className="related-assets"><span>关联资产</span>{relatedAssets.map((asset) => asset.id === primaryInvestAssetId ? <Link href="/invest" key={asset.id}>{asset.ticker}<ArrowRight size={11} /></Link> : <span className="related-asset" key={asset.id}>{asset.ticker}</span>)}</div>
      </section>

      <DocumentSection eyebrow="CORE QUESTIONS" title="核心问题" id="core-questions">
        <ol className="research-question-list">
          {topicQuestions.map((item, index) => (
            <li key={item.question}><span className="question-number">0{index + 1}</span><p>{item.question}</p><StatusBadge className="research-status" tone={item.status === "已验证" ? "positive" : item.status === "进行中" ? "warning" : "muted"}>{item.status}</StatusBadge></li>
          ))}
        </ol>
      </DocumentSection>

      <div className="evidence-columns">
        <DocumentSection eyebrow="SUPPORT" title="支持证据" id="supporting-evidence" tone="support">
          <EvidenceList items={supportingEvidence} />
        </DocumentSection>
        <DocumentSection eyebrow="COUNTER" title="反对证据" id="counter-evidence" tone="counter">
          <EvidenceList items={counterEvidence} />
        </DocumentSection>
      </div>

      <DocumentSection eyebrow="OPEN QUESTIONS" title="待验证问题" id="open-questions">
        <div className="open-question-list">
          {topicOpenQuestions.map((item) => (
            <div key={item.question}><CircleDot size={14} /><div><strong>{item.question}</strong><p>{item.note}</p></div><span>{item.status}</span></div>
          ))}
        </div>
      </DocumentSection>

      <DocumentSection eyebrow="SOURCES" title="资料来源" id="research-sources">
        <div className="source-list">
          {topicSources.map((source) => <div key={source.type}><strong>{source.type}</strong><span>{source.count} ITEMS</span><time>{source.updatedAt}</time></div>)}
        </div>
      </DocumentSection>
    </article>
  );
}

function DocumentSection({ eyebrow, title, id, tone, children }: { eyebrow: string; title: string; id: string; tone?: "support" | "counter"; children: React.ReactNode }) {
  return <section className={cn("document-section", tone && `document-${tone}`)} aria-labelledby={id}><SectionHeader variant="document" eyebrow={eyebrow} title={title} id={id} />{children}</section>;
}

function EvidenceList({ items }: { items: ReadonlyArray<Evidence> }) {
  return <div className="evidence-list">{items.map((item) => <article key={item.title}><div><h3>{item.title}</h3><p>{item.note}</p><footer><time>{item.date}</time><span>{item.source}</span></footer></div></article>)}</div>;
}
