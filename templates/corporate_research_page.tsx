// 自動配置: 管制塔の scripts/research_publish.py が置く（直接編集しない）。
// 中身は src/content/research/ai-answers.json（管制塔が聞き取り調査から書き出す）。
import type { Metadata } from "next";
import Link from "next/link";
import JsonLd from "@/components/JsonLd";
import { breadcrumbSchema } from "@/lib/schema";
import { pageMeta } from "@/lib/meta";
import d from "@/content/research/ai-answers.json";

export const metadata: Metadata = pageMeta({
  title: d.title,
  description: d.description,
  path: "/research/ai-answers",
});

export default function AiAnswers() {
  return (
    <>
      <JsonLd
        data={[
          breadcrumbSchema([
            { name: "トップ", path: "/" },
            { name: "AIへの聞き取り調査", path: "/research/ai-answers" },
          ]),
          { "@context": "https://schema.org", ...d.dataset },
        ]}
      />
      <section className="border-b border-line py-14 md:py-20">
        <div className="mx-auto max-w-7xl px-5">
          <p className="eyebrow">Research</p>
          <h1 className="mt-4 text-3xl font-black md:text-5xl">{d.h1}</h1>
          <p className="mt-6 max-w-3xl text-sm leading-8 text-slate md:text-base">{d.lead}</p>
          <p className="mt-6 max-w-3xl rounded-3xl border border-line bg-raise p-6 text-sm leading-8">
            <b>要点:</b> {d.period}に{d.engines.join("・")}へ問いを{d.rows.length}問聞いたところ、
            <b>{d.split}問でAIどうしの結論が分かれました</b>（結論が読み取れた{d.answers}回答の集計）。
            AIが根拠に挙げたページのうち、公的機関（go.jp など）のページは{d.public_pct}%でした。
          </p>
        </div>
      </section>
      <section className="py-14 md:py-20">
        <div className="mx-auto max-w-7xl px-5">
          <h2 className="text-2xl font-black">AIは何と答えたか（問いごと）</h2>
          <p className="mt-4 text-sm leading-8 text-slate">同じ問いでも、AIによって結論が違うことがあります。各AIの答えの結論と、その根拠になった一文です。</p>
          <div className="mt-6 overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr>
                  <th scope="col" className="border border-line bg-raise p-3">問い</th>
                  {d.engines.map((e) => (
                    <th key={e} scope="col" className="border border-line bg-raise p-3">{e}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.rows.map((r) => (
                  <tr key={r.q}>
                    <th scope="row" className="border border-line p-3 align-top font-bold">
                      {r.url ? <Link href={r.url} className="hover:text-pulse">{r.q}</Link> : r.q}
                    </th>
                    {d.engines.map((e) => {
                      const a = (r.answers as Record<string, { label: string; quote: string }>)[e];
                      return (
                        <td key={e} className="border border-line p-3 align-top">
                          <b>{a ? a.label : "（聞けず）"}</b>
                          {a && a.quote ? <span className="mt-1 block text-xs text-slate">「{a.quote.slice(0, 70)}」</span> : null}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-sm">
            <a href="/research/ai-answers/data.csv" download className="text-pulse underline">この表のデータ（CSV）</a>
            。引用するときは、調べた日とAIの名前を添えてください。
          </p>
          <h2 className="mt-12 text-2xl font-black">この結果の読み方</h2>
          <div className="mt-4 max-w-3xl text-sm leading-8" dangerouslySetInnerHTML={{ __html: d.readout_html }} />
          <h2 className="mt-12 text-2xl font-black">調べ方と限界</h2>
          <ul className="mt-4 max-w-3xl list-disc pl-5 text-sm leading-8">
            <li>調べた日: {d.period}。AIの答えは日によって変わります。これはその日の1回の結果です。</li>
            <li>聞いたAI: {d.engines.join("・")}（いずれも検索つきで回答させ、根拠にしたページのURLを残しました）。</li>
            <li>問い: 当サイトの記事で扱っている読者の質問から、「はい・いいえ」で答えられるものを選びました。</li>
            <li>答えの読み分け: 結論を「はい・条件による・いいえ」に分ける作業を2回独立に行い、2回が一致し、根拠の一文が答えの本文にあるものだけを数えました。</li>
            <li>当社は、AIの答えが正しいかを判定していません。この表は「AIが何と答えたか」の記録です。</li>
          </ul>
        </div>
      </section>
    </>
  );
}
