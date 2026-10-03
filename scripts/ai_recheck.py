# -*- coding: utf-8 -*-
"""AI診断の「1か月後の測り直し」（毎日・本人が印をつけた人だけ・1回だけ）。

AI診断（/tools/ai-check/）で「1か月後に同じ条件で測り直した結果を受け取る」に印をつけた人に、
28〜40日後、同じ3つの質問を Gemini（Google検索つき）にもう一度聞き、前回と比べた結果をメールで送る。
変化が分かれば、相談のきっかけになる。印の無い人・配信除外の人には送らない（管制塔が返さない）。

    python scripts/ai_recheck.py          # 対象を測り直して送る（手元では送らず、結果を出すだけ）
    python scripts/ai_recheck.py --dry    # 対象の一覧だけ

Gemini は無料枠の鍵（超えると 429 で止まり、課金されない）。1人3問。
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SITE_URL = "https://ai.7senses.co.jp"
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"}
E = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def norm(s):
    return re.sub(r"[\s　・（）()「」]", "", str(s or "").lower())


def host(u):
    try:
        h = urllib.parse.urlparse(u if "://" in u else "https://" + u).hostname or ""
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def real_host(uri, title):
    """Gemini の出典は中継アドレス。題がドメインならそれ、違えば行き先を1回だけ見る（ai-check.js と同じ）"""
    t = str(title or "").strip().lower()
    if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", t):
        return t[4:] if t.startswith("www.") else t

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        op = urllib.request.build_opener(NoRedirect)
        r = op.open(urllib.request.Request(uri, method="HEAD", headers=UA), timeout=15)
        return host(r.headers.get("location") or uri)
    except urllib.error.HTTPError as e:
        return host(e.headers.get("location") or uri)
    except Exception:
        return host(uri)


class NoAnswer(Exception):
    """AI が答えを返さなかった（測れなかった）"""


def ask(q):
    # 検索つきの Gemini は有料（無料枠では使えない）。使うと決めるまで呼ばない（ai_cite_check と同じ決まり）
    if os.environ.get("GEMINI_PAID_OK") != "1":
        raise NoAnswer(q)
    key = os.environ.get("GEMINI_API_KEY", "")
    model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    body = json.dumps({"contents": [{"parts": [{"text": q}]}], "tools": [{"google_search": {}}]}).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        data=body, headers={"Content-Type": "application/json", **UA}, method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.load(r)
    c = (d.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", []))
    if not text.strip():
        # 答えが返らなかった質問を「出典なし・社名なし」と数えると、測れていないのに 0/3 と送ってしまう（Codex の点検で指摘）
        raise NoAnswer(q)
    chunks = [x.get("web") or {} for x in (c.get("groundingMetadata") or {}).get("groundingChunks", [])]
    hosts = []
    for w in chunks[:12]:
        if w.get("uri"):
            h = real_host(w["uri"], w.get("title"))
            if h and h not in hosts:
                hosts.append(h)
    return text, hosts


def check(it):
    own = host(it["site"]) if it.get("site") else ""
    qs = [f'{it["area"]} {it["word"]} おすすめ', f'{it["area"]} {it["word"]} 評判 いい', f'{it["area"]} {it["word"]} 人気']
    res = []
    for q in qs:
        text, hosts = ask(q)
        res.append({"q": q, "hosts": hosts[:8],
                    "cited": bool(own) and any(h == own or h.endswith("." + own) for h in hosts),
                    "mentioned": norm(it["company"]) in norm(text)})
    return res


def mail(it, res):
    cited, mentioned = sum(r["cited"] for r in res), sum(r["mentioned"] for r in res)
    rows = "".join(
        f'<tr><td style="padding:8px;border-bottom:1px solid #e5e7eb;">{E(r["q"])}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e5e7eb;text-align:center;">{"○" if r["cited"] else "－"}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e5e7eb;text-align:center;">{"○" if r["mentioned"] else "－"}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#556;">{E("・".join(r["hosts"][:4]))}</td></tr>'
        for r in res)
    site_note = "" if it.get("site") else '<p style="font-size:13px;color:#556;">サイトのURLが未入力のため、出典に御社のサイトが入ったかは判定していません。</p>'
    subject = "【AI診断】1か月後の測り直しの結果"
    html = (f'<div style="font-family:sans-serif;max-width:640px;margin:auto;padding:24px;color:#334;line-height:1.8;font-size:14px;">'
            f'<p>{E(it["company"])} ご担当者様</p>'
            f'<p>{E(it["at"])} にご利用いただいたAI診断を、同じ条件（{E(it["area"])}・{E(it["word"])}）で測り直しました。</p>'
            '<table style="border-collapse:collapse;width:100%;margin:8px 0 12px;font-size:14px;">'
            '<tr><td style="padding:8px;"><b>出典に御社のサイト</b></td><td style="padding:8px;">'
            f'前回 {it["cited"]}/3問 → 今回 <b>{cited}/3問</b></td></tr>'
            '<tr><td style="padding:8px;"><b>回答に社名</b></td><td style="padding:8px;">'
            f'前回 {it["mentioned"]}/3問 → 今回 <b>{mentioned}/3問</b></td></tr></table>'
            '<table style="border-collapse:collapse;width:100%;font-size:13px;">'
            '<tr style="background:#eaf2fe;"><th style="padding:8px;text-align:left;">質問</th><th style="padding:8px;">出典に御社</th>'
            '<th style="padding:8px;">社名</th><th style="padding:8px;text-align:left;">主な出典</th></tr>'
            f'{rows}</table>{site_note}'
            '<p>AIの答えは、同じ質問でも日によって変わります。1回の結果だけで良し悪しを決めず、出典になっているサイトの種類を見てください。</p>'
            f'<p><a href="{SITE_URL}/tools/url-check/" style="color:#2563eb;font-weight:bold;">URL診断（サイトの14項目を採点）</a>'
            f' ／ <a href="{SITE_URL}/download/" style="color:#2563eb;">業種別チェックリスト（PDF）</a></p>'
            '<p>結果の読み方や、何から直すかのご相談は、このメールにご返信ください（無料）。</p>'
            '<p style="font-size:11px;color:#889;margin-top:24px;">このメールは、AI診断で「1か月後の結果を受け取る」を選んだ方へ1回だけお送りしています。'
            '今後のご案内が不要な場合は、このメールに「停止」とご返信ください。<br>'
            '発行: セブンセンシズ株式会社（AI集客ラボ）〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902 ／ TEL 06-4305-7547</p></div>')
    return subject, html, f"出典{cited}/3・社名{mentioned}/3"


def send(to, subject, html):
    key, sender = os.environ.get("RESEND_API_KEY"), os.environ.get("LEAD_FROM_EMAIL")
    payload = {"from": sender, "to": [to], "subject": subject, "html": html}
    if os.environ.get("LEAD_TO_EMAIL"):
        payload["reply_to"] = os.environ["LEAD_TO_EMAIL"]
    req = urllib.request.Request("https://api.resend.com/emails", method="POST", data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", **UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    import hub_client as HC
    items = (HC._post({"action": "ai_recheck_list"}) or {}).get("items", [])
    print(f"測り直しの対象: {len(items)}件")
    if "--dry" in sys.argv:
        for it in items:
            print(f"  {it['at']} {it['company']} {it['area']} {it['word']}")
        return 0
    live = bool(os.environ.get("GITHUB_ACTIONS")) and all(os.environ.get(k) for k in ("RESEND_API_KEY", "LEAD_FROM_EMAIL"))
    if not os.environ.get("GEMINI_API_KEY"):
        print("RECHECK=skip（GEMINI_API_KEY が無い）")
        return 0
    sent = 0
    for it in items:
        try:
            res = check(it)
        except urllib.error.HTTPError as e:
            print(f"  Gemini が止まりました（{e.code}）。残りは明日に回します")
            break
        except NoAnswer as e:
            print(f"  {it['company']}: 答えが返らない質問がありました（{e}）。明日もう一度測ります")
            continue
        subject, html, summary = mail(it, res)
        print(f"  {it['company']}: {summary}")
        if not live:
            continue                                    # 手元では本人に送らない（CLAUDE.md 8.7）
        # 先に「送った」と記録してから送る。送った後の記録に失敗すると、翌日も対象になり同じ人に2通届く
        # （Codex の点検で指摘）。記録できなければ送らない
        done = HC._post({"action": "ai_recheck_done", "row": it["row"], "result": "送信中 " + summary}) or {}
        if not done.get("ok"):
            print(f"要対応: AI診断の測り直し — 送信済みの記録ができないため {it['company']} に送っていません（明日もう一度）")
            continue
        try:
            send(it["email"], subject, html)
        except Exception as e:
            HC._post({"action": "ai_recheck_done", "row": it["row"], "result": "送信失敗 " + str(e)[:40]})
            print(f"要対応: AI診断の測り直しのメールを送れませんでした（{it['company']}・{str(e)[:60]}）。再送はしません")
            continue
        HC._post({"action": "ai_recheck_done", "row": it["row"], "result": summary})
        sent += 1
    print(f"RECHECK_SENT={sent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
