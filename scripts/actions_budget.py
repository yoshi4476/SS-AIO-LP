# -*- coding: utf-8 -*-
"""GitHub Actions実行時間の残枠を監視する

使い方: python scripts/actions_budget.py
環境変数: GITHUB_TOKEN（Actions内では自動供給）/ GITHUB_REPOSITORY

無料枠（Freeプラン・privateリポジトリ = 月2,000分）を使い切ると
全ワークフローが月末まで停止する。停止は「何も起きない」形で現れて
通知も出ないため、事前に残枠を検知して警告する。
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FREE_QUOTA = 2000          # Freeプランの月間無料枠（分）
OTHER_REPO_RESERVE = 950   # 同一アカウントの別リポジトリ（seven-HPunyou）の想定消費
WARN_RATIO = 0.75          # この割合を超えたら警告


def main():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repo:
        print("GITHUB_TOKEN / GITHUB_REPOSITORY 未設定 — 残枠チェックをスキップ")
        return

    now = datetime.now(timezone.utc)
    month = f"{now.year}-{now.month:02d}"
    used, page = 0.0, 1
    while page <= 5:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/runs?per_page=100&page={page}",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "ss-aio/1.0"})
        try:
            with urllib.request.urlopen(req) as r:
                runs = json.load(r).get("workflow_runs", [])
        except urllib.error.HTTPError as e:
            print(f"実行履歴の取得に失敗（HTTP {e.code}） — スキップ")
            return
        if not runs:
            break
        for w in runs:
            if not str(w.get("run_started_at", "")).startswith(month):
                continue
            a = datetime.fromisoformat(w["run_started_at"].replace("Z", "+00:00"))
            b = datetime.fromisoformat(w["updated_at"].replace("Z", "+00:00"))
            used += max((b - a).total_seconds(), 0) / 60
        page += 1

    budget = FREE_QUOTA - OTHER_REPO_RESERVE
    ratio = used / budget if budget else 0
    print(f"ACTIONS_USED={used:.0f}分 / 当リポジトリ想定枠{budget}分（{ratio*100:.0f}%）")
    if ratio < WARN_RATIO:
        print("ACTIONS_BUDGET=ok")
        return

    print("ACTIONS_BUDGET=warn")
    msg = (f"⚠️ GitHub Actionsの実行時間が残り少なくなっています\n"
           f"{month} の使用: {used:.0f}分 / 想定枠 {budget}分（{ratio*100:.0f}%）\n"
           f"枠を使い切ると月末まで記事の自動生成が停止します。\n"
           f"対策: リポジトリをpublicにする（無料無制限）か、GitHub Proへ変更（月$4で3,000分）")
    print(msg)
    try:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "notify_slack.py"), msg],
                       check=False, timeout=60)
    except Exception as e:
        print(f"通知送信に失敗: {e}")


if __name__ == "__main__":
    main()
