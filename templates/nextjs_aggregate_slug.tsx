// 自動配置（ss-aggregate）: 管制塔の scripts/publish.py（write_aggregate_nextjs）が置く。直接編集しない。
// 下のページが1つも無い入口には置かない（静的書き出しは generateStaticParams が空だとビルドが落ちる）
import type { Metadata } from "next";
import SsAggregatePage, { keysUnder, pageMetadata } from "__COMPONENT__";

type Props = { params: Promise<{ slug: string[] }> };

export const dynamicParams = false;

export function generateStaticParams() {
  return keysUnder("__KEY__").map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  return pageMetadata(["__KEY__", ...slug].join("/"));
}

export default async function Page({ params }: Props) {
  const { slug } = await params;
  return <SsAggregatePage pageKey={["__KEY__", ...slug].join("/")} />;
}
