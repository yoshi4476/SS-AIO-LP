// 管制塔（scripts/research_publish.py）が置く部品。手で直さない（次の配信で上書きされる）。
// 数字は src/content/research/aio-industries.json（AI集客ラボの業種別調査の集計そのもの）だけを使う
import data from "@/content/research/aio-industries.json";
import { SectionHead } from "@/components/ui";
import { Reveal } from "@/components/motion";

type Row = { name: string; questions: number; lp: number; lc: number; oa: number; url: string };

function Bar({ pct, tone }: { pct: number; tone: string }) {
  return (
    <span className="flex items-center gap-2">
      <span className="relative h-2.5 w-24 overflow-hidden rounded-full bg-line md:w-32">
        <span className={`absolute inset-y-0 left-0 rounded-full ${tone}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </span>
      <span className="w-12 text-right font-bold tabular-nums">{pct.toFixed(1)}%</span>
    </span>
  );
}

export default function AioResearchData() {
  const rows = data.rows as Row[];
  // 「ポータルが中心」と一律には言えない（2026-10 の集計で29業種中16業種）。言える数だけをデータから数えて書く
  const portalWins = rows.filter((r) => r.lp > r.lc).length;
  return (
    <section className="border-t border-line bg-mist py-20 md:py-24" aria-label="AIは何を出典に答えているか（業種別の調査）">
      <div className="mx-auto max-w-7xl px-5">
        <SectionHead
          en="AI Search Data"
          title="AIは何を出典に答えているか（業種別の調査）"
          lead={`当社が${data.n_industries}業種・計${data.total_questions.toLocaleString()}問をAIに聞き、答えの出典を数えました。会社を探す質問で、予約・比較ポータルが公式サイトより多く出典になったのは==${rows.length}業種中${portalWins}業種==。公式サイトが選ばれるかは、業種によって大きく違います。`}
        />
        <Reveal className="mt-10 overflow-x-auto rounded-2xl border border-line bg-white shadow-card">
          <table className="w-full min-w-[720px] text-sm">
            <caption className="sr-only">業種別・AIが出典にしたサイトの割合</caption>
            <thead className="bg-raise text-left text-xs text-slate">
              <tr>
                <th className="px-4 py-3">業種（質問数）</th>
                <th className="px-4 py-3">探す質問の出典: ポータル</th>
                <th className="px-4 py-3">探す質問の出典: 公式サイト</th>
                <th className="px-4 py-3">調べる質問で公式サイトを出典にした回答</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.name} className="border-t border-line">
                  <td className="px-4 py-3">
                    <a href={r.url} className="font-bold text-ink underline-offset-4 hover:underline">
                      {r.name}
                    </a>
                    <span className="ml-1 text-xs text-slate">（{r.questions}問）</span>
                  </td>
                  <td className="px-4 py-3"><Bar pct={r.lp} tone="bg-slate" /></td>
                  <td className="px-4 py-3"><Bar pct={r.lc} tone="bg-pulse" /></td>
                  <td className="px-4 py-3"><Bar pct={r.oa} tone="bg-gold" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Reveal>
        <p className="mt-4 text-xs leading-6 text-slate">
          出典: セブンセンシズ株式会社の調査（当社調べ・{data.period}）。各業種の質問を ChatGPT・Claude・Gemini などに聞き、答えに示された出典を種類ごとに数えました。AIの答えは同じ質問でも変わることがあります。業種名から、問いの一覧と集計（CSV）を見られます。
          <a href={data.index_url} className="ml-1 font-bold text-ink underline underline-offset-4">調査の一覧</a>
          <span className="mx-1">／</span>
          <a href={data.ranking_url} className="font-bold text-ink underline underline-offset-4">AIが出典にするサイトのランキング</a>
        </p>
      </div>
    </section>
  );
}
