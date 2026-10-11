# -*- coding: utf-8 -*-
"""ロボットよけ（Cloudflare Turnstile）の記録を読む。断る段階へ切り替える前に、本物の送信が ok になっているかを見る。

記録は管制塔の「ロボットよけ」タブ（contact.hub.gs の botLog_）。個人の情報は入っていない（サイト・経路・種別・結果・ドメインだけ）。
  経路 … ページから直接（補助金・コーポレート。管制塔が Cloudflare に確かめる）／サーバーで確認（AI集客ラボの受付が確かめた結果）
  結果 … ok / none（答えが無い）/ invalid / error（確かめられない）

--decide は、実際の記録で「断る」へ切り替えてよいかを決める（2026-10-11 運用者「自動ですべて」。週次の findings が --apply で呼ぶ）。
本物の相談（台帳の温度が営業・テストでない行）を、同じ時刻（前後3分）のロボットよけの記録と突き合わせ、
断っていたら本物の相談を落としていた（none / invalid）が1件も無いことを確かめてから切り替える。切り替えは2か所:
管制塔（Script Properties の TURNSTILE_ENFORCE）と AI集客ラボの受付（functions/_turnstile_enforce.js。コミットで配信される）。

    python scripts/turnstile_status.py            # 直近7日
    python scripts/turnstile_status.py --days 30
    python scripts/turnstile_status.py --decide            # 切り替えてよいかを見る（何も変えない）
    python scripts/turnstile_status.py --decide --apply    # 条件がそろっていれば切り替える
出す印: BOT_ENFORCE=on（断っている）/ switched（今回切り替えた）/ wait（理由）/ hold（本物の相談が ok にならなかった・要対応）/ unknown
"""
import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
DECIDED = ROOT / "functions" / "_turnstile_enforce.js"
JST = timezone(timedelta(hours=9))
MIN_DAYS = 14          # 記録を始めてから見る日数（2026-10-10 に記録だけで始めた）
MIN_LEADS = 3          # 突き合わせる本物の相談の数（月5件ほどなので、少なくとも3件は見る）
WINDOW = timedelta(minutes=3)
EXCLUDED = {"営業", "テスト"}


def _when(v):
    """台帳の受信日時（スプレッドシートの通し番号か文字列）→ 日本時間の datetime"""
    if isinstance(v, (int, float)):
        return datetime(1899, 12, 30, tzinfo=JST) + timedelta(days=float(v))
    s = str(v).strip()
    for f in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], f).replace(tzinfo=JST)
        except ValueError:
            pass
    return None


def decide(bots, leads, now=None):
    """bots: [(日時, 結果, 疎通確認か)]、leads: [(日時, 温度)]。(印, 理由) を返す"""
    now = now or datetime.now(JST)
    real = [b for b in bots if not b[2]]
    if not real:
        return "wait", "ロボットよけの記録がまだありません"
    first = min(b[0] for b in real)
    if now - first < timedelta(days=MIN_DAYS):
        return "wait", f"記録を始めてから {(now - first).days}日（{MIN_DAYS}日たってから決めます）"
    errs = sum(1 for b in real if b[1] == "error" and now - b[0] < timedelta(days=7))
    if errs >= 3:
        return "wait", f"直近7日に Cloudflare で確かめられなかった送信が {errs}件（確かめが安定してから決めます）"
    consult = [t for t, temp in leads if t and t >= first and temp not in EXCLUDED]
    bad, unmatched = 0, 0
    for t in consult:
        near = [b for b in real if abs(b[0] - t) <= WINDOW]
        if not near:
            unmatched += 1
        elif any(b[1] in ("none", "invalid") for b in near) and not any(b[1] == "ok" for b in near):
            bad += 1
    if bad:
        return "hold", (f"本物の相談 {len(consult)}件のうち {bad}件がロボットよけを通っていません（断っていたら落としていました）。"
                        "部品が読み込めない端末がないか確かめてください")
    if len(consult) - unmatched < MIN_LEADS:
        return "wait", (f"突き合わせられた本物の相談が {len(consult) - unmatched}件（{MIN_LEADS}件そろってから決めます。"
                        f"記録の無い相談 {unmatched}件）")
    if unmatched:
        return "wait", f"ロボットよけの記録が無い本物の相談が {unmatched}件あります（記録の漏れを直してから決めます）"
    return "switch", f"本物の相談 {len(consult)}件がすべてロボットよけを通り、記録は {(now - first).days}日分あります"


def decided_on():
    try:
        return "lead: true" in DECIDED.read_text(encoding="utf-8")
    except OSError:
        return False


def write_decided(on):
    DECIDED.write_text(
        "// ロボットよけで断るか（AI集客ラボの受付 /api/lead・/api/subscribe）。scripts/turnstile_status.py --decide --apply が、\n"
        "// 本物の相談がすべてロボットよけを通っていることを記録で確かめてから true にする（手で書き換えない）\n"
        f"export const DECIDED = {{ lead: {'true' if on else 'false'}, subscribe: {'true' if on else 'false'} }};\n",
        encoding="utf-8")


def _status(days):
    import hub_client as HC
    return HC._post({"action": "bot_status", "days": days, "all": True}) or {}


def run_decide(apply):
    r = _status(60)
    if not r.get("ok"):
        print(f"BOT_ENFORCE=unknown（記録を読めませんでした: {r.get('error', '応答なし')}）")
        return 0
    if r.get("enforce") and decided_on():
        refused = sum(n for k, n in (r.get("counts") or {}).items() if k.endswith("断った"))
        print(f"BOT_ENFORCE=on（断っています。直近60日に断った送信 {refused}件）")
        return 0
    bots = []
    for row in r.get("recent") or []:
        try:
            at = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00")).astimezone(JST)
        except ValueError:
            continue
        bots.append((at, str(row[4]).strip(), bool(str(row[7]).strip())))
    try:
        import hub_sheets as H
        leads = [(_when(x[0]), str(x[12]).strip()) for x in H.rows("問い合わせ", 14)]
    except Exception as e:
        print(f"BOT_ENFORCE=unknown（問い合わせの台帳を読めませんでした: {type(e).__name__}）")
        return 0
    mark, why = decide(bots, leads)
    if mark == "switch" and apply:
        import hub_client as HC
        g = HC._post({"action": "bot_enforce", "on": True}) or {}
        if not g.get("enforce"):
            print(f"BOT_ENFORCE=unknown（管制塔を切り替えられませんでした: {g.get('error', '応答なし')}）")
            return 0
        write_decided(True)
        print(f"BOT_ENFORCE=switched（{why}。管制塔と AI集客ラボの受付で、確かめに通らない送信を断ります）")
        print(f"要対応: ロボットよけを「断る」に切り替えました（{why}）。戻すときは python scripts/turnstile_status.py --off")
        return 0
    if mark == "hold":
        print(f"BOT_ENFORCE=hold（{why}）")
        print(f"要対応: ロボットよけを「断る」に切り替えていません。{why}")
        return 0
    print(f"BOT_ENFORCE={'wait' if mark != 'switch' else 'ready'}（{why}）")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--decide", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--off", action="store_true", help="断るのをやめて記録だけに戻す")
    a = ap.parse_args()
    if a.off:
        import hub_client as HC
        g = HC._post({"action": "bot_enforce", "on": False}) or {}
        write_decided(False)
        print(f"BOT_ENFORCE=off（管制塔: {'記録だけ' if g.get('ok') and not g.get('enforce') else '切り替えを確かめられません'}・"
              "AI集客ラボの受付は functions/_turnstile_enforce.js をコミットすると戻ります）")
        return 0
    if a.decide:
        return run_decide(a.apply)
    import hub_client as HC
    r = HC._post({"action": "bot_status", "days": a.days}) or {}
    if not r.get("ok"):
        print(f"記録を読めませんでした: {r.get('error', '応答なし')}")
        return 1
    print(f"管制塔: 断る={'はい' if r.get('enforce') else 'いいえ（記録だけ）'}／確かめの鍵={'あり' if r.get('secret') else 'なし'}")
    print(f"直近{r.get('days')}日（サイト｜経路｜結果｜疎通確認｜処置: 件数）")
    for k, n in sorted((r.get("counts") or {}).items()):
        print(f"  {k}: {n}")
    print("最近の記録")
    for row in r.get("recent") or []:
        print("  " + " / ".join(str(x) for x in row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
