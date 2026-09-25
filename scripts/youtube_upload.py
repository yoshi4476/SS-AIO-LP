# -*- coding: utf-8 -*-
"""作った動画を YouTube へ上げる。無料枠のまま1日100本まで。

**枠の話**: videos.insert の消費は 2026-06-01 から専用の枠になり、
1回1ユニット・既定で1日100回まで（以前は1,600ユニットで1日6本が上限だった）。
読み取りの10,000ユニットとは別枠なので、他の処理を圧迫しない。

**鍵**: サービスアカウントでは上げられない（YouTubeはチャンネルの所有者本人の
承認が要る）。1度だけブラウザで許可して `youtube-token.json` を作る。
配信用のPATとは別物で、`.env` には置かない。

  初回だけ:
    1. Google Cloud で OAuth クライアント（デスクトップ）を作り、
       youtube-client.json として置く
    2. python scripts/youtube_upload.py --auth   （ブラウザが開く）

  以降:
    python scripts/youtube_upload.py <mp4> --slug <slug>
    python scripts/youtube_upload.py --check          # 鍵と枠の確認だけ

**公開設定は既定で「限定公開」**。いきなり全体公開にすると、確認前のものが
チャンネルに並ぶ。中身を見てから `--public` を付けて上げ直す。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CLIENT = ROOT / "youtube-client.json"
TOKEN = ROOT / "youtube-token.json"
# upload だけだと字幕（captions.insert）が上げられない。force-ssl は upload を包含する。
# 既に youtube-token.json がある場合は、次の --auth で作り直すまで字幕は飛ばす
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CATEGORY_HOWTO = "27"        # 「教育」。解説動画はここに入れる


def creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    if not TOKEN.is_file():
        return None
    c = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if c and c.expired and c.refresh_token:
        c.refresh(Request())
        TOKEN.write_text(c.to_json(), encoding="utf-8")
    return c


def set_privacy(vid, status):
    """公開範囲だけを変える（消さない。記事と食い違った古い動画を限定公開に下げるのに使う）"""
    from googleapiclient.discovery import build
    c = creds()
    if not c:
        raise SystemExit("youtube-token.json がありません")
    yt = build("youtube", "v3", credentials=c, cache_discovery=False)
    yt.videos().update(part="status", body={"id": vid, "status": {"privacyStatus": status}}).execute()


def auth():
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not CLIENT.is_file():
        print(f"  {CLIENT.name} がありません。")
        print("  Google Cloud → APIとサービス → 認証情報 → OAuth クライアントID")
        print("  → デスクトップアプリ で作り、JSONをこの名前で置いてください")
        return 1
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    c = flow.run_local_server(port=0)
    TOKEN.write_text(c.to_json(), encoding="utf-8")
    print(f"  {TOKEN.name} を作りました（以降はブラウザ不要）")
    return 0


def describe(slug):
    """概要欄。**記事URLを必ず先頭に置く**（指名検索とサイトへの導線）"""
    import social_post as SP
    a = SP.article(slug)
    if not a:
        ds = ROOT / "data" / "datasets" / f"{slug}.json"
        if ds.is_file():
            d = json.loads(ds.read_text(encoding="utf-8"))
            url = f"https://ai.7senses.co.jp/data/{slug}/"
            return (f'{d["sentence"]}\n\n'
                    f'▼ 集計の元データ（表・グラフ・CSV・構造化データ）\n{url}\n\n'
                    f'母数: {d["n"]:,}{d["n_unit"]}\n対象期間: {d["period"]}\n'
                    f'集計方法: {d["method"]}\n\n'
                    f'セブンセンシズ株式会社\nhttps://ai.7senses.co.jp/'), d["title"], []
        return "", slug, []
    sid, cfg = SP.site_of(a["category"])
    pre = (cfg.get("url_prefix") or f'/{a["category"]}').strip("/")
    url = f'https://{cfg.get("domain", "")}/{pre}/{slug}/'
    body = "\n".join(f"・{x}" for x in a["leads"][:5])
    desc = (f'{a["desc"]}\n\n▼ 記事はこちら\n{url}\n\n'
            f'{body}\n\nセブンセンシズ株式会社\nhttps://{cfg.get("domain", "")}/')
    tags = [t for t in (cfg.get("x_tags") or [])]
    return desc, a["title"], tags


PLAYLISTS = ROOT / "data" / "youtube_playlists.json"


def _playlist_name(title):
    """業種が判定できれば「<業種>の集客・補助金」、できなければ「AI集客ラボ」"""
    try:
        import industry_hub as IH
        inds, _ = IH.load()
        s = IH.detect(title, "", inds)
        if s:
            name = next(i["name"] for i in inds if i["slug"] == s)
            return f"{name}の集客・補助金・AI活用"
    except Exception:
        pass
    return "AI集客ラボ｜AI検索・MEO・補助金"


def _add_to_playlist(yt, vid, title):
    name = _playlist_name(title)
    book = json.loads(PLAYLISTS.read_text(encoding="utf-8")) if PLAYLISTS.is_file() else {}
    pid = book.get(name)
    if not pid:
        res = yt.playlists().insert(part="snippet,status", body={
            "snippet": {"title": name[:150], "description": "セブンセンシズ株式会社（AI集客ラボ）の解説動画。記事の要点を本文と同じ内容で動画にしています。",
                        "defaultLanguage": "ja"},
            "status": {"privacyStatus": "public"}}).execute()
        pid = res["id"]
        book[name] = pid
        PLAYLISTS.parent.mkdir(exist_ok=True)
        PLAYLISTS.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    yt.playlistItems().insert(part="snippet", body={
        "snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
    return name


def upload(mp4, slug, public=False, quiet=False):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    c = creds()
    if not c:
        raise SystemExit("youtube-token.json がありません。--auth を先に実行してください")
    desc, title, tags = describe(slug)
    # タイトルは100字まで。超えると API が弾く
    title = (title or slug)[:100]
    # チャプター（video_make が <動画>.chapters.txt に書く）。説明欄の時刻がそのまま章になる
    ch = Path(mp4).with_suffix(".chapters.txt")
    if ch.is_file() and ch.read_text(encoding="utf-8").strip():
        desc = desc.rstrip() + "\n\n▼ チャプター\n" + ch.read_text(encoding="utf-8").strip() + "\n"
    body = {"snippet": {"title": title, "description": desc[:4900],
                        "tags": tags[:10], "categoryId": CATEGORY_HOWTO,
                        "defaultLanguage": "ja", "defaultAudioLanguage": "ja"},
            "status": {"privacyStatus": "public" if public else "unlisted",
                       "selfDeclaredMadeForKids": False}}
    yt = build("youtube", "v3", credentials=c)
    media = MediaFileUpload(str(mp4), chunksize=-1, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    res = req.execute()
    vid = res["id"]
    # 字幕（video_make が <動画>.srt に書く）。検索される文字になる。
    # 鍵の権限が upload だけの古い token では 403 になるので、落とさず知らせるだけ
    srt = Path(mp4).with_suffix(".srt")
    if srt.is_file():
        try:
            yt.captions().insert(part="snippet", body={"snippet": {"videoId": vid, "language": "ja",
                                                                     "name": "日本語", "isDraft": False}},
                                 media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream")).execute()
        except Exception as e:
            print(f"  [注意] 字幕を上げられませんでした（{str(e)[:70]}）。--auth をやり直すと権限が付きます")
    # 業種別の再生リストへ入れる（無ければ作る）。リストは「業種×集客」の言及の面になる
    try:
        _add_to_playlist(yt, vid, title)
    except Exception as e:
        print(f"  [注意] 再生リストに入れられませんでした（{str(e)[:70]}）")
    if not quiet:
        print(f"  上げました: https://www.youtube.com/watch?v={vid}")
        print(f"  公開設定: {'全体公開' if public else '限定公開（確認してから公開に変えてください）'}")
    return vid


def check():
    ok = True
    for p, why in ((CLIENT, "OAuthクライアント"), (TOKEN, "アクセス用の鍵")):
        have = p.is_file()
        print(f"  {why}（{p.name}）: {'あり' if have else 'なし'}")
        ok &= have
    try:
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
        print("  ライブラリ: あり")
    except ImportError:
        print("  ライブラリ: なし（pip install google-api-python-client google-auth-oauthlib）")
        ok = False
    print("  枠: videos.insert は1回1ユニット・1日100回まで（2026-06-01 から専用枠）")
    print("YT_OK=" + ("yes" if ok else "no"))
    if not ok:
        print("  初回だけ youtube-client.json を置いて --auth を実行してください")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mp4", nargs="?")
    ap.add_argument("--slug", help="記事か一次データのslug（概要欄に使う）")
    ap.add_argument("--auth", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--public", action="store_true", help="全体公開で上げる")
    a = ap.parse_args()

    if a.auth:
        return auth()
    if a.check or not a.mp4:
        return check()
    slug = a.slug or Path(a.mp4).stem
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise SystemExit(f"slug の形が違います: {slug}")
    upload(Path(a.mp4), slug, public=a.public)
    return 0


if __name__ == "__main__":
    sys.exit(main())
