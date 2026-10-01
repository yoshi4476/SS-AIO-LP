# -*- coding: utf-8 -*-
"""note に転載する下書きを、公開済みの記事からまとめて書き出す（投稿は人が手で行う）。

    python scripts/note_export.py                    # AIO・SEO・LLMO の記事（既定・読み物版）
    python scripts/note_export.py --short            # 短い版（各見出しの1文結論＋元記事）
    python scripts/note_export.py --all              # 全カテゴリ
    python scripts/note_export.py --copy-to <dir>    # 書き出したものを別の場所にも置く

**読み物版（既定）**: 1,200〜2,000字。元記事の文を写さず言い換えた note 向けの読み物にする。
元記事の文を長く載せると、評価の高い note 側が検索で上に出て、自社の記事が埋もれる。
claude（サブスク）に書かせ、機械が検算する。通らなければ書き直させ、3回で通らなければ短い版にする。
  - 記事に無い数字を書いていない
  - 長さ 1,200〜2,200字（空白を除く）
  - 元記事の文をそのまま写した割合が2割以下（25字以上の文で数える）
  - 元記事のURLと社名がある・題が元記事と同じでない
一度書いた記事は、元記事が変わるまで書き直さない（automation/note/.cache）。
並びは直近28日の検索表示の多い順（読まれている記事から転載する）。
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "automation" / "note"
CACHE = OUT / ".cache"
TOPIC = re.compile(r"AIO|SEO|LLMO|GEO|AI検索|AI Overview", re.I)

PROMPT = """次の記事をもとに、note に載せる読み物を書いてください。元記事は自社サイトにあり、note から元記事へ読者を案内するのが目的です。

守ること:
- 長さは本文1,400〜1,800字。ですます調。
- 元記事の文をそのまま写さない。必ず自分の言葉で言い換える（同じ文が並ぶと検索で元記事と食い合う）。
- **元記事に無い数字・事例・体験談・社名を書かない。** 数字は元記事にあるものだけ。「私が支援した」などの体験を作らない。
- 構成:
  1行目: note のタイトル（元記事と同じ題にしない。狙う話題「{kw}」は入れる。40字以内）
  2行目: 空行
  導入: この記事が誰向けで、読むと何が分かるか（2〜3文）
  要点を3〜5個。各要点は「■ 」で始まる見出し1行と、2〜3文の説明
  「よくある失敗」を1つ（元記事に書かれているものから）
  まとめ（2文）
  最後の2行は必ず次のとおり:
  詳しい手順・表・よくある質問は元記事にまとめています: {url}
  執筆: AI集客ラボ（セブンセンシズ株式会社）
- Markdown の記号（#、**、|）は使わない。プレーンテキストで出力し、前置きや説明は書かない。

元記事のタイトル: {title}

元記事:
{body}
"""


def _nums(s):
    return set(re.findall(r"\d+(?:\.\d+)?", s.replace(",", "")))


def _plain(md):
    t = re.sub(r"^---.*?---\s*", "", md, flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"[*_`#>|]", "", t)
    return t


def check(text, art, plain, url):
    """通してよい原稿か。問題の一覧を返す（空なら合格）"""
    ng = []
    lines = text.strip().splitlines()
    if not lines:
        return ["空です"]
    title = lines[0].strip()
    if title == art["title"]:
        ng.append("題が元記事と同じ")
    body = "\n".join(l for l in lines[1:] if url not in l)
    n = len(re.sub(r"\s", "", body))
    if not 1200 <= n <= 2200:
        ng.append(f"長さ{n}字（1,200〜2,200字）")
    extra = _nums(body) - _nums(plain + art["title"])
    if extra:
        ng.append(f"元記事に無い数字: {sorted(extra)[:5]}")
    if url not in text:
        ng.append("元記事のURLが無い")
    if "セブンセンシズ" not in text:
        ng.append("社名が無い")
    flat = re.sub(r"\s", "", plain)
    sents = [s for s in re.split(r"(?<=[。！？])", re.sub(r"\s", "", body)) if len(s) >= 25]
    copied = [s for s in sents if s in flat]
    if sents and len(copied) / len(sents) > 0.2:
        ng.append(f"元記事の文をそのまま写した割合が{len(copied)}/{len(sents)}")
    if re.search(r"\*\*|^#|^\|", text, re.M):
        ng.append("Markdown の記号が残っている")
    return ng


def write_long(art, url, md):
    import auto_rewrite as AR
    plain = _plain(md)
    exe = AR.claude_bin()
    prompt = PROMPT.format(kw=art.get("keyword") or art["title"], url=url, title=art["title"], body=plain[:12000])
    why = []
    for _ in range(3):
        p = prompt if not why else prompt + "\n\n前回の原稿は次の理由で使えませんでした。直して書き直してください:\n- " + "\n- ".join(why)
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([exe, "-p", *AR.model_args()], input=p, cwd=tmp,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        text = (r.stdout or "").strip()
        why = check(text, art, plain, url)
        if not why:
            return text + "\n", []
    return "", why


def impressions():
    """記事URLの末尾ごとの28日の表示回数（取れなければ空）"""
    try:
        import gsc_detail as G
        import sites as S
        sc = G.client()
        end = date.today() - timedelta(days=3)
        out = {}
        for cfg in S.load_all().values():
            for r in G.q(sc, cfg["domain"], str(end - timedelta(days=27)), str(end), ["page"], 25000):
                k = r["keys"][0].rstrip("/").split("/")[-1]
                out[k] = out.get(k, 0) + int(r["impressions"])
        return out
    except Exception:
        return {}


def main():
    import social_post as SP
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--short", action="store_true")
    ap.add_argument("--copy-to", default="")
    a = ap.parse_args()
    imp = impressions()
    rows = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        art = SP.article(p.stem)
        if not art:
            continue
        if not a.all and not TOPIC.search(art["title"]):
            continue
        sid, _ = SP.site_of(art["category"])
        if sid != "ai-lab" and not a.all:
            continue
        kw = re.search(r"^keyword:\s*(.+)$", p.read_text(encoding="utf-8-sig"), re.M)
        art["keyword"] = kw.group(1).strip() if kw else ""
        rows.append((imp.get(p.stem, 0), art))
    rows.sort(key=lambda x: (-x[0], x[1]["slug"]))
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    for f in OUT.glob("*.txt"):
        f.unlink()
    index = ["順番\t28日の表示\t形\tタイトル\tファイル"]
    long_n = 0
    for i, (n, art) in enumerate(rows, 1):
        name = f"{i:03d}_{art['slug']}.txt"
        post = SP.compose(art)
        text, kind = post["posts"]["note"] + "\n", "短い版"
        if not a.short:
            md = (ROOT / "articles" / f"{art['slug']}.md").read_text(encoding="utf-8-sig")
            key = hashlib.md5(md.encode("utf-8")).hexdigest()
            c = CACHE / f"{art['slug']}.json"
            cached = json.loads(c.read_text(encoding="utf-8")) if c.is_file() else {}
            if cached.get("key") == key and cached.get("text"):
                text, kind = cached["text"], "読み物"
            else:
                body, why = write_long(art, post["url"], md)
                if body:
                    text, kind = body, "読み物"
                    c.write_text(json.dumps({"key": key, "text": body}, ensure_ascii=False), encoding="utf-8")
                else:
                    print(f"  × {art['slug']}: 短い版にしました（{'／'.join(why)[:80]}）")
            long_n += kind == "読み物"
            print(f"  {i:>3}/{len(rows)} {kind} {art['slug']}", flush=True)
        (OUT / name).write_text(text, encoding="utf-8")
        index.append(f"{i}\t{n}\t{kind}\t{art['title']}\t{name}")
    (OUT / "一覧.tsv").write_text("\n".join(index) + "\n", encoding="utf-8-sig")
    print(f"note の下書き {len(rows)}本（読み物 {long_n}本）→ {OUT}")
    if a.copy_to:
        dst = Path(a.copy_to)
        dst.mkdir(parents=True, exist_ok=True)
        for f in dst.glob("*.txt"):
            f.unlink()
        for f in list(OUT.glob("*.txt")) + [OUT / "一覧.tsv"]:
            shutil.copy2(f, dst / f.name)
        print(f"コピーしました → {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
