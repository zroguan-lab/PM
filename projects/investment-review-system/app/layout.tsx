import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = { title: "决策复盘", description: "本机投资决策复盘系统" };

const nav = [
  ["/", "数据看板", "▦"], ["/judgments/new", "新建判断", "＋"],
  ["/judgments", "判断记录", "☷"], ["/reviews", "待复盘", "◷"]
];

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body><div className="app-shell">
    <aside className="sidebar"><Link href="/" className="brand"><span className="brand-mark">↗</span>决策复盘</Link>
      <nav>{nav.map(([href,label,icon])=><Link href={href} key={href}><span>{icon}</span>{label}</Link>)}</nav>
      <div className="local-note">● 数据仅保存在本机</div>
    </aside>
    <main className="content">{children}</main>
    <nav className="mobile-nav">{nav.map(([href,label])=><Link href={href} key={href}>{label.replace("数据","")}</Link>)}</nav>
  </div></body></html>;
}
