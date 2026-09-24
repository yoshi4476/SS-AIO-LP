# -*- coding: utf-8 -*-
"""営業動画を、サイトで配信できる形にして site/videos/ へ差し替える。

**なぜ再エンコードが要るか**: Cloudflare Pages は**1ファイル25MiBが上限**。
書き出したままの動画（PR 27.9MB）は、そのまま置くと配信に失敗する。

**なぜフレームレートを落とすか**: 中身はスライドで、6秒に1回しか絵が変わらない。
30fps で持つ意味がなく、10fps にしても見え方は変わらないまま容量が4割減る。
文字がぼやけないよう、大きさは 1920×1080 のまま変えない。

    python scripts/video_publish.py            # 何が差し替わるか見る
    python scripts/video_publish.py --write    # 差し替える
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(r"C:\Users\user\Desktop\AIO系")
DST = ROOT / "site" / "videos"
CAP = 25 * 1024 * 1024        # Cloudflare Pages の上限（1ファイル25MiB）
FPS = 10
CRF_STEPS = (30, 32, 34, 36)   # 上限に入るまで、この順に画質を落とす
GOP = FPS * 10                 # キーフレームは10秒ごと

# 書き出した動画 → サイトでの名前。名前はコーポレート側が参照しているので変えない
MAP = {
    "AI集客ラボ_PR_完成版.mp4": "aio-pr.mp4",
    "資料説明動画_完成版.mp4": "doc-guide.mp4",
    "運用デモ動画_完成版.mp4": "console-demo.mp4",
}


def mb(p):
    return p.stat().st_size / 1048576


def encode(src, dst):
    """上限に入るまで画質を落としながら変換する。

    **`+faststart` は外さないこと。** 索引が末尾にあると、
    長い動画は再生が途中で止まる（実測で13分と18分の動画が止まった）。
    """
    for crf in CRF_STEPS:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
                        "-r", str(FPS), "-c:v", "libx264", "-crf", str(crf),
                        "-preset", "medium", "-pix_fmt", "yuv420p",
                        "-g", str(GOP), "-keyint_min", str(FPS),
                        "-profile:v", "high", "-level", "4.0",
                        "-movflags", "+faststart",
                        "-c:a", "aac", "-b:a", "96k", str(dst)], check=True)
        if dst.stat().st_size <= CAP:
            return crf
    raise SystemExit(f"上限{CAP // 1048576}MiBに収まりません: {dst.name}"
                     f"（{mb(dst):.1f}MB）。動画を短くするか、"
                     f"CRF_STEPS に大きい値を足してください")


def poster(src, dst):
    """1枚目は表紙なので、そこをそのまま静止画にする"""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(src),
                    "-frames:v", "1", "-q:v", "4", str(dst)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="実際に差し替える")
    a = ap.parse_args()

    ng = 0
    for name, out in MAP.items():
        s = SRC / name
        d = DST / out
        if not s.is_file():
            print(f"  × 元が見つかりません: {s}")
            ng += 1
            continue
        old = f"{mb(d):.1f}MB" if d.is_file() else "（無し）"
        print(f"■ {out}   いま {old} ← {name}（{mb(s):.1f}MB）")
        if not a.write:
            continue
        crf = encode(s, d)
        poster(d, d.with_name(d.stem + "-poster.jpg"))
        head = d.open("rb").read(8192)
        ok = b"moov" in head          # 索引が先頭にあるか。無いと途中で止まる
        print(f"   → {mb(d):.1f}MB  画質CRF{crf}  "
              f"{'索引は先頭・OK' if ok else '★索引が末尾'}")
        if not ok:
            ng += 1
    if not a.write:
        print("\n  --write を付けると差し替えます")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
