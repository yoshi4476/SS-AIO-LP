# -*- coding: utf-8 -*-
"""食い合いのゲート。ワークフローから機械的に呼ぶ

手順書に「必ず実行すること」と書いても、それは関門ではない。
実行を忘れれば素通りする。実際、タイトル類似だけのゲートを通り抜けて、
狙う範囲が8記事と重なり51語・表示484回でクリック0の記事ができた。

2箇所で止める。
  --before  執筆前。次に書くKWを管制塔から取り、着手可否を判定する
  --after   執筆後。実際に書かれた記事の keyword を判定する
            （書き手が別のKWを選んでも、ここで捕まる）

使い方:
    python scripts/kw_gate.py --before --site ai-lab
    python scripts/kw_gate.py --after  --site ai-lab

終了コード: 0=通過 / 1=着手禁止（食い合う）
"""
import argparse
import glob
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def judge(kw, site, exclude_slug=""):
    """kw_guard を呼んで着手可否を返す。(レベル, 出力)"""
    cmd = [sys.executable, str(ROOT / "scripts" / "kw_guard.py"), kw, "--site", site]
    if exclude_slug:
        cmd += ["--exclude-slug", exclude_slug]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def next_keyword(site):
    """次に書くKWを管制塔から取る。取れなければローカルの計画から"""
    try:
        import hub_client
        n = hub_client.next_kw(site)
        if isinstance(n, dict) and n.get("keyword"):
            return n["keyword"], "管制塔"
    except Exception as e:
        print(f"   （管制塔から取得できません: {type(e).__name__}）")
    try:
        import kw_status
        from cannibal_check import kw_conflicts, load_articles
        arts = load_articles()
        for _g, k in kw_status.plan_keywords():
            if not kw_conflicts(k, arts):
                return k, "ローカルの計画"
    except Exception:
        pass
    return "", ""


def published_html(slug):
    """site/<cat>/<slug>/index.html が git で追跡済みか（＝以前のコミットで世に出ている）"""
    r = subprocess.run(["git", "ls-files", "--", f"site/*/{slug}/index.html"],
                       capture_output=True, text=True, cwd=ROOT)
    return bool(r.stdout.strip())


def written_keyword(site):
    """この実行で新しく書かれた記事の keyword を拾う。

    「変更された記事」は含めない。公開済みの記事は内部リンクの追加などで
    毎日書き換わるため、変更を拾うと既存記事が新規として審査され、
    別ページが同じ語で順位を持っているという理由で隔離されてしまう。
    実際、公開中でランクインしていた10本がこれで隔離された。
    審査したいのは「これから世に出る記事」だけ。
    """
    def added(args):
        r = subprocess.run(args, capture_output=True, text=True, cwd=ROOT)
        return [l.strip() for l in r.stdout.splitlines()
                if l.strip().startswith("articles/") and l.strip().endswith(".md")]

    # 未コミットで新規に置かれたもの（?? = 追跡外 / A = 追加）
    r = subprocess.run(["git", "status", "--short", "articles/"],
                       capture_output=True, text=True, cwd=ROOT)
    files = [l[3:].strip() for l in r.stdout.splitlines()
             if l[:2].strip() in ("??", "A") and l.strip().endswith(".md")]
    if not files:
        # 直前のコミットで「追加」された記事だけ（変更や改名は見ない）
        files = added(["git", "show", "--name-only", "--diff-filter=A",
                       "--pretty=", "HEAD"])
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, cwd=ROOT).stdout.strip()
    out = []
    for f in files:
        p = ROOT / f
        if not p.is_file():
            continue
        # 以前のコミットに存在していた記事は、既に世に出ている。審査の対象外。
        # site/ はラボ専用なので、3サイトを等しく見られる git の履歴で判定する
        hist = subprocess.run(["git", "log", "--format=%H", "--follow", "--", f],
                              capture_output=True, text=True, cwd=ROOT).stdout.split()
        if hist and not (len(hist) == 1 and hist[0] == head):
            continue
        # 執筆と公開（build.py実行＋push）が同じコミットにまとまることがある。
        # その場合は履歴の深さでは新規に見えるが、ビルド済みHTMLが git で
        # 追跡済み＝もう世に出ている。審査の対象外にする。
        # ファイルの有無では判定しない。この実行の build.py が作ったばかりの
        # HTMLまで「公開済み」に見え、新記事が審査を素通りする
        if published_html(p.stem):
            continue
        fm = p.read_text(encoding="utf-8-sig").split("---", 2)[1]
        kw = (re.search(r"^keyword:\s*(.+)$", fm, re.M) or [0, ""])[1].strip()
        if kw:
            out.append((p.stem, kw))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--before", action="store_true")
    ap.add_argument("--after", action="store_true")
    a = ap.parse_args()

    if a.before:
        # 食い合うKWで止まって終わり、では記事が出ない。
        # 食い合う候補は台帳から「対象外」へ退避し、通るKWが出るまで次を探す。
        tried = []
        for _ in range(8):
            kw, src = next_keyword(a.site)
            if not kw or kw in tried:
                break
            tried.append(kw)
            print(f"候補: 「{kw}」（{src}）")
            level, out = judge(kw, a.site)
            print("\n".join("   " + l for l in out.strip().splitlines()))
            # 3（判定不能）は GSC を読めなかっただけ。食い合いとして台帳から退避すると、
            # 鍵が切れた日に未着手の語を次々と捨てる。従来（1として扱っていた頃）どおり進める
            if level == 3:
                print("   食い合いの検査が動きませんでした（鍵・通信を確認）。語だけの審査で進めます")
            if level < 2 or level == 3:
                print(f"\n次に書くKW: 「{kw}」")
                print("KW_GATE=ok")
                return 0
            # 担当領域の外の語は、食い合いと書かずに理由を残す（台帳の掃除の記録になる）。
            # 通常は next_kw が先に飛ばすので、ここに来るのは台帳の一覧を読めなかった日だけ
            import kw_fit
            fit, why = kw_fit.judge(kw, a.site)
            reason = (f"担当領域の外（kw_fit: {why}）" if fit >= 2
                      else "既存ページと食い合うため自動退避（kw_gate）")
            try:
                import hub_client
                r = hub_client.retire_kw(a.site, [kw], reason) or {}
            except Exception as e:
                r = {"ok": False, "error": type(e).__name__}
            if not r.get("ok"):
                # 外せないまま次を取ると同じ語が返り、1件で「全部食い合う」と誤って止まる。
                # 管制塔は読むだけなら合言葉なしで通るので、書き込みだけ弾かれる形で現れる
                print(f"   → 台帳から外せませんでした（{r.get('error') or '応答なし'}）")
                print("KW_GATE=block")
                print("要対応: 管制塔の台帳を書き換えられません。GitHub Secrets の HUB_SECRET が"
                      "管制塔の合言葉と一致しているか確かめてください")
                return 1
            print("   → 台帳から退避しました。次の候補を探します\n")
        if not tried:
            print("次のKWを取得できませんでした。KW台帳の補充が必要です")
            print("KW_GATE=skip")
            return 0
        print("KW_GATE=block")
        print(f"{len(tried)}件の候補がすべて既存ページと食い合います。台帳の補充が必要です")
        return 1

    if a.after:
        # 書き手が別のKWを選ぶことがある。実際に書かれたものを見る。
        # 検査では必ず自分自身を除く。書いた記事はもうディスクにあるため、
        # 除かないと全記事が「自分と完全一致」で止まる（実際に正当な3本を止めた）。
        pairs = written_keyword(a.site)
        if not pairs:
            print("この実行で追加された記事はありません")
            print("KW_GATE=skip")
            return 0
        import kw_fit
        ng = []
        for slug, kw in pairs:
            level, out = judge(kw, a.site, exclude_slug=slug)
            print(f"■ {slug}（狙う語「{kw}」）")
            print("\n".join("   " + l for l in out.strip().splitlines()[-4:]))
            # 3（判定不能）で隔離すると、GSC を読めない日に正当な記事まで公開から外れる
            if level == 3:
                print("   食い合いの検査が動きませんでした（鍵・通信を確認）。隔離はしません")
            # 書き手が台帳と違う語を選んでも、担当領域の外の記事は世に出さない
            fit, why = kw_fit.judge(kw, a.site)
            if fit >= 2:
                print(f"   担当領域の外: {why}")
                ng.append((slug, kw, f"担当領域の外（kw_fit: {why}）"))
            elif level == 2:
                ng.append((slug, kw, "既存ページと食い合うため隔離（kw_gate）"))
        if not ng:
            print("\nKW_GATE=ok")
            return 0
        # 本物の食い合いは、その記事だけを隔離して残りは公開させる。
        # 全体を落とすと、問題のない記事まで巻き添えで消える
        qdir = ROOT / "articles" / "_conflicted"
        qdir.mkdir(exist_ok=True)
        for slug, kw, reason in ng:
            src = ROOT / "articles" / f"{slug}.md"
            if src.is_file():
                src.replace(qdir / f"{slug}.md")
            print(f"  隔離: {slug}（「{kw}」: {reason}）")
            try:
                import hub_client
                hub_client.retire_kw(a.site, [kw], reason, force=True)
            except Exception:
                pass
        print("\nKW_GATE=quarantined")
        print("食い合う・担当領域の外の記事は articles/_conflicted/ へ移しました。残りは公開できます")
        return 0

    ap.error("--before か --after のどちらかを指定してください")


if __name__ == "__main__":
    sys.exit(main())
