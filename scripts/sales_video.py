# -*- coding: utf-8 -*-
"""営業用の動画3本を作る。台本は提案書 v2（39ページ）と同じ数字を使う。

  pr    AI集客ラボ PR動画     なぜ今なのか → 何をやるか → 費用の理由 → 今日始める理由
  demo  運用デモ動画          システムが実際にどう動いているか（画面をそのまま見せる）
  doc   資料説明動画          提案書39ページを、ページ番号を言いながら1枚ずつ

**数字は sales_common に1か所だけ置く。** 3本で別々に書くと、片方だけ古くなる。

    python scripts/sales_video.py              # 3本とも作る
    python scripts/sales_video.py --only pr    # 1本だけ
    python scripts/sales_video.py --list       # 台本と長さの見込みだけ見る
    python scripts/sales_video.py --only pr --limit 6   # 冒頭6区間だけ試写する
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = Path(r"C:\Users\user\Desktop\AIO系")

from sales_common import FOOT, expand  # noqa: E402

MAKERS = {"pr": ("AI集客ラボ_PR_完成版", "sales_script_pr"),
          "demo": ("運用デモ動画_完成版", "sales_script_demo"),
          "doc": ("資料説明動画_完成版", "sales_script_doc")}


def load(key):
    """台本を読み、長い読み上げを割ってから返す"""
    sc = __import__(MAKERS[key][1]).script()
    sc["segments"] = expand(sc["segments"])
    sc.setdefault("footer", FOOT)
    return sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(MAKERS))
    ap.add_argument("--list", action="store_true", help="台本と見込みの長さだけ見る")
    ap.add_argument("--limit", type=int, help="冒頭の指定区間だけ作る（試写用）")
    a = ap.parse_args()

    for key, (name, _) in MAKERS.items():
        if a.only and key != a.only:
            continue
        sc = load(key)
        segs = sc["segments"]
        chars = sum(len(x["say"]) for x in segs)
        est = (chars / 6 + 0.4 * len(segs)) / 60
        if a.list:
            print(f'■ {name}（{len(segs)}区間 / {chars}字 / 約{est:.1f}分）')
            for i, x in enumerate(segs, 1):
                k = x.get("kind", "本文")
                print(f'   {i:3d} [{k:7s}] {x["say"][:46]}')
            continue

        if a.limit:
            sc = {**sc, "segments": segs[:a.limit]}
            name += f"_試写{a.limit}"
        print(f'■ {name}（{len(sc["segments"])}区間 / 見込み {est:.1f}分）')
        import video_make as V
        out = OUT / f"{name}.mp4"
        sec = V.build(sc, out, quiet=True)
        print(f"   {sec / 60:.1f}分 / {out.stat().st_size / 1024 / 1024:.0f}MB")
        print(f"   {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
