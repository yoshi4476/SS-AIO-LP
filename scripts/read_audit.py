# -*- coding: utf-8 -*-
"""台本の読み上げを、音読み・訓読みが入れ替わりそうな語で洗い出す。

**なぜ要るか**: 実際に「判断は人」が「はんだんはニン」と読まれていた。
音声を全部聞き直すのは現実的でないので、**間違えやすい語の一覧を持っておき、
台本に出てきたら知らせる**形にする。

`video_make.READ_AS` で直っているものは「対応済み」として出す。
残っているものだけを見れば済むようにする。

    python scripts/read_audit.py           # 3本ぜんぶ
    python scripts/read_audit.py --only pr
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 読みが割れる語。（探す形, 正しい読み, なぜ間違えるか）
RISKY = [
    ("人", "ひと／にん", "数の後ろは「にん」、助詞が続くと「ひと」"),
    ("行", "ぎょう／おこな", "「行のまま」は、ぎょう"),
    ("最中", "さなか", "「さいちゅう」と読まれる"),
    ("一度", "いちど", ""),
    ("何本", "なんぼん", "「なにほん」と読まれる"),
    ("大文字", "おおもじ", ""),
    ("上位", "じょうい", "「うわい」と読まれることがある"),
    ("下限", "かげん", ""),
    ("重複", "ちょうふく", "「じゅうふく」でも通じるが、ゆれる"),
    ("他社", "たしゃ", ""),
    ("生成", "せいせい", ""),
    ("設定", "せってい", ""),
    ("表", "ひょう", "「おもて」と読まれることがある"),
    ("字", "じ", ""),
    ("分", "ふん／ぶん", "「90秒〜3分」はふん、「1文」はぶん"),
    ("間", "あいだ／かん", ""),
    ("数", "すう／かず", ""),
    ("日", "にち／ひ", "日付は READ_AS で変換済み"),
]

# 記号のままだと1文字ずつ読まれて極端に遅くなるもの
SLOW = [(r"[A-Za-z]{4,}", "英字が4文字以上続く。読み方を決めているか確認"),
        (r"\d+\.\d+(?![年月日%])", "小数。読み上げがゆれやすい"),
        (r"[／/]", "スラッシュ。読み飛ばされるか「スラッシュ」と読まれる"),
        (r"[（）()]", "括弧。間が空く")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["pr", "demo", "doc"])
    a = ap.parse_args()

    import video_make as V
    from sales_common import expand

    names = {"pr": "sales_script_pr", "demo": "sales_script_demo",
             "doc": "sales_script_doc"}
    total = 0
    for key, mod in names.items():
        if a.only and key != a.only:
            continue
        segs = expand(__import__(mod).script()["segments"])
        print(f"■ {key}（{len(segs)}区間）")
        seen = {}
        for i, s in enumerate(segs, 1):
            raw = s["say"]
            spoken = V.read_text(raw)
            for word, yomi, why in RISKY:
                if word not in raw:
                    continue
                # READ_AS で置き換わっていれば、もう触れなくてよい
                fixed = raw.count(word) > spoken.count(word)
                k = (word, fixed)
                seen.setdefault(k, []).append(i)
            for pat, why in SLOW:
                for m in re.findall(pat, spoken):
                    seen.setdefault((f"〈{why}〉{m}", None), []).append(i)
        for (word, fixed), where in sorted(seen.items(), key=lambda x: -len(x[1])):
            if fixed:
                continue
            mark = "対応済み" if fixed else "要確認"
            print(f"   [{mark}] {word}  … {len(where)}区間（例: {where[:4]}）")
            total += 1
        print()
    print(f"要確認 {total} 件。読み方を決めたら video_make.READ_AS に足してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
