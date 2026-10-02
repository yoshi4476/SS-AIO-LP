# -*- coding: utf-8 -*-
"""業種別の調査「患者・顧客がAIに聞いたとき、AIは何を出典に答えているか」。

    python scripts/industry_ai_sources.py --industry dental --dry-run   # 質問と見積もりだけ（課金なし）
    python scripts/industry_ai_sources.py --industry dental              # 聞いて集計する（1回だけ回す）
    python scripts/industry_ai_sources.py --industry dental --classify   # 出典の種類分けをやり直す（課金なし）

質問は固定の一覧（ページでも公開する）。4つのAI（ChatGPT・Gemini・Perplexity・Claude）に聞き、
回答の出典URLをサイトの種類（予約・比較ポータル／医院の公式サイト／公的機関・学会…）に分けて数える。
個別の医院名は公開しない（種類ごとの集計だけ）。応答は ai_cite_check の30日キャッシュに残るので、
集計や種類分けを直すときに聞き直さない（課金は1回だけ）。
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "research"
CLASS_FILE = OUT / "source_class.json"

CITIES = ["大阪", "東京", "名古屋", "福岡", "札幌", "横浜", "京都", "神戸", "仙台", "広島"]
QUESTIONS = {
    "dental": {
        "name": "歯科",
        "groups": {
            "地域で探す": [f"{c} 歯医者 おすすめ" for c in CITIES] + [f"{c} 歯科 評判 いい" for c in CITIES],
            "費用": [f"{t} 費用 相場" for t in ("インプラント", "歯列矯正", "マウスピース矯正", "ホワイトニング",
                                              "セラミック 詰め物", "入れ歯", "根管治療", "親知らず 抜歯", "歯周病 治療", "小児矯正")]
                    + [f"{t} 保険 適用 されるか" for t in ("インプラント", "歯列矯正", "ホワイトニング", "セラミック",
                                                       "入れ歯", "根管治療", "親知らず 抜歯", "歯周病 治療", "小児矯正", "歯のクリーニング")]
                    + ["歯医者 初診料 いくら", "銀歯 白くする 費用", "インプラント 1本 値段", "部分矯正 費用",
                       "ブリッジ 費用 保険", "被せ物 種類 値段", "矯正 分割払い できる", "歯科 医療費控除 対象", "歯のクリーニング 自費 違い", "歯科 ローン 使える"],
            "治療の選び方": ["インプラント 失敗しない 歯医者の選び方", "矯正歯科 選び方", "ホワイトニング 歯科 エステ 違い",
                         "マウスピース矯正 デメリット", "インプラント 入れ歯 ブリッジ 比較", "セラミック 保険 違い",
                         "親知らず 抜くべきか", "根管治療 専門医 必要か", "歯周病 治るのか", "子供 矯正 何歳から",
                         "審美歯科 とは", "予防歯科 通う頻度", "歯科 セカンドオピニオン", "訪問歯科 とは", "口腔外科 とは 何をする"],
            "症状": ["歯が痛い 夜 どうする", "歯茎から血が出る 原因", "知覚過敏 治し方", "口臭 歯医者 行くべき",
                   "銀歯 取れた どうする", "歯ぎしり マウスピース 歯医者", "顎関節症 何科", "虫歯 放置 どうなる",
                   "歯が欠けた 応急処置", "親知らず 腫れた", "歯がしみる 原因", "歯茎 腫れ 膿", "子供 歯 ぐらぐら",
                   "口内炎 歯医者 行くべきか", "差し歯 取れた", "歯石 取り 頻度", "歯の黄ばみ 原因", "噛むと痛い 歯",
                   "インプラント 痛み 術後", "抜歯後 ドライソケット"],
            "受診のしかた": ["いい歯医者 見分け方", "歯医者 変えたい 途中", "歯医者 予約 取りやすい", "歯医者 土日 診療",
                         "歯医者 怖い 痛くない", "歯医者 初診 何をする", "歯科 自費 保険 違い", "歯医者 口コミ 信用できるか",
                         "歯医者 説明 しない", "歯医者 削りすぎ", "歯医者 何ヶ月ごと 検診", "女性 歯科医師 探し方",
                         "歯科 夜間 救急", "歯医者 治療 長い なぜ", "歯医者 転院 紹介状"],
        },
    },
}

CATS = {
    "portal": "予約・比較ポータル",
    "clinic": "医院・クリニックの公式サイト",
    "review": "口コミ・地図",
    "public": "公的機関・学会・業界団体",
    "maker": "メーカー・企業",
    "media": "ニュース・メディア・まとめ記事",
    "video": "動画・SNS",
    "wiki": "百科事典",
    "other": "その他",
}
# 決まったルールで分けられるもの。分けきれない分だけ claude に分けさせる（結果はファイルに残し、人が見直せる）
RULES = [
    # .or.jp を一律に公的機関にしない。医療法人の医院も .or.jp を使う（試しで ohnuki-dental.or.jp を公的機関と誤った）
    (r"(^|\.)go\.jp$|(^|\.)lg\.jp$|(^|\.)ac\.jp$|(^|\.)jda\.or\.jp$|(^|\.)perio\.jp$|(^|\.)kokuhoken\.or\.jp$|"
     r"who\.int$|nih\.gov$", "public"),
    (r"epark|haisha-yoyaku|caloo|byoinnavi|doctorsfile|qlife|scuel|shika-town|ha-channel|minnano-shika|"
     r"dentalbook|shika-navi|denternet|hospita|medicaldoc|fdoc|mrso|ishachoku|okbiz", "portal"),
    (r"google\.(com|co\.jp)/maps|maps\.google|maps\.app\.goo\.gl|tabelog|minkou|minkuru", "review"),
    (r"youtube\.com|youtu\.be|tiktok\.com|instagram\.com|x\.com|twitter\.com|facebook\.com|note\.com|ameblo\.jp", "video"),
    (r"wikipedia\.org", "wiki"),
    (r"yahoo\.co\.jp|nikkei\.com|asahi\.com|yomiuri\.co\.jp|mainichi\.jp|nhk\.or\.jp|allabout\.co\.jp|"
     r"diamond\.jp|president\.jp|news\.", "media"),
]


def domain(u):
    try:
        h = urllib.parse.urlparse(u).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def rule_class(d, u=""):
    for pat, c in RULES:
        if re.search(pat, d) or (c in ("review",) and re.search(pat, u)):
            return c
    return ""


def questions(ind):
    return [(g, q) for g, qs in QUESTIONS[ind]["groups"].items() for q in qs]


def estimate(n):
    # 公式の料金（2026-10-02 確認）: OpenAI web_search_preview $25/1k＋gpt-4.1-mini の文字量、
    # Gemini の検索つき回答は月5,000回まで無料、Perplexity fast は約$0.0065/回、Claude はサブスク
    usd = n * (0.025 + 0.002) + n * 0.0065
    return usd


def ask_all(ind, workers=6):
    import ai_cite_check as AC
    eng = AC.engines_available()
    qs = questions(ind)
    tasks = [(g, q, name) for g, q in qs for name in eng]
    res = defaultdict(dict)

    def one(t):
        g, q, name = t
        try:
            urls = eng[name](q) or []
            return g, q, name, urls, ""
        except Exception as e:
            return g, q, name, [], str(e)[:160]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (g, q, name, urls, err) in enumerate(ex.map(one, tasks), 1):
            res[q].setdefault("group", g)
            res[q][name] = {"urls": urls, "error": err}
            if i % 20 == 0:
                print(f"  {i}/{len(tasks)}", flush=True)
    return {"industry": ind, "date": date.today().isoformat(), "engines": sorted(eng), "answers": res}


def classify(raw):
    """出典のドメインを種類に分ける。ルール → 前回の結果 → claude（未知の分だけ）"""
    known = json.loads(CLASS_FILE.read_text(encoding="utf-8")) if CLASS_FILE.is_file() else {}
    samples = {}
    for q, by in raw["answers"].items():
        for name, r in by.items():
            if name == "group":
                continue
            for u in r["urls"]:
                d = domain(u)
                if d:
                    samples.setdefault(d, u)
    todo = [d for d in samples if not rule_class(d, samples[d]) and d not in known]
    if todo:
        import auto_rewrite as AR
        lines = "\n".join(f"{d}\t{samples[d][:120]}" for d in todo)
        prompt = ("次のドメイン（タブの後ろは実際に出典になったURLの例）を、サイトの種類に分けてください。\n"
                  "種類は次のキーのどれか1つ: " + ", ".join(f"{k}={v}" for k, v in CATS.items()) + "\n"
                  "歯科医院・クリニック・病院が自院について書いているサイトは clinic。複数の医院を比べる・予約を受ける・"
                  "医院を紹介するサイトは portal。医療法人の医院は .or.jp でも clinic（公的機関ではない）。"
                  "学会・歯科医師会・官公庁・大学だけが public。分からなければ other。\n"
                  "出力は JSON のオブジェクト1つだけ（{\"ドメイン\": \"キー\", ...}）。説明は書かない。\n\n" + lines)
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([AR.claude_bin(), "-p", "--model", "claude-sonnet-5-5"], input=prompt, cwd=tmp,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        m = re.search(r"\{.*\}", r.stdout or "", re.S)
        got = json.loads(m.group(0)) if m else {}
        for d in todo:
            c = got.get(d, "other")
            known[d] = c if c in CATS else "other"
        OUT.mkdir(parents=True, exist_ok=True)
        CLASS_FILE.write_text(json.dumps(known, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return lambda d, u="": rule_class(d, u) or known.get(d, "other")


def summarize(raw, cls):
    """種類ごとの割合（AIごと・質問の種類ごと）。1つの回答で同じドメインは1回だけ数える"""
    by_engine, by_group, total = defaultdict(Counter), defaultdict(Counter), Counter()
    answered, has_clinic, n_src = Counter(), Counter(), Counter()
    portal_dom = Counter()
    for q, by in raw["answers"].items():
        g = by.get("group", "")
        for name, r in by.items():
            if name == "group" or r.get("error"):
                continue
            doms = {}
            for u in r["urls"]:
                d = domain(u)
                if d:
                    doms.setdefault(d, u)
            if not doms:
                continue
            answered[name] += 1
            n_src[name] += len(doms)
            kinds = {d: cls(d, u) for d, u in doms.items()}
            if "clinic" in kinds.values():
                has_clinic[name] += 1
            for d, k in kinds.items():
                by_engine[name][k] += 1
                by_group[g][k] += 1
                total[k] += 1
                if k == "portal":
                    portal_dom[d] += 1
    return {"total": dict(total), "by_engine": {k: dict(v) for k, v in by_engine.items()},
            "by_group": {k: dict(v) for k, v in by_group.items()}, "answered": dict(answered),
            "has_clinic": dict(has_clinic), "sources": dict(n_src), "portal_top": portal_dom.most_common(10)}


def per_answer(raw):
    """もう1つの数え方: 回答ごとに『その種類を1つでも出典にしたか』（出典のある回答だけ）。
    出典の件数で数えると、出典を多く付ける AI（Claude 10件/回答）の重みが大きくなるため、両方を載せる"""
    known = json.loads(CLASS_FILE.read_text(encoding="utf-8")) if CLASS_FILE.is_file() else {}
    cls = lambda d, u="": rule_class(d, u) or known.get(d, "other")
    ans, hit = Counter(), defaultdict(Counter)
    for q, by in raw["answers"].items():
        g = by.get("group", "")
        for name, r in by.items():
            if name == "group" or not r.get("urls"):
                continue
            kinds = {cls(domain(u), u) for u in r["urls"] if domain(u)}
            for key in ("全体", g):
                ans[key] += 1
                for k in kinds:
                    hit[key][k] += 1
    return {k: {"answers": ans[k], **dict(hit[k])} for k in ans}


ENGINE_NOTE = {"ChatGPT": "gpt-4.1-mini＋Web検索", "Gemini": "Gemini Flash＋Google検索", "Perplexity": "Agent API（fast）",
               "Claude": "Claude Sonnet＋Web検索"}


def render(ind):
    """公開ページの中身（HTML）と構造化データ。数字は集計ファイルからだけ取る（手で書かない）"""
    import html as H
    s = json.loads((OUT / f"{ind}-summary.json").read_text(encoding="utf-8"))
    # 公開リポジトリには集計だけを置く（生データには個別の医院のURLが入るため、コミットしない）
    pa = s["per_answer"]
    name = s["name"]
    tot = sum(s["total"].values()) or 1
    pct = lambda c, k: round(c.get(k, 0) / max(sum(c.values()), 1) * 100, 1)
    apct = lambda key, k: round(pa[key].get(k, 0) / max(pa[key]["answers"], 1) * 100, 1)
    loc = "地域で探す"

    def bars(c):
        rows = sorted(((k, pct(c, k)) for k in CATS if c.get(k)), key=lambda x: -x[1])
        return "".join(f'<div class="rs-bar"><span class="rs-l">{CATS[k]}</span>'
                       f'<span class="rs-t"><span style="width:{v}%"></span></span><span class="rs-v">{v}%</span></div>'
                       for k, v in rows)
    grp_rows = "".join(
        f"<tr><th>{H.escape(g)}</th><td>{s['groups'][g]}問</td><td>{pct(c, 'clinic')}%</td><td>{pct(c, 'portal')}%</td>"
        f"<td>{pct(c, 'public')}%</td><td>{apct(g, 'clinic')}%</td><td>{apct(g, 'portal')}%</td></tr>"
        for g, c in s["by_group"].items())
    eng_rows = "".join(
        f"<tr><th>{H.escape(e)}<br><small>{ENGINE_NOTE.get(e, '')}</small></th><td>{s['answered'].get(e, 0)}/{s['questions']}</td>"
        f"<td>{round(s['sources'][e] / max(s['answered'][e], 1), 1)}</td><td>{pct(c, 'clinic')}%</td><td>{pct(c, 'portal')}%</td></tr>"
        for e, c in s["by_engine"].items())
    portals = "、".join(H.escape(d) for d, _ in s["portal_top"][:6])
    lc, lp = pct(s["by_group"][loc], "clinic"), pct(s["by_group"][loc], "portal")
    other = {g: c for g, c in s["by_group"].items() if g != loc}
    oc = round(sum(c.get("clinic", 0) for c in other.values()) / max(sum(sum(c.values()) for c in other.values()), 1) * 100, 1)
    y, m = s["date"][:4], int(s["date"][5:7])
    cite = (f"セブンセンシズ株式会社の調査（{y}年{m}月、{name}に関する{s['questions']}問を4つのAIに質問）では、"
            f"「地域名＋{name} おすすめ」のような医院を探す質問の出典は{lp}%が予約・比較ポータルで、医院の公式サイトは{lc}%でした。"
            f"一方、費用・治療・症状などを調べる質問では、出典の{oc}%が医院の公式サイトでした。")
    groups_q = "".join(f"<li><b>{H.escape(g)}</b>（{len(qs)}問）: {H.escape('／'.join(qs[:4]))} など</li>"
                       for g, qs in QUESTIONS[ind]["groups"].items())
    body = f"""<style>
.rs{{max-width:880px;margin:0 auto;display:grid;gap:2.2rem;min-width:0}}
.rs>*{{min-width:0}}
.rs h2{{font-size:clamp(1.2rem,2.3vw,1.5rem);margin:0 0 .8rem}}
.rs-key{{background:var(--bg-alt);border:1px solid var(--line);border-radius:18px;padding:1.2rem 1.4rem}}
.rs-key ul{{margin:.4rem 0 0;padding-left:1.2em}}
.rs-bar{{display:grid;grid-template-columns:minmax(9em,15em) 1fr 4em;gap:.6rem;align-items:center;margin:.35rem 0;font-size:.92rem}}
.rs-t{{background:var(--sky);border-radius:999px;height:12px;overflow:hidden}}
.rs-t span{{display:block;height:100%;background:var(--blue);border-radius:999px}}
.rs-v{{font-variant-numeric:tabular-nums;text-align:right;font-weight:700}}
.rs-tbl{{overflow-x:auto}}
.rs table{{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums}}
.rs th,.rs td{{border-bottom:1px solid var(--line);padding:.55rem .5rem;text-align:left;vertical-align:top}}
.rs td{{text-align:right}}
.rs-cite{{border-left:4px solid var(--blue);padding:.6rem 1rem;background:#fff}}
@media (max-width:600px){{.rs-bar{{grid-template-columns:1fr 3.5em}}.rs-bar .rs-t{{grid-column:1/-1;order:3}}}}
</style>
<div class="rs">
<section class="rs-key"><h2>この調査で分かったこと</h2><ul>
<li><b>医院を探す質問</b>（「大阪 歯医者 おすすめ」など）では、AIの出典の<b>{lp}%が予約・比較ポータル</b>で、医院の公式サイトは{lc}%でした。</li>
<li><b>費用・治療の選び方・症状・受診のしかたを調べる質問</b>では、出典の<b>{oc}%が医院の公式サイト</b>（解説のページ）でした。</li>
<li>1回答あたりの出典の数はAIによって違い、多いもので{max(round(s['sources'][e] / max(s['answered'][e], 1), 1) for e in s['answered'])}件、少ないもので{min(round(s['sources'][e] / max(s['answered'][e], 1), 1) for e in s['answered'])}件でした。</li>
</ul></section>
<section><h2>AIの回答の出典は、どんなサイトか（全体）</h2>
<p>出典として示されたサイトを種類ごとに数えました（1つの回答で同じサイトは1回）。出典の合計は{tot:,}件です。</p>
{bars(s["total"])}
<p style="font-size:.88rem;color:var(--muted)">別の数え方（回答ごとに、その種類を1つでも出典にしたか）では、医院の公式サイトを出典にした回答が{apct('全体', 'clinic')}%、予約・比較ポータルを出典にした回答が{apct('全体', 'portal')}%でした（出典のある{pa['全体']['answers']}回答）。</p>
</section>
<section><h2>質問の種類ごとの違い</h2>
<div class="rs-tbl"><table><thead><tr><th>質問の種類</th><th>質問数</th><th>医院の公式サイト<br><small>出典の割合</small></th><th>ポータル<br><small>出典の割合</small></th><th>公的機関・学会<br><small>出典の割合</small></th><th>医院を出典にした<br><small>回答の割合</small></th><th>ポータルを出典にした<br><small>回答の割合</small></th></tr></thead>
<tbody>{grp_rows}</tbody></table></div>
<p>医院を探す質問の出典に多かったポータルは、{portals} などです。</p>
</section>
<section><h2>AIごとの違い</h2>
<div class="rs-tbl"><table><thead><tr><th>AI</th><th>出典つきで答えた質問</th><th>1回答あたりの出典数</th><th>医院の公式サイト</th><th>ポータル</th></tr></thead>
<tbody>{eng_rows}</tbody></table></div>
<p style="font-size:.88rem;color:var(--muted)">APIで質問したため、Webを検索するかどうかはAIが質問ごとに決めます。出典を付けずに答えた回答は数えていません。アプリやブラウザで使うAIとは、結果が異なる場合があります。</p>
</section>
<section><h2>{H.escape(name)}の医院にとっての意味</h2>
<p><b>「探される」場面では、ポータルと口コミがAIの出典になります。</b>地域名で医院を探す人への答えには、医院の公式サイトよりも予約・比較サイトが多く使われていました。ポータルの掲載情報を最新に保つことが、AIの答えに名前が出る前提になります。</p>
<p><b>「調べられる」場面では、自院の解説ページがAIの出典になります。</b>費用・治療・症状の質問では、ほとんどの回答が医院の公式サイトを出典にしていました。費用の考え方や治療の選び方を、自院のサイトで分かりやすく説明しておくことが、AIに選ばれる近道です。</p>
<p>当社は、医療機関のSEO・AI検索対策を行っています。<a href="/lp/medical/" data-cta="research_lp_medical">クリニック・歯科医院のSEO・AI検索対策</a>をご覧ください。</p>
</section>
<section><h2>引用する場合</h2><p class="rs-cite">{H.escape(cite)}</p>
<p style="font-size:.88rem">集計データ（CSV）: <a href="/research/{ind}-ai-sources/data.csv" download>ダウンロード</a></p></section>
<section><h2>調査の方法</h2><ul>
<li>調査日: {s['date']}　質問数: {s['questions']}問　AI: {'・'.join(s['engines'])}</li>
<li>質問は患者が実際に調べそうな言い回しで、5つの種類に分けて固定しました。</li>
</ul><ul>{groups_q}</ul>
<p>出典のサイトの種類は、サイト名と内容から分けました（官公庁・大学・学会・歯科医師会は「公的機関・学会」、医院が自院について書いたサイトは「医院の公式サイト」、複数の医院を紹介・比較・予約するサイトは「予約・比較ポータル」）。件数の多い出典はサイトの題名と照らし合わせて確かめました。個別の医院名は公開していません。AIの回答は日によって変わるため、この結果は調査日時点のものです。</p>
</section>
</div>"""
    ld = {"@context": "https://schema.org", "@type": "Dataset",
          "name": f"{name}に関する質問に、AIは何を出典にして答えているか（{y}年{m}月）",
          "description": cite, "creator": {"@type": "Organization", "name": "セブンセンシズ株式会社", "url": "https://corp.7senses.co.jp/"},
          "datePublished": s["date"], "variableMeasured": ["出典のサイトの種類", "出典の割合"],
          "distribution": {"@type": "DataDownload", "encodingFormat": "text/csv",
                           "contentUrl": f"https://ai.7senses.co.jp/research/{ind}-ai-sources/data.csv"},
          "isAccessibleForFree": True, "inLanguage": "ja"}
    csv = ["区分,種類,出典の件数,出典の割合(%)"]
    for g, c in [("全体", s["total"])] + list(s["by_group"].items()) + [(f"AI:{e}", c) for e, c in s["by_engine"].items()]:
        for k in CATS:
            if c.get(k):
                csv.append(f"{g},{CATS[k]},{c[k]},{pct(c, k)}")
    title = f"{name}の質問にAIは何を出典に答えるか｜{s['questions']}問×4つのAIの調査"
    desc = cite
    return title, desc, body, ld, "\n".join(csv) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--industry", default="dental", choices=sorted(QUESTIONS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--classify", action="store_true")
    a = ap.parse_args()
    qs = questions(a.industry)
    print(f"■ {QUESTIONS[a.industry]['name']}: 質問{len(qs)}問 / 見積もり 約${estimate(len(qs)):.1f}（Claudeはサブスク・Geminiは無料枠）")
    for g, items in QUESTIONS[a.industry]["groups"].items():
        print(f"   {g}: {len(items)}問")
    if a.dry_run:
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    raw_path = OUT / f"{a.industry}-raw.json"
    if a.classify and raw_path.is_file():
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    else:
        t0 = time.time()
        raw = ask_all(a.industry)
        raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  聞き終わりました（{(time.time() - t0) / 60:.0f}分）")
    cls = classify(raw)
    s = summarize(raw, cls)
    s.update({"industry": a.industry, "name": QUESTIONS[a.industry]["name"], "date": raw["date"],
              "questions": len(qs), "engines": raw["engines"], "groups": {g: len(v) for g, v in QUESTIONS[a.industry]["groups"].items()}})
    s["per_answer"] = per_answer(raw)
    (OUT / f"{a.industry}-summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    tot = sum(s["total"].values()) or 1
    print("\n■ 出典の種類（全体）")
    for k, n in sorted(s["total"].items(), key=lambda x: -x[1]):
        print(f"   {CATS[k]:<20} {n:>4}件 {n / tot * 100:5.1f}%")
    print("\n■ 回答できた数（AIごと）", s["answered"])
    errs = Counter(name for by in raw["answers"].values() for name, r in by.items() if name != "group" and r.get("error"))
    if errs:
        print("■ 失敗した数", dict(errs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
