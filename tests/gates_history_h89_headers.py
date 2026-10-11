# -*- coding: utf-8 -*-
"""2026-10-11 AI集客ラボの応答に HSTS と CSP が無かった（コーポレートにはある）。守りの項目を足した。

CSP は読み込み先（script・default・img・style・connect・frame）を縛らない形にする。縛ると、計測タグ・
ロボットよけ（Turnstile）・YouTube の埋め込み・JSON-LD を新しく足したときに、画面には何も出ずに止まる。
閉じるのは、枠への埋め込み・<base>・<object>・フォームの送り先（全ページで同じドメインだけ）。

同じ日、補助金サイトにも同じ形の CSP を足すと、publish.youtube_blocked が「frame-src も default-src も無い」を
「YouTube を許さない」と読み、記事の動画を外すところだった。縛る項目が無い CSP は埋め込みを通す
"""
import re
import tempfile
from pathlib import Path

from test_gates import check, ROOT


def _block(text, path="/*"):
    """_headers の、指定した path の塊の「名前 → 値」（名前は小文字）"""
    out, cur = {}, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            cur = line.strip()
            continue
        if cur == path and ":" in line:
            k, v = line.strip().split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def test_ai_lab_headers_have_hsts_and_a_csp_that_does_not_limit_sources():
    print("\n■ AI集客ラボの _headers: HSTS と、読み込み先を縛らない CSP（2026-10-11）")
    h = _block((ROOT / "site" / "_headers").read_text(encoding="utf-8"))
    check("HSTS は1年・サブドメインまで", h.get("strict-transport-security"), "max-age=31536000; includeSubDomains")
    csp = {p.strip().split(" ", 1)[0]: p.strip() for p in h.get("content-security-policy", "").split(";") if p.strip()}
    check("CSP の守りの項目（枠は同じドメインだけ・base・object・フォームの送り先・http を https へ）",
          [csp.get("frame-ancestors"), csp.get("base-uri"), csp.get("object-src"), csp.get("form-action"),
           csp.get("upgrade-insecure-requests")],
          ["frame-ancestors 'self'", "base-uri 'self'", "object-src 'none'", "form-action 'self'",
           "upgrade-insecure-requests"])
    check("CSP は読み込み先を縛らない（script-src・default-src・connect-src・img-src・style-src・frame-src が無い）",
          sorted(set(csp) & {"script-src", "default-src", "connect-src", "img-src", "style-src", "frame-src"}), [])
    check("今までの守りの項目は残す",
          [h.get("x-content-type-options"), h.get("x-frame-options"), h.get("referrer-policy")],
          ["nosniff", "SAMEORIGIN", "strict-origin-when-cross-origin"])


def test_form_action_self_covers_every_form_on_the_site():
    print("\n■ form-action 'self' で、サイトのどのフォームも送れる（外部へ送るフォームが増えたら CSP に足す）")
    rx = re.compile(r"<form\b[^>]*?\baction=\"([^\"]*)\"", re.I)
    outside = set()
    for f in (ROOT / "site").rglob("*.html"):
        for a in rx.findall(f.read_text(encoding="utf-8", errors="ignore")):
            if re.match(r"(?i)(https?:)?//", a) and not re.match(r"(?i)(https?:)?//ai\.7senses\.co\.jp(/|$)", a):
                outside.add(a)
    for f in [*(ROOT / "templates").glob("*.html"), *(ROOT / "scripts").glob("*.py")]:
        for a in rx.findall(f.read_text(encoding="utf-8", errors="ignore")):
            if re.match(r"(?i)(https?:)?//", a):
                outside.add(a)
    check("外部へ送るフォームが無い", sorted(outside), [])


def test_youtube_blocked_reads_a_csp_without_source_limits_as_allowed():
    print("\n■ publish.youtube_blocked: 読み込み先を縛らない CSP は YouTube の埋め込みを通す（2026-10-11）")
    import publish as P
    cases = {
        "守りの形（frame-src も default-src も無い）": "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; "
                                                   "form-action 'self' https://ai.7senses.co.jp; upgrade-insecure-requests",
        "コーポレートと同じ（frame-src が Google マップだけ）": "default-src 'self'; frame-src https://www.google.com",
        "frame-src に YouTube": "default-src 'self'; frame-src https://www.youtube-nocookie.com",
        "default-src だけで YouTube が無い": "default-src 'self'",
    }
    got = {}
    with tempfile.TemporaryDirectory() as td:
        for name, csp in cases.items():
            dest = Path(td) / str(len(got))
            dest.mkdir()
            (dest / "_headers").write_text(f"# CSP の説明の行\n/*\n  content-security-policy: {csp}\n", encoding="utf-8")
            got[name] = P.youtube_blocked(dest)
    check("縛らない CSP は通す・frame-src に YouTube が無ければ止める（名前の大文字小文字は問わない）",
          got, {"守りの形（frame-src も default-src も無い）": False,
                "コーポレートと同じ（frame-src が Google マップだけ）": True,
                "frame-src に YouTube": False, "default-src だけで YouTube が無い": True})
