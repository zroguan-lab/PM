import { CalendarClock, Link2 } from "lucide-react";
import {
  assets,
  investAssetIds,
  primaryInvestAssetId,
} from "@/lib/mock/assets";
import { changes } from "@/lib/mock/changes";
import { decisions } from "@/lib/mock/decisions";
import { metrics } from "@/lib/mock/metrics";
import { getAsset, getTopicsForAsset, formatMockDate } from "@/lib/mock/selectors";
import { actionRules, catalysts } from "@/lib/mock/ui";
import { primaryInvestTopicId } from "@/lib/mock/topics";
import type { Direction } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/shared/page-header";
import { SectionHeader } from "@/components/shared/section-header";
import { StatusBadge, type StatusTone } from "@/components/shared/status-badge";
import { Timeline, TimelineRow } from "@/components/shared/timeline";

const impactLabels: Record<Direction, string> = { positive: "正面", neutral: "中性", negative: "负面" };

export function InvestDashboard() {
  const selectedAsset = getAsset(primaryInvestAssetId);
  const investAssets = investAssetIds.map((id) => assets.find((asset) => asset.id === id)).filter((asset) => asset !== undefined);
  const assetChanges = changes.filter((change) => change.relatedType === "Asset" && change.relatedId === selectedAsset.id);
  const assetMetrics = metrics.filter((metric) => metric.assetId === selectedAsset.id);
  const assetDecisions = decisions.filter((decision) => decision.assetId === selectedAsset.id);
  const assetRules = actionRules.filter((rule) => rule.assetId === selectedAsset.id);
  const assetCatalysts = catalysts.filter((catalyst) => catalyst.assetId === selectedAsset.id);
  const relatedTopic = getTopicsForAsset(selectedAsset.id).find((topic) => topic.id === primaryInvestTopicId);
  if (!relatedTopic) throw new Error("Related investment topic is missing");
  return (
    <section className="invest-page">
      <PageHeader className="invest-heading" eyebrow="INVEST" title="投资" subtitle="这个资产现在是什么状态，我要怎么做？" updatedAt={<div className="invest-updated"><span>LAST UPDATED</span><time>{selectedAsset.updatedAt}</time></div>} />

      <div className="asset-strip" aria-label="股票列表">
        {investAssets.map((asset) => (
          <div className={cn("asset-item", asset.id === selectedAsset.id && "asset-selected")} key={asset.ticker} aria-current={asset.id === selectedAsset.id ? "true" : undefined}>
            <div className="asset-name"><strong>{asset.ticker}</strong><span>{asset.name}</span></div>
            <div className="asset-price"><strong>{asset.price}</strong><span className={asset.dayChange.startsWith("-") ? "value-negative" : "value-positive"}>{asset.dayChange}</span></div>
            <span className="asset-status">{asset.fundamentalStatus}</span>
          </div>
        ))}
      </div>

      <section className="asset-overview" aria-labelledby="asset-overview-heading">
        <div className="overview-primary">
          <div><p className="eyebrow">SELECTED ASSET</p><h2 id="asset-overview-heading">{selectedAsset.ticker} <span>/ {selectedAsset.name}</span></h2></div>
          <div className="overview-price"><strong>{selectedAsset.price}</strong><span>{selectedAsset.dayChange}</span></div>
        </div>
        <div className="state-grid">
          <div><span>基本面状态</span><strong className="value-positive">{selectedAsset.fundamentalStatus}</strong></div>
          <div><span>当前观点</span><strong className="value-positive">{selectedAsset.viewpoint}</strong></div>
          <div><span>当前动作</span><strong>{selectedAsset.action}</strong></div>
          <div><span>当前仓位</span><strong>{selectedAsset.position}</strong></div>
        </div>
        <div className="related-research"><Link2 size={13} /><span>关联研究：{relatedTopic.name}</span><small>RESEARCH</small></div>
      </section>

      <div className="invest-two-column">
        <section className="invest-section" aria-labelledby="recent-changes-heading">
          <SectionHeader eyebrow="TIMELINE" title="最近变化" id="recent-changes-heading" />
          <Timeline className="change-timeline">
            {assetChanges.map((change) => (
              <TimelineRow className="change-row" key={change.id}>
                <time>{formatMockDate(change.happenedAt)}</time><i className={`timeline-${change.direction}`} />
                <div><strong>{change.title}</strong><span>{change.type}</span></div>
                <StatusBadge tone={change.direction} className={`impact-${change.direction}`}>{impactLabels[change.direction]}</StatusBadge>
              </TimelineRow>
            ))}
          </Timeline>
        </section>

        <section className="invest-section" aria-labelledby="catalysts-heading">
          <SectionHeader eyebrow="EVENTS" title="催化事件" id="catalysts-heading" />
          <Timeline className="catalyst-list">
            {assetCatalysts.map((item) => (
              <TimelineRow className="catalyst-row" key={`${item.date}-${item.event}`}>
                <CalendarClock size={14} /><time>{item.date}</time><strong>{item.event}</strong><StatusBadge tone={eventTone[item.status]}>{item.status}</StatusBadge>
              </TimelineRow>
            ))}
          </Timeline>
        </section>
      </div>

      <section className="invest-section" aria-labelledby="kpi-heading">
        <SectionHeader eyebrow="KPI" title="核心指标" id="kpi-heading" />
        <div className="table-scroll"><table className="kpi-table"><thead><tr><th>KPI</th><th>最新值</th><th>同比 / 环比变化</th><th>备注</th></tr></thead><tbody>
          {assetMetrics.map((metric) => <tr key={metric.id}><th>{metric.name}</th><td>{metric.value}</td><td className="value-positive">{metric.change}</td><td>{metric.note}</td></tr>)}
        </tbody></table></div>
      </section>

      <section className="invest-section" aria-labelledby="rules-heading">
        <SectionHeader eyebrow="ACTION RULES" title="操作规则" id="rules-heading" />
        <div className="rules-grid">
          {assetRules.map((group) => (
            <div className={`rule-group rule-${group.tone}`} key={group.key}>
              <header><strong>{group.key}</strong><span>{group.label}</span></header>
              <ul>{group.rules.map((rule) => <li key={rule}>{rule}</li>)}</ul>
            </div>
          ))}
        </div>
      </section>

      <section className="invest-section" aria-labelledby="decisions-heading">
        <SectionHeader eyebrow="DECISIONS" title="历史决策" id="decisions-heading" />
        <div className="decision-list">
          <div className="decision-row decision-header"><span>日期</span><span>动作</span><span>仓位</span><span>原因</span><span>结果</span></div>
          {assetDecisions.map((decision) => (
            <div className="decision-row" key={decision.id}>
              <time>{decision.createdAt}</time><strong>{decision.action}</strong><span>{decision.position}</span><p>{decision.reason}</p><StatusBadge tone={decision.result === "正确" ? "positive" : decision.result === "错误" ? "negative" : "muted"}>{decision.result}</StatusBadge>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}

const eventTone: Record<(typeof catalysts)[number]["status"], StatusTone> = { UPCOMING: "upcoming", TRACKING: "neutral", UNCONFIRMED: "warning" };
