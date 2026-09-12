"use client";
import { useState } from "react";
import { createJudgment } from "@/lib/actions";
import { localDate } from "@/lib/types";

export default function JudgmentForm() {
  const [confidence,setConfidence]=useState(70); const [horizon,setHorizon]=useState("30d");
  return <form action={createJudgment} className="form panel">
    <div className="form-grid">
      <div className="field"><label htmlFor="judgment_date">日期</label><input className="form-control" id="judgment_date" name="judgment_date" type="date" defaultValue={localDate()} required /></div>
      <div className="field"><label htmlFor="symbol">标的</label><input className="form-control" id="symbol" name="symbol" placeholder="如 BTC、贵州茅台" autoFocus required /></div>
      <div className="field"><label htmlFor="asset_type">资产类型</label><select className="form-control" id="asset_type" name="asset_type" defaultValue="股票"><option>股票</option><option>基金</option><option>加密资产</option><option>债券</option><option>商品</option><option>其他</option></select></div>
      <div className="field full"><label htmlFor="thesis">判断逻辑</label><textarea className="form-control" id="thesis" name="thesis" placeholder="你认为接下来会发生什么？为什么？" required minLength={5}/></div>
      <div className="field full"><label htmlFor="evidence">支持证据</label><textarea className="form-control" id="evidence" name="evidence" placeholder="记录当下可见的事实、数据或反证" required minLength={2}/></div>
      <div className="field full"><span className="section-label">决策</span><div className="choice">{[["buy","买入"],["add","加仓"],["hold","持有"],["reduce","减仓"],["sell","卖出"],["abandon","放弃"]].map(([v,l])=><label key={v}><input type="radio" name="decision" value={v} defaultChecked={v==="hold"}/><span>{l}</span></label>)}</div></div>
      <div className="field"><div className="range-line"><label htmlFor="confidence">信心度</label><strong className="positive">{confidence}%</strong></div><input id="confidence" name="confidence" type="range" min="0" max="100" value={confidence} onChange={e=>setConfidence(Number(e.target.value))}/></div>
      <div className="field"><label htmlFor="horizon_type">验证周期</label><select className="form-control" id="horizon_type" name="horizon_type" value={horizon} onChange={e=>setHorizon(e.target.value)}><option value="7d">7 天</option><option value="30d">30 天</option><option value="90d">90 天</option><option value="1y">1 年</option><option value="custom">自定义</option></select></div>
      {horizon==="custom"&&<div className="field"><label htmlFor="custom_due_date">自定义到期日</label><input className="form-control" type="date" id="custom_due_date" name="custom_due_date" required/></div>}
    </div>
    <details className="details"><summary>更多信息（可选）</summary><div className="form-grid"><div className="field"><label htmlFor="reference_price">参考价格</label><input className="form-control" type="number" step="any" id="reference_price" name="reference_price"/></div><div className="field"><label htmlFor="benchmark">对比基准</label><input className="form-control" id="benchmark" name="benchmark" placeholder="如 沪深 300、BTC"/></div><div className="field full"><label htmlFor="tags">标签</label><input className="form-control" id="tags" name="tags" placeholder="逗号分隔，如 宏观，估值，逆向"/></div></div></details>
    <div className="actions"><button className="button primary" type="submit">保存判断</button></div>
  </form>;
}
