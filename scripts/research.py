# -*- coding: utf-8 -*-
"""一次情報を集める（X投稿＋YouTube文字起こし）

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
X_DIR = ROOT / "data" / "x_trends"
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


def collect_x(kw, token, limit=30):
    """X API v2 で直近の投稿を集める。長文(note_tweet)も取る"""
    q = urllib.parse.quote(f"{kw} -is:retweet lang:ja")
    url = (f"https://api.twitter.com/2/tweets/search/recent?query={q}"
           f"&max_results={min(limit, 100)}"
           "&tweet.fields=created_at,public_metrics,note_tweet,conversation_id"
           "&expansions=author_id&user.fields=username,name,public_metrics")
    r = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(r, timeout=30) as res:
        d = json.loads(res.read().decode("utf-8"))
    users = {u["id"]: u for u in d.get("includes", {}).get("users", [])}
    out = []
    for t in d.get("data", []):
        u = users.get(t.get("author_id"), {})
        body = (t.get("note_tweet") or {}).get("text") or t.get("text", "")
        m = t.get("public_metrics", {})
        out.append({"user": u.get("username", ""), "name": u.get("name", ""),
                    "date": t.get("created_at", "")[:10], "text": body,
                    "url": f"https://x.com/{u.get('username','i')}/status/{t['id']}",
                    "impressions": m.get("impression_count", 0),
                    "likes": m.get("like_count", 0), "retweets": m.get("retweet_count", 0)})
    # 反応の多い順＝話題になっている実例から使う
    out.sort(key=lambda x: -(x["impressions"] or x["likes"]))
    return out


def collect_youtube(kw, api_key, limit=8):
    """関連動画を検索し、日本語の自動字幕を取る（yt-dlpが要る）"""
    q = urllib.parse.quote(kw)
    url = (f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
           f"&maxResults={limit}&relevanceLanguage=ja&q={q}&key={api_key}")
    with urllib.request.urlopen(url, timeout=30) as res:
        d = json.loads(res.read().decode("utf-8"))
    vids = [{"id": i["id"]["videoId"], "title": i["snippet"]["title"],
             "channel": i["snippet"]["channelTitle"],
             "url": f"https://www.youtube.com/watch?v={i['id']['videoId']}"}
            for i in d.get("items", [])]
    YT_DIR.mkdir(parents=True, exist_ok=True)
    for v in vids:
        out = YT_DIR / v["id"]
        if list(YT_DIR.glob(f"{v['id']}*.vtt")):
            v["transcript"] = "取得済み"
            continue
        r = subprocess.run(["yt-dlp", "--write-auto-sub", "--sub-lang", "ja",
                            "--skip-download", "-o", str(out), v["url"]],
                           capture_output=True, text=True, encoding="utf-8", errors="ignore")
        v["transcript"] = "取得" if r.returncode == 0 else "取得できず"
    return vids


def main():
    if len(sys.argv) < 2:
        raise SystemExit('使い方: python scripts/research.py "<キーワード>"')
    kw = sys.argv[1]
    e = env()
    missing = []

    print(f"■ 一次情報の収集: 「{kw}」\n")

    xt = e.get("X_BEARER_TOKEN", "")
    if is_set(xt):
        try:
            posts = collect_x(kw, xt)
            X_DIR.mkdir(parents=True, exist_ok=True)
            f = X_DIR / f"{re.sub(r'[^a-zA-Z0-9ぁ-んァ-ヶ一-龠]+', '_', kw)[:40]}.json"
            f.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  X投稿: {len(posts)}件 → {f.relative_to(ROOT).as_posix()}")
            for p in posts[:3]:
                print(f"    @{p['user']} {p['text'][:52]}…")
        except Exception as ex:
            print(f"  X投稿: 取得に失敗（{str(ex)[:70]}）")
    else:
        missing.append("X_BEARER_TOKEN（X API v2・Basic以上のプランが必要）")
        print("  X投稿: スキップ（X_BEARER_TOKEN が未設定）")

    yk = e.get("YOUTUBE_API_KEY", "")
    if is_set(yk):
        try:
            vids = collect_youtube(kw, yk)
            print(f"  YouTube: {len(vids)}本")
            for v in vids[:3]:
                print(f"    [{v['transcript']}] {v['title'][:44]}")
        except Exception as ex:
            print(f"  YouTube: 取得に失敗（{str(ex)[:70]}）")
    else:
        missing.append("YOUTUBE_API_KEY（YouTube Data API v3・無料枠あり）")
        print("  YouTube: スキップ（YOUTUBE_API_KEY が未設定）")

    print("\n  自社の一次情報:")
    subprocess.run([sys.executable, "scripts/facts.py",
                    sys.argv[sys.argv.index("--site") + 1] if "--site" in sys.argv else "ai-lab",
                    kw], cwd=ROOT)

    if missing:
        print("\n  ＜未設定のため使えない情報源＞")
        for m in missing:
            print(f"    - {m}")
        print("    .env に設定すると、次回から自動で収集します")


if __name__ == "__main__":
    main()
