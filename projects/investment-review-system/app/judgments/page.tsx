import Link from "next/link";
import StatusBadge from "@/components/StatusBadge";
import { listJudgments } from "@/lib/db";
import { decisionLabels, outcomeLabels } from "@/lib/types";

export const dynamic="force-dynamic";
export default async function JudgmentsPage({searchParams}:{searchParams:Promise<{q?:string;status?:string}>}){
 const p=await searchParams; const rows=listJudgments(p.q||"",p.status||"");
 return <><header className="page-head"><div><h1>判断记录</h1><div className="muted">{rows.length} 条记录 · 支持搜索和状态筛选</div></div><Link className="button primary" href="/judgments/new">＋ 新建判断</Link></header>
 <form className="toolbar"><input className="form-control" name="q" defaultValue={p.q} placeholder="搜索标的、判断、证据或标签"/><select className="form-control" name="status" defaultValue={p.status}><option value="">全部状态</option><option value="active">验证中</option><option value="pending">待复盘</option><option value="reviewed">已复盘</option></select><button className="button">筛选</button>{(p.q||p.status)&&<Link className="button" href="/judgments">清除</Link>}</form>
 <div className="panel table-wrap">{rows.length?<table><thead><tr><th>日期</th><th>标的</th><th>判断</th><th>决策</th><th>信心度</th><th>到期日</th><th>状态</th><th>结果</th></tr></thead><tbody>{rows.map(r=><tr className="record-link" key={r.id}><td>{r.judgment_date}</td><td><Link href={`/judgments/${r.id}`}><strong>{r.symbol}</strong></Link></td><td><Link href={`/judgments/${r.id}`}>{r.thesis.length>36?r.thesis.slice(0,36)+"…":r.thesis}</Link></td><td>{decisionLabels[r.decision]}</td><td>{r.confidence}%</td><td>{r.due_date}</td><td><StatusBadge row={r}/></td><td>{r.outcome?outcomeLabels[r.outcome]:"—"}</td></tr>)}</tbody></table>:<div className="empty">没有找到符合条件的判断。</div>}</div></>;
}
