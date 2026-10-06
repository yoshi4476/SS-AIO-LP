// 自動配置（ss-aggregate）: 管制塔の scripts/publish.py（nextjs_alternates_part）が置く。直接編集しない。
// 記事の JSON（src/content/blog/<slug>.json）の alternates は、日本語の記事と訳のページ（/en/… など）の組。
// 記事ページの generateMetadata で次のように返すと、head に <link rel="alternate" hreflang> が出る:
//   return { title: post.title, alternates: ssAlternates(post, canonicalUrl) };
// 訳の無い記事は languages を付けない（自分だけを指す hreflang は出さない）。
import type { Metadata } from "next";

type WithAlternates = { alternates?: Record<string, string> };

export function ssAlternates(post: WithAlternates, canonical?: string): Metadata["alternates"] {
  const langs = post.alternates ?? {};
  const others = Object.keys(langs).filter((k) => k !== "ja" && k !== "x-default");
  return {
    ...(canonical ? { canonical } : {}),
    ...(others.length ? { languages: langs } : {}),
  };
}
