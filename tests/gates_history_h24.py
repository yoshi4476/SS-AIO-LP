# -*- coding: utf-8 -*-
"""無料ツールの結果メールの「見てほしい」に、AIが「まず直す1か所」を返す仕組みの門（2026-10-05）。

結果メール（診断・サイト診断・AI紹介チェック）に運用者が決めた案内を足し、返信をGmailから拾って
Gemini で返す。相手に届く文面なので、文言・対象の種類・送ってよいかの検査・1スレッド1回・
1日の上限・フォームへの案内を固定する。Gmail・Gemini・台帳には触れない（ソースを読むだけ）。
"""
import re

from test_gates import check, ROOT

GS = ROOT / "automation" / "gas" / "contact.hub.gs"

OFFER = ["▼ 最初に直す1か所を、無料でお返事します",
         "今回の結果をもとに、御社がまず直すべき1か所と、その直し方をお返事します。",
         "このメールに「見てほしい」とだけご返信ください（2〜3営業日以内）。"]


def _func(src, name):
    m = re.search(r"^function " + re.escape(name) + r"\(.*?^}", src, re.S | re.M)
    return m.group(0) if m else ""


def test_review_reply_offer_and_auto_answer():
    src = GS.read_text(encoding="utf-8")
    print("\n■ 結果メールの「見てほしい」と、AIの自動回答")
    check("案内の文言は運用者が決めた3行のまま", all(s in src for s in OFFER), True)
    check("「担当が見て」とは書かない（AIが返すため）", "担当が見て" in src, False)
    reply = _func(src, "leadReply_")
    # 案内を付けるのは diagnosis / site_audit / AI紹介チェック（成功時）の3つだけ。資料請求には付けない
    check("案内を付ける箇所は3つ（診断・サイト診断・AI紹介チェック）", reply.count("offer = REVIEW_OFFER"), 3)
    dl = reply.split("type === 'download'")[1].split("} else if")[0] if "type === 'download'" in reply else ""
    check("資料請求の分岐には案内を付けない", bool(dl) and "REVIEW_OFFER" not in dl, True)
    check("AI紹介チェックは動かなかった回に付けない", "if (!failed) offer = REVIEW_OFFER;" in reply, True)
    from gates_history_d import replies, GAS
    out = replies("\n".join((GAS / f).read_text(encoding="utf-8") for f in ("hub.gs", "contact.hub.gs")))
    if out is None:
        print("  WARN  node が無いため、送られる文面は確かめられません")
    else:
        check("実際の文面: 診断・サイト診断・AI紹介チェックには付き、資料請求・問い合わせには付かない",
              {k: OFFER[2] in (out or {}).get(k, "") for k in ("diagnosis", "site_audit", "ai_check", "download", "contact")},
              {"diagnosis": True, "site_audit": True, "ai_check": True, "download": False, "contact": False})
    check("本文の組み立てに案内が入り、資料の案内の並びは問い合わせだけのまま",
          "body + offer + reco + materials + foot" in reply, True)

    check("禁止語（円・万円・保証・必ず・確実・担当の）を検査する",
          "const REVIEW_NG = ['円', '万円', '保証', '必ず', '確実', '担当の'];" in src, True)
    chk = _func(src, "reviewCheck_")
    check("検査は空・長さ・禁止語・結果に無いURLを見る",
          all(s in chk for s in ("'空'", "REVIEW_LEN.min", "REVIEW_LEN.max", "REVIEW_NG", "結果に無いURL")), True)
    one = _func(src, "reviewOne_")
    check("検査に外れたら作り直しは1回だけ（2回で打ち切り）", "for (let i = 0; i < 2; i++)" in one, True)
    check("作れなかったら相手には送らず運用者へ", "reviewAlert_(thread, ask.email, why)" in one
          and one.index("reviewAlert_(thread") < one.index("ask.msg.reply([who"), True)
    check("結果が見つからなければAIを呼ばずにフォームへ案内",
          one.index("if (!res)") < one.index("geminiText_(") and
          "結果が見つからなかったので、お問い合わせフォームからURLをお知らせください" in one, True)
    check("返信の最後にフォームへの固定文", "REVIEW_FORM_TEXT].join('\\n') + REPLY_FOOT" in one, True)
    check("フォームは LP の申込フォーム（#form）",
          "const REVIEW_FORM_URL = 'https://ai.7senses.co.jp/lp/#form';" in src
          and 'id="form"' in (ROOT / "site" / "lp" / "index.html").read_text(encoding="utf-8"), True)
    check("固定文は運用者の文言のまま",
          "'詳しくお聞きになりたい場合は、お問い合わせフォームからご連絡ください。\\n  ' + REVIEW_FORM_URL" in src, True)
    # 運用者の判断（2026-10-05）: 人が書いたともAIが書いたとも名乗らない。人を名乗るのは事実と違うので禁止のまま
    check("どちらとも名乗らない（AIの明記も担当の名乗りも無い）",
          ["AIで作成しています" in one, "担当" in one.replace("ご担当者", "")], [False, False])

    run = _func(src, "reviewReply")
    check("1スレッド1回: 処理済みのラベルを検索で除き、終わったら付ける",
          "-label:' + REVIEW_LABEL" in run and "th.addLabel(done)" in run, True)
    check("429・5xx はラベルを付けず次の回へ（3回まで）",
          "if (out === 'retry') continue;" in run and "REVIEW_MAX_TRY = 3" in src, True)
    check("1日の上限は30通", "const REVIEW_DAILY_MAX = 30;" in src and "reviewSentToday_" in run, True)
    check("同時に2つ動かない（二重に返さない）", "LockService.getScriptLock()" in run, True)
    top = _func(src, "replyTop_")
    check("引用の中の「見てほしい」を依頼と読まない", "最初に直す1か所を" in top and "^\\s*>" in top, True)
    check("記録は専用のシート（台帳の列を壊さない）", "insertSheet('自動回答')" in src, True)
    check("トリガーの設置関数があり、受信箱の確認をする",
          "function installReviewReplyTrigger()" in src and "everyMinutes(15)" in src
          and "GmailApp.getAliases()" in _func(src, "installReviewReplyTrigger"), True)
    check("モデルは ai_cite_check の既定と同じ・GEMINI_MODEL で上書き",
          "gemini-3.6-flash" in (ROOT / "scripts" / "ai_cite_check.py").read_text(encoding="utf-8")
          and "const REVIEW_MODEL = 'gemini-3.6-flash';" in src and "getProperty('GEMINI_MODEL')" in src, True)
    import gas_deploy as G
    check("gas_deploy が .env の GEMINI_API_KEY を埋める（無ければ空）",
          (G.fill("'GEMINI_KEY_XXXXXXXX'", {"GEMINI_API_KEY": "k"}), G.fill("'GEMINI_KEY_XXXXXXXX'", {})),
          ("'k'", "''"))
    check("鍵の実値をリポジトリに書かない", "const GEMINI_KEY_FILL = 'GEMINI_KEY_XXXXXXXX';" in src, True)
