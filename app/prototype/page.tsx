import PrototypeClient from "./prototype-client";

export const metadata = {
  title: "星流 AI｜非对话式内容生产原型",
  description: "以生产单驱动的超级 IP 内容策划与数字人视频生产原型。",
};

type PrototypeView = "project" | "create" | "studio" | "insight" | "assets" | "workflow" | "publish" | "admin";

export default async function PrototypePage({ searchParams }: { searchParams: Promise<{ view?: string }> }) {
  const { view } = await searchParams;
  const allowed: PrototypeView[] = ["project", "create", "studio", "insight", "assets", "workflow", "publish", "admin"];
  const initialView: PrototypeView = allowed.includes(view as PrototypeView) ? view as PrototypeView : "project";
  return <PrototypeClient initialView={initialView} />;
}
