# -*- coding: utf-8 -*-
"""無料診断を使った営業の下書き（承認制）。見込み先のサイトを当社の無料診断にかけ、結果つきの案内文を作る（2026-10-18）。

**なぜ要るか**: 検索から来る人の大半は「自分でやる人」で、依頼を考える人の語からのクリックは28日でほぼ0件だった
（GSC 9/17〜10/14。AI集客ラボの相談は90日で0件）。検索を待つだけでなく、こちらから「御社のサイトはこうでした」を届ける。

    python scripts/prospect_outreach.py --import <見込み先.csv>   # 取り込む（列: 会社名,URL,業種,メール,掲載元URL）
    python scripts/prospect_outreach.py --audit [--limit 10]        # 無料診断にかける（当社の /api/audit。診断の記録には入れない）
    python scripts/prospect_outreach.py --draft                     # 結果つきの案内文を作る（AI は使わない。結果の事実だけ）
    python scripts/prospect_outreach.py --review                    # 下書きを見て、送る・やめるを決める
    python scripts/prospect_outreach.py --send                      # 承認した分だけ送る（手元だけ。1日 DAILY_CAP 通）
    python scripts/prospect_outreach.py --track                     # 問い合わせの台帳と突き合わせ、相談につながった先を記録する
    python scripts/prospect_outreach.py --stop <id>                 # 配信停止の申し出。以後この会社（ドメイン）へは送らない
    python scripts/prospect_outreach.py                             # 台帳の状況

リードの追い方: 案内のリンクには見込み先ごとの印（?ref=pr-<id>）を付ける。site.js がその印を90日覚え、
どのフォームから送っても台帳の「流入経路」に「紹介元 pr-<id>」が残る。--track がそれを拾う。

守ること（特定電子メール法・景品表示法）:
  - 送ってよいのは、会社が自分のサイトで公表しているアドレスだけ（掲載元URLが要る）。掲載元に営業メールお断りの
    記載があれば送らない（--audit が掲載元を読んで止める。最後は人が見て決める）
  - 送信者の名称・住所・連絡先と、配信停止の方法を必ず付ける（機械が付ける）
  - 文面の数字は診断の結果（点数・項目の配点）だけ。料金・実績・お客様の声・順位の約束は書かない
  - 見込み先・連絡先・下書き・送った記録は公開リポジトリに置かない（data/prospects/ は .gitignore）。CI では動かさない
"""
import argparse
import csv
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import outreach as OR  # noqa: E402  送信の経路・会社の正規表記・禁止の語は言及の依頼と同じものを使う

STORE = ROOT / "data" / "prospects" / "prospects.json"
SENT_LOG = ROOT / "data" / "prospects" / "sent.jsonl"
AUDIT_API = "https://ai.7senses.co.jp/api/audit"
TOOL = "https://ai.7senses.co.jp/tools/url-check/"
LP = "https://ai.7senses.co.jp/lp/"
DAILY_CAP = 10
COOLDOWN_DAYS = 180
JST = timezone(timedelta(hours=9))
# AI集客ラボが打ち出す業種（医療・不動産・工務店。士業も業種LPがある）。ほかの業種も取り込めるが、一覧で知らせる
TARGET = re.compile(r"クリニック|医院|歯科|病院|整骨|接骨|鍼灸|不動産|工務店|リフォーム|住宅|税理士|司法書士|行政書士|社労士|士業")
REFUSE = re.compile(r"(営業|広告|宣伝|勧誘|セールス)(目的の)?(メール|ご連絡|お問い?合わ?せ)[^。]{0,20}(お断り|ご遠慮|控え|禁止)|"
                    r"(お断り|ご遠慮)[^。]{0,20}(営業|広告|宣伝|勧誘|セールス)")
STATUS = {"new": "未着手", "audited": "診断済み", "drafted": "下書きあり", "approved": "承認済み", "sent": "送った",
          "lead": "相談あり", "stopped": "配信停止", "skipped": "やめた", "blocked": "送れない"}


def now():
    return datetime.now(JST)


def host(url):
    h = urllib.parse.urlsplit(url if "//" in url else "https://" + url).hostname or ""
    return h.lower().removeprefix("www.")


def load():
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(d):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def new_id(d):
    return f"{max([int(k) for k in d if k.isdigit()] or [0]) + 1:04d}"


def ref_of(tid):
    return f"pr-{tid}"


def import_csv(path, d):
    """列: 会社名, URL, 業種, メール, 掲載元URL。同じドメインは2回入れない"""
    seen = {t["host"] for t in d.values()}
    added = skipped = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            g = lambda *ks: next((str(r.get(k) or "").strip() for k in ks if str(r.get(k) or "").strip()), "")
            name, url, mail, where = g("会社名", "name"), g("URL", "url"), g("メール", "email"), g("掲載元URL", "掲載元", "source")
            if not name or not url or host(url) in seen:
                skipped += 1
                continue
            tid = new_id(d)
            d[tid] = {"id": tid, "name": name, "url": url, "host": host(url), "industry": g("業種", "industry"),
                      "email": mail, "where": where, "status": "new", "events": [[now().isoformat(), "取り込み"]]}
            seen.add(host(url))
            added += 1
    print(f"取り込み: {added}件（重複・不足で飛ばした {skipped}件）")


def blocked_reason(t):
    """送ってはいけない理由（空なら送ってよい候補）"""
    if not OR.MAIL_RE.fullmatch(t.get("email") or ""):
        return "メールアドレスがありません"
    if not t.get("where"):
        return "アドレスの掲載元URLがありません（公表されているアドレスにだけ送れます）"
    dom = t["email"].split("@")[1].lower()
    if not (dom == t["host"] or dom.endswith("." + t["host"]) or t["host"].endswith("." + dom)):
        return "アドレスのドメインが会社のサイトと違います（人が確かめてください）"
    if host(t["where"]) != t["host"] and not host(t["where"]).endswith("." + t["host"]):
        return "掲載元が会社のサイトではありません（会社が自分で公表したアドレスか確かめられません）"
    return ""


def page(url, limit=300000):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(limit).decode("utf-8", "ignore")


def audit(t, call=None):
    """当社の無料診断（/api/audit）にかける。ref=prospect の分は診断の記録・同業の平均に入れない（functions/api/audit.js）"""
    if call is None:
        def call(url):
            req = urllib.request.Request(AUDIT_API, data=json.dumps({"url": url, "ref": "prospect"}).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": "ss-aio-pipeline/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
    res = call(t["url"])
    if res.get("error"):
        t["audit"] = {"error": str(res["error"])[:200], "at": now().isoformat()}
        return False
    ng = sorted((c for c in res.get("checks") or [] if not c.get("ok")), key=lambda c: -int(c.get("pts") or 0))
    t["audit"] = {"score": res.get("score"), "grade": res.get("grade"), "url": t["url"], "at": now().isoformat(),
                  "items": len(res.get("checks") or []),
                  "ng": [{"name": c.get("name"), "pts": c.get("pts"), "advice": c.get("advice")} for c in ng]}
    return True


def check_where(t, fetch=page):
    """掲載元に営業メールお断りの記載が無いかを見る（あれば送れない）"""
    try:
        text = re.sub(r"<[^>]+>", " ", fetch(t["where"]))
    except Exception as e:
        return f"掲載元を読めません（{type(e).__name__}）。人が確かめてください"
    if t["email"] not in text:
        return "掲載元にこのアドレスが見つかりません（公表されているアドレスか、人が確かめてください）"
    if REFUSE.search(text):
        return "掲載元に営業・広告のメールをお断りする記載があります"
    return ""


def compose(t, c=None):
    """件名と本文。AI は使わず、診断の結果の事実だけで組む（数字は点数と配点だけ）"""
    a = t["audit"]
    c = c or OR.company()
    q = urllib.parse.urlencode({"url": t["url"], "ref": ref_of(t["id"])})
    tool = f"{TOOL}?{q}"
    lp = f"{LP}?{urllib.parse.urlencode({'ref': ref_of(t['id'])})}#form"
    top = a["ng"][:3]
    if top:
        lines = "\n".join(f"・{x['name']}（{x['pts']}点の項目）: {x['advice']}" for x in top)
        found = (f"検索とAI検索（ChatGPT・GoogleのAIによる概要など）からの見え方を{a['items']}項目で確かめたところ、"
                 f"{a['score']}点でした。点数の大きい順に、直すと効きやすい項目です。\n\n{lines}")
    else:
        found = f"検索とAI検索からの見え方を{a['items']}項目で確かめたところ、{a['score']}点で、目立つ不足はありませんでした。"
    subject = f"{t['name']}様のサイトを無料診断した結果（{a['score']}点）"
    body = (f"{t['name']}\nご担当者様\n\n"
            f"突然のご連絡失礼いたします。{c['name']}の{c['ceo']}です。"
            f"AI集客ラボという、医療・不動産・工務店のSEOとAI検索対策の情報サイトを運営しています。\n\n"
            f"御社のサイト（{a['url']}）を、当社の無料診断ツールにかけました。\n\n{found}\n\n"
            f"同じ診断は、次のページで御社のURLを入れた状態でご覧いただけます（項目ごとの合否と直し方が出ます）。\n{tool}\n\n"
            f"この結果を見て、何から手を付けるかを15分ほどでお話しすることもできます。ご希望でしたら、"
            f"このメールにご返信いただくか、次のページからお申し込みください。\n{lp}\n\n"
            f"不要でしたら、このままお捨て置きください。")
    return subject, body + footer(t, c)


def footer(t, c):
    return ("\n\n――――――――――――――――\n"
            f"{c['name']}（法人番号 {c['corporate_number']}）\n"
            f"代表取締役 {c['ceo']}\n"
            f"〒{c['postal']} {c['address']}\n"
            f"TEL {c['tel']}（{c['hours']}）\n"
            f"Email {c['email']}\n"
            f"AI集客ラボ {c['sites']['ai-lab']}\n\n"
            f"本メールは、御社がサイトで公開している窓口（{t['where']}）宛てに、{c['name']}がお送りしています。\n"
            f"今後このようなご連絡が不要でしたら、本メールに「配信停止」とご返信いただくか、"
            f"{c['email']} までお知らせください。以後お送りしません。")


def inspect(t, subject, body, c=None):
    """送ってよい文面か。数字は診断の結果（点数・配点）と、署名・郵便番号・電話・法人番号・URL の中だけ"""
    c = c or OR.company()
    text = subject + "\n" + body
    bad = []
    for name, rx in (("料金", OR.PRICE), ("お客様の声", OR.VOICE), ("見返り", OR.QUID)):
        if rx.search(text):
            bad.append(f"{name}の語があります")
    if re.search(r"保証|必ず|確実に|上位表示を約束|1位", text):
        bad.append("成果を約束する語があります")
    a = t["audit"]
    allowed = {str(a.get("score")), str(a.get("items")), "15"} | {str(x["pts"]) for x in a["ng"]}
    plain = OR.URL_RE.sub(" ", text)
    for v in (c["postal"], c["tel"], c["corporate_number"], c["address"], c["hours"], c["email"]):
        plain = plain.replace(str(v), " ")
    extra = sorted(set(re.findall(r"\d+", plain)) - allowed)
    if extra:
        bad.append(f"診断の結果に無い数字があります: {extra[:5]}")
    if not all(x in body for x in (c["name"], c["address"], c["email"], c["tel"], "配信停止")):
        bad.append("送信者の情報か配信停止の案内が欠けています")
    if f"ref={ref_of(t['id'])}" not in body:
        bad.append("案内のリンクに見込み先の印（ref）がありません（相談につながったかを追えません）")
    return bad


def digest(subject, body):
    return hashlib.sha256((subject + "\n" + body).encode("utf-8")).hexdigest()[:16]


def sent_log():
    try:
        return [json.loads(x) for x in SENT_LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        return []


def send_blockers(d, t, log=None, when=None):
    when = when or now()
    log = sent_log() if log is None else log
    if t.get("status") != "approved":
        return "承認されていません"
    s, b = compose(t)
    if t.get("approved_digest") != digest(s, b):
        return "承認の後に文面が変わりました（もう一度 --review で承認してください）"
    if blocked_reason(t):
        return blocked_reason(t)
    if any(x.get("status") == "stopped" and x["host"] == t["host"] for x in d.values()):
        return "この会社は配信停止の申し出があります"
    recent = [x for x in log if x.get("host") == t["host"]
              and datetime.fromisoformat(x["at"]) > when - timedelta(days=COOLDOWN_DAYS)]
    if recent:
        return f"{COOLDOWN_DAYS}日以内に送っています"
    today = [x for x in log if x["at"][:10] == when.date().isoformat()]
    if len(today) >= DAILY_CAP:
        return f"今日はもう {DAILY_CAP} 通送りました"
    return ""


def send(d, mailer=None):
    import os
    if os.environ.get("GITHUB_ACTIONS"):
        print("PROSPECT_SEND=skip（CI では送りません。送るかは人が手元で決めます）")
        return 0
    mailer = mailer or OR.resend_mail
    n = 0
    for t in d.values():
        if t.get("status") != "approved":
            continue
        why = send_blockers(d, t)
        if why:
            print(f"  {t['id']} {t['name']}: 送りません（{why}）")
            continue
        s, b = compose(t)
        mid = mailer(t["email"], s, b, OR.company()["email"])
        rec = {"id": t["id"], "host": t["host"], "at": now().isoformat(), "mid": mid, "ref": ref_of(t["id"])}
        SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SENT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        t["status"] = "sent"
        t["events"].append([rec["at"], "送った"])
        n += 1
        print(f"  {t['id']} {t['name']}: 送りました")
    save(d)
    print(f"PROSPECT_SENT={n}")
    return n


def track(d, rows=None):
    """問い合わせの台帳の「流入経路」に「紹介元 pr-<id>」がある行を、その見込み先の相談として記録する"""
    if rows is None:
        import lead_reconcile as LR
        rows = LR.ledger_rows()
    hits = 0
    for t in d.values():
        mark = ref_of(t["id"])
        mine = [r for r in rows if re.search(rf"紹介元\s*{re.escape(mark)}\b", r.get("route") or "")]
        if mine and t.get("status") != "lead":
            t["status"] = "lead"
            t["lead"] = [{"day": r["day"], "type": r.get("type"), "temp": r.get("temp")} for r in mine]
            t["events"].append([now().isoformat(), f"相談あり（{len(mine)}件）"])
            hits += 1
    save(d)
    sent = sum(1 for t in d.values() if t.get("status") in ("sent", "lead"))
    leads = sum(1 for t in d.values() if t.get("status") == "lead")
    print(f"PROSPECT_LEADS={leads}/{sent}（送った先のうち相談につながった数。今回新しく {hits}件）")
    return hits


def review(d):
    for t in d.values():
        if t.get("status") != "drafted":
            continue
        s, b = compose(t)
        print("=" * 70 + f"\n[{t['id']}] {t['name']}（{t['industry']}）→ {t['email']}\n件名: {s}\n\n{b}\n")
        ans = input("送る(y) / やめる(n) / 後で(Enter): ").strip().lower()
        if ans == "y":
            t["status"], t["approved_digest"] = "approved", digest(s, b)
            t["events"].append([now().isoformat(), "承認"])
        elif ans == "n":
            t["status"] = "skipped"
            t["events"].append([now().isoformat(), "やめた"])
    save(d)


def summary(d):
    from collections import Counter
    c = Counter(t.get("status") for t in d.values())
    print("■ 見込み先の台帳: " + " / ".join(f"{STATUS.get(k, k)} {v}" for k, v in c.items()) if d else "■ 見込み先はまだありません")
    off = [t["name"] for t in d.values() if not TARGET.search(t.get("industry") or "")]
    if off:
        print(f"  打ち出す業種（医療・不動産・工務店・士業）の外: {len(off)}件")
    print(f"PROSPECT_OK=yes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--import", dest="imp")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--track", action="store_true")
    ap.add_argument("--stop")
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    d = load()
    if a.imp:
        import_csv(a.imp, d)
        save(d)
    elif a.audit:
        todo = [t for t in d.values() if t["status"] == "new"][:a.limit]
        for t in todo:
            why = blocked_reason(t) or check_where(t)
            if why:
                t["status"], t["blocked"] = "blocked", why
                print(f"  {t['id']} {t['name']}: 送れません（{why}）")
                continue
            ok = audit(t)
            t["status"] = "audited" if ok else "blocked"
            if not ok:
                t["blocked"] = t["audit"]["error"]
            print(f"  {t['id']} {t['name']}: " + (f"{t['audit']['score']}点" if ok else f"診断できません（{t['audit']['error']}）"))
        save(d)
    elif a.draft:
        for t in d.values():
            if t["status"] != "audited":
                continue
            if not t["audit"]["ng"]:
                # 不足の無いサイトに「診断しました」と送っても、相談の理由にならない
                t["status"], t["blocked"] = "skipped", f"診断で不足が見つからない（{t['audit']['score']}点）"
                print(f"  {t['id']} {t['name']}: 送りません（{t['blocked']}）")
                continue
            s, b = compose(t)
            bad = inspect(t, s, b)
            if bad:
                t["status"], t["blocked"] = "blocked", " / ".join(bad)
                print(f"  {t['id']} {t['name']}: 下書きを止めました（{t['blocked']}）")
            else:
                t["status"] = "drafted"
                t["events"].append([now().isoformat(), "下書き"])
                print(f"  {t['id']} {t['name']}: 下書きができました")
        save(d)
    elif a.review:
        review(d)
    elif a.send:
        send(d)
    elif a.track:
        track(d)
    elif a.stop:
        t = d.get(a.stop)
        if t:
            t["status"] = "stopped"
            t["events"].append([now().isoformat(), "配信停止の申し出"])
            save(d)
            print(f"{t['name']}（{t['host']}）へは以後送りません")
    summary(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
