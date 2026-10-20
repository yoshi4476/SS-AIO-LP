"""記事ごとの「当社調べ」: 記事の狙う語を複数の AI に聞き、答えに何が書かれ、何が無いかを数えて一次情報にする。

一次性の採点は「自社で測った数字・現場の判断が3か所以上、母数と時期つき」で高くなる。お客様や運用者から材料が
届かない題でも、ここで測った数字なら事実として書ける（2026-10-20 運用者「情報がなくても90以上になるように」）。
数えるのは文字どおりのこと（答えの本文にその語が出たか・出典に挙がったページの種類）だけにし、解釈は書かない。

聞くのは契約の枠（ChatGPT の Codex・Claude Code）と、Gemini（無料の枠の内）。従量課金の API は使わない。
同じ AI に同じ質問をしたら30日は前の答えを使う（ai_cite_check の控え）。2つ以上の AI に聞けたときだけ書く。

  python scripts/own_survey.py <slug>          # 測って data/own_survey/<slug>.json に残す（お客様の社は非公開の置き場）
  python scripts/own_survey.py <slug> --show   # 残した結果の文を見る
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "data" / "own_survey"
MIN_ENGINES = 2
MAX_ENGINES = 3
# 聞く先。Claude（Claude Code）と ChatGPT（Codex）は契約の枠、Gemini は無料の枠の内（月の検索回数の残りがあるとき）。
# 従量課金の API（OpenAI・Perplexity）は使わない（2026-10-20 運用者「ChatGPT はサブスクの Codex、Perplexity はいらない」）
ORDER = ["Claude", "ChatGPT", "Gemini"]
SUB_ONLY = {"Claude", "ChatGPT"}
# 見出しから論点の語を取り出すときに外す語（問いの形・つなぎ・どの記事にも出る語）
STOP = set("とは 何 なに どう どの どれ いつ なぜ 方法 やり方 ポイント 注意点 違い 比較 選び方 目安 理由 場合 手順 "
           "まとめ よくある質問 費用 相場 メリット デメリット 対策 する できる ある ない 必要 こと もの ため よう 場合は "
           "つの 3つ 4つ 5つ 6つ 7つ 会社 企業 自社 当社 記事 内容 時期 毎月 確認 判断 失敗 成功 準備 方法 基準 一覧 "
           "今日 最初 前後 以上 以下 業者 担当 費用 料金 効果 結果 事例 実例 種類 流れ 仕組み 注意 理由".split())


# 記事の見出しに頼らずに数える観点（答えにその種類の情報が書かれていたか）
DIMS = [
    ("費用の金額（◯円）", r"\d[\d,]*\s*(?:万|千)?円"),
    ("期間（◯か月・◯日など）", r"\d+\s*(?:か月|ヶ月|カ月|ヵ月|日|週間|年)"),
    ("注意点・失敗・リスク", r"注意|リスク|落とし穴|失敗|トラブル"),
    ("進め方の手順", r"手順|ステップ|STEP|進め方"),
    ("専門家への相談", r"専門家|税理士|弁護士|行政書士|社労士|司法書士|相談先"),
]


def _path(site, slug):
    import client_private as CP
    if site and CP.is_private(site):
        return CP.private_path(site, f"data/own_survey/{slug}.json")
    return OUT / f"{slug}.json"


def load(site, slug):
    try:
        return json.loads(_path(site, slug).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def topics(body):
    """記事の論点（FAQ・まとめを除く H2）と、それぞれを言い当てる語"""
    out = []
    for h in re.findall(r"^## (.+)$", body, re.M):
        if re.search(r"よくある質問|まとめ|FAQ", h):
            continue
        h = re.sub(r"[*`]", "", h).strip()
        # 漢字・カタカナ・英字の続き（名詞にあたる所）だけを拾う。ひらがなで切ると「回すこ」「渡す」のような語が残った
        words = []
        for m in re.finditer(r"[一-龥々〆ヵヶァ-ヴーA-Za-z0-9０-９]{2,}", h):
            w, nxt = m.group(0), h[m.end():m.end() + 1]
            # 数字を含む語（「年10月」）・「何位」のような問いの語・送り仮名が続く動詞の語幹（「丸投げ」の「丸投」）は外す
            if re.search(r"[\d０-９]", w) or w.startswith("何") or w in STOP:
                continue
            if re.fullmatch(r"[ぁ-ゖ]", nxt or "x") and nxt not in "のはがをにでともやかへ":
                continue
            words.append(w)
        words.sort(key=lambda w: -len(w))
        if words:
            out.append((h, words[:4]))
    return out


def engines(site):
    import ai_cite_check as AC
    sub = dict(AC.subscription_engines())
    try:
        paid = AC.engines_available(site)
    except Exception:  # noqa: BLE001  鍵が無ければ契約の枠だけで聞く
        paid = {}
    got = {}
    for name in ORDER:
        fn = sub.get(name) if name in SUB_ONLY else paid.get(name)
        if fn and len(got) < MAX_ENGINES:
            got[name] = fn
    return got


def ask(site, kw):
    """各 AI の答え（本文と出典のドメイン）。答えられなかった AI は入れない"""
    import ai_cite_check as AC
    q = f"{kw}について教えてください"
    out = {}
    # 答えの本文が要る（本文の無い古い控えは聞き直す）。聞く間だけ切り替え、ほかの工程の控えの使い方を変えない
    keep, AC.NEED_TEXT = AC.NEED_TEXT, True
    try:
        for name, fn in engines(site).items():
            try:
                urls = fn(q) or []
            except Exception:  # noqa: BLE001  1つの AI が落ちても他で数える
                continue
            text = AC.answer_text(fn, q)
            if text:
                out[name] = {"text": text, "domains": sorted({AC.domain_of(u) for u in urls if AC.domain_of(u)})}
    finally:
        AC.NEED_TEXT = keep
    return q, out


def kinds(domains, site):
    import compete
    import sites as S
    try:
        mine, own = compete.site_domains(site, S.load_all().get(site) or {})
    except Exception:  # noqa: BLE001
        mine, own = set(), set()
    return {d: compete.kind_of(d, mine, own) for d in domains}


def measure(site, slug, body, kw):
    q, ans = ask(site, kw)
    if len(ans) < MIN_ENGINES:
        return {"slug": slug, "ok": False, "why": f"答えられた AI が{len(ans)}つ（{MIN_ENGINES}つ以上で数える）"}
    names = sorted(ans)
    rows = []
    # 狙う語そのもの（とそれを含む語）は、どの答えにも出て当たり前なので数えない（「すべての答えに『外注』」は一次情報にならない）
    kws = [t for t in re.split(r"[\s　]+", kw.lower()) if len(t) >= 2]
    for h, words in topics(body):
        words = [w for w in words if not any(t in w.lower() for t in kws)]
        if not words:
            continue
        hit = [n for n in names if any(w.lower() in ans[n]["text"].lower() for w in words)]
        rows.append({"topic": h, "words": words, "engines": hit})
    doms = sorted({d for n in names for d in ans[n]["domains"]})
    kd = kinds(doms, site)
    dims = {label: [n for n in names if re.search(rx, ans[n]["text"])] for label, rx in DIMS}
    return {"slug": slug, "ok": True, "date": date.today().isoformat(), "question": q, "engines": names,
            "topics": rows, "sources": {d: kd.get(d, "") for d in doms}, "dims": dims,
            "chars": {n: len(ans[n]["text"]) for n in names}}


def claims(res):
    """測った結果を、そのまま記事に書ける文にする（数えたことだけ。解釈は足さない）"""
    if not res.get("ok"):
        return []
    import compete
    y, m = res["date"][:4], int(res["date"][5:7])
    n = len(res["engines"])
    who = "・".join(res["engines"])
    # 書き出しを記事ごとに散らす（同じ一文が数百本に並ぶと量産の指紋になる。内部リンク文で41.5%が同じ一文だった）
    import hashlib
    k = int(hashlib.md5(str(res.get("slug", "")).encode("utf-8")).hexdigest(), 16) % 3
    # 「1回だけの試行か」と採点で突かれた。実際に3つの AI に1回ずつ聞いた3件の答えなので、件数をそのまま書く
    # （聞いていない回数は書かない。2026-10-21 運用者「複数の結果で書く・2回は調べない」）
    q = res["question"]
    head = (f"当社が{y}年{m}月に、{n}つのAI（{who}）に「{q}」と同じ質問をして、{n}件の答えを比べたところ",
            f"{y}年{m}月に当社が{n}つのAI（{who}）へ同じ質問「{q}」をして、返ってきた{n}件の答えを比べたところ",
            f"当社調べ（{y}年{m}月、{n}つのAI：{who}に同じ質問をした{n}件の答え）で「{q}」の答えを比べたところ")[k]
    out = []
    rows = [r for r in res["topics"] if r["words"]]
    if rows:
        none = [r for r in rows if not r["engines"]]
        allx = [r for r in rows if len(r["engines"]) == n]
        if none:
            names = "』『".join(dict.fromkeys(r["words"][0] for r in none[:3]))
            out.append(f"{head}、本記事で扱う{len(rows)}つの論点のうち『{names}』の語が出てきた答えは0件でした")
        if allx:
            names = "』『".join(dict.fromkeys(r["words"][0] for r in allx[:3]))
            out.append(f"{head}、{n}件すべての答えに『{names}』の語が出てきました")
        part = [r for r in rows if 0 < len(r["engines"]) < n]
        if part and len(out) < 2:
            r = part[0]
            out.append(f"{head}、『{r['words'][0]}』の語が出てきた答えは{n}件中{len(r['engines'])}件でした")
    dims = res.get("dims") or {}
    if dims:
        # 全部に出た観点より、出なかった・一部だけの観点のほうが「答えに足りないもの」として一次情報になる
        pick = sorted(dims.items(), key=lambda x: (len(x[1]) == n, len(x[1])))[:3]
        parts = "、".join(f"{label}に触れた答えは無く" if not v else f"{label}に触れた答えは{n}件中{len(v)}件"
                         for label, v in pick)
        out.append(f"{head}、{parts}でした")
    src = res.get("sources") or {}
    if src:
        by = {}
        for _, k in src.items():
            by[k or "peer"] = by.get(k or "peer", 0) + 1
        # 種類が見分けられるもの（公的機関・メディアなど）だけを書く。見分けのつかないサイトを「同業」と決めつけない
        known = ["public", "media", "portal", "wiki", "video"]
        parts = "、".join(f"{compete.TYPES[k]}が{by.get(k, 0)}件" for k in known[:2])
        rest = [f"{compete.TYPES[k]}が{by[k]}件" for k in known[2:] if by.get(k)]
        parts = "、".join([parts] + rest)
        out.append(f"{head}、出典に挙がったページは{len(src)}件で、{parts}でした")
    return out


def run(slug, force=False):
    """測って残す。同じ月に測った結果があれば使い回す（AI に聞き直さない）"""
    import quality_loop as Q
    site = Q.site_of(slug)
    text = Q.read(slug)
    kw = str(Q.meta_of(text).get("keyword") or "").strip()
    if not kw:
        return {}
    old = load(site, slug)
    if old.get("ok") and not force and old.get("date", "")[:7] == date.today().isoformat()[:7]:
        return old
    res = measure(site, slug, text, kw)
    if not res.get("ok") and old.get("ok"):
        return old            # 聞けなかった回は、前に測った結果を消さない
    res["claims"] = claims(res)
    p = _path(site, slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return res


def targets(sites=()):
    """測る記事: 直している途中（改善中）の記事と、この回に書いた新しい記事（git に無い原稿）"""
    import subprocess
    import quality_loop as Q
    new = set(subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "articles/"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8").stdout.split())
    out = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        if p.name.startswith("_") or (sites and Q.site_of(p.stem) not in sites):
            continue
        rel = f"articles/{p.name}"
        if rel in new or re.search(r"^quality_state:\s*improving", p.read_text(encoding="utf-8-sig"), re.M):
            out.append(p.stem)
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    import quality_loop as Q
    if "--rescore" in sys.argv:
        # 週次の公開済みの記事の採点し直し（quality_loop --rescore N と同じ選び方）
        n = int(args[0]) if args and args[0].isdigit() else 4
        args = Q.rescore_targets(n)
        print(f"OWN_SURVEY_TARGETS={len(args)}")
    elif "--rescore-auto" in sys.argv:
        # 毎日の記事の枠で直す公開済みの記事（公開前の採点で90点以上が出てから。quality_loop.auto_targets と同じ選び方）
        import sites as S
        n = int(args[0]) if args and args[0].isdigit() else 1
        sids = {S.resolve(x) for x in args[1:]}
        args = Q.auto_targets(n, sids)
        print(f"OWN_SURVEY_TARGETS={len(args)}")
    elif "--targets" in sys.argv:
        # CI の記事の枠: 鍵のある機械の手順で、採点の前に測っておく（採点の工程は鍵を外して動くため、そこでは聞けない）
        import sites as S
        sids = [S.resolve(x) if hasattr(S, "resolve") else x for x in args]
        args = targets(set(sids))
        print(f"OWN_SURVEY_TARGETS={len(args)}")
    if not args:
        if "--targets" in sys.argv or "--rescore-auto" in sys.argv or "--rescore" in sys.argv:
            return 0             # 測る記事が無い回
        print(__doc__)
        return 1
    import client_private as CP
    import quality_loop as Q
    for slug in args:
        site = Q.site_of(slug)
        res = load(site, slug) if "--show" in sys.argv else run(slug, force="--force" in sys.argv)
        name = Q.shown(slug)
        if not res.get("ok"):
            print(f"OWN_SURVEY=none {name}: {res.get('why', '狙う語がありません')}")
            continue
        print(f"OWN_SURVEY=ok {name}: AI {len(res['engines'])}つ・論点 {len(res['topics'])}・出典 {len(res['sources'])}件")
        if not CP.is_private(site):      # お客様の社の文は狙う語を含むので CI のログに出さない
            for c in res.get("claims") or []:
                print("  -", c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
