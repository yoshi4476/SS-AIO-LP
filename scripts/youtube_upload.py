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


def is_client(site):
    """受託のクライアントか（data/clients/<id> がある社）。自社3サイトは同じチャンネルに上げる"""
    import sites as S
    return S.is_client(site)


def token_path(site=None):
    """その社のチャンネルの鍵。クライアントは youtube-token-<id>.json（CI では YOUTUBE_TOKENS_JSON から書き出す）。
    クライアントの動画を当社のチャンネルに上げないため、クライアントは共通の鍵に落とさない"""
    return ROOT / f"youtube-token-{site}.json" if is_client(site) else TOKEN


def site_of(slug):
    try:
        import duo_video as DV
        import sites as S
        return S.find_category_owner(DV.article(slug)["category"])
    except Exception:
        return None


def creds(site=None):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    tp = token_path(site)
    if not tp.is_file():
        return None
    # BOM 付きで保存された鍵でも読めるように、ファイル名ではなく中身で渡す（BOM で Google の認証が全滅した前例がある）
    c = Credentials.from_authorized_user_info(json.loads(tp.read_text(encoding="utf-8-sig")), SCOPES)
    if c and c.expired and c.refresh_token:
        c.refresh(Request())
        tp.write_text(c.to_json(), encoding="utf-8")
    return c


def set_privacy(vid, status, site=None):
    """公開範囲だけを変える（消さない。記事と食い違った古い動画を限定公開に下げるのに使う）"""
    from googleapiclient.discovery import build
    c = creds(site)
    if not c:
        raise SystemExit("youtube-token.json がありません")
    yt = build("youtube", "v3", credentials=c, cache_discovery=False)
    yt.videos().update(part="status", body={"id": vid, "status": {"privacyStatus": status}}).execute()


# Secret に鍵を入れた社の一覧（鍵そのものは書かない）。Secret の中身は読めないので、ここで覚えておく
CONNECTED = ROOT / "data" / "youtube_connected.json"


def expected_clients(root=ROOT):
    """Secret に鍵があるはずの社: 前に登録した社と、sites/*.json に YouTube チャンネルを書いたクライアント"""
    ids = set()
    man = root / "data" / "youtube_connected.json"
    if man.is_file():
        ids |= set(json.loads(man.read_text(encoding="utf-8")).get("sites", []))
    import sites as S
    for sid, cfg in (S.load_all().items() if root == ROOT else ()):
        if S.is_client(sid) and (cfg.get("channels") or {}).get("youtube"):
            ids.add(sid)
    for p in (root / "sites").glob("*.json") if root != ROOT else ():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if ((root / "data" / "clients" / p.stem).is_dir() or cfg.get("client")) and (cfg.get("channels") or {}).get("youtube"):
            ids.add(p.stem)
    return ids


def tokens_bundle(root=ROOT):
    """Secret に入れる全社分の鍵と、手元に鍵ファイルが無い既存の社"""
    allk = {p.stem.replace("youtube-token-", ""): json.loads(p.read_text(encoding="utf-8-sig"))
            for p in root.glob("youtube-token-*.json")}
    return allk, sorted(expected_clients(root) - set(allk))


def save_connected(allk):
    CONNECTED.parent.mkdir(parents=True, exist_ok=True)
    CONNECTED.write_text(json.dumps({"sites": sorted(allk)}, ensure_ascii=False, indent=1), encoding="utf-8")


def auth(site=None):
    """チャンネルの持ち主のアカウントで1回だけ許可する。クライアントは --site <id> を付け、先方に許可してもらう"""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not CLIENT.is_file():
        print(f"  {CLIENT.name} がありません。")
        print("  Google Cloud → APIとサービス → 認証情報 → OAuth クライアントID")
        print("  → デスクトップアプリ で作り、JSONをこの名前で置いてください")
        return 1
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    c = flow.run_local_server(port=0)
    tp = token_path(site)
    tp.write_text(c.to_json(), encoding="utf-8")
    print(f"  {tp.name} を作りました（以降はブラウザ不要）")
    if is_client(site):
        # 全クライアントの鍵を1つにまとめて GitHub に入れる（SNS の SOCIAL_TOKENS_JSON と同じ。手で登録させない）
        import subprocess
        allk, missing = tokens_bundle()
        if missing:
            # Secret は丸ごと置き換わる。手元に鍵の無い社を外して上書きすると、その社の動画が上がらなくなる
            print(f"  GitHub の YOUTUBE_TOKENS_JSON は書き換えませんでした: 手元に鍵が無い社があります"
                  f"（{', '.join(missing)}）。youtube-token-<id>.json を全社分そろえてからやり直してください")
        else:
            r = subprocess.run(["gh", "secret", "set", "YOUTUBE_TOKENS_JSON"], cwd=ROOT,
                               input=json.dumps(allk), text=True, encoding="utf-8", capture_output=True)
            if r.returncode == 0:
                save_connected(allk)
            print(f"  GitHub の YOUTUBE_TOKENS_JSON に登録しました（{len(allk)}社）" if r.returncode == 0 else
                  f"  GitHub に登録できませんでした（gh auth login を確認）: {r.stderr.strip()[:120]}")
    try:
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", credentials=c, cache_discovery=False)
        items = yt.channels().list(part="id", mine=True).execute().get("items", [])
        _count_user(items[0]["id"] if items else "")
    except Exception as e:
        print(f"  ※ 許可したチャンネルを台帳に数えられませんでした（{type(e).__name__}）")
    return 0


# Google の確認を受けていないアプリは、許可できるアカウントが累計100まで（使い終わっても減らない）。
# 上限に着いてから確認を申請すると数週間止まるので、90で知らせる
USERS = ROOT / "data" / "youtube_oauth_users.json"
USER_CAP, USER_WARN = 100, 90


def _count_user(channel_id):
    d = json.loads(USERS.read_text(encoding="utf-8")) if USERS.is_file() else {"channels": []}
    if channel_id and channel_id not in d["channels"]:
        d["channels"].append(channel_id)
        USERS.parent.mkdir(parents=True, exist_ok=True)
        USERS.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  許可したアカウント: 累計{len(d['channels'])}（未確認アプリの上限 {USER_CAP}）")


def users():
    """許可したアカウントの累計が上限に近づいたら知らせる（週次の findings が呼ぶ）"""
    d = json.loads(USERS.read_text(encoding="utf-8")) if USERS.is_file() else {"channels": []}
    n = len(d.get("channels", []))
    print(f"■ YouTube の許可: 累計{n}アカウント（未確認アプリの上限 {USER_CAP}）")
    if n >= USER_WARN:
        print(f"要対応: YouTube 用アプリの許可が累計{n}に達しました。上限{USER_CAP}を超えると新しい"
              "チャンネルを追加できません。Google Cloud の同意画面から「アプリの確認」を申請してください")
    print("YT_USERS_OK=" + ("no" if n >= USER_WARN else "yes"))
    return 0


def tools_block(a):
    """説明欄の「無料で確かめる」。AI紹介チェックと、業種が分かればその業種のチェックリスト"""
    lines = ["▼ 無料で確かめる", "・AIに御社がどう紹介されているか（無料チェック）", "https://ai.7senses.co.jp/tools/ai-check/"]
    try:
        import industry_hub as IH
        import industry_ai_sources as IAS
        hub = IH.detect(a.get("title", ""), a.get("keyword", ""), IH.load()[0])
        r = IAS.HUB_TO_RESEARCH.get(hub or "")
        cl = IAS.RESEARCH_TO_CHECKLIST.get(r or "")
        if cl:
            import checklist_make as CM
            # PDF の題・受け取りページの選択肢と同じ名前にする（「歯科版」と「歯科医院版」が混ざらないように）
            name = CM.INDUSTRIES[cl]["label"]
            lines += [f"・AI検索対策チェックリスト（{name}版・PDF）", f"https://ai.7senses.co.jp/download/?ind={cl}"]
    except Exception:
        pass
    return "\n".join(lines) + "\n\n"


LEAD_LONG = "lead-long"     # 台帳のショートの desc にこの印があるものだけ、説明欄の先頭に通常の動画を置く
# 説明欄の上限は 5,000 バイト（UTF-8）。文字数で 4,900 に切っていたため、日本語（1字3バイト）では
# API が弾く長さになっていた。余裕を見て 4,900 バイトに収める
DESC_BYTES = 4900
CHAPTER_HEAD = "\n\n▼ チャプター\n"


def fit_description(desc, limit=DESC_BYTES):
    """説明欄を UTF-8 で limit バイト以下にする。字の途中では切らない。
    チャプターは末尾にあり、途中で切れると章が壊れるので残し、その前の本文を詰める"""
    if len(desc.encode("utf-8")) <= limit:
        return desc
    head, sep, chap = desc.partition(CHAPTER_HEAD)
    tail = sep + chap
    room = limit - len(tail.encode("utf-8"))
    if not sep or room <= 0:
        head, tail, room = desc, "", limit
    cut = head.encode("utf-8")[:room].decode("utf-8", "ignore")
    return cut.rstrip() + tail


def full_description(slug, short=False, chapters=None, lead_long=False):
    """概要欄の完成形。アップロードと書き直しの両方がここを通る（別々に組むと片方だけ古くなる）。
    リンクは畳まれた状態でも見える先頭の行に置く。要約の下にあると「もっと見る」を押さないと出てこない（2026-10-03）。
    lead_long はこれから上げるショートだけ（上げ済みのショートの説明欄は前の形のまま変えない）"""
    desc, title, tags = describe(slug)
    if not desc:
        return desc, title, tags
    if short:
        import duo_video as DV
        br = DV.brand(DV.article(slug))
        head = [f"詳しくは「{br['search']}」で検索してください。"]
        lp = ROOT / "data" / "videos.json"
        long_id = (json.loads(lp.read_text(encoding="utf-8")).get(slug) or {}).get("youtube") if lp.is_file() else None
        if long_id and lead_long:
            # ショートは見られて通常の動画は見られていなかった（2026-10-05）。続きをいちばん上に置く。
            # 関連動画の欄・コメントの固定は API に項目が無く設定できない
            head.insert(0, f"▶ 続きの解説（通常の動画）\nhttps://youtu.be/{long_id}")
        elif long_id:
            # ショートを見た人を本編へ送る（ショートの説明欄は押せる場合がある。押せなくても題で探せる）
            head.append(f"▶ 本編の動画（くわしい解説）\nhttps://youtu.be/{long_id}")
        desc = "\n".join(head) + "\n\n" + desc
    ch = Path(chapters) if chapters else None
    if not short and ch and ch.is_file() and ch.read_text(encoding="utf-8").strip():
        # チャプター（<動画>.chapters.txt）。説明欄の時刻がそのまま章になる
        desc = desc.rstrip() + CHAPTER_HEAD + ch.read_text(encoding="utf-8").strip() + "\n"
    return fit_description(desc), title, tags


def update_descriptions():
    """すでに上げた動画の説明欄を、いまの describe() で書き直す（ショートは題に #Shorts を残す）"""
    import article_videos as AV
    from googleapiclient.discovery import build
    c = creds()
    if not c:
        raise SystemExit("youtube-token.json がありません")
    yt = build("youtube", "v3", credentials=c, cache_discovery=False)
    led = AV.load()
    n = 0
    for slug, v in led.items():
        for vid, short in ((v.get("youtube"), False), ((v.get("short") or {}).get("youtube"), True)):
            if not vid:
                continue
            desc, _, _ = full_description(slug, short=short, chapters=ROOT / "automation" / "video" / f"{slug}.chapters.txt",
                                          lead_long=short and (v.get("short") or {}).get("desc") == LEAD_LONG)
            if not desc:
                continue
            cur = yt.videos().list(part="snippet", id=vid).execute().get("items", [])
            if not cur:
                continue
            sn = cur[0]["snippet"]
            if sn.get("description", "").strip() == desc.strip():
                continue
            body = {"id": vid, "snippet": {"title": sn["title"], "categoryId": sn.get("categoryId", "27"),
                                           "description": fit_description(desc), "tags": sn.get("tags", [])}}
            yt.videos().update(part="snippet", body=body).execute()
            n += 1
            print(f"  説明欄を更新: {vid} {sn['title'][:30]}")
    print(f"YT_DESC_UPDATED={n}")
    return 0


def describe(slug):
    """概要欄。**記事URLを必ず先頭に置く**（指名検索とサイトへの導線）"""
    import social_post as SP
    a = SP.article(slug)
    if not a and slug.startswith("research-") and not (ROOT / "articles" / f"{slug}.md").is_file():
        import research_promo as RP
        return RP.describe(slug[len(RP.PREFIX):])
    if not a:
        ds = ROOT / "data" / "datasets" / f"{slug}.json"
        if ds.is_file():
            d = json.loads(ds.read_text(encoding="utf-8"))
            import data_intake
            # 一次データを非公開にしている間は /data/ が404になるので、サイトの入口へ送る
            url = f"https://ai.7senses.co.jp/data/{slug}/" if data_intake.PUBLIC else "https://ai.7senses.co.jp/"
            return (f'{d["sentence"]}\n\n'
                    f'▼ 集計の元データ（表・グラフ・CSV・構造化データ）\n{url}\n\n'
                    f'母数: {d["n"]:,}{d["n_unit"]}\n対象期間: {d["period"]}\n'
                    f'集計方法: {d["method"]}\n\n'
                    f'セブンセンシズ株式会社\nhttps://ai.7senses.co.jp/'), d["title"], []
        return "", slug, []
    sid, cfg = SP.site_of(a["category"])
    import wp_bridge     # WordPress の社はパーマリンク設定が決めたURL（組み立てると説明欄のリンクが404）
    url = wp_bridge.article_url(cfg, {"slug": slug, "category": a["category"]})
    body = "\n".join(f"・{x}" for x in a["leads"][:5])
    desc = (f'▼ 記事はこちら\n{url}\n\n{a["desc"]}\n\n'
            f'{body}\n\n{tools_block(a) if sid == "ai-lab" else ""}セブンセンシズ株式会社\nhttps://{cfg.get("domain", "")}/')
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
    # 作ったばかりの再生リストや、上げたばかりの動画は YouTube 側の反映が間に合わず 409 になる。
    # 数秒おけば通る（実測 2026-09-26）
    import time
    from googleapiclient.errors import HttpError
    for i in range(4):
        try:
            yt.playlistItems().insert(part="snippet", body={
                "snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
            break
        except HttpError as e:
            if e.resp.status != 409 or i == 3:
                raise
            time.sleep(5 * (i + 1))
    return name


def existing(yt, title, n=50, skip=()):
    """直近 n 本のうち、題が同じで非公開でない動画の id（skip は差し替え中の古い版。上げてから下げるため）"""
    up = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids = [i["contentDetails"]["videoId"] for i in
           yt.playlistItems().list(part="contentDetails", playlistId=up, maxResults=n).execute().get("items", [])]
    if not ids:
        return None
    for v in yt.videos().list(part="snippet,status", id=",".join(ids)).execute().get("items", []):
        if v["snippet"]["title"] == title and v["status"]["privacyStatus"] != "private" and v["id"] not in skip:
            return v["id"]
    return None


def upload(mp4, slug, public=False, quiet=False, short_title="", replacing=(), title="", lead_long=False):
    """short_title を渡すと縦型ショートとして上げる（題に #Shorts、説明は短く、再生リストには入れない）。
    title は通常の動画の題（yt_demand が YouTube の検索語から決めたもの。無ければ記事の題）"""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    site = site_of(slug)
    c = creds(site)
    if not c:
        if is_client(site):
            # 当社のチャンネルに上げる事故を防ぐ。先方のチャンネルを接続するまで上げない
            raise RuntimeError(f"{site} の YouTube チャンネルが未接続です（youtube_upload.py --auth --site {site}）")
        raise SystemExit("youtube-token.json がありません。--auth を先に実行してください")
    # 字幕の無い動画は上げない。YouTube の自動字幕が出て「[音楽]」や聞き違いが
    # そのまま表示される（2026-10-03: ショートはすべて字幕なしで上がっていた）
    if not Path(mp4).with_suffix(".srt").is_file():
        raise RuntimeError(f"字幕ファイル {Path(mp4).with_suffix('.srt').name} がありません。上げません")
    desc, art_title, tags = full_description(slug, short=bool(short_title), chapters=Path(mp4).with_suffix(".chapters.txt"),
                                             lead_long=lead_long)
    title = short_title[:88] + " #Shorts" if short_title else (title or art_title)
    # タイトルは100字まで。超えると API が弾く
    title = (title or slug)[:100]
    body = {"snippet": {"title": title, "description": fit_description(desc),
                        "tags": tags[:10], "categoryId": CATEGORY_HOWTO,
                        "defaultLanguage": "ja", "defaultAudioLanguage": "ja"},
            "status": {"privacyStatus": "public" if public else "unlisted",
                       "selfDeclaredMadeForKids": False}}
    yt = build("youtube", "v3", credentials=c)
    # 台帳の記録が漏れると、同じ動画を翌日また上げる（2026-09-27〜29 に同じ動画が3本公開された）。
    # 台帳に頼らず、チャンネルに同じ題の公開中の動画があればそれを返す
    dup = existing(yt, title, skip=set(replacing))
    if dup:
        print(f"  同じ題の動画がすでにあります（{dup}）。上げ直しません")
        return dup
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
        if not short_title:
            _add_to_playlist(yt, vid, title)
    except Exception as e:
        print(f"  [注意] 再生リストに入れられませんでした（{str(e)[:70]}）")
    # サムネイルは記事と同じ業種・テーマの画像（サイト・note・YouTube で見た目をそろえる）。ショートは縦型なので付けない
    if not short_title:
        set_thumbnail(yt, vid, slug)
    if not quiet:
        print(f"  上げました: https://www.youtube.com/watch?v={vid}")
        print(f"  公開設定: {'全体公開' if public else '限定公開（確認してから公開に変えてください）'}")
    return vid


def thumb_for(slug):
    """記事に付く業種・テーマの画像（site/images/thumbs/）を 1280×720 の JPEG にして返す。無ければ None"""
    import tempfile
    import build
    from PIL import Image
    p = ROOT / "articles" / f"{slug}.md"
    if not p.is_file():
        return None
    try:
        meta, _ = build.parse_article(p)
    except ValueError:
        return None                                # 他サイト（コーポレート・補助金）の記事
    e = str(meta.get("eyecatch", ""))
    # 業種・テーマの画像か、手で選んだ画像だけ。自動で描いたアイキャッチ（eyecatch.png）は動画の場面より弱い
    if not e or e.endswith("/eyecatch.png") or not (ROOT / "site" / e.lstrip("/")).is_file():
        return None
    im = Image.open(ROOT / "site" / e.lstrip("/")).convert("RGB")
    w, h = im.size
    th = round(w * 9 / 16)                         # 16:9 に切りそろえる（上下を少しだけ落とす）
    if th < h:
        top = (h - th) // 2
        im = im.crop((0, top, w, top + th))
    out = Path(tempfile.gettempdir()) / f"yt-thumb-{slug}.jpg"
    im.resize((1280, 720), Image.LANCZOS).save(out, "JPEG", quality=88, optimize=True)   # 上限 2MB
    return out


def set_thumbnail(yt, vid, slug):
    from googleapiclient.http import MediaFileUpload
    try:
        f = thumb_for(slug)
        if not f:
            return False
        yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(f), mimetype="image/jpeg")).execute()
        print(f"  サムネイル: {f.name}")
        return True
    except Exception as e:
        # 独自サムネイルは電話番号の確認が済んだチャンネルだけ。権限の古い鍵でも 403 になる
        print(f"  [注意] サムネイルを設定できませんでした（{str(e)[:90]}）")
        return False


def update_thumbnails():
    """上げ済みの動画（ショート以外）のサムネイルを、記事の業種・テーマの画像にそろえる"""
    from googleapiclient.discovery import build as gbuild
    c = creds()
    if not c:
        raise SystemExit("youtube-token.json がありません")
    yt = gbuild("youtube", "v3", credentials=c)
    vids = json.loads((ROOT / "data" / "videos.json").read_text(encoding="utf-8"))
    n = 0
    for slug, v in vids.items():
        if isinstance(v, dict) and v.get("youtube"):          # 横型の本編（ショートは v["short"] に別で持つ）
            n += set_thumbnail(yt, v["youtube"], slug)
    print(f"YT_THUMBS_SET={n}")


def audit():
    """チャンネルの公開中の動画を点検する（週次）。同じ題が2本以上・自前の字幕が無い・台帳に無い。
    2026-10-03: 同じ動画が3本公開され、ショートは全本が自動字幕（[音楽]・聞き違い）のままだった"""
    from googleapiclient.discovery import build
    c = creds()
    if not c:
        print("YT_AUDIT_OK=unknown（鍵がありません）")
        return 1
    yt = build("youtube", "v3", credentials=c)
    up = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=up, maxResults=50, pageToken=tok).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        tok = r.get("nextPageToken")
        if not tok:
            break
    lp = ROOT / "data" / "videos.json"
    led = json.loads(lp.read_text(encoding="utf-8")) if lp.is_file() else {}
    known = {x for v in led.values() if isinstance(v, dict) for x in (v.get("youtube"), (v.get("short") or {}).get("youtube"))}
    pub, bad = [], []
    for i in range(0, len(ids), 50):
        for v in yt.videos().list(part="snippet,status", id=",".join(ids[i:i + 50])).execute().get("items", []):
            if v["status"]["privacyStatus"] == "public":
                pub.append((v["id"], v["snippet"]["title"]))
    seen = {}
    for vid, title in pub:
        seen.setdefault(title, []).append(vid)
        kinds = {x["snippet"]["trackKind"] for x in yt.captions().list(part="snippet", videoId=vid).execute().get("items", [])}
        if "standard" not in kinds:
            bad.append(f"自前の字幕が無い（自動字幕が出る）: {vid} {title[:40]}")
        if vid not in known:
            bad.append(f"台帳に無い公開動画: {vid} {title[:40]}")
    bad += [f"同じ題が{len(v)}本公開: {', '.join(v)} {t[:40]}" for t, v in seen.items() if len(v) > 1]
    for b in bad:
        print("  " + b)
    print(f"公開 {len(pub)}本を点検")
    print("YT_AUDIT_OK=" + ("no" if bad else "yes"))
    return 0


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
    ap.add_argument("--site", help="--auth の対象の社（クライアントのチャンネルをつなぐとき）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--audit", action="store_true", help="公開中の動画の重複・字幕・台帳漏れを点検する")
    ap.add_argument("--users", action="store_true", help="許可したアカウントの累計（上限100の手前で知らせる）")
    ap.add_argument("--public", action="store_true", help="全体公開で上げる")
    ap.add_argument("--update-desc", action="store_true", help="上げ済みの動画の説明欄を今の内容に書き直す")
    ap.add_argument("--update-thumbs", action="store_true", help="上げ済みの動画のサムネイルを記事の業種・テーマの画像にそろえる")
    a = ap.parse_args()
    if a.audit:
        return audit()
    if a.update_desc:
        return update_descriptions()
    if a.update_thumbs:
        return update_thumbnails()

    if a.auth:
        return auth(a.site)
    if a.users:
        return users()
    if a.check or not a.mp4:
        return check()
    slug = a.slug or Path(a.mp4).stem
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise SystemExit(f"slug の形が違います: {slug}")
    upload(Path(a.mp4), slug, public=a.public)
    return 0


if __name__ == "__main__":
    sys.exit(main())
