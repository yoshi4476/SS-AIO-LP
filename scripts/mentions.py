# -*- coding: utf-8 -*-
"""外部サイトでの「言及」を数える。リンクの有無で分けずに数える。

**なぜ被リンクと別に数えるか**: AI検索での可視性は、被リンク（相関0.218）より
リンクの無いWeb言及（0.656）のほうが3倍強く相関する（Ahrefs・75,000ブランド・
Spearman・2025-12）。AIの回答がブランドに触れてもリンクを張るのは28%だけなので、
**リンクだけを数えると実態の3割ちょっとしか見ていないことになる。**

`data/backlinks.json` はリンクだけを記録している。こちらは「社名が出ている場所」を
すべて記録し、リンクの有無は属性として持つ。

**見つける工程は自動化できない**（検索APIの契約が無い）。見つけたものを登録し、
**消えていないかを毎週機械が確かめる**。実際、掲載されていたはずのページが
黙って消えることがある。

    python scripts/mentions.py              # いまの本数と推移
    python scripts/mentions.py --check      # 登録済みが生きているか確かめる（週次）
    python scripts/mentions.py --add <URL> --where "媒体名" [--linked]
    python scripts/mentions.py --how        # 探し方（人がやる分）

終了コードは常に0（CLAUDE.md 8.7）。判定は MENTION_OK= の印で行う。
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "mentions.json"
TIMEOUT = 25
UA = "Mozilla/5.0 (compatible; SevenSensesMentionCheck/1.0)"

# 社名・サービス名の表記ゆれ。brand_search.py と同じ考え方で、一般語は入れない
BRAND = re.compile(
    r"セブンセンシズ|せぶんせんしず|7\s*senses|seven\s*senses|"
    r"7senses\.co\.jp|"
    r"原口\s*優|原口優|"
    r"g-?ran|ジーラン|"
    r"ラクシフト|rakushift|"
    r"ai集客ラボ", re.I)

HOW = """  探し方（ここだけ人がやる。検索APIの契約が無いため）

    1. Google で次を検索し、自社サイト以外の結果を拾う
         "セブンセンシズ株式会社" -site:7senses.co.jp
         "G-ran" MEO -site:7senses.co.jp
         "ラクシフト" -site:7senses.co.jp
    2. 取引先・業界団体・登録先のサイトで社名が出ているページ
    3. 登壇・寄稿・取材の掲載先
    4. 見つけたら登録する
         python scripts/mentions.py --add <URL> --where "媒体名" [--linked]

  **リンクが無くても登録する。** リンクの有無はAI検索の可視性にほとんど効かない。
  買ったリンク・相互リンク目的の掲載は登録しない（ペナルティの対象）。
  自社が運営する別ドメイン（www.7senses.co.jp・3サイト相互）は third=false で入れる。
  検索エンジンにとって推薦にはならないため、本数に数えない。"""


def load():
    if STORE.is_file():
        return json.loads(STORE.read_text(encoding="utf-8"))
    return {"_readme": ("外部サイトでの社名の言及。リンクの有無は linked で持つ。"
                        "AI検索の可視性は被リンクより言及のほうが3倍強く相関するため、"
                        "リンクが無いものも数える。買ったリンク・相互リンク目的の掲載は入れない。"),
            "items": [], "history": []}


def save(d):
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read(400_000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def check(d):
    """生きている / 消えた / 確かめられない の3つに分ける。

    **「確かめられない」を「消えた」と数えない。** 403・429・接続失敗は
    こちらが弾かれただけで、掲載が消えた証拠ではない（CLAUDE.md 0.1）。
    実際、中小機構のページは通常のブラウザでは見えるのに403を返す。
    """
    alive, gone, unknown = [], [], []
    for it in d["items"]:
        code, body = fetch(it["url"])
        found = bool(BRAND.search(re.sub(r"<[^>]+>", " ", body))) if body else False
        it["last_checked"] = date.today().isoformat()
        if code == 200 and found:
            state, mark, why = "alive", "○", ""
        elif code in (404, 410):
            state, mark, why = "gone", "×", f"HTTP {code}（ページが無い）"
        elif code == 200:
            state, mark, why = "gone", "×", "ページはあるが社名が見当たりません"
        else:
            state, mark, why = "unknown", "?", (f"HTTP {code}（こちらが弾かれた）"
                                                if code else "つながりません")
        it["state"] = state
        {"alive": alive, "gone": gone, "unknown": unknown}[state].append(it)
        print(f"  {mark} {it.get('where', '')[:22]:<22} {it['url'][:58]}  {why}")
    return alive, gone, unknown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="登録済みが生きているか確かめる")
    ap.add_argument("--add", metavar="URL", help="言及を登録する")
    ap.add_argument("--where", default="", help="媒体名")
    ap.add_argument("--linked", action="store_true", help="リンクが張られている")
    ap.add_argument("--own", action="store_true", help="自社が運営するドメイン（本数に数えない）")
    ap.add_argument("--how", action="store_true", help="探し方を出す")
    a = ap.parse_args()

    d = load()
    if a.how:
        print(HOW)
        return 0

    if a.add:
        if any(x["url"] == a.add for x in d["items"]):
            print("  すでに登録されています")
            return 0
        d["items"].append({"url": a.add, "where": a.where, "linked": a.linked,
                           "third": not a.own, "added": date.today().isoformat()})
        save(d)
        kind = "リンクあり" if a.linked else "リンクなし"
        who = "自社ドメイン（数えない）" if a.own else "第三者"
        print(f"  登録しました（{kind} / {who}）: {a.where or a.add}")
        return 0

    items = d["items"]
    third = [x for x in items if x.get("third", True)]
    linked = [x for x in third if x.get("linked")]

    print("■ 外部での言及")
    if not items:
        print("  まだ1件も登録されていません")
        print(f"  被リンク（{len(linked)}件）より言及のほうが3倍強く相関します。"
              "リンクが無くても登録してください")
        print()
        print(HOW)
        print("MENTION_OK=no")
        return 0

    if a.check:
        alive, gone, unknown = check(d)
        d["history"].append({"at": date.today().isoformat(), "third": len(third),
                             "alive": len(alive), "gone": len(gone),
                             "unknown": len(unknown), "linked": len(linked)})
        save(d)
        print()
        print(f"  第三者の言及 {len(third)}件（うちリンクあり {len(linked)}件）／"
              f"生きている {len(alive)}件 / 消えた {len(gone)}件 / 確かめられない {len(unknown)}件")
        if unknown:
            print("  「確かめられない」は、掲載先がこちらのアクセスを弾いただけです。"
                  "消えた証拠ではないので、目視で確認してください")
        if gone:
            print(f"  **消えた言及 {len(gone)}件。** 掲載先の改修や記事の取り下げで落ちます")
            print("MENTION_OK=no")
        else:
            print("MENTION_OK=yes")
        return 0

    print(f"  第三者の言及 {len(third)}件（うちリンクあり {len(linked)}件・"
          f"リンクなし {len(third) - len(linked)}件）")
    for x in third[:12]:
        mark = "🔗" if x.get("linked") else "・"
        print(f"     {mark} {x.get('where', '')[:26]:<26} {x['url'][:56]}")
    if len(third) > 12:
        print(f"     …ほか {len(third) - 12}件")
    own = [x for x in items if not x.get("third", True)]
    if own:
        print(f"  自社ドメインからの言及 {len(own)}件（推薦にはならないため数えていません）")
    if d.get("history"):
        h = d["history"][-1]
        print(f"  前回の確認 {h['at']}: 第三者{h['third']}件 / 生きている{h['alive']}件")
    print("MENTION_OK=yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
