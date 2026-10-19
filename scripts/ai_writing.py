# -*- coding: utf-8 -*-
"""記事の AI っぽい言い回しを textlint で見つけて直す（2026-10-20 運用者の決定「AIぽい言い回しは自動で直すこと」）。

道具: automation/textlint/（package.json・package-lock.json で版を固定。CI は npm ci --prefix automation/textlint）。
ルールは textlint-rule-preset-ja-technical-writing と @textlint-ja/textlint-rule-preset-ai-writing。
本サイトの書式の決まり（CLAUDE.md 6章）とぶつかるルールは .textlintrc.json で止めた（止めた理由は RULES.txt）。

2つに分けて直す:
  - 機械で安全に直せるもの（.textlintrc.fix.json のルールだけ・誤用の辞書と文字の正規化）は textlint の直しを当て、
    fix_guard（auto_review.guard・数字・出典・見出し・フロントマター）に外れたら書かない
  - 判断の要るもの（誇張・「〜することができます」・箇条書きの「**札**:」など）は auto_rewrite の種類 aiwriting で、
    検出された文だけを claude に言い換えさせる（auto_rewrite の検算すべて＋rewrite_guard）

検査しない場所: フロントマター・「よくある質問」の節（本文とフロントマターの FAQ は同じ文でないといけない）・
コードブロックと HTML のブロック（textlint の Markdown の読み方で外れる）・リンクの URL・「」の中（出典や文例の引用）・
引用（> の行）。行の番号は原稿の行のまま（外した行は空にして渡す）。

  python scripts/ai_writing.py --detect [--sites <社>] [--slugs a,b]   # 検出の件数（ルール別・多い記事）
  python scripts/ai_writing.py --fix [--write] [--sites <社>]           # 公開済みの記事に機械の直しを当てる
  python scripts/ai_writing.py --report                                 # 週次の findings: 検出件数の推移（増えたら要対応）
  python scripts/ai_writing.py --brief                                  # 書く AI への案内（site_brief が出す）
  python scripts/ai_writing.py --selftest                               # 検算が悪い直しを止めるか（auto_rewrite --kind aiwriting --selftest も同じ）
"""
import argparse
import collections
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

TL = ROOT / "automation" / "textlint"
CONFIG = TL / ".textlintrc.json"            # 検出（止めていないルール全部）
FIX_CONFIG = TL / ".textlintrc.fix.json"    # 機械で直してよいルールだけ
LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"
TREND = ROOT / "data" / "ai_writing_trend.json"
WEEKLY_PER_SITE = 4      # 週次に判断の直しを当てる本数（社ごと。sites/<id>.json の ai_writing_weekly で変えられる）
HIT_LIMIT = 12           # 1回の直しで AI に渡す指摘の数（多すぎると指摘の無い文まで書き換える）
OTHER_LINES = 2          # 指摘の無い行の変更を許す数（句読点の調整など）
OTHER_CHARS = 20         # その行の変更の字数の合計の上限

# 判断の要るルール → 書く AI・直す AI に渡す説明（止めたルールは載せない。stopped() が .textlintrc.json から決める）
RULES = {
    "@textlint-ja/ai-writing/no-ai-hype-expressions":
        "誇張・絶対の言い方（完璧な・完全に・大幅に・革命的・最高の・次世代の）は、数字か条件に言い換える。"
        "「NAPを完全に一致させる」のように事実として要る言い方はそのままでよい",
    "@textlint-ja/ai-writing/no-ai-list-formatting":
        "箇条書きの「- **札**: 説明」は、コロンを外して「- **札**は、説明」の文にする（太字は残す）。行頭の絵文字は外す",
    "@textlint-ja/ai-writing/no-ai-emphasis-patterns":
        "「**注意**」「**重要**」のような太字の札・見出しの中の太字は、札を外して文で言い、太字は文の核心の語へ移す",
    "@textlint-ja/ai-writing/no-ai-colon-continuation":
        "「〜します:」のように述語の後のコロンで箇条書き・表へつながない。「〜は次のとおりです。」にする",
    "@textlint-ja/ai-writing/ai-tech-writing-guideline":
        "回りくどい義務表現（〜する必要があります）は「〜してください」、あいまいな判断（適切な・必要に応じて）は具体的な条件にする",
    "ja-technical-writing/ja-no-redundant-expression":
        "「〜することができます」「〜することも可能です」は「〜できます」にする",
    "ja-technical-writing/no-mix-dearu-desumasu":
        "本文の「だ・である」調は、ですます調にそろえる",
    "ja-technical-writing/no-doubled-conjunction":
        "同じ接続詞（まずは・または）を続けて使わない",
    "ja-technical-writing/no-doubled-conjunctive-particle-ga":
        "1文に逆接の「が」を2回使わない（文を分ける）",
    "ja-technical-writing/no-double-negative-ja":
        "二重否定（〜ないわけではない）は肯定で言い切る",
    "ja-technical-writing/no-dropping-the-ra":
        "ら抜き言葉を使わない",
    "ja-technical-writing/ja-no-abusage":
        "言葉の誤用（目が止まる→目が留まる）を直す（機械の直しが先に当たる）",
}
# 機械で直してよいルール（意味の変わらない直しだけ。.textlintrc.fix.json と同じ並び）
FIX_RULES = ("ja-technical-writing/ja-no-abusage", "ja-technical-writing/no-nfd",
             "ja-technical-writing/no-zero-width-spaces", "ja-technical-writing/no-invalid-control-character",
             "ja-technical-writing/no-hankaku-kana")


class Unavailable(RuntimeError):
    """textlint（node と automation/textlint/node_modules）が無い"""


def available():
    return bool(shutil.which("node")) and (TL / "node_modules" / "textlint").is_dir()


def stopped():
    """.textlintrc.json で止めたルール（"ja-technical-writing/<名>" の形）"""
    try:
        d = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    out = set()
    for preset, short in (("preset-ja-technical-writing", "ja-technical-writing"),
                          ("@textlint-ja/preset-ai-writing", "@textlint-ja/ai-writing")):
        for k, v in ((d.get("rules") or {}).get(preset) or {}).items():
            if v is False:
                out.add(f"{short}/{k}")
    return out


# ── 原稿の下ごしらえ ─────────────────────────────────────────────────

def _front_end(lines):
    """フロントマターの最後の行（---）の位置。無ければ -1"""
    if not lines or lines[0].strip() != "---":
        return -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i
    return -1


def mask(text):
    """検査に渡す文。フロントマターと「よくある質問」の節の行を空にする（行の数・番号はそのまま）"""
    lines = text.split("\n")
    out = list(lines)
    end = _front_end(lines)
    for i in range(end + 1):
        out[i] = ""
    faq = False
    for i in range(end + 1, len(lines)):
        if re.match(r"^##\s", lines[i]):
            faq = bool(re.search(r"よくある質問|FAQ|Q&A", lines[i]))
        if faq:
            out[i] = ""
    return "\n".join(out)


def front_text(text):
    lines = text.split("\n")
    return "\n".join(lines[:_front_end(lines) + 1])


def body_text(text):
    lines = text.split("\n")
    return "\n".join(lines[_front_end(lines) + 1:])


def _in_quote(line, col):
    """col（0始まり）が「」『』の中か"""
    depth = 0
    for ch in line[:col]:
        if ch in "「『":
            depth += 1
        elif ch in "」』" and depth:
            depth -= 1
    return depth > 0


def sentence_at(line, col):
    """col を含む1文（。で区切る）"""
    a = line.rfind("。", 0, max(col, 0)) + 1
    b = line.find("。", col)
    return line[a:(b + 1 if b >= 0 else len(line))].strip()


# ── textlint を動かす ───────────────────────────────────────────────

def run(texts, mode="lint", config=None):
    """texts（[文]）を textlint に当てる。返すのは [{messages, output?, error?}]（並びは texts と同じ）"""
    if not available():
        raise Unavailable("textlint が入っていません（npm ci --prefix automation/textlint）")
    req = {"config": str(config or CONFIG), "mode": mode,
           "items": [{"name": f"a{i}", "text": t} for i, t in enumerate(texts)]}
    r = subprocess.run(["node", str(TL / "run.cjs")], cwd=TL, input=json.dumps(req, ensure_ascii=False),
                       capture_output=True, text=True, encoding="utf-8", timeout=1800)
    if r.returncode:
        raise Unavailable(f"textlint が動きませんでした（{(r.stderr or '').strip()[:160]}）")
    return json.loads(r.stdout)


def hits_of(text, res):
    """textlint の結果 → 指摘（「」の中・引用の行・止めたルールは除く）。[{rule, line, col, message, sentence}]"""
    lines = text.split("\n")
    off = stopped()
    out = []
    for m in res.get("messages") or []:
        rule = m.get("ruleId") or ""
        if rule in off:
            continue
        ln = int(m.get("line") or 1)
        col = max(int(m.get("column") or 1) - 1, 0)
        src = lines[ln - 1] if 0 < ln <= len(lines) else ""
        if src.lstrip().startswith(">") or _in_quote(src, col):
            continue
        out.append({"rule": rule, "line": ln, "col": col,
                    "message": str(m.get("message") or "").split("\n")[0][:160],
                    "sentence": sentence_at(src, col)[:200]})
    return out


def detect_texts(texts):
    """[原稿の全文] → [[指摘]]（並びは同じ。1本が落ちてもほかは返す。落ちた原稿は None）"""
    if not texts:
        return []
    res = run([mask(t) for t in texts])
    return [None if r.get("error") else hits_of(t, r) for t, r in zip(texts, res)]


DETECT = detect_texts     # 門ではこれを差し替える（本物の textlint を呼ばない回）


def count(text):
    """原稿1本の指摘の数（数えられなければ None）"""
    try:
        got = DETECT([text])
    except Unavailable:
        return None
    return None if not got or got[0] is None else len(got[0])


# ── 記事 ─────────────────────────────────────────────────────────────

def _read(slug):
    return (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")


def _meta(text):
    import auto_rewrite as A
    return A.front_safe(text)


def shown(slug):
    try:
        import private_store as PS
        return PS.shown(slug)
    except Exception:
        return "（記事）"


def site_of(slug):
    import auto_rewrite as A
    try:
        return A.site_of(slug)
    except Exception:
        return ""


def published(sites=(), slugs=()):
    """公開済み（点数が門を通る・noindex でない・改善中でない）の記事。sites・slugs で絞る"""
    import rubric as R
    out = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        if p.name.startswith("_") or (slugs and p.stem not in slugs):
            continue
        m = _meta(p.read_text(encoding="utf-8-sig"))
        if not m or m.get("noindex") or R.improving(m) or not R.gate_ok(m):
            continue
        if sites and site_of(p.stem) not in sites:
            continue
        out.append(p.stem)
    return out


def detect_slugs(slugs):
    """{slug: [指摘] | None}"""
    texts = [_read(s) for s in slugs]
    return dict(zip(slugs, DETECT(texts)))


def item_for(slug, hits=None):
    """auto_rewrite の種類 aiwriting の1件（指摘が無ければ None）"""
    if hits is None:
        hits = detect_slugs([slug]).get(slug)
    if not hits:
        return None
    by = collections.Counter(h["rule"] for h in hits)
    return {"kind": "aiwriting", "slug": slug, "site": site_of(slug), "hits": hits[:HIT_LIMIT], "count": len(hits),
            "why": f"AIっぽい言い回し {len(hits)}か所（" + "・".join(
                f"{r.rsplit('/', 1)[-1]} {n}" for r, n in by.most_common(3)) + "）"}


def per_site_quota(sid):
    try:
        import sites as S
        return int((S.load(sid) or {}).get("ai_writing_weekly", WEEKLY_PER_SITE))
    except Exception:
        return WEEKLY_PER_SITE


def items(sites=()):
    """週次の候補: 公開済みの記事のうち指摘の多い順に、社ごとに ai_writing_weekly 本（既定4本）"""
    slugs = published(sites)
    got = detect_slugs(slugs)
    rows = [item_for(s, h) for s, h in got.items() if h]
    rows.sort(key=lambda x: -x["count"])
    out, used = [], collections.Counter()
    for x in rows:
        if used[x["site"]] >= per_site_quota(x["site"]):
            continue
        used[x["site"]] += 1
        out.append(x)
    return out


def hits_text(hits, limit=HIT_LIMIT):
    """直す AI に渡す指摘（行番号つき）"""
    out = []
    for h in hits[:limit]:
        why = RULES.get(h["rule"]) or h["message"]
        out.append(f"- {h['line']}行目: 「{h['sentence']}」\n  直し方: {why}")
    return "\n".join(out)


# ── 機械の直し ───────────────────────────────────────────────────────

def _textlint_fix(text):
    """FIX_CONFIG のルールだけで直した全文と、当てたルール。フロントマター・FAQ の行は触らない"""
    masked = mask(text)
    r = run([masked], "fix", FIX_CONFIG)[0]
    if r.get("error") or r.get("output") is None:
        return text, []
    ml, ol, tl = masked.split("\n"), r["output"].split("\n"), text.split("\n")
    if len(ol) != len(ml):
        return text, []          # 行がずれる直しは当てない（どの行の直しか確かめられない）
    for i, (m, o) in enumerate(zip(ml, ol)):
        if m != o and m != "":
            tl[i] = o
    return "\n".join(tl), [a.get("ruleId", "") for a in r.get("applied") or []]


FIXER = _textlint_fix     # 門ではこれを差し替える


def _heads(text):
    return re.findall(r"^#{1,6}\s.*$", text, re.M)


def fix_guard(before, after):
    """機械の直しの検算（空なら合格）。題・説明文・狙う語（フロントマター）・数字・出典・見出し・タグ・導線を変えない"""
    import auto_review as AR
    import auto_rewrite as A
    if front_text(before) != front_text(after):
        return "フロントマター（題・説明文・狙う語など）が変わりました"
    g = AR.guard("", body_text(before), body_text(after), 0)
    if g:
        return g
    if A.new_fact_numbers(before, after) or A.new_fact_numbers(after, before):
        return "数字が変わりました"
    if A.sources(before) != A.sources(after):
        return "出典リンクが変わりました"
    if _heads(before) != _heads(after):
        return "見出しが変わりました"
    return ""


def note(slug, kind, ok, why, **extra):
    import client_private as CP
    CP.append_jsonl(LOG, {"at": time.strftime("%Y-%m-%d %H:%M"), "by": "ai_writing", "slug": slug, "kind": kind,
                          "ok": ok, "note": why, **extra})


def fix_text(before):
    """全文に機械の直しを当てて検算する。返すのは (直した後の全文, 状態, 理由, 当てたルール)。
    状態は none / fixed / reverted（reverted のときの全文は before のまま）"""
    after, applied = FIXER(before)
    rules = sorted({a.rsplit("/", 1)[-1] for a in applied if a})
    if after == before:
        return before, "none", "", rules
    why = fix_guard(before, after)
    if why:
        return before, "reverted", why, rules
    return after, "fixed", f"{len(applied)}か所（{'・'.join(rules)}）", rules


def machine_fix(slug, write=True, path=None):
    """1本に機械の直しを当てる（台帳 auto_fix.jsonl に残す）。返すのは (状態, 理由)。状態は none / fixed / reverted"""
    p = Path(path) if path else ROOT / "articles" / f"{slug}.md"
    before = p.read_text(encoding="utf-8-sig")
    after, st, why, rules = fix_text(before)
    if st == "reverted":
        note(slug, "textlint-fix", False, f"検算で戻しました（{why}）", rules=rules)
    elif st == "fixed" and write:
        p.write_text(after, encoding="utf-8", newline="")
        note(slug, "textlint-fix", True, f"機械の直し {why}", rules=rules)
    return st, why


# ── 判断の直しの検算（auto_rewrite の種類 aiwriting） ─────────────────

def _moved_chars(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")


def rewrite_guard(before, after, hits, total_before):
    """aiwriting の直しの検算（空なら合格）。auto_rewrite.check（数字・出典・狙う語・警告・食い合い・ビルド）の後に見る:
    フロントマター・行の数が同じ／指摘の無い行はほぼ触らない／「」の引用を変えない／タグと導線を変えない／指摘が減った"""
    import auto_review as AR
    if front_text(before) != front_text(after):
        return "フロントマターが変わりました（直すのは指摘の文だけ）"
    bl, al = before.split("\n"), after.split("\n")
    if len(bl) != len(al):
        return f"行の数が変わりました（{len(bl)}→{len(al)}）。指摘の文だけを直すこと"
    flagged = {h["line"] for h in hits}
    other = [i for i, (x, y) in enumerate(zip(bl, al)) if x != y and (i + 1) not in flagged]
    if other and (len(other) > OTHER_LINES or sum(_moved_chars(bl[i], al[i]) for i in other) > OTHER_CHARS):
        return f"指摘の無い行まで変わりました（{len(other)}行。{other[0] + 1}行目など）"
    quotes = set(re.findall(r"「[^」\n]{6,}」", before))
    lost = sorted(q for q in quotes if q not in after)
    if lost:
        return f"かぎ括弧の引用が変わりました（{lost[0][:30]}）"
    g = AR.guard("", body_text(before), body_text(after), 0)
    if g:
        return g
    n1 = count(after)
    if n1 is None:
        return "検出の道具が動かないため、指摘が減ったか確かめられません"
    if n1 >= total_before:
        return f"指摘が減っていません（{total_before}→{n1}件）"
    return ""


# ── 書く AI への案内（site_brief） ─────────────────────────────────

def brief():
    """書く AI に渡す「書かない言い回し」（12行まで）。止めたルールは載せない"""
    off = stopped()
    rows = [v for k, v in RULES.items() if k not in off]
    if not rows:
        return []
    head = ["■ AIっぽい言い回しを書かない（公開前に textlint が検出し、機械と別工程の AI が直す。最初から書かなければ直しの時間が要らない）"]
    return head + [f"  - {v[:90]}" for v in rows[:11]]


# ── 週次の推移（findings） ───────────────────────────────────────────

def _week(d=None):
    y, w, _ = (d or date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def report(today=None, trend=None):
    """公開済みの記事の検出件数を社ごとに数え、前の週と比べる。1本あたりの件数と合計の両方が増えた社は要対応"""
    import sites as S
    trend = Path(trend or TREND)
    if not available():
        print("要対応: AIっぽい言い回しの検査を動かせません（textlint が入っていません。npm ci --prefix automation/textlint）")
        print("AI_WRITING_OK=unknown")
        return 0
    slugs = published()
    try:
        got = detect_slugs(slugs)
    except Unavailable as e:
        print(f"要対応: AIっぽい言い回しの検査が動きませんでした（{e}）")
        print("AI_WRITING_OK=unknown")
        return 0
    now = {}
    for s, h in got.items():
        sid = site_of(s)
        try:
            pub = S.public_id(sid)
        except Exception:
            pub = sid
        row = now.setdefault(pub, {"articles": 0, "hits": 0, "failed": 0})
        row["articles"] += 1
        if h is None:
            row["failed"] += 1
        else:
            row["hits"] += len(h)
    try:
        hist = json.loads(trend.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hist = {}
    wk = _week(today)
    prev_wk = max((k for k in hist if k < wk), default="")
    prev = hist.get(prev_wk) or {}
    print(f"■ AIっぽい言い回しの検出件数（公開済みの記事・{wk}）")
    bad = False
    for pub, r in sorted(now.items()):
        rate = r["hits"] / r["articles"] if r["articles"] else 0
        p = prev.get(pub)
        was = (f"・前の週 {p['hits']}件／{p['articles']}本"
               f"（1本あたり{p['hits'] / p['articles']:.2f}）") if p and p.get("articles") else "・前の週の記録なし"
        print(f"  {pub}: {r['hits']}件／{r['articles']}本（1本あたり{rate:.2f}）{was}"
              + (f"・検査できず {r['failed']}本" if r["failed"] else ""))
        if p and p.get("articles") and r["hits"] > p["hits"] and rate > p["hits"] / p["articles"] + 0.005:
            bad = True
            print(f"要対応: {pub} の AIっぽい言い回しが増えました（{p['hits']}→{r['hits']}件・1本あたり"
                  f"{p['hits'] / p['articles']:.2f}→{rate:.2f}）。書く指示（site_brief の案内）と公開前の直しを確かめてください")
    hist[wk] = now
    trend.parent.mkdir(parents=True, exist_ok=True)
    trend.write_text(json.dumps(dict(sorted(hist.items())[-26:]), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("AI_WRITING_OK=" + ("no" if bad else "yes"))
    return 0


# ── 自己診断（悪い直しを止めるか） ────────────────────────────────────

SAMPLE = """---
title: AI検索対策の始め方と費用の目安
keyword: AI検索対策 始め方
---

## AI検索対策とは？

AI検索対策は、AIの回答に自社の情報が引用されるように記事を整える取り組みです。

この方法なら、問い合わせを大幅に増やすことができます。

当社は「申請書類はお客様が作成し、当社は内容の確認を行います」と案内しています。

比較の表は、読み手の目が止まる場所に置きます。

費用は月3万円からです。詳しくは[料金の記事](/aio/hiyou/)をご覧ください。
"""


def selftest():
    """検算が効くかを確かめる（claude は呼ばない）。悪い直し・機械の直しの悪い結果を当てて止まるか、良い直しを通すか"""
    if not available():
        print("  NG  textlint が入っていません（npm ci --prefix automation/textlint）")
        return 1
    base = count(SAMPLE)
    hits = (DETECT([SAMPLE])[0] or [])
    lines = {h["line"] for h in hits}
    ok = 0
    good = SAMPLE.replace("問い合わせを大幅に増やすことができます。", "問い合わせを増やせます。")
    cases = [
        ("指摘の文を言い換える（通す）", good, True),
        ("指摘が減らない（言い回しを残したまま語順だけ変える）",
         SAMPLE.replace("問い合わせを大幅に増やすことができます。", "大幅に問い合わせを増やすことができます。"), False),
        ("指摘の無い行まで書き換える",
         good.replace("自社の情報が引用されるように記事を整える取り組みです。", "自社の名前と事実がAIの答えに載るように、記事の構成と中身をまとめて作り直す取り組みのことです。"), False),
        ("かぎ括弧の引用を変える", good.replace("内容の確認を行います", "内容を確認します"), False),
        ("題を変える", good.replace("title: AI検索対策の始め方と費用の目安", "title: AI検索対策の始め方"), False),
        ("行を増やす", good.replace("問い合わせを増やせます。", "問い合わせを増やせます。\n\nまずは相談してください。"), False),
    ]
    if not lines:
        print("  NG  自己診断の文から指摘を拾えません（検出が動いていません）")
        return 1
    for name, after, want in cases:
        why = rewrite_guard(SAMPLE, after, hits, base)
        passed = not why
        good_case = passed == want
        ok += good_case
        print(f"  {'OK' if good_case else 'NG'}  {name}: " + ("通した" if passed else f"止めた（{why[:50]}）"))
    fcases = [
        ("機械の直しが数字を変える", SAMPLE.replace("月3万円", "月30万円"), False),
        ("機械の直しが題を変える", SAMPLE.replace("費用の目安", "費用"), False),
        ("機械の直しがリンクを消す", SAMPLE.replace("[料金の記事](/aio/hiyou/)", "料金の記事"), False),
        ("機械の直しが言葉の誤用だけを直す（通す）", SAMPLE.replace("目が止まる", "目が留まる"), True),
    ]
    for name, after, want in fcases:
        why = fix_guard(SAMPLE, after)
        good_case = (not why) == want
        ok += good_case
        print(f"  {'OK' if good_case else 'NG'}  {name}: " + ("通した" if not why else f"止めた（{why[:50]}）"))
    total = len(cases) + len(fcases)
    print(f"\n  {ok}/{total} が期待どおりでした（指摘 {base}件の見本で確かめました）")
    return 0 if ok == total else 1


# ── 実行 ─────────────────────────────────────────────────────────────

def _sites(spec):
    import sites as S
    out = set()
    for x in re.split(r"[\s,]+", spec or ""):
        if x:
            try:
                out.add(S.resolve(x))
            except Exception:
                out.add(x)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--detect", action="store_true")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--sites", default="")
    ap.add_argument("--slugs", default="")
    a = ap.parse_args(argv)
    if a.brief:
        print("\n".join(brief()))
        return 0
    if a.report:
        return report()
    if a.selftest:
        print("■ AIっぽい言い回しの直しの検算の自己診断\n")
        return selftest()
    if not available():
        print("要対応: textlint が入っていません（npm ci --prefix automation/textlint）")
        print("AI_WRITING=unavailable")
        return 0
    sites = _sites(a.sites)
    want = [s.strip() for s in a.slugs.split(",") if s.strip()]
    slugs = want or published(sites)
    if a.fix:
        res = collections.Counter()
        for s in slugs:
            st, why = machine_fix(s, write=a.write)
            res[st] += 1
            if st != "none":
                print(f"  {'○' if st == 'fixed' else '×'} {shown(s)[:40]}: {why[:60]}")
        print(f"AI_WRITING_FIX=fixed {res['fixed']}, reverted {res['reverted']}, none {res['none']}"
              + ("" if a.write else "（確認のみ）"))
        return 0
    got = detect_slugs(slugs)
    by = collections.Counter(h["rule"] for hs in got.values() if hs for h in hs)
    failed = sum(1 for hs in got.values() if hs is None)
    print(f"■ AIっぽい言い回しの検出: {sum(by.values())}件／{len(got)}本" + (f"（検査できず {failed}本）" if failed else ""))
    for r, n in by.most_common():
        print(f"  {n:5}  {r}")
    top = sorted(((len(h), s) for s, h in got.items() if h), reverse=True)[:10]
    for n, s in top:
        print(f"  {n:3}件  {shown(s)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
