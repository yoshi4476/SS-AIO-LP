# -*- coding: utf-8 -*-
"""品質スコアを、書いた本人ではない工程が付け直す。

**なぜ要るか**: 公開条件は `score >= 90` だが、その点数は記事を書いた
エージェント自身が付けている。結果、372本すべてが90点以上で90点未満は0本、
95点に177本（48%）が集中した。**一度も門として働いていない。**
さらに実測では、96点以上の記事の順位（21.7位）が91〜93点（17.6位）より
悪く、点数と成果が逆に出ていた。

ここでは採点だけを行う別の工程を作る。

  読むのは**公開HTML**（原稿ではない）   … 点数がどこにも書かれていないので引きずられない
  道具は Read だけ                      … 書き換えられない。採点しかできない
  結果は data/score_audit.json へ        … 元の点数と並べて差を見る

採点の基準は CLAUDE.md 第5章の6観点（各20点・合計120点）をそのまま使う。

    python scripts/score_audit.py --limit 10      # 10本を採点し直す
    python scripts/score_audit.py --compare       # 自己申告との差を見る
"""
import argparse
import json
import random
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "data" / "score_audit.json"

PROMPT = """次のHTMLは、公開済みの記事です。初めて読む読者・審査員として採点してください。

{path}

CLAUDE.md 第5章の6観点で、各20点・合計120点で採点します。

1. デザイン   H2構成と目次の対応／各H2冒頭の1文結論／表の体裁／CTA2箇所以上／
              H2直下の図解／強調12〜18箇所／段落3行以内／alt設定
2. SEO        タイトル30字以内で狙う語を含む／メタ記述120字以内／本文5,000字以上／
              外部権威リンク／E-E-A-T／FAQ5問以上／内部リンク3本以上／独自ファクト3箇所以上
3. 編集       AI感の排除（あいまいな結論・「重要です」の連発・文末の単調・
              3連続箇条書き・「これにより」・「おすすめします」・一人称の欠如）／
              ですます調／1文50字以下／体言止め2〜3箇所
4. 技術       説明の正確性／手順の再現性／限界と注意点／数値の信頼性／最新動向との整合
5. 読者       悩みへの答え／専門用語の説明／「まず何から」が明確／表が単体で完結／
              読後の次の行動が分かる
6. AIO/LLMO   冒頭200字の断言型回答／H2直下の1文結論が40〜60字で単体で通る／
              定義ブロック／比較表が単体で完結／FAQの回答が40〜60字／
              出典つき数値ファクト3箇所以上／鮮度表記／ファクトと意見の分離／
              対象読者の限定／失敗例の節

**採点の前に、この記事の欠点を3つ以上挙げてください。**欠点ゼロの採点は無効です。
甘く付けないでください。基準に届いていないものは届いていないと書きます。

最後の行に、次の形式だけを出力してください（他の文字を入れない）。

SCORES design=<0-20> seo=<0-20> editorial=<0-20> expert=<0-20> persona=<0-20> aio=<0-20>
"""


def published(limit=0, seed=0):
    """公開HTMLがある記事。slug -> (html_path, 自己申告の点数)"""
    out = {}
    for p in sorted((ROOT / "articles").glob("*.md")):
        if p.name.startswith("_"):
            continue
        t = p.read_text(encoding="utf-8-sig", errors="ignore")[:2000]
        m = re.search(r"^score:\s*(\d+)", t, re.M)
        if not m or int(m.group(1)) < 90:
            continue
        sl = re.search(r"^slug:\s*(\S+)", t, re.M)
        slug = sl.group(1) if sl else p.stem
        html = list((ROOT / "site").glob(f"*/{slug}/index.html"))
        if html:
            out[slug] = (html[0], int(m.group(1)))
    if limit:
        keys = sorted(out)
        random.Random(seed).shuffle(keys)
        out = {k: out[k] for k in keys[:limit]}
    return out


def audit_one(slug, html_path):
    """1本を採点し直す。書き換えはできない（Read だけ）。

    基準は rubric.py（3軸×10点）。機械で数えられることは採点させない。
    証拠を書かせたうえで、最後の1行だけを機械が読む。
    """
    import auto_rewrite as A
    import rubric as R
    rel = html_path.relative_to(ROOT).as_posix()
    prompt = R.prompt_for(rel)
    r = A.sh([A.claude_bin(), "-p", "--max-turns", "12", "--allowedTools", "Read"],
             timeout=900, stdin_text=prompt)
    text = (r.stdout or "")
    m = re.search(r"SCORES\s+originality=(\d+)\s+extractability=(\d+)\s+"
                  r"decision=(\d+)", text)
    if not m:
        return None, text[-200:] if text else "応答がありません"
    sc = {"originality": int(m.group(1)), "extractability": int(m.group(2)),
          "decision": int(m.group(3))}
    got = R.judge(sc)
    # 証拠（採点者が書いた弱い点）も残す。点数だけでは直せない
    reason = text[:1800]
    return {"axes": sc, **got, "reason": reason}, ""


def load():
    if OUT.is_file():
        try:
            return json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save(d):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                   encoding="utf-8", newline="\n")


def compare():
    d = load()
    rows = [(s, v["self"], v["audit"].get("total", 0), v["audit"].get("weak") or {})
            for s, v in d.items() if v.get("audit") and "total" in v["audit"]]
    if not rows:
        print("  採点し直した記事がありません（--limit で実行してください）")
        print("SCORE_AUDIT_OK=yes")
        return 0
    import rubric as R
    import statistics as st
    below = [r for r in rows if r[2] < R.PASS_TOTAL]
    weak = [r for r in rows if r[3]]
    print(f"■ 別工程の採点（基準 {R.VERSION}・{len(rows)}本）\n")
    print(f"{'記事':<34}{'合計':>7}{'一次性':>7}{'抽出性':>7}{'決定':>6}  判定")
    for s, _self, tot, w in sorted(rows, key=lambda x: x[2]):
        ax = (d[s]["audit"].get("axes") or {})
        mark = d[s]["audit"].get("why", "")
        print(f"{s[:32]:<34}{tot:>5}/30{ax.get('originality', 0):>7}"
              f"{ax.get('extractability', 0):>7}{ax.get('decision', 0):>6}  {mark[:28]}")
    tots = [r[2] for r in rows]
    print(f"\n  合計の中央値: {st.median(tots):.0f}/30")
    print(f"  合計{R.PASS_TOTAL}点を割った記事: {len(below)}/{len(rows)}本")
    print(f"  1軸が{R.PASS_EACH}点未満（足切り）: {len(weak)}/{len(rows)}本")
    for a in R.AXES:
        vals = [(d[s]["audit"].get("axes") or {}).get(a["key"], 0) for s, *_ in rows]
        if vals:
            print(f"    {a['name']:<8}中央値 {st.median(vals):>4.1f}/10"
                  f"  （{a['what']}）")
    bad = len(below) + len(weak)
    print("SCORE_AUDIT_OK=" + ("no" if bad else "yes"))
    if bad:
        print(f"   ::warning::別工程の採点で合計が基準を割った記事が{len(below)}本、"
              f"1軸が壊滅している記事が{len(weak)}本あります")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="採点し直す本数")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--compare", action="store_true")
    a = ap.parse_args()

    if a.compare or not a.limit:
        return compare()

    import shutil
    if not (shutil.which("claude") or shutil.which("claude.cmd")):
        print("  claude が見つかりません（npm install -g @anthropic-ai/claude-code）")
        return 1

    d = load()
    targets = published(a.limit, a.seed)
    print(f"■ {len(targets)}本を採点し直します（公開HTMLを読む・書き換えはできません）\n")
    for i, (slug, (html, self_score)) in enumerate(targets.items(), 1):
        res, err = audit_one(slug, html)
        if not res:
            print(f"  {i:>2}. × {slug[:32]:<34} 採点できません（{err[:50]}）")
            continue
        d[slug] = {"at": str(date.today()), "self": self_score, "audit": res}
        ax = res["axes"]
        print(f"  {i:>2}. {slug[:32]:<34} 合計{res['total']:>2}/30"
              f"（一次性{ax['originality']} 抽出性{ax['extractability']}"
              f" 決定{ax['decision']}）{res['why'][:24]}")
        save(d)
    print()
    return compare()


if __name__ == "__main__":
    sys.exit(main())
