# -*- coding: utf-8 -*-
"""登録済みの一次情報どうしの計算だけで、新しい一次情報を作る（例:「継続中31社÷累計48社＝約65%」）。

**なぜ要るか**: 一次性の採点（80点）に届かない記事が多く、具体的な数字を増やしたい。ところが記入済みのヒアリングシートの
数字は台帳に登録済みのものだけだった（2026-11-01）。AI に「仮の実績」を作らせるのは優良誤認なので断り、運用者が認めた
2つの手のうちの1つがこれ（もう1つは記事の中の「試算」。score_check.estimate_issues）。

**守ること**: AI は計算の候補（使う一次情報の id・式・文）を出すだけ。登録の前に機械が全部を検算する。
- 式の数は、元の一次情報の文にある数だけ（単位の換算の 100・10・12 は、文が %・割・年 を言うときだけ）
- 文の数は、元の一次情報の文・期間にある数か、式を計算し直した値（四捨五入の幅まで）だけ。**新しい生の数字は1つも通さない**
- 割合は割る数が10以上のときだけ（0.1節。10未満は割合にしない）。期間の違う一次情報を混ぜるときは、文に両方の期間を書く
- 外れた候補は登録しない。同じ元・同じ式は同じ id を上書きする（積み増さない）。1回に登録するのは1社 MAX 件まで

    python scripts/derived_facts.py --site ai-lab            # 候補と検算の結果を見るだけ
    python scripts/derived_facts.py --site ai-lab --write    # 検算を通った候補を登録する

お客様の社は、一次情報の文も id もログに出さない（件数と却下の理由の内訳だけ）。読み書きは private_store を通す。
"""
import argparse
import ast
import hashlib
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OWN_FACTS = ROOT / "data" / "first_party_facts.json"
CHUNK = 30           # 1回の claude に渡す一次情報の数（material_sheet と同じく、詰めすぎると応答が壊れる）
MAX = 20             # 1回の実行で1社に登録する数（一度に出しすぎない）
MIN_RATE = 10
# 単位の換算に使ってよい数と、それを使うとき文に要る語
UNIT_CONST = {100.0: re.compile(r"%|％|パーセント"), 10.0: re.compile(r"\d割"), 12.0: re.compile(r"年間|年あたり")}
# 「1社あたり」の1は単位で、数えた数ではない
PER = re.compile(r"1\s*(?:社|件|人|名|か月|ヶ月|月|日|時間|本|回|年)\s*(?:あたり|当たり)")
RATE = re.compile(r"\s*(?:%|％|パーセント|割)")       # 計算の結果の直後に置かれたとき、その結果は割合
UNIT_OF = re.compile(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*の?\s*(社|件|店舗|店|回|語|名|人|時間|か月|位|本|日|サイト|%)")
NUM = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
KANJI_NUM = re.compile(r"[一二三四五六七八九十百千]+(?:割|社|件|名|人|%|時間|か月|円)")
# 計算で出した数は事実の言い方にする。見込み・仮定の言い方は試算（記事の中で書く）で、一次情報ではない
NOT_FACT = re.compile(r"見込|予測|予想|推定|想定|仮に|試算|と思われ")
_ZEN = str.maketrans("０１２３４５６７８９．，％÷×－＋（）", "0123456789.,%/*-+()")


def _vals(text):
    return [float(x.replace(",", "")) for x in NUM.findall(str(text or "").translate(_ZEN))]


def _decimals(s):
    return len(s.split(".")[1]) if "." in s else 0


def _eval(node, consts):
    """+ − × ÷ と数だけの式を計算する。それ以外が入っていれば ValueError"""
    if isinstance(node, ast.Expression):
        return _eval(node.body, consts)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        consts.append(float(node.value))
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand, consts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        a, b = _eval(node.left, consts), _eval(node.right, consts)
        if isinstance(node.op, ast.Div):
            if b == 0:
                raise ValueError("0で割っている")
            const = (lambda n: float(n.value) if isinstance(n, ast.Constant) else None)
            consts.append(("div", b, const(node.left), const(node.right)))
            return a / b
        return {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b}[type(node.op)]
    raise ValueError("式に四則演算と数以外が入っている")


def _period_ok(inputs, claim):
    periods = {str(f.get("period") or "").strip() for f in inputs} - {""}
    if len(periods) <= 1:
        return True
    have = set(_vals(claim))
    return all(set(_vals(p)) <= have for p in periods)


def verify(cand, facts):
    """(登録する行, None) か (None, 却下の理由)。理由は決まった文だけ（お客様の社でも内訳として出せる）"""
    byid = {str(f.get("id")): f for f in facts}
    ids = [str(x) for x in (cand.get("inputs") or [])]
    expr, claim = str(cand.get("expr") or "").translate(_ZEN), str(cand.get("claim") or "").strip()
    if not ids or not expr or not claim:
        return None, "元・式・文のどれかが空"
    if len(ids) > 4 or len(set(ids)) != len(ids) or any(i not in byid for i in ids):
        return None, "元の一次情報が登録に無い"
    inputs = [byid[i] for i in ids]
    if any(f.get("derived_from") or f.get("retired") for f in inputs):
        return None, "計算で作った一次情報・取り下げた一次情報を元にしている"
    if NOT_FACT.search(claim) or KANJI_NUM.search(claim) or len(claim) > 160:
        return None, "文が事実の言い方でない（見込み・漢数字・長すぎ）"
    src = [set(_vals(f.get("claim"))) for f in inputs]
    pool = set().union(*src) | set().union(*(set(_vals(f.get("period"))) for f in inputs))
    consts = []
    try:
        result = _eval(ast.parse(re.sub(r"(?<=\d),(?=\d{3})", "", expr), mode="eval"), consts)
    except (SyntaxError, ValueError, RecursionError):
        return None, "式が四則演算として読めない"
    nums = [c for c in consts if not isinstance(c, tuple)]
    divs = [c for c in consts if isinstance(c, tuple)]
    if len(nums) < 2:
        return None, "計算になっていない（数が1つ）"
    units = {c for c in nums if c not in pool}
    if any(c not in UNIT_CONST or not UNIT_CONST[c].search(claim) for c in units):
        return None, "式に元の一次情報に無い数がある"
    if any(not any(c in s for c in nums) for s in src):
        return None, "式に使っていない一次情報を元に挙げている"
    if not _period_ok(inputs, claim):
        return None, "期間の違う一次情報を混ぜ、文に両方の期間が無い"
    hit, rate, text = None, False, PER.sub("", claim.translate(_ZEN))
    for m in NUM.finditer(text):
        s = m.group(0)
        v, d = float(s.replace(",", "")), _decimals(s)
        if abs(v - result) <= 0.5 * 10 ** -d + 1e-9:
            if d > 1:
                return None, "小数が2桁以上"
            hit = max(hit or 0, d)
            rate = rate or bool(RATE.match(text, m.end()))
        elif v not in pool and v not in units:
            return None, "文に元の一次情報にも計算の結果にも無い数がある"
    if hit is None:
        return None, "文に計算の結果が無い"
    if rate:
        dens = [f.get("denominator") for f in inputs if isinstance(f.get("denominator"), (int, float))]
        if any(abs(d) < MIN_RATE for d in [c[1] for c in divs] + dens):
            return None, "母数10未満を割合にしている"
        # 「3回」÷「15の語」のように数えた物の違う数の割合は、意味の無い%になる（2026-11-01 の試しで出た）
        unit_of = {}
        for f in inputs:
            for n, u in UNIT_OF.findall(str(f.get("claim") or "").translate(_ZEN)):
                unit_of.setdefault(float(n.replace(",", "")), set()).add(u)
        if any(a is not None and b is not None and unit_of.get(a) and unit_of.get(b) and not unit_of[a] & unit_of[b]
               for _, _, a, b in divs):
            return None, "数えた物の違う数で割合を出している"
    approx = {float(n.replace(",", "")) for f in inputs for n in re.findall(r"約\s*(" + NUM.pattern + ")", str(f.get("claim") or ""))}
    if hit and approx & set(nums):
        return None, "概数（約◯）からの計算に小数を付けている"
    if any(abs(result - v) < 1e-9 for v in pool):
        return None, "計算の結果が元の一次情報にある数と同じ（言い直し）"
    key = "|".join(sorted(ids)) + "|" + re.sub(r"\s", "", expr)
    topic = list(dict.fromkeys(t for f in inputs for t in (f.get("topic") or [])))[:6]
    periods = list(dict.fromkeys(str(f.get("period")) for f in inputs if f.get("period")))
    row = {"key": key, "inputs": ids, "expr": re.sub(r"\s", "", expr), "claim": claim, "topic": topic,
           "as_of": max(str(f.get("as_of") or "") for f in inputs)}
    if periods:
        row["period"] = "・".join(periods)
    if rate and len(divs) == 1 and float(divs[0][1]).is_integer():
        row["denominator"] = int(divs[0][1])
    else:
        dn = {f.get("denominator") for f in inputs}
        if len(dn) == 1 and None not in dn:
            row["denominator"] = dn.pop()
    return row, None


def _ask(prompt):
    """読むだけの claude を1回呼ぶ（門ではこれを差し替える）。material_sheet と同じ呼び方"""
    import auto_rewrite as A
    import quality_loop as Q
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        r = A.sh(Q.scorer_args(), timeout=900, stdin_text=prompt, cwd=tmp)
    return r.stdout or ""


def _cached_ask(prompt, ask):
    """同じ問いは聞き直さない。置き場は手元の一時フォルダ（お客様の文が入るので公開側に置かない）"""
    d = Path(tempfile.gettempdir()) / "ss-derived-facts"
    p = d / (hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16] + ".txt")
    if ask is _ask and p.is_file():
        return p.read_text(encoding="utf-8")
    raw = ask(prompt)
    if ask is _ask and raw.strip():
        d.mkdir(exist_ok=True)
        p.write_text(raw, encoding="utf-8")
    return raw


PROMPT = """次の一次情報（登録済みの事実）どうしの四則演算だけで言える、新しい事実の候補を最大10個出してください。

決まり:
- 使ってよい数は、下の一次情報の文にある数だけ。新しい数字・仮の数字・見込みは書かない
- 式（expr）は数と + - * / ( ) だけ。割合は (a/b)*100 の形で、b が10以上のときだけ
- 文（claim）には、計算の元にした数と計算の結果（整数か小数1桁に四捨五入、「約」を付けてよい）だけを書く
- 母数・期間の違う数を混ぜない。期間の違う一次情報を使うときは、文に両方の期間を書く
- 読者の判断に役立つものだけ（継続した割合・1社あたり・1か月あたりなど）。無理に作らない。無ければ空の配列

答えは JSON だけ: {{"calcs": [{{"inputs": ["id1", "id2"], "expr": "31/48*100", "claim": "累計48社のうち継続中は31社で、継続している割合は約65%です"}}]}}

一次情報（id ｜ 期間 ｜ 母数 ｜ 文）:
{facts}
"""


def _json(raw):
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        got = json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def usable(site):
    """計算の元にしてよい一次情報（そのサイトで使えて、計算で作ったもの・取り下げたもの・数の無いものを除く）"""
    import facts as F
    _, got = F.load_for(site)
    return [f for f in got if not f.get("derived_from") and not f.get("retired") and len(_vals(f.get("claim"))) >= 1]


def propose(site, facts, ask=_ask):
    """(候補の行, 却下 [(候補, 理由)])。一次情報は CHUNK 件ずつ、主題の近いものをまとめて渡す"""
    facts = sorted(facts, key=lambda f: (str((f.get("topic") or [""])[0]), str(f.get("id"))))
    ok, bad, seen = [], [], set()
    for i in range(0, len(facts), CHUNK):
        part = facts[i:i + CHUNK]
        lines = "\n".join(f"{f.get('id')} ｜ {f.get('period') or '-'} ｜ {f.get('denominator') or '-'} ｜ {f.get('claim')}"
                          for f in part)
        for c in _json(_cached_ask(PROMPT.format(facts=lines), ask)).get("calcs") or []:
            if not isinstance(c, dict):
                continue
            row, why = verify(c, part)
            if why:
                bad.append((c, why))
            elif row["key"] not in seen:
                seen.add(row["key"])
                ok.append(dict(row, id=f"{site}-calc-" + hashlib.sha1(row["key"].encode("utf-8")).hexdigest()[:10]))
    return ok, bad


def write(site, rows, today=None):
    """同じ id は上書き。お客様の社は非公開の置き場、自社は data/（case_ledger.write と同じ形）"""
    import private_store as P
    today = today or date.today().isoformat()
    if P.is_client(site):
        fd = P.read_json(site, "facts.json", {"facts": []}) or {"facts": []}
    else:
        fd = json.loads(OWN_FACTS.read_text(encoding="utf-8"))
    fs = {str(x.get("id")): x for x in fd.setdefault("facts", [])}
    for it in rows:
        row = {"id": it["id"], "sites": [site], "topic": it["topic"], "claim": it["claim"],
               "source": "計算（元: " + "・".join(it["inputs"]) + "）", "as_of": it["as_of"] or today[:7],
               "verifiable": True, "derived_from": it["inputs"], "expr": it["expr"]}
        for k in ("period", "denominator"):
            if it.get(k):
                row[k] = it[k]
        if it["id"] in fs:
            fs[it["id"]].clear()
            fs[it["id"]].update(row)
        else:
            fd["facts"].append(row)
    if P.is_client(site):
        P.write_json(site, "facts.json", fd)
    else:
        OWN_FACTS.write_text(json.dumps(fd, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def run(site, do_write=False, ask=_ask, cap=MAX):
    import sites as S
    client = S.is_client(site)
    facts = usable(site)
    who = "（お客様の社）" if client else site
    if len(facts) < 2:
        print(f"{who}: 計算の元にできる一次情報が{len(facts)}件で、計算の候補を作れません")
        return [], []
    ok, bad = propose(site, facts, ask)
    use = ok[:cap]
    if not client:
        for r in use:
            print(f"   ○ {r['claim']}  ［{r['expr']}／元: {'・'.join(r['inputs'])}］")
        for c, why in bad:
            print(f"   × {str(c.get('claim'))[:80]}  ［{why}］")
    reasons = "・".join(f"{w} {n}件" for w, n in Counter(w for _, w in bad).most_common())
    print(f"{who}: 一次情報 {len(facts)}件から、計算の候補 {len(ok) + len(bad)}件・検算を通った {len(ok)}件"
          + (f"（登録は {cap}件まで）" if len(ok) > cap else "")
          + (f"・却下 {len(bad)}件（{reasons}）" if bad else "")
          + ("。登録しました" if do_write and use else "。--write で登録します" if use else ""))
    if do_write and use:
        write(site, use)
    return use, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--max", type=int, default=MAX)
    a = ap.parse_args()
    import private_store as P
    import sites as S
    site = S.resolve(a.site)
    if not P.require(site, "計算の一次情報"):
        return
    run(site, a.write, cap=a.max)


if __name__ == "__main__":
    main()
