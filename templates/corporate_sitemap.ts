import fs from "node:fs";
import path from "node:path";
import type { MetadataRoute } from "next";
import { services } from "@/lib/services";
import { news } from "@/lib/news";
import { posts, type BlogPost } from "@/lib/blog";
import { themes } from "@/lib/themes";
import { site } from "@/lib/site";

// 管制塔（SSオウンドメディア）の templates/corporate_sitemap.ts から配布している。ここを直さず管制塔側を直す。
// 画像: https://developers.google.com/search/docs/crawling-indexing/sitemaps/image-sitemaps
// 動画: https://developers.google.com/search/docs/crawling-indexing/sitemaps/video-sitemaps

// 静的書き出し (output: export) でファイルとして生成させる
export const dynamic = "force-static";

// Next.js はサイトマップの値を XML 用に退避しない。& や < が1つ混ざるとファイル全体が読めなくなる
const x = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const PUBLIC = path.join(process.cwd(), "public");

/** 記事のために作った画像（アイキャッチ・図解）。パスに記事のスラッグを含み、実在するものだけ */
function postImages(p: BlogPost): string[] {
  const srcs = [p.eyecatch ?? "", ...[...p.html.matchAll(/<img\b[^>]*?\ssrc="([^"]+)"/g)].map((m) => m[1])];
  const out: string[] = [];
  for (const s of srcs) {
    if (!s.startsWith("/") || !s.includes(`/${p.slug}/`)) continue;
    const rel = s.split("?")[0];
    if (!fs.existsSync(path.join(PUBLIC, rel.replace(/^\//, "")))) continue;
    const full = x(`${site.url}${rel}`);
    if (!out.includes(full)) out.push(full);
  }
  return out.slice(0, 1000);
}

/** 本文に埋め込んだ動画。題・説明はページの VideoObject と同じにする（公式はページの説明との一致を求める） */
function postVideos(p: BlogPost): NonNullable<MetadataRoute.Sitemap[number]["videos"]> {
  const out: NonNullable<MetadataRoute.Sitemap[number]["videos"]> = [];
  const ldRx = /<script type="application\/ld\+json">([\s\S]*?)<\/script>/g;
  const shown = p.html.replace(ldRx, "");
  for (const m of p.html.matchAll(ldRx)) {
    let ld: Record<string, unknown>;
    try {
      ld = JSON.parse(m[1]);
    } catch {
      continue;
    }
    if (ld["@type"] !== "VideoObject") continue;
    const thumb = String(ld.thumbnailUrl ?? ""), name = String(ld.name ?? "");
    const desc = String(ld.description ?? ""), player = String(ld.embedUrl ?? "");
    if (!thumb || !name || !desc || !player) continue;
    // 構造化データだけあって、実際には埋め込まれていない動画は載せない
    if (!shown.includes(`/embed/${player.replace(/\/+$/, "").split("/").pop()}`)) continue;
    out.push({ title: x(name), thumbnail_loc: x(thumb), description: x(desc.slice(0, 2048)), player_loc: x(player) });
  }
  return out;
}

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    { url: site.url, lastModified: now, changeFrequency: "weekly", priority: 1 },
    { url: `${site.url}/services`, lastModified: now, changeFrequency: "monthly", priority: 0.9 },
    ...services.map((s) => ({
      url: `${site.url}/services/${s.slug}`,
      lastModified: now,
      changeFrequency: "monthly" as const,
      priority: 0.9,
    })),
    // 自社プロダクトのLP。契約獲得の入口なので事業ページと同じ優先度にする
    { url: `${site.url}/rakushift`, lastModified: now, changeFrequency: "monthly", priority: 0.9 },
    { url: `${site.url}/aio-agent`, lastModified: now, changeFrequency: "monthly", priority: 0.9 },
    { url: `${site.url}/company`, lastModified: now, changeFrequency: "monthly", priority: 0.7 },
    { url: `${site.url}/news`, lastModified: now, changeFrequency: "weekly", priority: 0.6 },
    ...news.map((n) => ({
      url: `${site.url}/news/${n.slug}`,
      lastModified: new Date(n.dateISO),
      changeFrequency: "yearly" as const,
      priority: 0.5,
    })),
    { url: `${site.url}/blog`, lastModified: now, changeFrequency: "daily", priority: 0.8 },
    { url: `${site.url}/research/ai-answers`, lastModified: now, changeFrequency: "monthly", priority: 0.6 },
    { url: `${site.url}/blog/theme`, lastModified: now, changeFrequency: "weekly", priority: 0.7 },
    { url: `${site.url}/tools/keiri-check`, lastModified: now, changeFrequency: "monthly", priority: 0.7 },
    ...themes.map((t) => ({
      url: `${site.url}/blog/theme/${t.slug}`,
      lastModified: now,
      changeFrequency: "weekly" as const,
      priority: 0.7,
    })),
    ...posts.map((p) => {
      const images = postImages(p), videos = postVideos(p);
      return {
        url: `${site.url}/blog/${p.slug}`,
        lastModified: new Date(p.dateModified),
        changeFrequency: "monthly" as const,
        priority: 0.7,
        ...(images.length ? { images } : {}),
        ...(videos.length ? { videos } : {}),
      };
    }),
    { url: `${site.url}/contact`, lastModified: now, changeFrequency: "yearly", priority: 0.8 },
  ];
}
