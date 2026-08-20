import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "星流 AI · 超级 IP 营销工作台",
  description: "从 IP 定位、内容策划到数字人口播成片的独立 AI 营销工作台。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
