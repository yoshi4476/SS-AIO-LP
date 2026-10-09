# -*- coding: utf-8 -*-
"""IndexNow即時通知（Phase 7 / 週次リライト後に実行）

使い方: python scripts/notify_indexnow.py <URL> [<URL> ...]
        引数なしの場合は sitemap.xml の全URLを通知
        python scripts/notify_indexnow.py --site <id>   # その社の本日公開・更新の記事だけ（記事CIの公開直後）
前提: .env に INDEXNOW_KEY を設定し、site/{KEY}.txt を配置していること

処理はすべて main() の中に置く。モジュールの直下に書くと、他のスクリプトが
`import notify_indexnow` した瞬間に外部へ送信が飛ぶ（実際、検査のために
読み込んだだけで136件を送ってしまった）。
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    p = ROOT / ".env"
    if not p.exists():
        return {}
    return dict(l.split("=", 1) for l in p.read_text(encoding="utf-8-sig").splitlines()
                if "=" in l and not l.strip().startswith("#"))


def find_key(env):
    key = env.get("INDEXNOW_KEY", "").strip()
    if key and "YOUR_" not in key:
        return key
    # .envがない環境（GitHub Actions等）ではsite/直下のキーファイル名から自動検出
    # （IndexNowキーは公開URLに置く仕様のため秘匿不要）
    for f in (ROOT / "site").glob("*.txt"):
        if re.fullmatch(r"[0-9a-f]{16,64}", f.stem) and f.read_text().strip() == f.stem:
            return f.stem
    return ""


def sitemap_urls(domain=None):
    """公開中の sitemap。他サイトは手元に無いのでHTTPで取る"""
    if domain is None:
        sm = (ROOT / "site" / "sitemap.xml").read_text(encoding="utf-8")
        return re.findall(r"<loc>(.*?)</loc>", sm)
    try:
        import urllib.request as _u
        req = _u.Request(f"https://{domain}/sitemap.xml", headers={"User-Agent": "Mozilla/5.0"})
        with _u.urlopen(req, timeout=30) as r:
            return re.findall(r"<loc>(.*?)</loc>", r.read().decode("utf-8", "ignore"))
    except Exception as e:
        print(f"  {domain}: sitemapを取得できません（{str(e)[:50]}）")
        return []


def key_for(domain, key):
    """そのドメインで公開している鍵。先方が自分の鍵を既に置いている社は sites/<id>.json の indexnow_key。
    お客様の社は先方の鍵が直下で返るのに、共通の鍵で確かめて毎回「鍵ファイルが出ていません」と
    出していた（2026-10-08）。IndexNow は host ごとに別の鍵でよい"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import sites as S
    dom = domain.split("//", 1)[-1].strip("/").lower()
    for c in S.load_all().values():
        if (c.get("domain") or "").lower() == dom and c.get("indexnow_key"):
            return c["indexnow_key"]
    return key


def key_ok(domain, key):
    """鍵ファイルが置かれているか。無いドメインへの通知は拒否される（実際にそうなっていた）"""
    try:
        import urllib.request as _u
        req = _u.Request(f"https://{domain}/{key}.txt", headers={"User-Agent": "Mozilla/5.0"})
        with _u.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "ignore").strip() == key
    except Exception:
        return False


def by_host(urls):
    """URL をドメインごとに束ねる（IndexNow は1回の送信で1つの host しか受け付けない）"""
    out = {}
    for u in urls:
        p = urllib.parse.urlsplit(u.strip())
        out.setdefault(f"{p.scheme or 'https'}://{p.netloc}", []).append(u.strip())
    return out


def notify(urls, key, site_url):
    payload = json.dumps({"host": site_url.split("//", 1)[-1].strip("/"), "key": key,
                          "keyLocation": f"{site_url}/{key}.txt",
                          "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        return res.status


def recent_urls(cfg):
    """本日公開・更新した記事のうち、本番の sitemap に載っているもの（記事CIの公開直後に1社分だけ送る）"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import notify_indexing as NX
    known = {u.rstrip("/") + "/" for u in NX.sitemap_of(cfg)}
    return [u for u in NX.todays_urls(cfg) if u.rstrip("/") + "/" in known]


def main(argv=None, cfgs=None):
    """全サイトに通知する。以前は AI集客ラボ だけを見ていたため、
    コーポレートと補助金は記事を出しても検索エンジンに知らせていなかった。
    --site <id> は記事CIの公開直後の分（その社の本日の記事だけ。お客様の社も同じ）"""
    argv = list(sys.argv[1:] if argv is None else argv)
    only = ""
    if "--site" in argv:
        i = argv.index("--site")
        only = argv[i + 1] if len(argv) > i + 1 else ""
        argv = argv[:i] + argv[i + 2:]
    env = load_env()
    key = find_key(env)
    if not key:
        raise SystemExit("INDEXNOW_KEY が未設定です（.env または site/{KEY}.txt を設置してください）")
    if argv:
        # host は URL のドメインから決める。SITE_URL 固定だと、補助金サイトの URL を
        # host=ai.7senses.co.jp で送って HTTP 422 になっていた（2026-09-26）
        for site_url, urls in by_host(argv).items():
            status = notify(urls, key_for(site_url, key), site_url)
            print(f"IndexNow通知: {site_url} {len(urls)}件 → HTTP {status}")
        return 0
    sys.path.insert(0, str(ROOT / "scripts"))
    import sites as S
    sent, base_key = 0, key
    cfgs = S.load_all() if cfgs is None else cfgs
    for sid, cfg in cfgs.items():
        if only and sid != only:
            continue
        dom = cfg["domain"]
        key = cfg.get("indexnow_key") or base_key
        wp = cfg.get("type") == "wordpress"
        if wp and not key_ok(dom, key):
            # WordPress は鍵ファイルを置けない。先方の mu-plugin に鍵を渡すと、/<鍵>.txt を返すようになる
            import wp_bridge
            try:
                wp_bridge.push_settings(cfg)
            except SystemExit as e:
                print(f"  {sid}: 橋渡しへ鍵を渡せません（{str(e)[:60]}）")
        if not key_ok(dom, key):
            print(f"  {sid}: 鍵ファイル https://{dom}/{key}.txt がありません（通知は拒否されます）")
            if only and S.is_client(sid):
                # 鍵ファイルは配信と一緒に置いている（search_connect.place・WordPress は橋渡し）。出ていなければ置き場が違う
                print(f"要対応: {cfg.get('name', sid)} の IndexNow の鍵ファイル https://{dom}/{key}.txt が出ていません"
                      "（配信先の公開フォルダの直下に置かれているか確かめてください）")
            continue
        if only:
            urls = recent_urls(cfg)
        elif wp:
            import wp_bridge
            urls = wp_bridge.site_urls(cfg)
        else:
            urls = sitemap_urls(None if sid == S.primary() else dom)
        if not urls:
            if only:
                print(f"  {sid}: 通知対象なし（本日の記事が本番の sitemap にまだありません）")
            continue
        try:
            status = notify(urls, key, f"https://{dom}")
        except Exception as e:
            print(f"  {sid}: 通知に失敗（{str(e)[:60]}）")
            continue
        sent += len(urls)
        print(f"  {sid}: {len(urls)}件 → HTTP {status}")
    print(f"IndexNow通知: 合計{sent}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
