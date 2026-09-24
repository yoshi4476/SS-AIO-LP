# -*- coding: utf-8 -*-
"""各社の月次レポートを1通にまとめて送る。**要対応がある社を先頭に**並べる。

**なぜ要るか**: 社ごとに1通ずつ届くと、20社なら月20通。どれを見るべきか分からず、
本当に手当てが要る社が埋もれる。monthly_report.py --queue が照合を通したPDFを列に積み、
ここで1通にまとめる。照合に落ちた社は添付せず「照合で止めた」と理由を書く。

要対応の判断: report_actions（レポート直後に機械が改善を当てた結果）の「人の手が要る」項目。

  python scripts/report_digest.py            # 本文を見るだけ
  python scripts/report_digest.py --email    # 送る（送ったら列を空にする）
"""
import base64
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
QUEUE = ROOT / "automation" / "logs" / "report_queue.jsonl"
ACTIONS = ROOT / "automation" / "logs" / "report_actions"
MAX_BYTES = 30 * 1024 * 1024        # Resend の上限（40MB）より手前で止める


def env():
    import hub_client as HC
    return HC.ENV


def human_items():
    """report_actions の最新結果から、社ごとの「人の手が要る」項目"""
    import report_actions as RA
    files = sorted(ACTIONS.glob("*.json"))
    if not files:
        return {}
    out = {}
    for it in json.loads(files[-1].read_text(encoding="utf-8")):
        if it.get("kind") in RA.HUMAN:
            out.setdefault(it["site"], []).append(f"{it['finding']} → {it['action']}")
    return out


def main():
    rows = [json.loads(l) for l in QUEUE.read_text(encoding="utf-8").splitlines() if l.strip()] if QUEUE.is_file() else []
    if not rows:
        print("まとめて送るレポートがありません")
        print("DIGEST_OK=yes")
        return 0
    last = {}
    for r in rows:                                   # 同じ社が2回積まれたら新しい方
        last[(r["site"], r["ym"])] = r
    rows = list(last.values())
    hum = human_items()
    rows.sort(key=lambda r: (not hum.get(r["site"]), not r["ok"] is False, r["name"]))
    ym = rows[0]["ym"]
    lines = [f"{ym} の月次レポート（{len(rows)}社）をまとめてお送りします。", ""]
    need = [r for r in rows if hum.get(r["site"]) or not r["ok"]]
    lines.append(f"■ 手当てが要る社: {len(need)}社" if need else "■ 手当てが要る社はありません")
    for r in rows:
        if not r["ok"]:
            lines.append(f"・{r['name']}: 照合で止めました（PDFは添付していません）— " + " / ".join(r.get("why") or [])[:200])
        elif hum.get(r["site"]):
            lines.append(f"・{r['name']}:")
            lines += [f"    - {x}" for x in hum[r["site"]][:6]]
    lines += ["", "■ 添付", ""]
    attach, size = [], 0
    for r in rows:
        p = Path(r["pdf"])
        if not r["ok"] or not p.is_file():
            continue
        b = p.read_bytes()
        if size + len(b) * 4 // 3 > MAX_BYTES:
            lines.append(f"・{r['name']}（容量の上限のため添付を省略。reports/ にあります）")
            continue
        size += len(b) * 4 // 3
        attach.append({"filename": f"{r['site']}-{r['ym']}.pdf", "content": base64.b64encode(b).decode()})
        lines.append(f"・{r['name']}（{r['site']}-{r['ym']}.pdf）")
    body = "\n".join(lines)
    print(body)
    if "--email" not in sys.argv:
        print("DIGEST_OK=yes")
        return 0
    e = env()
    key, frm, to = e.get("RESEND_API_KEY", ""), e.get("LEAD_FROM_EMAIL", ""), e.get("LEAD_TO_EMAIL", "") or "info.ai@7senses.co.jp"
    if not key or not frm:
        print("メール未送信: RESEND_API_KEY / LEAD_FROM_EMAIL がありません")
        print("DIGEST_OK=no")
        return 0
    payload = json.dumps({"from": frm, "to": [to],
                          "subject": f"【月次レポート】{ym}（{len(rows)}社" + (f"・要対応{len(need)}社" if need else "") + "）",
                          "text": body, "attachments": attach}).encode()
    req = urllib.request.Request("https://api.resend.com/emails", data=payload, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"})
    with urllib.request.urlopen(req, timeout=60) as res:
        print("メール送信:", res.status)
    QUEUE.unlink(missing_ok=True)
    print("DIGEST_OK=yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
