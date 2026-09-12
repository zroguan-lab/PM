import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "W40 / OS",
  description: "个人投资研究工作台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
