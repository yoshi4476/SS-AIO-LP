# -*- coding: utf-8 -*-
"""公開リポジトリ（管制塔）の CI のログに、お客様の守秘の語（社名・ドメイン・記事の題・slug）が出ていないかを数える（週次）。

管制塔は public で、CI のログは誰でも読める（2026-10-11 から保存14日）。2026-10-11 に手で直近400回を調べたら、
10/09〜10/10 の16回にお客様の社の記事の名前・題・ドメインが出ていた。門はコードを読むだけなので、新しく足した工程が
同じことをしても見つからない。そこで毎週、実際のログを取って数える（findings.py が呼び、出たら要対応）。

  python scripts/log_leak_check.py                    # 直近8日の完了した回
  python scripts/log_leak_check.py --days 2 --max-runs 100

数えない回: 2026-10-11 0時（日本時間）より前に作られた回（直す前の回は把握済み。毎週同じものを知らせ続けないため）と、
中身の無い skipped の回。照らす語は門 gates_history_h77 と同じ（ci_mask.identity_terms）で、4文字以上の語だけ。

出力は回ごとに「日付・ワークフロー名・run id・公開の id・件数・種類（domain / name・title・slug）」だけ。
語そのもの・該当行は出さない（この出力も CI のログ）。最後の行が LOG_LEAK_OK=yes|no|unknown。
非公開のデータが無い・API に失敗した・対象の回が0回は unknown（「問題なし」にしない）。
見つかっても終了コードは0、検査が動かなければ1（CLAUDE.md 8.7）。

鍵（actions: read）: LOG_LEAK_GH_TOKEN → GH_TOKEN → GITHUB_TOKEN → 手元は gh auth token。週次は LOG_LEAK_GH_TOKEN で渡す
（GH_TOKEN にすると、同じ工程のほかの検査の gh の動きまで変わる）。
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

REPO = "yoshi4476/SS-AIO-LP"
API = "https://api.github.com"
JST = timezone(timedelta(hours=9))
FLOOR = datetime(2026, 10, 11, tzinfo=JST)
MIN_LEN = 4
# 1回ずつ gh run view --log で取ると400回で約25分かかった。zip を並べて取る
WORKERS = 8
# findings は1検査を900秒で打ち切る。その前に自分で止めて、調べた分だけで判定する
BUDGET = 600
# GITHUB_TOKEN は1時間1,000回まで（リポジトリごと）。8日分のログは約730回になるので、同じ時間に動くほかの工程
# （自動修復・配信）の分を残し、足りなければ古い回を調べない（調べなかった回が多ければ unknown）
RESERVE = 200
TOKEN_ENVS = ("LOG_LEAK_GH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
DOMAIN, OTHER = "domain", "name・title・slug"
# 英数の語は、前後が英数・-・_ でないときだけ数える（別の slug・別のドメインの一部を拾わない）
EDGE = "A-Za-z0-9_-"


def patterns(ident):
    """{社の id: (探す正規表現, {語の小文字: 種類})}。ident は ci_mask.identity_terms() の形"""
    out = {}
    for sid, (names, arts, dom) in ident.items():
        kinds = {}
        for w, kind in ([(w, DOMAIN if "." in w else OTHER) for w in names] + [(w, OTHER) for w in arts]
                        + ([(dom, DOMAIN)] if dom else [])):
            w = str(w).strip()
            if len(w) >= MIN_LEN:
                kinds.setdefault(w.lower(), kind)
        if not kinds:
            continue
        # 長い語を先に試す（URL とその中のドメインを1か所として数える）
        alts = [rf"(?<![{EDGE}]){re.escape(w)}(?![{EDGE}])" if w.isascii() else re.escape(w)
                for w in sorted(kinds, key=len, reverse=True)]
        out[sid] = (re.compile("|".join(alts), re.I), kinds)
    return out


def scan(text, pats):
    """{社の id: (件数, 種類の集合)}。当たった社だけ"""
    out = {}
    for sid, (rx, kinds) in pats.items():
        n, ks = 0, set()
        for m in rx.finditer(text):
            n += 1
            ks.add(kinds.get(m.group(0).lower(), OTHER))
        if n:
            out[sid] = (n, ks)
    return out


def scan_zip(data, pats):
    """ログの zip を数える。中身はジョブごとの全文（<n>_<ジョブ>.txt）と、同じ中身を工程ごとに分けたもの
    （<ジョブ>/<n>_<工程>.txt）。全文があればそれだけを読む（両方読むと同じ行を2回数える）"""
    z = zipfile.ZipFile(io.BytesIO(data))
    files = [i for i in z.infolist() if not i.is_dir()]
    top = [i for i in files if "/" not in i.filename]
    total = {}
    for i in top or files:
        for sid, (n, ks) in scan(z.read(i).decode("utf-8", "replace"), pats).items():
            pn, pks = total.get(sid, (0, set()))
            total[sid] = (pn + n, pks | ks)
    return total


def _token():
    for k in TOKEN_ENVS:
        if os.environ.get(k):
            return os.environ[k]
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _get(url, token, timeout=60):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "X-GitHub-Api-Version": "2022-11-28",
                                               "User-Agent": "ss-aio-log-leak-check"})
    # ログの本体は別のホストへ転送される。鍵は GitHub にだけ渡し、転送先へ持ち越さない
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_runs(repo, token, since, until):
    """since 以降に作られた完了した回（新しい順）。created で絞ると1回の問い合わせで1,000件までしか返らない
    （8日で1,410回あった）ため、1日ずつ（多ければ半分ずつ）に分けて聞く"""
    runs, seen = [], set()

    def window(a, b):
        page = 1
        while True:
            q = urllib.parse.urlencode({"status": "completed", "per_page": 100, "page": page,
                                        "exclude_pull_requests": "true", "created": f"{_iso(a)}..{_iso(b)}"})
            d = json.loads(_get(f"{API}/repos/{repo}/actions/runs?{q}", token))
            if page == 1 and int(d.get("total_count") or 0) > 1000 and b - a > timedelta(hours=1):
                mid = a + (b - a) / 2
                window(a, mid)
                window(mid, b)
                return
            got = d.get("workflow_runs") or []
            for r in got:
                if r["id"] not in seen:
                    seen.add(r["id"])
                    runs.append(r)
            if len(got) < 100 or page >= 10:
                return
            page += 1

    t = since
    while t < until:
        window(t, min(t + timedelta(days=1), until))
        t += timedelta(days=1)
    return sorted(runs, key=lambda r: r.get("created_at") or "", reverse=True)


def remaining(token):
    """API の残りの回数（/rate_limit はこの回数に数えない）。読めなければ None"""
    try:
        return int(json.loads(_get(f"{API}/rate_limit", token, timeout=30))["resources"]["core"]["remaining"])
    except Exception:
        return None


def fetch_log(repo, token, run_id):
    return _get(f"{API}/repos/{repo}/actions/runs/{run_id}/logs", token, timeout=120)


def _one(run, repo, token, pats, deadline):
    """(ok|nolog|fail|late, 当たり)"""
    for attempt in range(2):
        if time.monotonic() > deadline:
            return "late", {}
        try:
            data = fetch_log(repo, token, run["id"])
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):          # ログが無い（期限切れ・ジョブの無い回）
                return "nolog", {}
            if attempt:
                return "fail", {}
            time.sleep(2)
            continue
        except (urllib.error.URLError, OSError):
            if attempt:
                return "fail", {}
            time.sleep(2)
            continue
        try:
            return "ok", scan_zip(data, pats)
        except zipfile.BadZipFile:
            return "fail", {}
    return "fail", {}


def _when(run):
    try:
        return datetime.fromisoformat(str(run.get("created_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _wf_name(run):
    """ワークフローの名前は yml の name から取る（回の名前は入力から作られることがあるので出さない）"""
    rel = str(run.get("path") or "")
    try:
        m = re.search(r"^name:\s*[\"']?(.+?)[\"']?\s*$", (ROOT / rel).read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    return Path(rel).name or "（不明）"


def _end(state, rc):
    print(f"LOG_LEAK_OK={state}")
    return rc


def check(days=8, max_runs=400, repo=REPO, now=None, budget=BUDGET, ident=None, token=None):
    """数えて出力し、終了コードを返す。ident・token は門が差し替える"""
    import sites as S
    now = now or datetime.now(timezone.utc)
    if ident is None:
        import private_store as PS
        if not PS.available():
            print("非公開のデータ（private/）が無いため、照らす語を作れません（手元は python scripts/private_store.py --fetch）")
            return _end("unknown", 1)
        import ci_mask as M
        ident = M.identity_terms()
    pats = patterns(ident)
    if not pats:
        print("照らす語がありません（お客様の社の設定が非公開のデータから読めない）")
        return _end("unknown", 1)
    token = token or _token()
    if not token:
        print("GitHub の鍵がありません（LOG_LEAK_GH_TOKEN・GH_TOKEN・GITHUB_TOKEN。手元は gh auth login）")
        return _end("unknown", 1)
    since = max(now - timedelta(days=days), FLOOR)
    try:
        runs = list_runs(repo, token, since, now)
    except Exception as e:                  # 鍵の値は例外の文に入らない
        print(f"回の一覧を読めません（{type(e).__name__}: {str(e)[:80]}）。鍵と actions: read を確かめる")
        return _end("unknown", 1)
    runs = [r for r in runs if (_when(r) or FLOOR - timedelta(1)) >= since]
    skipped = sum(1 for r in runs if r.get("conclusion") == "skipped")
    target = [r for r in runs if r.get("conclusion") != "skipped"]
    cut = max(0, len(target) - max_runs)
    target = target[:max_runs]
    head = f"CI のログ（{since.astimezone(JST):%Y-%m-%d %H:%M} JST 以降に作られた完了した回）"
    if not target:
        print(f"{head}: 対象の回が0回です（skipped {skipped}回）")
        return _end("unknown", 0)
    left, rate_cut = remaining(token), 0
    if left is not None and len(target) > left - RESERVE:
        rate_cut = len(target) - max(0, left - RESERVE)
        target = target[:len(target) - rate_cut]

    t0 = time.monotonic()
    deadline = t0 + budget
    with ThreadPoolExecutor(WORKERS) as ex:
        res = list(ex.map(lambda r: _one(r, repo, token, pats, deadline), target))
    tally = {k: sum(1 for s, _ in res if s == k) for k in ("ok", "nolog", "fail", "late")}
    print(f"{head}: 対象 {len(target)}回（中身の無い skipped {skipped}回は除く）／調べた {tally['ok']}回・"
          f"ログ無し {tally['nolog']}回・取れず {tally['fail']}回・時間切れ {tally['late']}回（{time.monotonic() - t0:.0f}秒）")
    if cut:
        print(f"注意: 上限 {max_runs}回で打ち切り、古い {cut}回は調べていません（--max-runs）")
    if rate_cut:
        print(f"注意: API の残り（{left}回）からほかの工程の分 {RESERVE}回を残すため、古い {rate_cut}回は調べていません")
    hits = [(run, sid, n, ks) for run, (_, got) in zip(target, res) for sid, (n, ks) in sorted(got.items())]
    if hits:
        print(f"要対応: CI のログにお客様の守秘の語が出た回が {len({r['id'] for r, *_ in hits})}回あります"
              "（public のログは誰でも読めます。語は出しません）。出した工程を直してください。ログを消すかは運用者が決めます"
              f"（gh api -X DELETE repos/{repo}/actions/runs/<run id>/logs）")
        for run, sid, n, ks in hits:
            when = _when(run)
            day = when.astimezone(JST).strftime("%Y-%m-%d") if when else "----"
            print(f"  - {day} {_wf_name(run)} run {run['id']} {S.public_id(sid)}: {n}件（{', '.join(sorted(ks))}）")
        return _end("no", 0)
    missed = tally["fail"] + tally["late"] + rate_cut
    if missed > max(5, (len(target) + rate_cut) // 10):
        print(f"調べられなかった回が多すぎます（{missed}/{len(target) + rate_cut}回）。鍵の権限（actions: read）か API の上限を確かめる")
        return _end("unknown", 1)
    return _end("yes", 0)


def check_tracked():
    """公開側で追跡しているファイルに、お客様の守秘の語が出ていないか（2026-10-11: CI が書いた学びの台帳に
    お客様の記事の slug が入り、公開リポジトリに残っていた。門は毎回の記事では回らないので週次でも見る）。
    照らし方は門（gates_history_h77.find_identity）と同じ（表示の場所の社名・他社の URL の中の同じ綴りは数えない）。
    TRACKED_LEAK_OK=yes/no/unknown。語そのものは出さない"""
    sys.path.insert(0, str(ROOT / "tests"))
    try:
        import gates_history_h77 as G
        words = G._client_words()
    except Exception as e:
        print(f"TRACKED_LEAK_OK=unknown（守秘の語を集められません: {type(e).__name__}）")
        return 1
    if not words:
        print("TRACKED_LEAK_OK=unknown（非公開のデータが無く、照らす語がありません）")
        return 0
    _own, doms = G._own()
    files = G._tracked()
    hits = sorted(set(G.find_identity(files, words, doms)))
    terms = [w.lower() for n, a, d in words.values() for w in list(n) + list(a) + [d] if w and len(w) >= 4]
    for f, kind in hits:
        shown = "（お客様の語を含むファイル名）" if any(t in f.lower() for t in terms) else f
        print(f"  {shown}: {kind}")
    print(f"TRACKED_LEAK_OK={'no' if hits else 'yes'}（公開側の追跡ファイル {len(files)}件を照らしました）")
    if hits:
        print(f"要対応: 公開リポジトリのファイルにお客様の守秘の語が出ています（{len(hits)}件）。語を伏せるか、非公開の置き場へ移してください")
    return 0


def main(argv=None):
    if argv is None and "--tracked" in sys.argv[1:]:
        return check_tracked()
    ap = argparse.ArgumentParser(description="CI のログにお客様の守秘の語が出ていないか数える（語は出さない）")
    ap.add_argument("--days", type=int, default=8, help="さかのぼる日数（2026-10-11 より前の回は数えない）")
    ap.add_argument("--max-runs", type=int, default=400, help="調べる回の上限（新しい順）")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or REPO)
    ap.add_argument("--budget", type=int, default=BUDGET, help="ログを取る時間の上限（秒）")
    a = ap.parse_args(argv)
    return check(days=a.days, max_runs=a.max_runs, repo=a.repo, budget=a.budget)


if __name__ == "__main__":
    sys.exit(main())
