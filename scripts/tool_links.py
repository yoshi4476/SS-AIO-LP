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
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# その場で点数が出る自己診断につなぐときの文末。登録不要で完結する
TOOL_TAIL = "で確かめられます。登録は不要で、その場で点数が出ます。"
# コーポレートには自己診断が無く、人が読んで返す現状分析につなぐ。
# 同じ文末を使うと「その場で点数が出る」が事実と違ってしまうため分けている
TALK_TAIL = "からご相談いただけます。ご契約を前提としたご案内ではありません。"

# カテゴリ → (リンク先, アンカー, 導入の一文, 文末)
OFFER = {
    "meo": ("/diagnosis/meo/", "マップ集客の整備度チェック（無料・30秒）",
            "いまの自店舗がどこでつまずいているかは、", TOOL_TAIL),
    "aio": ("/diagnosis/aio/", "AI検索の対応度チェック（無料・30秒）",
            "自社サイトがAI検索にどこまで対応できているかは、", TOOL_TAIL),
    "seo": ("/site-audit/", "サイトの技術チェック（無料・URL入力だけ）",
            "自社サイトの技術面が基準を満たしているかは、", TOOL_TAIL),
    "ai-marketing": ("/diagnosis/aio/", "AI検索の対応度チェック（無料・30秒）",
                     "自社がAI検索からどう見えているかは、", TOOL_TAIL),
    # 補助金サイトはトップに4つの診断をまとめて置いている
    "hojokin": ("/#diagnosis", "3分の適性診断（無料・8問）",
                "自社が補助金の対象になるかどうかは、", TOOL_TAIL),
    # コーポレートは88本中75本に行き先が無かった。読んだ人が動けない
    "keiri-bpo": ("https://corp.7senses.co.jp/contact/?s=keiri-shindan",
                  "経理の現状分析（無料）",
                  "どこから手をつけるべきかの整理は、", TALK_TAIL),
    "keiri-jitsumu": ("https://corp.7senses.co.jp/contact/?s=keiri-shindan",
                      "経理の現状分析（無料）",
                      "自社の経理のどこに時間がかかっているかは、", TALK_TAIL),
    "backoffice": ("https://corp.7senses.co.jp/contact/?s=backoffice",
                   "バックオフィスの現状分析（無料）",
                   "どの業務から整理すべきかは、", TALK_TAIL),
}
# 同じ一文を何十本にも貼ると、それ自体が量産の指紋になる（実測で1文が106本に並んでいた）。
# 事実（無料・登録不要・その場で点数／契約が前提ではない）は変えず、言い回しだけを記事ごとに変える。
# どれを使うかは slug で決める。実行のたびに変わると、同じ記事が毎週書き換わる
LEAD_ALT = {
    "meo": ["いまの自店舗がどこでつまずいているかは、", "マップ検索で自店舗が見落とされている箇所は、",
            "口コミや店舗情報のどこから直すべきかは、"],
    "aio": ["自社サイトがAI検索にどこまで対応できているかは、", "AIの回答に自社サイトが載る準備ができているかは、",
            "AI検索への対応で抜けている箇所は、"],
    "seo": ["自社サイトの技術面が基準を満たしているかは、", "検索エンジンが自社サイトを読めているかは、",
            "表示速度や構造化データなど技術面の抜けは、"],
    "ai-marketing": ["自社がAI検索からどう見えているかは、", "AIに尋ねたとき自社が候補に挙がる状態かは、",
                     "AI経由の集客で自社がどこまで準備できているかは、"],
    "hojokin": ["自社が補助金の対象になるかどうかは、", "使えそうな補助金があるかどうかは、",
                "申請の要件に自社が当てはまるかは、"],
    "keiri-bpo": ["どこから手をつけるべきかの整理は、", "外に任せられる経理業務の見極めは、",
                  "経理のどの作業を先に軽くするかは、"],
    "keiri-jitsumu": ["自社の経理のどこに時間がかかっているかは、", "毎月の締めが遅れる原因の切り分けは、",
                      "経理の手間が集中している作業の洗い出しは、"],
    "backoffice": ["どの業務から整理すべきかは、", "手放せるバックオフィス業務の見極めは、",
                   "総務・経理のどこに負担が偏っているかは、"],
}
TAIL_ALT = {
    TOOL_TAIL: [TOOL_TAIL, "で確かめられます。登録なしで、答えるとその場で点数が表示されます。",
                "で見られます。登録は要らず、結果はその場で出ます。"],
    TALK_TAIL: [TALK_TAIL, "でご相談を受け付けています。契約を前提にしたご案内ではありません。",
                "からお問い合わせいただけます。ご相談だけでもかまいません。"],
}


def phrase(key, slug):
    """その記事で使う書き出しと文末。slug で決まるので、何度実行しても同じになる"""
    _, _, lead, tail = OFFER[key]
    i = zlib.crc32(slug.encode("utf-8"))
    leads = LEAD_ALT.get(key) or [lead]
    tails = TAIL_ALT.get(tail) or [tail]
    return leads[i % len(leads)], tails[(i // 7) % len(tails)]


def vary(write=False):
    """既に入っている同じ一文を、その記事の言い回しに置き換える（リンク先と文言の事実は変えない）"""
    conf = {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in (ROOT / "sites").glob("*.json")}
    cat_site = {k: s for s, c in conf.items() for k in (c.get("categories") or {})}
    n = 0
    for f in sorted(glob.glob(str(ROOT / "articles" / "*.md"))):
        p = Path(f)
        t = p.read_text(encoding="utf-8-sig")
        cat = article_category(t)
        key = cat if cat in OFFER else ("hojokin" if cat_site.get(cat) == "subsidy" else None)
        if not key:
            continue
        url, anchor, lead, tail = OFFER[key]
        old = f"{lead}[{anchor}]({url}){tail}"
        if old not in t:
            continue
        nl, nt = phrase(key, p.stem)
        new = f"{nl}[{anchor}]({url}){nt}"
        if new == old:
            continue
        n += 1
        if write:
            p.write_bytes(p.read_bytes().replace(old.encode("utf-8"), new.encode("utf-8"), 1))
    print(f"  言い回しを{'変えた' if write else '変える候補'}: {n}本")
    return 0


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
        url, anchor, lead, tail = OFFER[key]
        if url in t:
            continue
        pos = insert_at(t)
        if pos is None:
            continue
        lead, tail = phrase(key, p.stem)
        line = f"\n{lead}[{anchor}]({url}){tail}\n\n"
        done[key] = done.get(key, 0) + 1
        if write:
            p.write_text(t[:pos] + line + t[pos:], encoding="utf-8", newline="")
    for k, n in sorted(done.items()):
        print(f"  {k:<14} {'追加' if write else '候補'} {n}本 → {OFFER[k][1]}")
    print(f"  合計 {sum(done.values())}本")
    return 0


if __name__ == "__main__":
    if "--vary" in sys.argv:
        sys.exit(vary("--write" in sys.argv))
    sys.exit(main("--write" in sys.argv))
