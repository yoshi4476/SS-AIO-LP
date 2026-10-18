# -*- coding: utf-8 -*-
"""2026-10-18 無料診断を使った営業の下書き（prospect_outreach.py）の門。

検索から来る人の大半が「自分でやる人」で、AI集客ラボの相談は90日で0件だった。こちらから診断の結果を届ける。
送ってよい宛先（公表されたアドレス・お断りの記載なし）・文面（診断の結果に無い数字・料金・約束を書かない）・
送信者の情報・承認の後に文面が変わったら送らない・CI では送らない・相談につながったかを台帳で追える、を確かめる。
"""
import json
import os
import subprocess
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

CO = {"name": "例示株式会社", "corporate_number": "1234567890123", "ceo": "山田太郎", "postal": "530-0001",
      "address": "大阪府大阪市北区梅田1-2-3", "tel": "06-0000-0000", "hours": "平日9:00〜18:00",
      "email": "info@zz.example", "sites": {"ai-lab": "https://ai.zz.example/"}}


def _t(**kw):
    t = {"id": "0007", "name": "テスト歯科", "url": "https://zz-dental.example/", "host": "zz-dental.example",
         "industry": "歯科", "email": "info@zz-dental.example", "where": "https://zz-dental.example/contact/",
         "status": "audited", "events": [],
         "audit": {"score": 62, "grade": "C", "url": "https://zz-dental.example/", "items": 14,
                   "ng": [{"name": "AIクローラーの許可", "pts": 10, "advice": "robots.txt で GPTBot を止めています"},
                          {"name": "構造化データ", "pts": 8, "advice": "会社情報の構造化データがありません"}]}}
    t.update(kw)
    return t


def test_prospect_outreach_rules():
    import prospect_outreach as P
    print("\n■ 営業の下書き: 宛先・文面・承認・送信・リードの追い方")
    t = _t()
    s, b = P.compose(t, CO)
    check("文面: 点数・項目・御社のURLつきの診断ページ・申込ページ・印（ref）が入る",
          ("62点" in s, "AIクローラーの許可" in b, "url=https%3A%2F%2Fzz-dental.example%2F" in b,
           "ref=pr-0007" in b, "/lp/?ref=pr-0007#form" in b), (True,) * 5)
    check("文面: 送信者の名称・住所・電話・メールと配信停止の案内", P.inspect(t, s, b, CO), [])
    check("文面: 診断に無い数字・料金・約束は止める",
          (bool(P.inspect(t, s, b + "\n導入した30社で成果", CO)), bool(P.inspect(t, s, b + "\n月額3万円", CO)),
           bool(P.inspect(t, s, b + "\n必ず上がります", CO))), (True, True, True))
    check("宛先: メールなし・掲載元なし・別ドメインのアドレス・掲載元が他所 は送れない",
          [bool(P.blocked_reason(_t(email=""))), bool(P.blocked_reason(_t(where=""))),
           bool(P.blocked_reason(_t(email="x@gmail.com"))), bool(P.blocked_reason(_t(where="https://portal.example/x/"))),
           P.blocked_reason(_t())], [True, True, True, True, ""])
    page_ok = "<p>お問い合わせ: info@zz-dental.example</p>"
    page_ng = page_ok + "<p>営業目的のメールはお断りしております。</p>"
    check("掲載元: アドレスがあり・お断りの記載が無いときだけ通す",
          (P.check_where(_t(), lambda u: page_ok), bool(P.check_where(_t(), lambda u: page_ng)),
           bool(P.check_where(_t(), lambda u: "<p>電話のみ</p>"))), ("", True, True))
    d = {"0007": _t(status="approved")}
    check("承認していない・承認の後に文面が変わった分は送らない",
          (bool(P.send_blockers(d, _t())), bool(P.send_blockers(d, _t(status="approved", approved_digest="x"), log=[]))),
          (True, True))
    ok = _t(status="approved")
    ok["approved_digest"] = P.digest(*P.compose(ok))
    d = {"0007": ok}
    check("条件を満たせば送れる・同じ会社へは期間内に2回送らない・配信停止の会社へは送らない",
          (P.send_blockers(d, ok, log=[]),
           bool(P.send_blockers(d, ok, log=[{"host": ok["host"], "at": P.now().isoformat()}])),
           bool(P.send_blockers({"0007": ok, "0008": _t(id="0008", status="stopped")}, ok, log=[]))),
          ("", True, True))
    old = os.environ.get("GITHUB_ACTIONS")
    os.environ["GITHUB_ACTIONS"] = "true"
    try:
        sent = P.send({"0007": ok}, mailer=lambda *a: (_ for _ in ()).throw(AssertionError("CI で送った")))
    finally:
        if old is None:
            os.environ.pop("GITHUB_ACTIONS", None)
        else:
            os.environ["GITHUB_ACTIONS"] = old
    check("CI では送らない", sent, 0)
    store = P.STORE
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        P.STORE = type(store)(tmp) / "p.json"
        try:
            d = {"0007": _t(status="sent")}
            hits = P.track(d, rows=[{"day": "2026-10-20", "route": "紹介元 pr-0007 / 記事", "type": "相談", "temp": "WARM"},
                                    {"day": "2026-10-20", "route": "紹介元 pr-00070", "type": "相談", "temp": ""}])
        finally:
            P.STORE = store
    check("リード: 台帳の「紹介元 pr-<id>」で、その見込み先の相談として記録する（別の番号と取り違えない）",
          (hits, d["0007"]["status"], len(d["0007"]["lead"])), (1, "lead", 1))
    ign = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "data/prospects/prospects.json"]).returncode
    check("見込み先・連絡先・送った記録は公開リポジトリに置かない", ign, 0)
    js = (ROOT / "functions" / "api" / "audit.js").read_text(encoding="utf-8")
    check("営業のための診断（ref=prospect）は診断の記録・同業の平均に入れない",
          ('body.ref === "prospect"' in js, "!own && !prospect" in js), (True, True))


def test_publish_gap_redelivers_unconverted_markdown():
    import json
    import tempfile
    from pathlib import Path
    import publish_gap as PG
    print("\n■ 配信の照合: 配った記事に変換漏れ（** など）があれば「内容が古い」として配り直す")
    with tempfile.TemporaryDirectory() as d:
        c = {"type": "nextjs-json", "content_dir": "src/content/blog", "id": "client-zz"}
        p = Path(d) / c["content_dir"]
        p.mkdir(parents=True)
        (p / "bad.json").write_text(json.dumps({"html": "<p>**強調のまま。**ただし</p>"}, ensure_ascii=False), encoding="utf-8")
        (p / "good.json").write_text(json.dumps({"html": "<p><strong>強調。</strong>ただし</p>"}, ensure_ascii=False), encoding="utf-8")
        got = PG.delivered_leftovers(c, ["bad", "good", "none"], work=d)
        other = PG.delivered_leftovers({**c, "type": "external-html"}, ["bad"], work=d)
    check("変換漏れの記事だけを拾う・作業コピーに無い記事と他の配信方式は見ない", (got, other), (["bad"], []))


def test_writers_do_not_get_private_data_urls():
    import json
    import facts as F
    import data_intake
    print("\n■ 一次データのページを止めている間は、書く AI に渡す出典から /data/ の URL を外す")
    f = {"id": "x", "claim": "10社の中央値", "source": "当社の一次データ「月次決算」 https://ai.7senses.co.jp/data/keiri/"}
    old = data_intake.PUBLIC
    try:
        data_intake.PUBLIC = False
        hidden = F.hide_private_urls(f)
        data_intake.PUBLIC = True
        shown = F.hide_private_urls(f)
    finally:
        data_intake.PUBLIC = old
    check("止めている間は URL を外し、出典の文は残す・公開中はそのまま",
          (hidden["source"], shown["source"] == f["source"], hidden["claim"]), ("当社の一次データ「月次決算」", True, "10社の中央値"))
    if not old:
        left = [s for s in ("corporate", "subsidy", "ai-lab")
                if any("ai.7senses.co.jp/data/" in json.dumps(x, ensure_ascii=False) for x in F.load_for(s)[1])]
        check("いまの登録で、書く AI に渡る出典に /data/ の URL が無い", left, [])
