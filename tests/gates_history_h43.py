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
        t2["draft"] = dict(GOOD)
        d["targets"].append(t2)
        O.approve(t2, "テスト")
        later = O.now() + timedelta(days=89)
        why89 = O.blockers(d, t2, when=later)
        why91 = O.blockers(d, t2, when=O.now() + timedelta(days=91))
        check("同じ媒体へは90日送らない（89日目は止め、91日目は通す）",
              (any("90日" in w for w in why89), why91), (True, []))
        t3 = _target("06", domain="other.example.jp")
        t3["draft"] = dict(GOOD)
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
