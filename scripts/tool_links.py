# -*- coding: utf-8 -*-
"""記事の話題に合う無料診断への導線を、本文に組み込む。

汎用の「無料相談」はどの記事にも同じ文言で入っているが、
相談は身構える。30秒で終わる診断のほうが最初の一歩として軽く、
点数を見た人はそのまま相談へ進む。

置く場所は「読者が困りを自覚した直後」。失敗例や注意点の節の
すぐ後ろに置き、無ければ「まとめ」の手前にする。読み終えた後より、
問題を突きつけられた直後のほうが動く。

  python scripts/tool_links.py            # 候補を出す
  python scripts/tool_links.py --write    # 本文に入れる
"""
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# カテゴリ → (リンク先, アンカー, 導入の一文)
OFFER = {
    "meo": ("/diagnosis/meo/", "マップ集客の整備度チェック（無料・30秒）",
            "いまの自店舗がどこでつまずいているかは、"),
    "aio": ("/diagnosis/aio/", "AI検索の対応度チェック（無料・30秒）",
            "自社サイトがAI検索にどこまで対応できているかは、"),
    "seo": ("/site-audit/", "サイトの技術チェック（無料・URL入力だけ）",
            "自社サイトの技術面が基準を満たしているかは、"),
    "ai-marketing": ("/diagnosis/aio/", "AI検索の対応度チェック（無料・30秒）",
                     "自社がAI検索からどう見えているかは、"),
    # 補助金サイトはトップに4つの診断をまとめて置いている
    "hojokin": ("/#diagnosis", "3分の適性診断（無料・8問）",
                "自社が補助金の対象になるかどうかは、"),
}
TAIL = "で確かめられます。登録は不要で、その場で点数が出ます。"
# 困りを自覚した直後に置く。この見出しの後ろが最良
AFTER = re.compile(r"^## .*(失敗|注意点|やってはいけない|つまずく|落とし穴|NG).*$", re.M)


def article_category(text):
    m = re.search(r"^category:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def insert_at(body):
    """置く位置。困りの節の直後 → 無ければ まとめ の手前"""
    heads = list(re.finditer(r"^## .+$", body, re.M))
    for i, m in enumerate(heads):
        if AFTER.match(m.group(0)):
            return heads[i + 1].start() if i + 1 < len(heads) else None
    m = re.search(r"^## まとめ", body, re.M)
    return m.start() if m else None


def main(write=False):
    conf = {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in (ROOT / "sites").glob("*.json")}
    cat_site = {k: s for s, c in conf.items() for k in (c.get("categories") or {})}
    done = {}
    for f in sorted(glob.glob(str(ROOT / "articles" / "*.md"))):
        p = Path(f)
        t = p.read_text(encoding="utf-8-sig")
        cat = article_category(t)
        key = cat if cat in OFFER else ("hojokin" if cat_site.get(cat) == "subsidy" else None)
        if not key:
            continue
        url, anchor, lead = OFFER[key]
        if url in t:
            continue
        pos = insert_at(t)
        if pos is None:
            continue
        line = f"\n{lead}[{anchor}]({url}){TAIL}\n\n"
        done[key] = done.get(key, 0) + 1
        if write:
            p.write_text(t[:pos] + line + t[pos:], encoding="utf-8", newline="")
    for k, n in sorted(done.items()):
        print(f"  {k:<14} {'追加' if write else '候補'} {n}本 → {OFFER[k][1]}")
    print(f"  合計 {sum(done.values())}本")
    return 0


if __name__ == "__main__":
    sys.exit(main("--write" in sys.argv))
