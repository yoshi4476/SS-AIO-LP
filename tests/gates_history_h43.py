# -*- coding: utf-8 -*-
"""言及の依頼を承認制の半自動にする（outreach.py・2026-10-07 運用者の依頼）。

外へは何も送らない。送信は偽の関数、Claude は偽の応答、置き場は一時フォルダに差し替えて確かめる:

  - 承認なしでは送らない。承認の後に文面を変えたら送らない。配信停止・やめた宛先には送らない
  - 下書きに材料（当社の公開ページ・登録済みの一次情報）に無い数字があれば捨てる（3回とも外れたら下書きを残さない）
  - 採択率・支援社数・料金・お客様の声・掲載の見返り・当社以外のURLを止める
  - 送信者情報（社名・住所・電話・メール）と配信停止の案内を機械が必ず付ける
  - 同じ媒体（ドメイン）へは90日送らない。1日10通まで
  - 宛先・連絡先・下書き・送った記録は public に置かない（data/outreach/ は .gitignore）
  - md の宛先の表を読む（メール／フォーム／手で出す、有料は保留）。掲載は mentions の台帳と照合する
"""
import contextlib
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path

from test_gates import check, ROOT

MAT = {"pages": [("https://ai.7senses.co.jp/research/dental-ai-sources/",
                  "歯科の質問100問を4つのAIに聞いた（2026-10-02・出典の合計2,437件）。地域で探す質問では出典の73.1%が"
                  "予約・比較ポータル、21.3%が医院の公式サイト。費用・治療などの質問では回答の96.5%が公式サイトを出典にした。")],
       "facts": ["2020年3月創業、大阪市東成区を拠点に店舗集客とAI活用を支援しています"]}

GOOD_BODY = ("日本歯科新聞 編集部 御中\n\n大阪市でWeb集客の支援をしているセブンセンシズ株式会社の原口と申します。"
             "歯科医院に関わる調査結果を公開しましたので、情報提供としてお送りします。\n\n"
             "患者が調べそうな質問100問を、ChatGPT・Gemini・Claude・Perplexity の4つのAIに聞き、"
             "回答の出典になったサイトを種類ごとに数えました（2026年10月2日・出典の合計2,437件）。\n"
             "地域で歯医者を探す質問では、出典の73.1%が予約・比較ポータルで、医院の公式サイトは21.3%でした。"
             "費用・治療などを調べる質問では、回答の96.5%が医院の公式サイトを出典にしていました。\n\n"
             "調査ページ: https://ai.7senses.co.jp/research/dental-ai-sources/\n"
             "出典（社名・調査名・URL・調査年月）を明記いただければ、自由にお使いいただけます。")
GOOD = {"subject": "歯科の質問100問をAI 4種に聞き、回答の出典を数えた調査のご案内", "body": GOOD_BODY}

SAMPLE_MD = """# 宛先

## 1. 宛先の一覧

### A. 医療

| # | 優先 | 名称／URL | 窓口 | 持ち込むもの | 費用 | 理由・確認方法 |
|:--|:--|:--|:--|:--|:--|:--|
| 1 | A | 例の歯科新聞 https://dental.example.jp/ | 情報提供フォーム https://forms.example.com/abc | 歯科の調査 | 無料 | 窓口はページで確認 |
| 2 | B | 例のマーケ媒体 https://www.mk.example.jp/ | release@mk.example.jp （https://www.mk.example.jp/faq ） | 調査公開のプレスリリース | 無料 | ページで確認 |
| 3 | C | 例の配信サービス https://pr.example.jp/ | 企業登録して配信 | 同上 | **有料** | 予算が付いたときだけ |
| — | A | （本人が記入） | 先方の担当者 | 事例 | 無料 | 本人が選ぶ |

## 2. 依頼文の下書き

| 9 | A | ここは読まない https://x.example/ | a@x.example | x | 無料 | x |
"""


@contextlib.contextmanager
def sandbox(O):
    """置き場を一時フォルダに、材料を固定のものに差し替える"""
    old = (O.STORE_DIR, O.material)
    with tempfile.TemporaryDirectory() as d:
        O.STORE_DIR, O.material = Path(d) / "outreach", (lambda t: MAT)
        try:
            yield Path(d)
        finally:
            O.STORE_DIR, O.material = old


def _target(i="01", domain="dental.example.jp", channel="email"):
    return {"id": i, "name": "例の歯科新聞", "media_url": f"https://{domain}/", "domain": domain,
            "channel": channel, "contact": "edit@dental.example.jp" if channel == "email" else "https://forms.example.com/a",
            "kind": "情報提供", "bring": "歯科の調査", "status": "new"}


def test_outreach_is_approved_and_checked_before_sending():
    import outreach as O
    print("\n■ 言及の依頼（承認制）")
    with sandbox(O) as tmp:
        md = tmp / "list.md"
        md.write_text(SAMPLE_MD, encoding="utf-8")
        check("取り込み: 番号のある行だけ・第2章は読まない", O.import_md(md), 3)
        d = O.load()
        by = {t["id"]: t for t in d["targets"]}
        check("取り込み: フォーム／メール／手で出す、有料は保留",
              [(by["01"]["channel"], by["01"]["contact"]), (by["02"]["channel"], by["02"]["contact"], by["02"]["domain"]),
               (by["03"]["channel"], by["03"]["status"])],
              [("form", "https://forms.example.com/abc"), ("email", "release@mk.example.jp", "mk.example.jp"),
               ("manual", "hold")])
        by["01"]["status"] = "sent"
        O.save(d)
        O.import_md(md)
        check("取り込み直し: 送った状況を消さない", O.find(O.load(), "01")["status"], "sent")

        # 下書き: 材料に無い数字は3回とも外れれば捨てる
        calls = []

        def bad(prompt):
            calls.append(prompt)
            return '{"subject": "調査のご案内", "body": "%s"}' % GOOD_BODY.replace("73.1%", "80%").replace("\n", "\\n")
        t = _target()
        check("下書き: 材料に無い数字（80%）は捨てる", (O.draft_one(t, ask=bad), "draft" in t, len(calls)),
              (False, False, O.MAX_TRIES))
        check("下書き: 書き直しの指示に外れた理由を渡す", "材料に無い数字: 80" in calls[-1], True)
        check("下書き: 指示に見返り・料金・署名を書かせない決まりがある",
              all(w in calls[0] for w in ("見返り", "料金", "署名", "配信停止")), True)
        good = lambda p: '{"subject": "%s", "body": "%s"}' % (GOOD["subject"], GOOD_BODY.replace("\n", "\\n"))
        check("下書き: 材料の数字だけなら残す", (O.draft_one(t, ask=good), t.get("status")), (True, "drafted"))

        # 検査: 止めるもの
        cases = {"採択率": GOOD_BODY + "\n当社の採択率は90%です。",
                 "料金": GOOD_BODY + "\n当社の運用は月額でご提供しています。",
                 "お客様の声": GOOD_BODY + "\nお客様の声も多数いただいています。",
                 "見返り": GOOD_BODY + "\n掲載いただけましたら、当社サイトからもご紹介します。",
                 "リンクのお願い": GOOD_BODY + "\n記事からリンクを張っていただけますと幸いです。",
                 "当社以外のURL": GOOD_BODY + "\nhttps://example.com/x",
                 "旧サイト": GOOD_BODY + "\nhttps://www.7senses.co.jp/"}
        check("検査: 採択率・料金・声・見返り・リンクのお願い・他のURL・旧サイトを止める",
              {k: bool(O.inspect(GOOD["subject"], v, MAT)) for k, v in cases.items()},
              {k: True for k in cases})
        check("検査: 正しい下書きは通す", O.inspect(GOOD["subject"], GOOD_BODY, MAT), [])
        check("数字の読み: 桁区切り・全角・10.0 をそろえ、URLの中は数えない",
              O.numbers("２，４３７件と10.0件 https://a.example/2026/99"), {"2437", "10"})

        # 送信者情報
        s, b = O.compose(t)
        c = O.company()
        check("送信者情報: 社名・住所・電話・メール・配信停止の案内を必ず付ける",
              (O.has_sender_info(b), b.startswith(GOOD_BODY), c["corporate_number"] in b), (True, True, True))

        # 承認
        d = O.load()
        d["targets"].append(t)
        sent = []
        mailer = lambda to, subj, text, reply: sent.append((to, subj, text, reply)) or "msg-1"
        check("承認なしでは送らない", (O.send_approved(d, t, mailer)[0], sent), (False, []))
        O.approve(t, "テスト")
        t["draft"]["body"] += "\n追記"
        ok, why = O.send_approved(d, t, mailer)
        check("承認の後に文面を変えたら送らない", (ok, sent, any("承認の後" in w for w in why)), (False, [], True))
        t["draft"]["body"] = GOOD_BODY
        O.approve(t, "テスト")
        ok, why = O.send_approved(d, t, mailer)
        check("承認したものは送る（送信者情報つき・返信先は会社の窓口）",
              (ok, len(sent), O.has_sender_info(sent[0][2]) if sent else None, sent[0][3] if sent else None),
              (True, 1, True, c["email"]))
        log = O.sent_log()
        check("送った記録: いつ・どの宛先・誰の承認", (len(log), log[0]["id"], log[0]["approved_by"], t["status"]),
              (1, "01", "テスト", "sent"))

        # 90日・上限・配信停止
        t2 = _target("05")
        t2["draft"], t2["status"] = dict(GOOD), "drafted"
        d["targets"].append(t2)
        O.approve(t2, "テスト")
        later = O.now() + timedelta(days=89)
        why89 = O.blockers(d, t2, when=later)
        why91 = O.blockers(d, t2, when=O.now() + timedelta(days=91))
        check("同じ媒体へは90日送らない（89日目は止め、91日目は通す）",
              (any("90日" in w for w in why89), why91), (True, []))
        t3 = _target("06", domain="other.example.jp")
        t3["draft"], t3["status"] = dict(GOOD), "drafted"
        O.approve(t3, "テスト")
        d["targets"].append(t3)
        today = O.now().isoformat(timespec="seconds")
        many = [{"at": today, "id": str(i), "domain": f"d{i}.example"} for i in range(O.DAILY_CAP)]
        check("1日の上限（10通）を超えて送らない",
              (O.DAILY_CAP, any("上限" in w for w in O.blockers(d, t3, log=many)), O.blockers(d, t3, log=many[:-1])),
              (10, True, []))
        t3["status"] = "stopped"
        check("配信停止の宛先には送らない", any("配信停止" in w for w in O.blockers(d, t3, log=[])), True)
        t4 = _target("07", channel="form")
        t4["draft"] = dict(GOOD)
        check("フォームの窓口は送らない（貼って送ったあと承認つきで記録するだけ）",
              (O.send_approved(d, t4, mailer)[0], O.mark_posted(d, t4)[0], len(sent)), (False, False, 1))

        # 掲載の照合
        n = O.track(d, [{"url": "https://dental.example.jp/news/123", "added": "2999-01-01"}])
        # 取り込んだ 01（同じ媒体・送った）と、ここで送った宛先の2件
        check("mentions の台帳に載った媒体を「掲載された」にする", (n, t["status"], t.get("mention")),
              (2, "published", "https://dental.example.jp/news/123"))
        check("掲載の照合: 送っていない宛先は変えない", O.track(d, [{"url": "https://other.example.jp/a",
                                                         "added": "2999-01-01"}]), 0)

    # 公開しない
    ign = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "data/outreach/targets.json"]).returncode
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "data/outreach"], capture_output=True, text=True).stdout
    check("宛先・下書き・記録は public に置かない（.gitignore・追跡なし・置き場は data/outreach）",
          (ign, tracked.strip(), O.STORE_DIR == ROOT / "data" / "outreach"), (0, "", True))
    src = (ROOT / "scripts" / "outreach.py").read_text(encoding="utf-8")
    check("送るのは承認の画面からだけ（main は送信を呼ばない）",
          "send_approved(" not in src.split("def main(")[1], True)
    t = {"bring": "歯科の調査（地域で探す質問）"}
    check("材料: 持ち込むものから当社の調査ページを選ぶ",
          [u for u, _ in O.material(t)["pages"]], ["https://ai.7senses.co.jp/research/dental-ai-sources/"])
    check("材料: サービスの成績・店舗数の一次情報は使わない",
          any("3,200" in f or "継続率" in f for f in O.material(t)["facts"]), False)


def _md(rows):
    head = "## 1. 宛先\n\n| # | 優先 | 名称 | 窓口 | 持ち込むもの | 費用 | 理由 |\n|--|--|--|--|--|--|--|\n"
    return head + "".join(f"| {r} |\n" for r in rows)


def _drafted(O, i, **kw):
    t = {**_target(i), "draft": dict(GOOD), "status": "drafted", **kw}
    return t


def test_outreach_holes_found_2026_10_07():
    """2026-10-07 の敵対的な見直しで再現した穴（送信・Claude・Resend はすべて偽物）"""
    import urllib.error
    import urllib.request
    import outreach as O
    import send_reports as SR
    print("\n■ 言及の依頼: 見直しで見つけた穴")
    with sandbox(O) as tmp:
        md = tmp / "a.md"
        # 1. メールだけの宛先（名称にも窓口にもURLが無い）。以前は媒体の鍵が空で、90日も配信停止も効かなかった
        md.write_text(_md(["1 | A | メールだけの媒体 | news@mailonly.example.jp | 歯科の調査 | 無料 | x",
                           "2 | A | 同じ窓口の別名 | news@mailonly.example.jp | 歯科の調査 | 無料 | x",
                           "3 | A | フォームだけの媒体 | https://forms.gle/aaa | 歯科の調査 | 無料 | x",
                           "4 | A | 別のフォームだけの媒体 | https://forms.gle/bbb | 歯科の調査 | 無料 | x"]),
                      encoding="utf-8")
        O.import_md(md)
        d = O.load()
        by = {t["id"]: t for t in d["targets"]}
        check("媒体の鍵: メールだけの宛先は @ の後ろ、共用のフォームは窓口そのもの（Google フォームどうしを同じ媒体にしない）",
              [by[i]["domain"] for i in ("01", "03", "04")],
              ["mailonly.example.jp", "https://forms.gle/aaa", "https://forms.gle/bbb"])
        for t in d["targets"]:
            t["draft"], t["status"] = dict(GOOD), "drafted"
        sent = []
        mailer = lambda to, s, b, r: sent.append(to) or "m"
        O.approve(by["01"], "テスト")
        check("メールだけの宛先も送れる", O.send_approved(d, by["01"], mailer)[0], True)
        O.approve(by["02"], "テスト")
        check("同じ宛先へは、媒体名が違っても90日送らない",
              any("90日" in w for w in O.blockers(d, by["02"])), True)
        check("送った宛先は承認が残っていても送らない（下書きあり以外は止める）",
              any("状況" in w for w in O.blockers(d, by["01"])), True)
        O.approve(by["04"], "テスト")
        check("別の Google フォームの媒体は止め合わない", O.blockers(d, by["04"], log=[]), [])
        by["03"]["status"] = "stopped"
        check("配信停止は同じ窓口にだけ効く（同じフォーム・サービスの別媒体は巻き込まない）",
              (O.blockers(d, by["04"], log=[]), any("配信停止" in w for w in O.blockers(d, {**by["03"], "status": "drafted",
                                                                                         "id": "99"}, log=[]))),
              ([], True))

        # 2. 送れたか分からない失敗（読み取りのタイムアウト）。以前は下書きのまま残り、もう一度押すと二重に送れた
        t = _drafted(O, "10", domain="t10.example.jp", contact="a@t10.example.jp")
        d["targets"].append(t)
        O.approve(t, "テスト")

        def timeout(*a):
            raise TimeoutError("read timed out")
        ok, why = O.send_approved(d, t, timeout)
        O.approve(t, "テスト")
        check("送れたか不明: 「不明」にして送らない（送った記録には入れない）",
              (ok, t["status"], any("状況" in w for w in O.blockers(d, t)), len(O.sent_log())),
              (False, "unknown", True, 1))
        n0 = len(O.sent_log())
        O.resolve(d, t, sent=True)
        check("送れたか不明 → 届いていたと確かめたら送った記録へ（90日・上限に数える）",
              (t["status"], len(O.sent_log()) - n0, O.sent_log()[-1]["approved_by"]), ("sent", 1, "テスト"))
        t11 = _drafted(O, "11", domain="t11.example.jp", contact="a@t11.example.jp")
        d["targets"].append(t11)
        O.approve(t11, "テスト")
        O.send_approved(d, t11, timeout)
        O.resolve(d, t11, sent=False)
        check("送れたか不明 → 届いていなければ下書きへ戻し、承認はやり直し", (t11["status"], "approval" in t11),
              ("drafted", False))

        def rejected(*a):
            raise urllib.error.HTTPError("https://api.resend.com/emails", 422, "bad", {}, None)
        O.approve(t11, "テスト")
        try:
            O.send_approved(d, t11, rejected)
            raised = False
        except urllib.error.HTTPError:
            raised = True
        check("Resend が受け付けなかった（4xx）は送った記録にも不明にもしない",
              (raised, t11["status"], len(O.sent_log()) - n0), (True, "drafted", 1))

        # 3. 承認の画面の「送る」（submit）: フォームは上限・90日を開く前に確かめる
        f = _drafted(O, "12", channel="form", domain="f12.example.jp")
        f["contact"] = "https://f12.example.jp/form"
        d["targets"].append(f)
        opened, copied = [], []
        full = [{"at": O.now().isoformat(timespec="seconds"), "id": str(i), "domain": f"x{i}.example"}
                for i in range(O.DAILY_CAP)]
        old_log = O.sent_log
        O.sent_log = lambda: full
        ok, why = O.submit(d, f, lambda *a: True, copied.append, opened.append)
        O.sent_log = old_log
        check("フォーム: 上限に当たっていればコピーもフォームを開くこともしない（送った後に記録できない、を防ぐ）",
              (ok, copied, opened, any("上限" in w for w in why), "approval" in f), (False, [], [], True, False))
        ok, _ = O.submit(d, f, lambda title, text: title != "フォーム", copied.append, opened.append)
        check("フォーム: 貼って送っていなければ記録せず、承認も外す", (ok, f["status"], "approval" in f, len(opened)),
              (None, "drafted", False, 1))
        n1 = len(O.sent_log())
        ok, _ = O.submit(d, f, lambda *a: True, copied.append, opened.append)
        check("フォーム: 貼って送ったら必ず記録する", (ok, f["status"], len(O.sent_log()) - n1), (True, "sent", 1))
        e = _drafted(O, "13", domain="e13.example.jp", contact="a@e13.example.jp")
        d["targets"].append(e)
        sent.clear()
        check("メール: 人が「送る」でやめたら送らない",
              (O.submit(d, e, lambda title, text: title != "送る", mailer=mailer)[0], sent), (None, []))
        check("メール: 人が確かめたら承認して送る", (O.submit(d, e, lambda *a: True, mailer=mailer)[0], sent),
              (True, ["a@e13.example.jp"]))

        # 4. 取り込み直しで費用が有料になった下書きは保留へ戻す
        md.write_text(_md(["7 | A | 例 https://m7.example.jp/ | news@m7.example.jp | 歯科の調査 | 無料 | x"]), encoding="utf-8")
        O.import_md(md)
        d = O.load()
        t7 = O.find(d, "07")
        t7["draft"], t7["status"] = dict(GOOD), "drafted"
        O.save(d)
        md.write_text(md.read_text(encoding="utf-8").replace("| 無料 |", "| 有料（月3万円） |"), encoding="utf-8")
        O.import_md(md)
        check("取り込み直し: 下書きの後に有料になったら保留へ戻す", O.find(O.load(), "07")["status"], "hold")

    # 5. 漢字の数・「3千」が材料の数字の検査をすり抜けていた
    check("検査: 漢字の数（八割・二百社）と「3千社」を材料に無い数字として止める",
          [bool(O.inspect(GOOD["subject"], GOOD_BODY + x, MAT)) for x in
           ("\n歯科医院の八割がAIで探されています。", "\n二百社が導入しました。", "\n3千社が対象です。")],
          [True, True, True])
    check("検査: 材料にある数の漢字（四つのAI）と、数でない語（十分・一部）は止めない",
          O.inspect(GOOD["subject"], GOOD_BODY + "\n四つのAIに聞き、十分に確かめ、一部を公開しました。", MAT), [])
    check("数字の読み: 漢字の数・千万の単位", O.numbers("三千二百件・二〇二六年・2.4万件・八割"),
          {"3200", "2026", "24000", "8"})

    # 6. Resend の呼び方: List-Unsubscribe に生の日本語を置かない・送り直しを1通にまとめる鍵を付ける
    cap = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"id": "x"}'
    old = (urllib.request.urlopen, SR.env)
    urllib.request.urlopen = lambda req, timeout=0: cap.setdefault("req", req) and Resp()
    SR.env = lambda k, default="": {"RESEND_API_KEY": "re_test"}.get(k, default)
    try:
        O.resend_mail("a@b.example", "件名", "本文", "info@example.jp")
    finally:
        urllib.request.urlopen, SR.env = old
    import json
    hd = json.loads(cap["req"].data)["headers"]["List-Unsubscribe"]
    check("Resend: List-Unsubscribe は ASCII だけ（件名は %XX）・Idempotency-Key を付ける",
          (hd.isascii(), "subject=%E9%85%8D" in hd, bool(cap["req"].get_header("Idempotency-key"))), (True, True, True))

    # 7. 掲載の照合: 登録日の無い言及を「依頼の後に載った」と数えない
    t = {**_target("20", domain="m20.example.jp"), "status": "sent", "sent_at": "2026-10-07T10:00:00+09:00"}
    with sandbox(O):
        check("掲載の照合: 登録日の無い言及・自社の言及は数えない",
              O.track({"targets": [t]}, [{"url": "https://m20.example.jp/old"},
                                         {"url": "https://m20.example.jp/own", "added": "2999-01-01", "third": False}]),
              0)

    # 8. フォームに貼る文面で「本メールにご返信」と書かない（返信できない窓口）
    fb = O.footer({"channel": "form", "contact": "https://f.example/"})
    check("署名: フォームの文面は「本メールにご返信」と書かず、配信停止の窓口は会社のメール",
          ("本メール" in fb, O.has_sender_info(fb)), (False, True))


def test_outreach_second_review_2026_10_07():
    """2026-10-07 の2回目の見直しで再現した穴（送信はすべて偽物）"""
    import outreach as O
    print("\n■ 言及の依頼: 2回目の見直しで見つけた穴")
    url = "https://ai.7senses.co.jp/research/dental-ai-sources/"
    # 1. 当社URLの直後に空白なしで続く文の数字・他社URLが、URL の一部とみなされて検査を素通りした
    check("検査: 当社URLの直後に空白なしで続く、材料に無い数字を止める",
          bool(O.inspect(GOOD["subject"], GOOD_BODY + f"\n詳しくは {url}では997件が誤りでした。", MAT)), True)
    check("検査: 当社URLの直後に空白なしで続く他社URLを止める",
          bool(O.inspect(GOOD["subject"], GOOD_BODY + f"\n{url}やhttps://other.example/x", MAT)), True)
    # 2. http の無い他社URL
    check("検査: http の無い他社のURL（example.com/x・www.example.co.jp）を止める",
          [bool(O.inspect(GOOD["subject"], GOOD_BODY + f"\n参考: {u}", MAT))
           for u in ("example.com/x", "www.example.co.jp", "HTTPS://example.com/x")], [True, True, True])
    check("検査: 当社のドメインだけの書き方・Next.js のような語は止めない",
          O.inspect(GOOD["subject"], GOOD_BODY + "\nai.7senses.co.jp で公開し、Next.js で作りました。", MAT), [])

    with sandbox(O):
        O.save({"targets": [_drafted(O, "01"), {**_target("02", domain="m2.example.jp"), "status": "new"},
                            _drafted(O, "03", domain="m3.example.jp", contact="a@m3.example.jp")]})
        # 3. 承認の画面を開いたまま --draft を走らせると、画面の保存が下書きを消した
        screen = O.load()
        draft = O.load()
        t2 = O.find(draft, "02")
        t2["draft"], t2["status"] = dict(GOOD), "drafted"
        O.save(draft)
        O.edit_draft(O.find(screen, "01"), GOOD["subject"] + "（直した）", GOOD_BODY)
        O.save(screen)
        now = O.load()
        check("同時の保存: 画面の保存が、その間に --draft が書いた下書きを消さない（画面の直しも残る）",
              (O.find(now, "02")["status"], "（直した）" in O.find(now, "01")["draft"]["subject"]), ("drafted", True))
        # 4. --draft の途中に --stop が入ると、--draft の保存が配信停止を消した
        draft = O.load()
        cli = O.load()
        O.find(cli, "03")["status"] = "stopped"
        O.save(cli)
        O.find(draft, "03")["draft"]["subject"] += "x"
        O.save(draft)
        check("同時の保存: 配信停止は、ほかの工程の保存で消えない", O.find(O.load(), "03")["status"], "stopped")
        # 5. 画面を開いた後に --stop が入っても、画面の「送る」は読んだ時点の台帳のまま送った
        screen = O.load()
        cli = O.load()
        O.find(cli, "01")["status"] = "stopped"
        O.save(cli)
        sent = []
        ok, why = O.submit(screen, O.find(screen, "01"), lambda *a: True, mailer=lambda *a: sent.append(a) or "m")
        check("送る直前に読み直す: 画面を開いた後の配信停止で止める",
              (ok, sent, any("配信停止" in w or "状況" in w for w in why)), (False, [], True))
        # 6. 配信停止の後に返事を記録すると「返事あり」になり、停止が外れた（同じ媒体の別の宛先へ送れた）
        import sys as _s
        old = _s.argv
        try:
            _s.argv = ["outreach.py", "--reply", "03", "配信停止の旨の返信"]
            with contextlib.redirect_stdout(__import__("io").StringIO()):
                O.main()
        finally:
            _s.argv = old
        check("返事の記録: 配信停止の宛先は停止のまま", O.find(O.load(), "03")["status"], "stopped")
