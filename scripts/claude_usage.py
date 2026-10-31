# -*- coding: utf-8 -*-
"""Claude の使用量（トークン）を、Claude Code が残す実行の記録から数える（2026-10-24 運用者「トークン消費量がエグい」）。

CI で Claude を呼ぶ工程は18本あるのに、使った量をどこにも残していなかった。どこを削れば効くかを数字で決めるため、
ジョブの終わりに、そのジョブの中で書かれた実行の記録（~/.claude/projects/**/*.jsonl）の手番ごとの使用量を合計する。
呼び方は変えない（--output-format を変えると、答えを読む側の作りが変わる）。

    python scripts/claude_usage.py --since <開始の UNIX 秒> --job <ジョブの名前> [--site <公開の id>] [--write]
    python scripts/claude_usage.py --report [--days 7]      # 記録した分を工程ごとにまとめる

--write は data/claude_usage/<日時>-<実行の番号>.json に1件書く（社は公開の id だけ。記事の題・語は書かない）。
並行するジョブが同じファイルに行を足すと送るときに衝突するので、1回ごとに別のファイルにする。
数えるのは同じ手番を1回だけ（記録には同じ手番が分かれて複数行で残ることがある）。キャッシュの読み込みは別に数える
（同じ文脈を読み直す分。指示書が大きいほど増える）
"""
import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "claude_usage"
KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
# サブスクの上限に当たると claude は「You've hit your weekly limit · resets 8am (Asia/Tokyo)」の1行だけを返す。
# 2026-10-27〜10-30 は全社の記事の枠がこれで止まり、工程は「記事が増えていません」を3回繰り返すだけで理由を残さなかった
LIMIT_RE = re.compile(r"hit your (?:[\w-]+ )?limit|usage limit reached|limit will reset", re.I)


def limit_hit(text):
    """AI の出力が利用の上限の知らせなら、その1行（120字まで）。違えば空"""
    for ln in (text or "").splitlines():
        if LIMIT_RE.search(ln):
            return ln.strip()[:120]
    return ""


def public_site(site):
    """記録に書く社は公開の id だけ（sites/<公開の id>.json がある名前）。社の id を渡されたら伏せる"""
    return site if not site or (ROOT / "sites" / f"{site}.json").is_file() else "?"


def projects_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"


def tally(since, base=None):
    """since（UNIX 秒）より後に書かれた記録の手番を、モデルごと・実行の場所ごとに合計する"""
    seen, total, by_model, sessions = set(), defaultdict(int), defaultdict(lambda: defaultdict(int)), set()
    turns = 0
    for p in sorted((base or projects_dir()).rglob("*.jsonl")):
        try:
            if p.stat().st_mtime < since:
                continue
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for ln in lines:
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            m = d.get("message") if isinstance(d, dict) else None
            u = m.get("usage") if isinstance(m, dict) else None
            if d.get("type") != "assistant" or not isinstance(u, dict):
                continue
            ts = d.get("timestamp")
            if ts:
                try:
                    if datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() < since:
                        continue
                except ValueError:
                    pass
            key = (m.get("id"), d.get("requestId"))
            if key != (None, None) and key in seen:
                continue
            seen.add(key)
            turns += 1
            sessions.add(d.get("sessionId") or p.stem)
            for k in KEYS:
                v = int(u.get(k) or 0)
                total[k] += v
                by_model[m.get("model") or "?"][k] += v
    return {"turns": turns, "sessions": len(sessions), **{k: total[k] for k in KEYS},
            "models": {k: dict(v) for k, v in by_model.items()}}


def report(days):
    files = sorted(LOG.glob("*.json")) if LOG.is_dir() else []
    if not files:
        print("CLAUDE_USAGE=unknown（まだ記録がありません）")
        return
    cut = datetime.now(timezone.utc) - timedelta(days=days)
    agg = defaultdict(lambda: defaultdict(int))
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if datetime.fromisoformat(r["at"]) < cut:
            continue
        a = agg[r.get("job", "?")]
        a["runs"] += 1
        for k in ("turns", *KEYS):
            a[k] += int(r.get(k) or 0)
    print(f"■ Claude の使用量（直近{days}日・ジョブごと。単位は千トークン）")
    print("  ジョブ / 回 / 手番 / 入力 / 出力 / キャッシュ書き / キャッシュ読み")
    for job, a in sorted(agg.items(), key=lambda x: -(x[1]["cache_read_input_tokens"] + x[1]["input_tokens"])):
        print(f"  {job} / {a['runs']} / {a['turns']} / {a['input_tokens'] // 1000} / {a['output_tokens'] // 1000} / "
              f"{a['cache_creation_input_tokens'] // 1000} / {a['cache_read_input_tokens'] // 1000}")
    print("CLAUDE_USAGE=ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=float, default=0, help="この時刻（UNIX 秒）より後の記録だけ数える")
    ap.add_argument("--job", default="")
    ap.add_argument("--site", default="")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--limit-hit", metavar="FILE", help="AI の出力のファイルが利用の上限の知らせかを見る")
    a = ap.parse_args()
    if a.limit_hit:
        try:
            line = limit_hit(Path(a.limit_hit).read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            line = ""
        print(f"AI_LIMIT={'yes' if line else 'no'}")
        if line:
            print(f"AI_LIMIT_LINE={line}")
        return 0
    if a.report:
        report(a.days)
        return 0
    t = tally(a.since or (time.time() - 6 * 3600))
    print(f"CLAUDE_USAGE: {a.job or '?'} 手番{t['turns']}・入力{t['input_tokens']:,}・出力{t['output_tokens']:,}・"
          f"キャッシュ書き{t['cache_creation_input_tokens']:,}・キャッシュ読み{t['cache_read_input_tokens']:,}")
    if a.write and t["turns"]:
        LOG.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        row = {"at": now.isoformat(timespec="seconds"), "job": a.job[:60], "site": public_site(a.site[:40]), **t}
        name = f"{now:%Y%m%d-%H%M%S}-{os.environ.get('GITHUB_RUN_ID', 'local')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}.json"
        (LOG / name).write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
