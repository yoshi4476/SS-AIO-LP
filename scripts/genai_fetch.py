# -*- coding: utf-8 -*-
"""Search Console の「生成AIのパフォーマンス」を、ブラウザで開いて先月ぶんを落とす。

API が無い（Search Console API の type にも GA4 の指標にも AI 分の内訳が無い。2026-10 確認）ため、
人が毎月3サイトぶん画面から落としていた。その操作を、このPCの専用ブラウザに代わりにやらせる。

    python scripts/genai_fetch.py --login     # 最初の1回だけ。開いたブラウザで Google にログインする
    python scripts/genai_fetch.py             # 先月ぶんを3サイト落として取り込む（月初のタスクが呼ぶ）
    python scripts/genai_fetch.py --explore   # 画面の構成が変わったときの調べ用（左メニューのリンクを出す）

ログインの状態は専用のプロファイル（%LOCALAPPDATA%/ss-gsc-profile）に残り、ふだんの Chrome とは混ざらない。
パスワードはこのスクリプトもリポジトリも持たない。ログインが切れたら要対応として知らせる。
落としたファイルは genai_import.ingest が取り込み（サイトはURL、月は日付の表から決める）、git へ反映する。
"""
import argparse
import os
import sys
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
PROFILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ss-gsc-profile"
OUT = ROOT / "automation" / "logs" / "genai_dl"
GSC = "https://search.google.com/search-console"


def last_month():
    first = date.today().replace(day=1)
    end = first - timedelta(days=1)
    return end.replace(day=1), end


def browser(p, headless):
    PROFILE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    kw = dict(user_data_dir=str(PROFILE), headless=headless, accept_downloads=True, downloads_path=str(OUT),
              locale="ja-JP", args=["--disable-blink-features=AutomationControlled"])
    # Chrome 本体（channel="chrome"）は 154 でダウンロードの完了直前に落ちた（2026-10-01）。
    # Playwright 同梱の Chromium なら同じプロファイルのまま最後まで保存できる
    return p.chromium.launch_persistent_context(**kw)


def logged_in(page):
    page.goto(GSC, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    return "accounts.google.com" not in page.url and "/about" not in page.url


def login():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = browser(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(GSC, wait_until="domcontentloaded")
        print("開いたブラウザで、Search Console を見ている Google アカウントにログインしてください（最大10分待ちます）")
        for _ in range(120):
            page.wait_for_timeout(5000)
            if "search-console" in page.url and "accounts.google.com" not in page.url and "/about" not in page.url:
                print("ログインできました。このブラウザは閉じてかまいません")
                ctx.close()
                return 0
        ctx.close()
    print("ログインを確認できませんでした")
    return 1


def resource(cfg):
    return urllib.parse.quote(f"https://{cfg['domain']}/", safe="")


def explore():
    import sites as S
    from playwright.sync_api import sync_playwright
    cfg = next(iter(S.load_all().values()))
    with sync_playwright() as p:
        ctx = browser(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"{GSC}?resource_id={resource(cfg)}", wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        for a in page.query_selector_all("a[href]"):
            t, h = (a.inner_text() or "").strip(), a.get_attribute("href")
            if t and "search-console" in (h or ""):
                print(f"  {t[:30]:<30} {h[:140]}")
        ctx.close()
    return 0


def genai_url(page, cfg):
    """生成AIレポートのURL。左メニューには無く、検索パフォーマンスの中の /search-analytics/ai にある
    （2026-10 の画面）。移ったときに備え、検索パフォーマンスの画面のリンクからも探す"""
    known = f"{GSC}/performance/search-analytics/ai?resource_id={resource(cfg)}"
    page.goto(known, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    if "/search-analytics/ai" in page.url:
        return known
    page.goto(f"{GSC}/performance/search-analytics?resource_id={resource(cfg)}", wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    for h in page.eval_on_selector_all("a[href]", "as => as.map(a => a.href)"):
        if "/search-analytics/ai" in h or "generative" in h.lower():
            return h
    return ""


def fetch_one(page, cfg, start, end):
    url = genai_url(page, cfg)
    if not url:
        return None, "生成AIレポートが見つかりません（データが無いか、画面が変わった）"
    import re
    sep = "&" if "?" in url else "?"
    page.goto(f"{url}{sep}start_date={start:%Y%m%d}&end_date={end:%Y%m%d}", wait_until="domcontentloaded")
    page.wait_for_timeout(8000)
    page.locator("[role=button],button").filter(has_text=re.compile("エクスポート")).first.click()
    page.wait_for_timeout(1500)
    with page.expect_download(timeout=60000) as dl:
        page.get_by_text(re.compile("CSV.*ダウンロード")).first.click()
    d = dl.value
    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / d.suggested_filename
    d.save_as(str(dst))
    return dst, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--explore", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--headed", action="store_true", help="画面を出して動かす（調べ用）")
    ap.add_argument("--month", default="", help="先月以外の月を取る（YYYY-MM。過去分の取り直し用）")
    a = ap.parse_args()
    if a.login:
        return login()
    if a.explore:
        return explore()

    import sites as S
    import genai_import as G
    from playwright.sync_api import sync_playwright
    start, end = last_month()
    if a.month:
        start = date(int(a.month[:4]), int(a.month[5:7]), 1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    print(f"■ 生成AIレポートの取得 {start}〜{end}")
    # タスクは毎日動く。先月ぶんがそろっているサイトは開かない（そろうまで毎日やり直す形）
    have = G.load().get(f"{start:%Y-%m}", {})
    todo = {sid: cfg for sid, cfg in S.load_all().items() if sid not in have}
    if not todo:
        print("  先月ぶんは全サイト取り込み済みです")
        print("GENAI_FETCH=ok")
        return 0
    got = []
    with sync_playwright() as p:
        ctx = browser(p, headless=not a.headed)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not logged_in(page):
            ctx.close()
            print("要対応: Search Console のログインが切れています。`python scripts/genai_fetch.py --login` を実行してください")
            print("GENAI_FETCH=login")
            return 0
        for sid, cfg in todo.items():
            try:
                f, why = fetch_one(page, cfg, start, end)
            except Exception as e:
                f, why = None, str(e)[:120]
            if not f:
                if "not-verified" in page.url:
                    why = "このアカウントに閲覧権限がありません（Search Console の設定 → ユーザーと権限で追加）"
                print(f"  × {sid}: {why[:160]}")
                got.append(False)
                continue
            ok, msg = G.ingest(f)
            print(f"  {'○' if ok else '×'} {msg}")
            got.append(ok)
        ctx.close()
    if any(got) and not a.no_push:
        import subprocess
        run = lambda *c: subprocess.run(c, cwd=ROOT, capture_output=True, text=True)
        run("git", "add", str(G.STORE.relative_to(ROOT)))
        run("git", "commit", "-m", f"生成AIレポートを取り込む（{start:%Y-%m}・自動取得）")
        run("git", "pull", "--rebase", "--autostash")
        r = run("git", "push")
        print("  反映しました" if r.returncode == 0 else f"  反映できませんでした: {r.stderr[:120]}")
    status = 'ok' if got and all(got) else 'partial' if any(got) else 'none'
    if status != "ok":
        print("要対応: 生成AIレポートを取れないサイトがあります（上の × を参照）")
    print(f"GENAI_FETCH={status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
