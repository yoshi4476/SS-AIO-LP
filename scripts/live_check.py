# -*- coding: utf-8 -*-
"""公開されたページを実際に取得して検査する

品質ゲートはすべて原稿とビルド出力を見ている。公開後の実物を見る工程が
無いため、次のものが本番に届いていた。

  ・社内向けのHTMLコメント（LPに6件、補助金サイトに9件。個人名入りの
    未確定メモを含む。画面には出ないがソースを見れば誰でも読める）
  ・生成時の作業タグ </content> が3記事の末尾に残っていた
  ・購読フォームが失敗すると、訪問者を素のエラー文だけのページへ飛ばしていた

いずれも原稿の検査では見つからない。出力された実物を読むしかない。

使い方:
    python scripts/live_check.py                 # 全サイトの主要ページ
    python scripts/live_check.py --site ai-lab
    python scripts/live_check.py --all           # sitemapの全URL（時間がかかる）

終了コード: 0=問題なし / 1=問題あり
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sites as sites_mod  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-livecheck/1.0)"}
VOID = {"br", "img", "hr", "input", "meta", "link", "source", "col",
        "area", "base", "embed", "wbr", "track", "param"}

# 社内向けの言葉。公開ページのソースに出てはいけない
INTERNAL = re.compile(
    r"TODO|FIXME|仮:|【仮】|後で|あとで|確認すること|差し替え|ダミー|"
    r"サンプル値|要修正|未確定|社内|ご本人の確認", re.I)


def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return r.status, r.read().decode("utf-8", "ignore"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception as e:
        return 0, f"__ERR__{type(e).__name__}", url


def post(url, body):
    """受け口が生きているかだけを見る。HTTPコードを返す"""
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={**UA, "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def tag_balance(html):
    """開始タグを積んで照合する。数を数えるだけだと、閉じ忘れと
    余分な閉じが相殺して見つからない"""
    src = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S)
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    stack, bad = [], []
    for m in re.finditer(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*?)(/?)>", src):
        close, name, self_ = m.group(1), m.group(2).lower(), m.group(4)
        if name in VOID or self_:
            continue
        if not close:
            stack.append(name)
        elif stack and stack[-1] == name:
            stack.pop()
        elif name in stack:
            while stack and stack[-1] != name:
                bad.append(f"<{stack.pop()}> が閉じられていない")
            stack.pop()
        else:
            bad.append(f"</{name}> に対応する開始タグが無い")
    return bad + [f"<{t}> が閉じられていない" for t in stack]


def check_page(url, html, status, final):
    out = []
    if status != 200:
        return [f"HTTP {status}"]
    if final.rstrip("/") != url.rstrip("/"):
        out.append(f"別のURLへ転送 → {final}")

    # 社内向けコメントがソースに残っていないか
    for c in re.findall(r"<!--(.*?)-->", html, re.S):
        if INTERNAL.search(c):
            out.append("社内向けコメントが残っている: " + " ".join(c.split())[:56])

    # コメントの閉じ漏れで本文に --> が出ていないか
    if re.search(r"(?<!-)-->", re.sub(r"<!--.*?-->", "", html, flags=re.S)):
        out.append("本文に --> が露出している")

    out += tag_balance(html)[:3]

    # 誤ってnoindexになっていないか
    rob = re.search(r'<meta[^>]+name="robots"[^>]+content="([^"]*)"', html, re.I)
    if rob and "noindex" in rob.group(1).lower():
        out.append("noindex が付いている")

    # 構造化データが壊れていないか
    for j in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            json.loads(j)
        except Exception as e:
            out.append(f"構造化データの構文エラー: {str(e)[:44]}")

    # フォームの送信先が実在するか（送信できないフォームは置いていないのと同じ）。
    # GETで確かめてはいけない。受け口は onRequestPost だけを持つため、
    # GETは404を返す。生きている受け口を「無い」と誤って報告することになる。
    base = re.match(r"(https?://[^/]+)", url).group(1)
    for act in sorted(set(re.findall(r'<form[^>]+action="([^"]+)"', html))):
        if not act.startswith("/"):
            continue
        # 必須項目を空で送る。受け口が生きていれば入力エラー（400）が返り、
        # リードは作られない
        st = post(base + act, b"name=&company=&email=")
        if st in (404, 405, 0):
            out.append(f"フォームの送信先が応答しない: {act}（POST HTTP {st}）")
        elif st >= 500:
            out.append(f"フォームの送信先がエラーを返す: {act}（POST HTTP {st}）")

    # 画像の参照切れ。1ページに何十枚もあるため、先頭6枚だけ見る
    base = re.match(r"(https?://[^/]+)", url).group(1)
    for src in sorted(set(re.findall(r'<img[^>]+src="(/[^"]+)"', html)))[:6]:
        st_i, _b, _f = fetch(base + src)
        if st_i != 200:
            out.append(f"画像が表示できない: {src}（HTTP {st_i}）")
    return out


def targets(site_id, all_urls):
    cfg = sites_mod.load(site_id)
    base = "https://" + cfg["domain"]
    if all_urls:
        st, body, _ = fetch(base + "/sitemap.xml")
        return re.findall(r"<loc>([^<]+)</loc>", body) if st == 200 else []
    # 主要ページ。人が最も見る場所と、CVに関わる場所を優先する
    paths = ["/", "/lp/", "/contact/", "/about/", "/diagnosis/aio/",
             "/diagnosis/meo/", "/site-audit/", "/blog/"]
    st, body, _ = fetch(base + "/sitemap.xml")
    locs = re.findall(r"<loc>([^<]+)</loc>", body) if st == 200 else []
    arts = [u for u in locs if u.count("/") >= 4][:5]     # 記事も数本見る
    return [base + p for p in paths] + arts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--all", action="store_true", help="sitemapの全URLを見る")
    a = ap.parse_args()

    ng = 0
    for sid, cfg in sites_mod.load_all().items():
        if a.site and sid != a.site:
            continue
        urls = targets(sid, a.all)
        print(f"■ {cfg['name']}（{len(urls)}ページ）", flush=True)
        checked = 0
        for u in urls:
            st, html, final = fetch(u)
            if html.startswith("__ERR__"):
                continue                      # 存在しない任意ページは飛ばす
            if st == 404:
                continue
            checked += 1
            probs = check_page(u, html, st, final)
            for p in probs:
                print(f"   NG {u.replace('https://' + cfg['domain'], '') or '/'}: {p}", flush=True)
            ng += len(probs)
        print(f"   {checked}ページを確認", flush=True)
    print(f"\nLIVE_CHECK={'ng' if ng else 'ok'}（問題 {ng}件）")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
