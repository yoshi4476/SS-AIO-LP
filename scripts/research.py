# -*- coding: utf-8 -*-
"""一次情報を集める（YouTubeの字幕）

使い方: python scripts/research.py "<キーワード>" [--site ai-lab]

外部統計の引き写しだけでは、どのサイトでも書ける記事になり引用先に選ばれない。
実際の発言・現場の声を混ぜることで、その記事にしかない内容になる。

キーが未設定なら、何が足りないかを表示して終わる（黙って空を返さない）。
"""
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
YT_DIR = ROOT / "data" / "youtube_transcripts"


def env():
    d = {}
    p = ROOT / ".env"
    if p.is_file():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                d[k.strip()] = v.strip()
    return d


def is_set(v):
    """未設定と雛形（YOUR_...）を同じ扱いにする。雛形のまま動いたと誤解しないため"""
    return bool(v) and not v.upper().startswith("YOUR_")


def collect_youtube(kw, api_key=None, limit=6):
    """関連動画を検索し、日本語の自動字幕を取る。

    YouTube Data API のキーは要らない。yt-dlp の検索（ytsearch）で
    同じことができるため、キー取得を待たずに一次情報を集められる。
    """
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "--flat-playlist", "--dump-json",
                        "--playlist-end", str(limit), f"ytsearch{limit}:{kw}"],
                       capture_output=True, text=True, encoding="utf-8", errors="ignore")
    vids = []
    for line in r.stdout.strip().splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        vids.append({"id": d.get("id"), "title": d.get("title", ""),
                     "channel": d.get("channel") or d.get("uploader", ""),
                     "views": d.get("view_count") or 0,
                     "url": f"https://www.youtube.com/watch?v={d.get('id')}"})
    # 再生数が多い＝多くの人が確認した内容。引用元として妥当性が高い
    vids.sort(key=lambda v: -v["views"])

    YT_DIR.mkdir(parents=True, exist_ok=True)
    for v in vids:
        if list(YT_DIR.glob(f"{v['id']}*.vtt")):
            v["transcript"] = "取得済み"
            continue
        out = YT_DIR / v["id"]
        rr = subprocess.run([sys.executable, "-m", "yt_dlp", "--write-auto-sub",
                             "--sub-lang", "ja", "--skip-download", "-o", str(out), v["url"]],
                            capture_output=True, text=True, encoding="utf-8", errors="ignore")
        got = list(YT_DIR.glob(f"{v['id']}*.vtt"))
        v["transcript"] = "字幕あり" if got else ("字幕なし" if rr.returncode == 0 else "取得できず")
    return vids



def read_vtt(path):
    """自動字幕(VTT)を読みやすい本文に直す。

    VTTはタイムコードと1文字ごとのタグで埋まっており、そのままでは使えない。
    タグを外し、行の重複（カラオケ表示のため同じ行が繰り返される）を潰す。
    """
    t = path.read_text(encoding="utf-8", errors="ignore")
    lines, seen = [], set()
    for ln in t.splitlines():
        if "-->" in ln or ln.startswith(("WEBVTT", "Kind:", "Language:")) or not ln.strip():
            continue
        s = re.sub(r"<[^>]+>", "", ln).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        lines.append(s)
    return "\n".join(lines)


def save_transcripts(vids):
    """字幕を読める本文に直して .txt に保存し、保存先を返す。

    自動字幕は誤変換が多く（「LLMO」→「LMO」「エルエム」など）、
    機械で切り出した断片をそのまま引用すると事実を誤って書くことになる。
    整形した全文を残し、内容の判断と引用は本文を読んだうえで行うこと。
    """
    saved = []
    for v in vids:
        src = list(YT_DIR.glob(f"{v['id']}*.ja.vtt"))
        if not src:
            continue
        body = read_vtt(src[0])
        if len(body) < 500:
            continue
        out = YT_DIR / f"{v['id']}.txt"
        header = (f"# {v['title']}\n"
                  f"# {v['channel']} / 再生{v['views']:,} / {v['url']}\n\n")
        out.write_text(header + body + "\n", encoding="utf-8")
        saved.append({"path": out, "title": v["title"], "chars": len(body), "url": v["url"]})
    return saved


def main():
    if len(sys.argv) < 2:
        raise SystemExit('使い方: python scripts/research.py "<キーワード>"')
    kw = sys.argv[1]
    e = env()
    missing = []

    print(f"■ 一次情報の収集: 「{kw}」\n")

    # YouTubeはキー不要（yt-dlpの検索を使う）。導入されていなければそれだけ伝える
    try:
        vids = collect_youtube(kw)
        got = [v for v in vids if v["transcript"] in ("字幕あり", "取得済み")]
        print(f"  YouTube: {len(vids)}本（字幕取得 {len(got)}本）")
        for v in vids[:4]:
            print(f"    [{v['transcript']}] 再生{v['views']:,} {v['title'][:38]}")
        saved = save_transcripts(vids)
        if saved:
            print(f"\n  文字起こし {len(saved)}本を保存しました（執筆前に読むこと）")
            for s in saved:
                print(f"    {s['path'].relative_to(ROOT).as_posix()}  {s['chars']:,}字  {s['title'][:34]}")
            print("    ※ 自動字幕は誤変換があります。数値や固有名詞は動画で確認してから書くこと")
    except FileNotFoundError:
        missing.append("yt-dlp（pip install yt-dlp）")
        print("  YouTube: スキップ（yt-dlp が未導入）")
    except Exception as ex:
        print(f"  YouTube: 取得に失敗（{str(ex)[:70]}）")

    print("\n  自社の一次情報:")
    subprocess.run([sys.executable, "scripts/facts.py",
                    sys.argv[sys.argv.index("--site") + 1] if "--site" in sys.argv else "ai-lab",
                    kw], cwd=ROOT)

    # 字幕は数万字ある。そのまま渡しても読まれないので、
    # 引用できそうな一文だけを抜き出して見せる。
    try:
        import yt_quotes
        shown = 0
        for v in yt_quotes.load(kw):
            num, exp, bad = yt_quotes.pick(v["sentences"])
            if not (num or exp or bad):
                continue
            if shown == 0:
                print("\n  ■ 記事に使えそうな発言（字幕から抜粋）")
            shown += 1
            print(f"\n    {v['title'][:50]}")
            print(f"    https://www.youtube.com/watch?v={v['id']}")
            for label, items in (("数字", num), ("体験", exp), ("つまずき", bad)):
                for s in items[:2]:
                    print(f"      [{label}] {s[:76]}")
            if shown >= 4:
                break
        if shown:
            print("\n    ※ 自動字幕は誤変換があります。数値と固有名詞は動画で確認してから引用すること")
    except Exception as err:
        print(f"\n  発言の抜き出しに失敗: {err}")

    if missing:
        print("\n  ＜未設定のため使えない情報源＞")
        for m in missing:
            print(f"    - {m}")
        print("    .env に設定すると、次回から自動で収集します")


if __name__ == "__main__":
    main()
