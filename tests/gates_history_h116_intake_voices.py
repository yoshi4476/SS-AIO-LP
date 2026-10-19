# -*- coding: utf-8 -*-
"""2026-10-20 運用者の指示: ヒアリングシートに自社の数字・お客さんの一言・声・過去の事例の項目を入れる。

自社の数字は5つ、お客さんの一言は3つ（新設）、過去の事例は4つ（依頼前の困りごと・やったこと・期間つき）、お客様の声は4つ。
一言と、掲載が「可」で本人の確認が「済」の事例は、非公開の clients/<id>/experiences.json（体験の台帳）に入り、
originality が「登録した体験」として通す。使ってよいと書かれていないもの・本人の確認が無いものは入れない。
"""
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_sheet_has_numbers_quotes_cases_and_voices():
    import client_intake as C
    print("\n■ ヒアリングシートに自社の数字5・お客さんの一言3・事例4・声4の欄があり、流れ先がある")
    keys = [k for k, *_ in C.FIELDS if not k.startswith("#")]
    check("自社の数字 ①〜⑤", all(f"facts.{i}.claim" in keys for i in range(1, 6)), True)
    check("お客さんの一言 ①〜③（言葉・相手・時期・使ってよいか）",
          all(f"quote.{i}.{f}" in keys for i in range(1, 4) for f in ("text", "who", "when", "use")), True)
    check("事例 ①〜④（依頼前・やったこと・期間・結果・掲載・本人の確認）",
          all(f"case.{i}.{f}" in keys for i in range(1, 5) for f in ("summary", "before", "did", "period", "result", "publish", "confirmed")), True)
    check("お客様の声 ①〜④", all(f"voice.{i}.text" in keys for i in range(1, 5)), True)
    check("欄に重なりが無く、どの欄にも流れ先がある", (len(keys) == len(set(keys)), [k for k in keys if not C.flow_of(k)]), (True, []))


def test_only_allowed_quotes_and_confirmed_cases_become_experiences():
    import client_intake as C
    print("\n■ 体験の台帳に入るのは「可」の一言と、掲載可・本人確認済みの事例だけ")
    got = {"quote.1.text": "「来月の締めができるか分からない」", "quote.1.who": "製造業の社長", "quote.1.use": "可",
           "quote.2.text": "使ってはいけない一言", "quote.2.use": "不可",
           "case.3.summary": "歯科医院の予約導線", "case.3.publish": "可（社名を出さない）", "case.3.confirmed": "済",
           "case.4.summary": "本人未確認の事例", "case.4.publish": "可（社名を出さない）", "case.4.confirmed": "未",
           "voice.4.text": "助かりました", "voice.4.publish": "可", "voice.4.by": "未確認"}
    exps = C.to_experiences(got, "client-zz")
    check("一言1つ・事例1つだけ", [e["kind"] for e in exps], ["お客さんの一言", "事例"])
    check("一言の目印は言葉そのもの（かぎかっこを外す）・時期が無ければ「不明」",
          (exps[0]["key"], exps[0]["when"]), ("来月の締めができるか分からない", "不明"))
    check("本人の確認が無い声は記事に使わない", C.usable_voices(got), [])
    check("記事の材料（brief）に一言を渡す", [q["text"] for q in C.to_brief(got)["quotes"]], ["来月の締めができるか分からない"])
    src = (ROOT / "scripts" / "originality.py").read_text(encoding="utf-8")
    check("originality はお客様の社の非公開の体験の台帳も読む", 'client_path(site, "experiences.json")' in src, True)
