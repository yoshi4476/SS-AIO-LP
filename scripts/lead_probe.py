# -*- coding: utf-8 -*-
"""問い合わせが管制塔の台帳まで届くかを、本物と同じ経路で週に1回確かめる（疎通確認）。

2026-09-18 に、AI集客ラボの診断ツールからの送信2件が、台帳にもメールにも残らず失われた。
気づいたのは10日後で、取り戻せなかった。経路が黙って壊れても、1週間以内に気づけるようにする。

  AI集客ラボ   … Cloudflare の受付（/api/lead）→ 管制塔
  補助金サイト … ページから直接 Apps Script へ（URLは公開中のページから読む）
  コーポレート … ページから直接 Apps Script へ（URLは配信先リポジトリの src/lib/site.ts から読む）

送るのはテスト専用のアドレス（@pipeline-check.invalid）。管制塔はこれを見分けて「疎通確認」シートにだけ残し、
問い合わせの台帳・通知・自動返信には出さない（contact.hub.gs の form_）。

    python scripts/lead_probe.py
"""
import base64
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0; lead-probe)"}
GAS = re.compile(r"https://script\.google\.com/macros/s/(AKfy[A-Za-z0-9_-]{20,})/exec")


def post(url, data, headers):
    req = urllib.request.Request(url, data=data, headers={**UA, **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]


def get(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def addr(site):
    return f"probe-{site}-{int(time.time())}@pipeline-check.invalid"


def probe_ai_lab():
    # urllib はリダイレクトを追う。/thanks/ に着けば受付が管制塔の ok を受け取った
    fields = {"name": "疎通確認", "company": "疎通確認", "email": addr("ai-lab"),
              "form_type": "お問い合わせ", "message": "週次の疎通確認（自動）"}
    b = "----probe" + str(int(time.time()))
    body = "".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in fields.items())
    body = (body + f"--{b}--\r\n").encode("utf-8")
    code, text = post("https://ai.7senses.co.jp/api/lead", body, {"Content-Type": f"multipart/form-data; boundary={b}"})
    return code < 400, f"/api/lead → {code}"


def probe_direct(site, endpoint, extra):
    payload = {"site": site, "type": "contact", "name": "疎通確認", "email": addr(site),
               "message": "週次の疎通確認（自動）", "referer": "lead_probe", **extra}
    code, text = post(endpoint, json.dumps(payload).encode("utf-8"), {"Content-Type": "text/plain;charset=utf-8"})
    try:
        ok = bool(json.loads(text).get("ok"))
    except ValueError:
        ok = False
    return ok, f"{endpoint[-18:]} → {code} {text[:60]}"


def subsidy_endpoint():
    found = [m for m in GAS.findall(get("https://lp.7senses.co.jp/")) if "XXXX" not in m]
    return f"https://script.google.com/macros/s/{found[0]}/exec" if found else ""


def corporate_endpoint():
    """配信先リポジトリの src/lib/site.ts から、フォームの送り先と鍵を読む（ページの組み立て後の JS からは読みにくい）"""
    import sites as S
    cfg = S.load("corporate")
    tok = os.environ.get("SITE_PUSH_TOKEN") or os.environ.get("GH_TOKEN") or ""
    h = {"Accept": "application/vnd.github.raw"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    try:
        src = get(f"https://api.github.com/repos/{cfg['repo']}/contents/src/lib/site.ts?ref={cfg['branch']}", h)
    except Exception:
        local = ROOT / ".publish-work" / "corporate" / "src" / "lib" / "site.ts"
        src = local.read_text(encoding="utf-8") if local.is_file() else ""
    m = GAS.search(src)
    k = re.search(r"formKey:\s*\"([^\"]+)\"", src)
    return (m.group(0) if m else ""), (k.group(1) if k else "")


def main():
    import hub_client as HC
    started = datetime.now(timezone.utc) - timedelta(seconds=5)
    results = {"ai-lab": probe_ai_lab()}
    ep = subsidy_endpoint()
    results["subsidy"] = probe_direct("subsidy", ep, {}) if ep else (False, "送り先が公開中のページに見つからない")
    ep, key = corporate_endpoint()
    results["corporate"] = probe_direct("corporate", ep, {"formKey": key}) if ep else (False, "送り先が site.ts に見つからない")
    time.sleep(15)
    st = (HC._post({"action": "probe_status"}) or {}).get("last", {})
    labels = {"ai-lab": "AI集客ラボ", "subsidy": "補助金", "corporate": "コーポレート"}
    bad = []
    for sid, (sent, how) in results.items():
        # 台帳のサイト名は表示名（例「AI集客ラボ (ai.7senses.co.jp)」）。名前の一部で引く
        at = max((v for k, v in st.items() if labels[sid] in k or sid in k), default="")
        reached = bool(at) and datetime.fromisoformat(at.replace("Z", "+00:00")) >= started
        print(f"   {labels[sid]:<8} 送信 {'○' if sent else '×'}（{how}）／ 台帳に届いた {'○' if reached else '×'}")
        if not reached:
            bad.append(labels[sid])
    print(f"LEAD_PROBE_OK={'no' if bad else 'yes'}")
    if bad:
        print(f"   要対応: 問い合わせが台帳まで届いていません（{'・'.join(bad)}）。フォームの送り先と管制塔のデプロイを確かめてください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
