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
    python scripts/turnstile_status.py --off       # 手で止める（印が残り、週次は「断る」へ戻さない）
    python scripts/turnstile_status.py --resume    # 手で止めた印を外し、その時刻より後の記録で判断し直す
出す印: BOT_ENFORCE=on（断っている）/ switched（今回切り替えた）/ wait（理由）/ hold（本物の相談が ok にならなかった・要対応）/
off（手で止めている）/ unknown。週次の findings が拾う BOT_ENFORCE_OK=yes|no|unknown も出す（switched・hold・片側だけは no）

突き合わせるのは、断る対象の経路と社だけ（管制塔はページから直接届く送信＝補助金・コーポレートを、AI集客ラボの受付は自分で
確かめた送信を断る）。合言葉つきの転送・別事業のサイト・AI紹介チェック（自分で確かめる）は、どちらの切り替えでも断られないので数えない。
相談ごとに同じ社の一番近い記録1件で判定する（近くに別の送信の ok があっても、その相談の none を見逃さない）
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
MIN_PER_ROUTE = 2      # 経路ごとにも見る（片方の経路で部品が読めなくても、もう片方の ok で切り替えない）
# 断る対象の社と経路（自社のドメイン → その社の送信が通る経路）
ROUTE_OF = {"ai.7senses.co.jp": "サーバーで確認", "lp.7senses.co.jp": "ページから直接", "corp.7senses.co.jp": "ページから直接"}
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


def _dom(site):
    """台帳・記録のサイト名（「名前 (ドメイン)」）→ 断る対象の社のドメイン。対象でなければ空"""
    return next((d for d in ROUTE_OF if d in str(site)), "")


def decide(bots, leads, now=None, since=None):
    """bots: [(日時, 結果, 疎通確認か, サイト, 経路, 処置)]、leads: [(日時, 温度, サイト, 詳細)]。(印, 理由) を返す。
    since（判断を再開した時刻）より前の記録は見ない"""
    now = now or datetime.now(JST)
    real = [b for b in bots if not b[2] and (since is None or b[0] >= since)]
    if not real:
        return "wait", "ロボットよけの記録がまだありません"
    first = min(b[0] for b in real)
    if now - first < timedelta(days=MIN_DAYS):
        return "wait", f"記録を始めてから {(now - first).days}日（{MIN_DAYS}日たってから決めます）"
    refused = sum(1 for b in real if b[5] == "断った")
    if refused:
        # 断っていない今、断った記録があるのは、以前に断っていた（手で戻した・片側だけ戻った）とき。断られた相談は台帳に残らないので、
        # 台帳だけでは本物を落としていないと言えない。人が確かめてから --resume で判断を再開する
        return "hold", (f"以前に断った送信が {refused}件あります（断られた相談は台帳に残らないため、本物だったかを確かめてから"
                        "python scripts/turnstile_status.py --resume で判断を再開してください）")
    errs = sum(1 for b in real if b[1] == "error" and now - b[0] < timedelta(days=7))
    if errs >= 3:
        return "wait", f"直近7日に Cloudflare で確かめられなかった送信が {errs}件（確かめが安定してから決めます）"
    seen = {r: {"n": 0, "ok": 0, "bad": 0, "none": 0} for r in set(ROUTE_OF.values())}
    for t, temp, site, detail in leads:
        dom = _dom(site)
        # AI紹介チェックの行は受付が自分で確かめて書く（ロボットよけの記録を残さない・どちらの切り替えでも断られない）
        if not t or t < first or temp in EXCLUDED or not dom or "AI紹介チェック" in str(detail):
            continue
        g = seen[ROUTE_OF[dom]]
        g["n"] += 1
        near = [b for b in real if _dom(b[3]) == dom and b[4] == ROUTE_OF[dom] and abs(b[0] - t) <= WINDOW]
        if not near:
            g["none"] += 1
            continue
        res = min(near, key=lambda b: abs(b[0] - t))[1]
        if res in ("none", "invalid"):
            g["bad"] += 1
        elif res == "ok":
            g["ok"] += 1
        else:
            g["none"] += 1      # 確かめられなかった（error）相談は、通ったとも落としたとも数えない
    n = sum(g["n"] for g in seen.values())
    bad = sum(g["bad"] for g in seen.values())
    unmatched = sum(g["none"] for g in seen.values())
    ok = sum(g["ok"] for g in seen.values())
    if bad:
        return "hold", (f"本物の相談 {n}件のうち {bad}件がロボットよけを通っていません（断っていたら落としていました）。"
                        "部品が読み込めない端末がないか確かめてください")
    if unmatched:
        return "wait", f"ロボットよけの記録が無い本物の相談が {unmatched}件あります（記録の漏れを直してから決めます）"
    short = [f"{r} {g['ok']}件" for r, g in sorted(seen.items()) if g["ok"] < MIN_PER_ROUTE]
    if ok < MIN_LEADS or short:
        return "wait", (f"突き合わせられた本物の相談が {ok}件（全体で{MIN_LEADS}件・経路ごとに{MIN_PER_ROUTE}件そろってから決めます。"
                        f"足りない経路: {'・'.join(short) or 'なし'}）")
    return "switch", f"本物の相談 {ok}件（経路ごとに{MIN_PER_ROUTE}件以上）がすべてロボットよけを通り、記録は {(now - first).days}日分あります"


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


def _iso(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(JST) if v else None
    except ValueError:
        return None


def run_decide(apply):
    r = _status(60)
    if not r.get("ok"):
        print(f"BOT_ENFORCE=unknown（記録を読めませんでした: {r.get('error', '応答なし')}）")
        print("BOT_ENFORCE_OK=unknown")
        return 0
    hub_on, file_on = bool(r.get("enforce")), decided_on()
    if r.get("manual_off") and not hub_on:
        # 手で止めたのは運用者の判断なので要対応にしない（片側が断ったままなら下で知らせる）
        if file_on:
            print("BOT_ENFORCE=unknown（手で止めましたが、AI集客ラボの受付はまだ断っています。"
                  "functions/_turnstile_enforce.js を false にしてコミットしてください）")
            print("BOT_ENFORCE_OK=no")
            return 0
        print(f"BOT_ENFORCE=off（{str(r['manual_off'])[:10]} に手で止めています。判断を再開するときは --resume）")
        print("BOT_ENFORCE_OK=yes")
        return 0
    if hub_on and file_on:
        refused = sum(n for k, n in (r.get("counts") or {}).items() if k.endswith("断った"))
        print(f"BOT_ENFORCE=on（断っています。直近60日に断った送信 {refused}件）")
        print("BOT_ENFORCE_OK=yes")
        return 0
    if hub_on != file_on:
        print(f"BOT_ENFORCE=unknown（片側だけ断っています: 管制塔={'断る' if hub_on else '記録だけ'}・"
              f"AI集客ラボの受付={'断る' if file_on else '記録だけ'}。切り替えの push か配信が失敗した可能性があります）")
        print("要対応: ロボットよけが片側だけ切り替わっています（python scripts/turnstile_status.py --decide で確かめてください）")
        print("BOT_ENFORCE_OK=no")
        return 0
    bots = []
    for row in r.get("recent") or []:
        at = _iso(row[0])
        if at is None or len(row) < 9:
            continue
        bots.append((at, str(row[4]).strip(), bool(str(row[7]).strip()), str(row[1]), str(row[2]).strip(), str(row[8]).strip()))
    try:
        import hub_sheets as H
        leads = [(_when(x[0]), str(x[12]).strip(), str(x[1]), str(x[8]) + str(x[9])) for x in H.rows("問い合わせ", 14)]
    except Exception as e:
        print(f"BOT_ENFORCE=unknown（問い合わせの台帳を読めませんでした: {type(e).__name__}）")
        print("BOT_ENFORCE_OK=unknown")
        return 0
    mark, why = decide(bots, leads, since=_iso(r.get("resumed_at")))
    if mark == "switch" and apply:
        import hub_client as HC
        g = HC._post({"action": "bot_enforce", "on": True}) or {}
        if not g.get("enforce"):
            print(f"BOT_ENFORCE=unknown（管制塔を切り替えられませんでした: {g.get('error', '応答なし')}）")
            print("BOT_ENFORCE_OK=unknown")
            return 0
        write_decided(True)
        print(f"BOT_ENFORCE=switched（{why}。管制塔と AI集客ラボの受付で、確かめに通らない送信を断ります）")
        print(f"要対応: ロボットよけを「断る」に切り替えました（{why}）。AI集客ラボの受付は週次の最後の配信で切り替わります。"
              "戻すときは python scripts/turnstile_status.py --off")
        print("BOT_ENFORCE_OK=no")
        return 0
    if mark == "hold":
        print(f"BOT_ENFORCE=hold（{why}）")
        print(f"要対応: ロボットよけを「断る」に切り替えていません。{why}")
        print("BOT_ENFORCE_OK=no")
        return 0
    print(f"BOT_ENFORCE={'wait' if mark != 'switch' else 'ready'}（{why}）")
    print("BOT_ENFORCE_OK=yes")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--decide", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--off", action="store_true", help="断るのをやめて記録だけに戻す（手で止めた印を残す）")
    ap.add_argument("--resume", action="store_true", help="手で止めた印を外し、今より後の記録で判断し直す")
    a = ap.parse_args()
    if a.off:
        import hub_client as HC
        g = HC._post({"action": "bot_enforce", "on": False, "manual": True}) or {}
        write_decided(False)
        print(f"BOT_ENFORCE=off（管制塔: {'記録だけ・手で止めた印あり' if g.get('ok') and not g.get('enforce') and g.get('manual_off') else '切り替えを確かめられません'}・"
              "AI集客ラボの受付は functions/_turnstile_enforce.js をコミットして配信すると戻ります。"
              "週次は --resume するまで「断る」へ戻しません）")
        return 0
    if a.resume:
        import hub_client as HC
        g = HC._post({"action": "bot_enforce", "resume": True}) or {}
        print(f"BOT_ENFORCE=resumed（{'手で止めた印を外しました。' + str(g.get('resumed_at', ''))[:16] + ' より後の記録で週次が判断します' if g.get('ok') else '管制塔に届きませんでした'}）")
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
