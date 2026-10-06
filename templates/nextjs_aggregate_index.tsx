// 自動配置（ss-aggregate）: 管制塔の scripts/publish.py（write_aggregate_nextjs）が置く。直接編集しない。
import type { Metadata } from "next";
import SsAggregatePage, { pageMetadata } from "__COMPONENT__";

export const metadata: Metadata = pageMetadata("__KEY__");

export default function Page() {
  return <SsAggregatePage pageKey="__KEY__" />;
}
