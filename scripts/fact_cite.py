# -*- coding: utf-8 -*-
"""自社の一次情報（登録済みの数字）を、関係する記事へ1文だけ引用として入れる。

**なぜ要るか**: 数字つきの断定文は AI に引用されやすい。一次情報は facts に登録
されているのに、使うのは新規記事の執筆時だけで、既存記事には入らなかった。
関係の深い記事へ、登録済みの文をそのまま1文入れる（新しい数字は作らない）。

入れる場所は最初のH2の1文結論の直後（AIが段落単位で切り出す位置）。
1記事1文まで。既に「セブンセンシズ株式会社が…計測」の文がある記事には入れない。

  python scripts/fact_cite.py                 # どこに何が入るか
  python scripts/fact_cite.py --write --limit 3
出す印: FACT_CITE_OK=yes / CITED=<本>。台帳: automation/logs/auto_fix.jsonl
検算: 増える数字は引用文にある数字だけ／段落・見出し・表の数が変わらない／build が通る
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"
MIN_OVERLAP = 2
MARK = "実測の参考として"


def _tokens(s):
    return {t for t in re.findall(r"[一-龥ァ-ヶー]{2,}|[A-Za-z][A-Za-z0-9]{2,}", str(s).lower()) if len(t) >= 2}


def candidates(site_id):
    import facts as F
    import sites as S
    _, fs = F.load_for(site_id)
    fs = [f for f in fs if f.get("claim") and re.search(r"\d", f["claim"]) and len(f["claim"]) < 220]
    out = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.group(1), m.group(2)

        def g(k):
            x = re.search(rf"^{k}:\s*(.+)$", fm, re.M)
            return x.group(1).strip().strip('"') if x else ""
        if int(g("score") or 0) < 90 or S.find_category_owner(g("category")) != site_id:
            continue
        if MARK in body or "セブンセンシズ株式会社が" in body:
            continue
        key = _tokens(g("title") + " " + g("keyword"))
        best, score = None, 0
        for f in fs:
            n = len(key & _tokens(f["claim"]))
            if n > score:
                best, score = f, n
        if best and score >= MIN_OVERLAP:
            out.append({"slug": p.stem, "site": site_id, "fact": best, "overlap": score, "title": g("title")})
    out.sort(key=lambda x: -x["overlap"])
    return out


def _counts(body):
    return (len(re.findall(r"^#{2,4} ", body, re.M)), len(re.findall(r"^\|", body, re.M)),
            len(re.findall(r"^\s*[-*] ", body, re.M)))


def insert(slug, fact, saved=None):
    p = ROOT / "articles" / f"{slug}.md"
    t = p.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
    fm, body = m.group(1), m.group(2)
    heads = list(re.finditer(r"^## .+$", body, re.M))
    if not heads:
        return False, "H2が無い"
    # 最初のH2の直後の段落（1文結論）の末尾に、段落を1つ足す
    start = heads[0].end()
    seg = body[start:heads[1].start() if len(heads) > 1 else len(body)]
    paras = re.split(r"\n\s*\n", seg.strip("\n"), maxsplit=1)
    if not paras or not paras[0].strip() or paras[0].lstrip().startswith(("<", "|", "!", "-")):
        return False, "1文結論が見つからない"
    src = fact.get("source") or "自社の実測"
    sentence = f"{MARK}、{fact['claim'].rstrip('。')}（出典: {src}）。"
    new_seg = paras[0] + "\n\n" + sentence + ("\n\n" + paras[1] if len(paras) > 1 else "")
    new_body = body[:start] + "\n\n" + new_seg.strip("\n") + "\n" + body[start + len(seg):]
    if _counts(new_body) != _counts(body):
        return False, "段落・表・見出しの数が変わる"
    nums_before = set(re.findall(r"\d[\d,.]*", body))
    nums_claim = set(re.findall(r"\d[\d,.]*", sentence))
    added = set(re.findall(r"\d[\d,.]*", new_body)) - nums_before - nums_claim
    if added:
        return False, f"引用文に無い数字が増える {sorted(added)[:3]}"
    if saved is not None:
        saved.setdefault(p, p.read_bytes())
    p.write_text(f"---\n{fm}\n---\n{new_body}", encoding="utf-8", newline="")
    return True, sentence[:60]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--site", default="")
    ap.add_argument("--limit", type=int, default=3)
    a = ap.parse_args()
    import sites as S
    rows = []
    for sid in ([a.site] if a.site else list(S.load_all())):
        rows += candidates(sid)
    print(f"■ 一次情報を引用として入れられる記事: {len(rows)}本")
    for r in rows[:10]:
        print(f"   [{r['site']:<9}] {r['slug'][:36]:<36} ← {r['fact']['claim'][:50]}（重なり{r['overlap']}）")
    n = 0
    if a.write:
        saved, recs = {}, []
        for r in rows[:a.limit]:
            ok, why = insert(r["slug"], r["fact"], saved)
            print(f"   {'○' if ok else '×'} {r['slug'][:36]:<36} {why}")
            recs.append({"at": time.strftime("%Y-%m-%d %H:%M"), "by": "fact_cite", "slug": r["slug"],
                         "kind": "cite", "ok": ok, "note": why})
            n += ok
        if n:
            r = subprocess.run([sys.executable, "scripts/build.py"], cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode or "BLOCKED" in (r.stdout or ""):
                # HEAD へ戻すと、同じ週次で先に当てた未コミットの直しまで消える
                for p, raw in saved.items():
                    p.write_bytes(raw)
                print("   ★ ビルドが通らないため、今回の引用は全部戻しました")
                n = 0
                # 戻した分を ok のまま台帳に残すと、effect_ab が「打った手」として数える
                for x in recs:
                    if x["ok"]:
                        x.update(ok=False, note="ビルドが通らず戻した")
        # 台帳はビルドの結果が出てから書く
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            for x in recs:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"FACT_CITE_OK=yes\nCITED={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
