# -*- coding: utf-8 -*-
"""採点の基準。1か所にまとめ、版を付けて管理する。

**なぜ作り直したか**（すべて実測にもとづく・2026-09-23）

| 分かったこと | 数字 |
|:--|:--|
| 自己申告の点数は成果を予測しない | 96点以上の順位21.7位 < 91〜93点の17.6位 |
| 自己申告は門にならない | 372本すべて90点以上・90点未満0本・95点に177本 |
| 60項目×2点は差がつかない | 別工程の採点でも6観点が13〜18に収束（旧基準での実測） |
| 機械検査と重複している | score_check が21項目をすでに機械で判定 |
| 別工程の採点は機械が見落とす欠陥を見つける | 画像376個の破損を発見 |

**新しい考え方**

  機械で測れること … 門にする（出せる／出せない）。点数にしない
  判断が要ること   … 3軸だけを採点する。各軸に「証拠を挙げろ」と求める

3軸は、2026年の検索とAI検索で「選ばれる理由」から選んだ。

  一次性   そこにしか無い情報があるか（AIが引用する理由そのもの）
  抽出性   AIが答えとして切り出せる単位になっているか
  決定支援 読者が次の行動を決められるか

各100点。**1軸でも80点未満なら不合格**（総合で壊滅軸を隠さない）。
総合は3軸の**平均**で、90点以上が公開の条件（ご提案資料 v2・17ページと同じ基準）。
推奨は95点。

採点者には必ず「なぜその点か」の証拠（引用・箇所）を書かせる。
証拠の無い点数は採点ではなく感想になる。
"""

VERSION = "2026-09-v3"

AXES = [
    {
        "key": "originality",
        "name": "一次性",
        "what": "そこにしか無い情報があるか",
        "why": ("AIが回答の根拠に選ぶのは、他所に無い数字と経験。"
                "まとめ直しは、どれだけ整っていても引用されない"),
        "anchors": [
            (100, "自社で測った数字・取材・現場の判断が3箇所以上あり、"
                 "いずれも母数と時期つきで、他所では確認できない"),
            (80, "自社の経験や数字が2箇所以上ある。うち1つは母数つき"),
            (60, "自社の話が1箇所ある。ただし数字は公開情報の引き写し"),
            (40, "公開情報を正しくまとめているが、自社の要素が無い"),
            (20, "どこにでも書いてある内容の言い換えにとどまる"),
        ],
    },
    {
        "key": "extractability",
        "name": "抽出性",
        "what": "AIが答えとして切り出せる単位になっているか",
        "why": ("AI検索は本文を段落単位で切り出す。"
                "その1つを取り出して意味が通らなければ、引用されない"),
        "anchors": [
            (100, "冒頭200字・各H2直下の1文結論・定義・比較表・FAQのどれを"
                 "切り出しても、単体で質問への答えになっている"),
            (80, "ほとんどの単位が単体で通る。1〜2箇所だけ前後を読まないと分からない"),
            (60, "見出しの構造は整っているが、結論が前後に依存する箇所が目立つ"),
            (40, "通読すれば分かるが、切り出すと意味が変わる"),
            (20, "文章が続きもので、切り出せる単位が無い"),
        ],
    },
    {
        "key": "decision",
        "name": "決定支援",
        "what": "読者が次の行動を決められるか",
        "why": ("読んで終わる記事は、順位が取れても問い合わせにならない。"
                "条件で分かれる判断と、やらない判断の材料が要る"),
        "anchors": [
            (100, "条件ごとに何を選ぶかが示され、やらない判断の材料もあり、"
                 "今日できる次の一歩が具体的に書いてある"),
            (80, "条件による分岐があり、次の一歩も書いてある"),
            (60, "次にやることは書いてあるが、条件による分岐が無い"),
            (40, "一般論の手順にとどまり、自分の場合に当てはめられない"),
            (20, "読後に何をすればよいか分からない"),
        ],
    },
]

MAX = 100              # 各軸の満点（資料 v2 と同じ）
PASS_EACH = 80         # 1軸でもこれ未満なら不合格
PASS_TOTAL = 90        # 総合（3軸の平均）の下限
RECOMMEND = 95         # 推奨水準。90は「公開してよい最低ライン」であり目標ではない


def prompt_for(path):
    """採点の指示。証拠を必ず書かせる"""
    nl = chr(10)
    parts = [
        f"次のHTMLは公開済みの記事です。初めて読む読者として読み、採点してください。{nl}",
        f"  {path}{nl}",
        "採点は3つの軸だけです。機械で数えられること（文字数・見出しの数・"
        "リンクの本数・FAQの個数）は別の工程がすでに判定済みなので、"
        "**ここでは数えないでください**。見るのは中身の質だけです。" + nl,
    ]
    for i, a in enumerate(AXES, 1):
        parts.append(f"{nl}{i}. {a['name']}（{MAX}点）— {a['what']}")
        parts.append(f"   なぜ見るか: {a['why']}")
        for pt, desc in a["anchors"]:
            parts.append(f"   {pt:>3}点: {desc}")
    parts.append(nl + "守ること:")
    parts.append("- 各軸について、**本文から根拠を1つ引用**してから点を付ける。"
                 "引用の無い点数は認めません")
    parts.append("- 甘く付けない。80点は「よくできている」ではなく"
                 "「上位の記事と並べても選ばれる」水準です")
    parts.append("- 良い点より先に、弱い点を各軸1つずつ書く")
    parts.append(nl + "最後の行に、次の形式だけを出力してください（他の文字を入れない）。")
    parts.append("SCORES originality=<0-100> extractability=<0-100> "
                 "decision=<0-100>")
    return nl.join(parts)


def judge(scores):
    """合否と理由。**総合は合計ではなく平均**（資料 v2 の判定例と同じ計算）。

    1軸でも下限を割れば、総合が足りていても不合格。
    壊滅した観点を、総合点で覆い隠さないための決まり。
    """
    vals = [scores.get(a["key"], 0) for a in AXES]
    total = round(sum(vals) / len(AXES))
    weak = {a["name"]: scores.get(a["key"], 0) for a in AXES
            if scores.get(a["key"], 0) < PASS_EACH}
    ok = not weak and total >= PASS_TOTAL
    why = []
    if weak:
        why.append("足切り: " + "・".join(f"{k}{v}点" for k, v in weak.items())
                   + f"（各{PASS_EACH}点以上が必要）")
    if total < PASS_TOTAL:
        why.append(f"総合{total}点（{PASS_TOTAL}点以上が必要）")
    return {"total": total, "max": MAX, "ok": ok, "weak": weak,
            "why": "／".join(why) or "合格", "version": VERSION}


def cutoff(breakdown):
    """score_breakdown の足切り点と満点。rubric の3観点は100点満点で PASS_EACH、旧6観点は20点満点で16。

    満点を見分けないと、100点満点の70点が16以上として素通りする
    """
    nums = [v for v in breakdown.values() if isinstance(v, (int, float))]
    if set(breakdown) & {a["key"] for a in AXES} or max(nums or [0]) > 20:
        return PASS_EACH, MAX
    return 16, 20


def weak_axes(meta):
    """足切りを割った観点 {観点: 点}。score_breakdown が無ければ空"""
    bd = meta.get("score_breakdown") or {}
    if not isinstance(bd, dict):
        return {}
    th, _ = cutoff(bd)
    return {k: v for k, v in bd.items() if isinstance(v, (int, float)) and v < th}


def gate_ok(meta):
    """公開してよいか。総合が PASS_TOTAL 以上で、1観点も足切りを割っていないこと。

    build.py と同じ規則。配信（publish.py など）もここを見れば、ビルドと判定がずれない
    """
    sc = meta.get("score")
    if isinstance(sc, bool) or not isinstance(sc, (int, float)) or sc < PASS_TOTAL:
        return False
    return not weak_axes(meta)


def main():
    print(f"■ 採点の基準 {VERSION}\n")
    for a in AXES:
        print(f"  {a['name']}（{MAX}点）— {a['what']}")
        print(f"     {a['why']}")
        for pt, desc in a["anchors"][:2]:
            print(f"     {pt:>3}点: {desc[:60]}")
        print()
    print(f"  合格: 各軸{PASS_EACH}点以上、かつ総合（3軸の平均）{PASS_TOTAL}点以上"
          f"（各{MAX}点満点・推奨{RECOMMEND}点）")
    print("\n  機械で数えられることは score_check と build.py が判定します。"
          "ここでは中身の質だけを見ます。")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
