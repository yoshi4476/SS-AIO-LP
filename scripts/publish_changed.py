# -*- coding: utf-8 -*-
"""変更された記事をまとめて配信する

publish.py は1記事ずつしか配信できない。パイプラインもその日に書いた
新記事1本しか配信しないため、既存記事に加筆しても本番へ届かない。
実際、リライトした60本が手元に残ったままになっていた。

週次のリライトでも同じことが起きるので、差分から拾って配信する。

使い方:
    python scripts/publish_changed.py --site corporate            # 対象を出すだけ
    python scripts/publish_changed.py --site corporate --push     # 実際に配信
    python scripts/publish_changed.py --all --push                # 全サイト
    python scripts/publish_changed.py --site corporate --since HEAD~30

既定では、配信先リポジトリにある本文と手元の本文を突き合わせて、
中身が変わっているものだけを配信する。gitの履歴に頼らないので、
どこまで配信したかを覚えておく必要がない。
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import publish as P  # noqa: E402
import sites as sites_mod  # noqa: E402

def failure_line(failed):
    """配信に落ちた記事の「要対応」の1行（呼び出し側のワークフローが findings.txt へ足す）。
    週次・集中モード・月次は `|| true` で呼び、--since でその回に直した分だけを送る。
    落ちた記事は次に原稿が変わるまで送られず、印も通知も無いため誰も気づかなかった（2026-10-07 の点検）"""
    if not failed:
        return ""
    failed, sites = masked(failed)
    return (f"要対応: 書き直した記事のうち {len(failed)}本が配信先に届いていません"
            f"（{'、'.join(failed[:4])}{' ほか' if len(failed) > 4 else ''}）。"
            + "・".join(f"python scripts/publish_changed.py --site {s} --push" for s in sites)
            + " で送り直してください（--since なしでも push されるのは本文の変わった記事だけ）")


def site_articles(site_id):
    """そのサイトが担当する記事を返す（公開基準を満たすものだけ）"""
    out = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        if p.name.startswith("_"):
            continue
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)
        cat = (re.search(r"^category:\s*(\S+)", fm, re.M) or [0, ""])[1]
        if sites_mod.find_category_owner(cat) != site_id:
            continue
        # 観点の足切りまで見る（score だけだと、build.py が止める記事を配信してしまう）
        meta = P.read_meta(p)
        if not meta or not P.gate_ok(meta):
            continue
        out.append(p.stem)
    return out


def changed_by_git(site_id, since):
    """gitの差分から、変更された記事を拾う"""
    r = subprocess.run(["git", "diff", "--name-only", since, "--", "articles/"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    touched = {Path(l).stem for l in r.stdout.splitlines() if l.endswith(".md")}
    # お客様の社の記事は公開側の git に無い（非公開のリポジトリ）。この回に書いた・直した分を合わせる
    import private_store
    touched |= {Path(x).stem for x in private_store.client_changes()
                if x.startswith("articles/") and x.endswith(".md") and x.count("/") == 1}
    return [s for s in site_articles(site_id) if s in touched]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--all", action="store_true", help="全サイトを対象にする")
    ap.add_argument("--since", default="", help="この地点からの差分だけを見る（例: HEAD~30）")
    ap.add_argument("--push", action="store_true", help="実際に配信する")
    ap.add_argument("--limit", type=int, default=0, help="1回に配信する本数の上限")
    a = ap.parse_args()

    ids = list(sites_mod.load_all()) if a.all else ([a.site] if a.site else [])
    if not ids:
        ap.error("--site か --all を指定してください")

    total_ok = total_ng = 0
    failed = []         # 届かなかった記事（社/slug）。打ち切った残りも含める
    for sid in ids:
        cfg = sites_mod.load(sid)
        if cfg["type"] == "self-static":
            print(f"■ {cfg['name']}: 本リポジトリのサイトです（build.py が担当）")
            continue

        targets = changed_by_git(sid, a.since) if a.since else site_articles(sid)
        if a.limit:
            targets = targets[:a.limit]
        print(f"■ {public_name(sid) if is_client(sid) else cfg['name'] + '（' + (cfg.get('repo') or cfg['type']) + '）'}: 対象 {len(targets)}本")
        if not a.push:
            for s in targets[:12]:
                print(f"     {shown(s)}")
            if len(targets) > 12:
                print(f"     …ほか{len(targets) - 12}本")
            continue

        ok = ng = gated = 0
        miss = 0        # 続けて落ちた数（環境の問題だけ。門で止まった記事は数えない）。1本の失敗で残り全部を諦めない
        for i, slug in enumerate(targets, 1):
            # 配信先は push のたびに自分のビルドが書き戻すことがあり、続けて push すると
            # 先に進まれて1本おきに落ちた（2026-09-28: 補助金47本中17本。単発では全部通った）。
            # 落ちたら少し待って1回だけやり直す
            for attempt in range(2):
                r = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "publish.py"),
                     "--site", sid, "--slug", slug, "--push"],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", cwd=ROOT)
                if r.returncode == 0 or attempt or gate_blocked((r.stdout or "") + (r.stderr or ""), sid):
                    break
                time.sleep(20)
            out = (r.stdout or "") + (r.stderr or "")
            why = out.strip().splitlines()
            line = (why[-1][:70] if why else "原因不明").replace(slug, shown(slug))
            if r.returncode == 0:
                ok += 1
                miss = 0
                print(f"   [{i}/{len(targets)}] ○ {shown(slug)}", flush=True)
            elif gate_blocked(out, sid):
                # 記事の中身で止まった（直すまで何度送っても同じ）。届いていないので失敗に数えるが、環境の問題には数えない
                ng += 1
                gated += 1
                failed.append(f"{sid}/{slug}")
                print(f"   [{i}/{len(targets)}] × {shown(slug)}: 門で止まりました"
                      + ("" if is_client(sid) else f"（{line}）"), flush=True)
            else:
                ng += 1
                miss += 1
                failed.append(f"{sid}/{slug}")
                print(f"   [{i}/{len(targets)}] × {shown(slug)}: {'配信できませんでした' if is_client(sid) else line}",
                      flush=True)
                # 1本落ちただけで残りを諦めない。配信先が一時的に進んでいるなど、
                # 次の1本では通ることが多い（79本中18本で止まり、単発では通った）。
                # 続けて落ちるときだけ、環境の問題とみなして止める。
                if miss >= 3:
                    print("   → 3本続けて失敗しました。環境の問題とみなして中断します")
                    print("      python scripts/token_check.py で権限を確かめてください")
                    failed += [f"{sid}/{s}" for s in targets[i:]]
                    break
        print(f"   配信 {ok}本 / 失敗 {ng}本" + (f"（うち門で止まった {gated}本）" if gated else "") + "\n")
        total_ok += ok
        total_ng += ng

    if a.push:
        print(f"PUBLISH_CHANGED: 成功 {total_ok}本 / 失敗 {total_ng}本")
        if failed:
            print(failure_line(failed))
    else:
        print("※ --push を付けると実際に配信します")
    return 1 if total_ng else 0


# publish.py が記事の中身で止めたときに出す印（どれも何度送っても同じ結果になる）。待ってやり直す・「3本続けて失敗」に
# 数えると、門で止まった記事が3本並んだだけで残りの配信を「環境の問題」として打ち切り、1本ごとに20秒待っていた
# （2026-10-20 の点検）。印は publish.main の SystemExit の文の頭。下に置くのは、配信の仕組みの表（data/capabilities.json）が
# この道具の行番号を根拠にしているため
GATE_MARKS = ("BLOCKED(", "HELD(", "公開基準未達のため配信しません", "git の衝突マーカーが原稿に残っています",
              "当社の採択率・支援社数、または申請書類の作成・代行と読める文があります", "は {} に定義されていません")


def gate_blocked(out, sid=""):
    """publish.py の出力が、記事の中身による門の止め（環境の問題ではない）か"""
    return any((m.format(sid) if "{}" in m else m) in out for m in GATE_MARKS)


def is_client(sid):
    """お客様の社か（ログで社名・slug を伏せるため）。社の一覧に問い合わせられなければ自社とみなす"""
    f = getattr(sites_mod, "is_client", None)
    return bool(f and f(sid))


def public_name(sid):
    f = getattr(sites_mod, "public_id", None)
    return f(sid) if f else sid


def shown(slug):
    """CI のログ（public）に出す記事の名前。お客様の記事は slug を出さない"""
    import private_store
    return private_store.shown(slug)


def masked(failed):
    """届かなかった記事（社/slug）と社の一覧。お客様の社は公開の id・記事は slug を伏せる（findings と CI のログに出る）"""
    out = [f"{public_name(s)}/{shown(x)}" if is_client(s) else f"{s}/{x}" for s, x in (e.split("/", 1) for e in failed)]
    return out, sorted({public_name(s) if is_client(s) else s for s in (e.split("/", 1)[0] for e in failed)})


if __name__ == "__main__":
    sys.exit(main())
