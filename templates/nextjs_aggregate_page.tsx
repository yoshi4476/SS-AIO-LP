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

// サイトの CSS はリセットされている（Tailwind など）ので、ページの枠と最低限の見た目だけここで持つ。
// 上の余白は固定ヘッダー（スマホ 64px・768px 以上 80px）より広くする。48px では h1 がヘッダーの下に潜り、
// スマホではメニューの丸ボタンが h1 に重なっていた（2026-10-08）。一覧・見出しの部品は管制塔の aggregate_pages.CSS を足す
const CSS =
  `
.ss-aggregate{max-width:880px;margin:0 auto;padding:112px 20px 80px;line-height:1.85}
@media (min-width:768px){.ss-aggregate{padding-top:136px}}
.ss-aggregate h1{font-size:1.9rem;font-weight:800;line-height:1.4;margin:0 0 1.2rem}
.ss-aggregate h2{font-size:1.25rem;font-weight:700;margin:2.2rem 0 .8rem}
.ss-aggregate ul,.ss-aggregate ol{padding-left:1.3rem;margin:.6rem 0}
.ss-aggregate ul{list-style:disc}.ss-aggregate ol{list-style:decimal}
.ss-aggregate li{margin:.45rem 0}
.ss-aggregate a{text-decoration:underline}
.ss-aggregate h3{font-size:1.08rem;font-weight:700;margin:1.8rem 0 .6rem}
.ss-aggregate .faq-groups{display:flex;flex-wrap:wrap;gap:.4rem .9rem;margin:1rem 0;font-size:.92rem}
.ss-aggregate .faq-groups span{opacity:.7;margin-left:.3rem}
.ss-aggregate .ss-crumb ol{display:flex;flex-wrap:wrap;gap:.2rem .5rem;list-style:none;padding:0;margin:0 0 1rem;font-size:.82rem;opacity:.8}
.ss-aggregate .ss-crumb li{margin:0}
.ss-aggregate .ss-crumb li+li::before{content:"›";margin-right:.5rem}
` + __CSS__;

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

/** パンくずの階層（入口 › このページ）。入口のページが無い階層は飛ばす */
function crumbs(key: string) {
  const parts = key.split("/");
  return parts
    .map((_, i) => parts.slice(0, i + 1).join("/"))
    .filter((k) => pages[k])
    .map((k) => ({ key: k, title: pages[k].title, url: pages[k].url, path: new URL(pages[k].url).pathname }));
}

export default function SsAggregatePage({ pageKey }: { pageKey: string }) {
  const p = pages[pageKey];
  if (!p) notFound();
  const trail = crumbs(pageKey);
  const crumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [{ title: "ホーム", url: new URL(p.url).origin + "/" }, ...trail].map((c, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: c.title,
      item: c.url,
    })),
  };
  return (
    <section className="ss-aggregate" lang={p.lang}>
      <style>{CSS}</style>
      <nav className="ss-crumb" aria-label="パンくずリスト">
        <ol>
          <li>
            <a href="/">ホーム</a>
          </li>
          {trail.map((c, i) => (
            <li key={c.key}>
              {i < trail.length - 1 ? <a href={c.path}>{c.title}</a> : <span aria-current="page">{c.title}</span>}
            </li>
          ))}
        </ol>
      </nav>
      <h1>{p.title}</h1>
      <div dangerouslySetInnerHTML={{ __html: p.html }} />
      {[...p.jsonld, crumbLd].map((ld, i) => (
        <script
          key={i}
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(ld).replace(/</g, "\\u003c") }}
        />
      ))}
    </section>
  );
}
