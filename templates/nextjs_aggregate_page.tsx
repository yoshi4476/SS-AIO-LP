// 自動配置（ss-aggregate）: 管制塔の scripts/publish.py（write_aggregate_nextjs）が置く。直接編集しない。
// まとめのページ（比較表・テーマ・エリア・今の時期の特集・業種・用語集・多言語の要約）を、管制塔が書き出した JSON から描く。
// 中身（本文の HTML・構造化データ）は管制塔の aggregate_pages.collect が作る。ここは置くだけ。
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import data from "__DATA__";

type AggregatePage = {
  title: string;
  description: string;
  html: string;
  jsonld: unknown[];
  lang: string;
  url: string;
  alternates?: Record<string, string>;
};

const pages = (data as unknown as { pages: Record<string, AggregatePage> }).pages;

// サイトの CSS はリセットされている（Tailwind など）ので、一覧と表の最低限の見た目だけここで持つ
const CSS = `
.ss-aggregate{max-width:880px;margin:0 auto;padding:48px 20px 80px;line-height:1.85}
.ss-aggregate h1{font-size:1.9rem;font-weight:800;line-height:1.4;margin:0 0 1.2rem}
.ss-aggregate h2{font-size:1.25rem;font-weight:700;margin:2.2rem 0 .8rem}
.ss-aggregate .cat-head{display:flex;gap:.8rem;align-items:baseline;flex-wrap:wrap}
.ss-aggregate .cnt{font-size:.85rem;opacity:.7;margin-left:.5rem}
.ss-aggregate ul,.ss-aggregate ol{padding-left:1.3rem;margin:.6rem 0}
.ss-aggregate ul{list-style:disc}.ss-aggregate ol{list-style:decimal}
.ss-aggregate li{margin:.45rem 0}
.ss-aggregate a{text-decoration:underline}
.ss-aggregate .hub-lead{margin:.6rem 0}.ss-aggregate .hub-note{font-size:.9rem;opacity:.8;margin:.6rem 0}
.ss-aggregate .table-wrap{overflow-x:auto}
.ss-aggregate table{border-collapse:collapse;width:100%;font-size:.92rem;margin:.6rem 0}
.ss-aggregate th,.ss-aggregate td{border:1px solid rgba(127,127,127,.35);padding:.5rem .7rem;text-align:left;vertical-align:top}
.ss-aggregate details{margin:.6rem 0;padding:.7rem 1rem;border:1px solid rgba(127,127,127,.35);border-radius:10px}
.ss-aggregate summary{font-weight:700;cursor:pointer}
.ss-aggregate h3{font-size:1.08rem;font-weight:700;margin:1.8rem 0 .6rem}
.ss-aggregate .definition-box{margin:.6rem 0;padding:.8rem 1rem;border-left:4px solid rgba(127,127,127,.5);background:rgba(127,127,127,.08)}
.ss-aggregate .definition-box .term{font-weight:700}
.ss-aggregate .gl-toc,.ss-aggregate .faq-groups{display:flex;flex-wrap:wrap;gap:.4rem .9rem;margin:1rem 0;font-size:.92rem}
.ss-aggregate .faq-groups span{opacity:.7;margin-left:.3rem}
.ss-aggregate .gl-term{scroll-margin-top:80px}
`;

/** 「compare」のような入口の下にあるページの slug の並び（generateStaticParams 用） */
export function keysUnder(top: string): string[][] {
  return Object.keys(pages)
    .filter((k) => k.startsWith(top + "/"))
    .map((k) => k.slice(top.length + 1).split("/"));
}

export function pageMetadata(key: string): Metadata {
  const p = pages[key];
  if (!p) return {};
  return {
    title: p.title,
    description: p.description,
    alternates: { canonical: p.url, ...(p.alternates ? { languages: p.alternates } : {}) },
    openGraph: { title: p.title, description: p.description, url: p.url, type: "website", __OG__ },
  };
}

export default function SsAggregatePage({ pageKey }: { pageKey: string }) {
  const p = pages[pageKey];
  if (!p) notFound();
  return (
    <section className="ss-aggregate" lang={p.lang}>
      <style>{CSS}</style>
      <h1>{p.title}</h1>
      <div dangerouslySetInnerHTML={{ __html: p.html }} />
      {p.jsonld.map((ld, i) => (
        <script
          key={i}
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(ld).replace(/</g, "\\u003c") }}
        />
      ))}
    </section>
  );
}
