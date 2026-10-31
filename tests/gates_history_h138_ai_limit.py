# -*- coding: utf-8 -*-
"""2026-10-31: AI（Claude のサブスク）の週の上限で、10-27〜10-30 の全社の記事の枠が止まった。
claude は「You've hit your weekly limit · resets 8am (Asia/Tokyo)」の1行だけを返し、記事の枠は「記事が増えていません」を
3回繰り返して「3回試しても記事を書けませんでした」とだけ残した。理由が残らず、4日間だれも気づかなかった。
もう1つ、使用量の記録（data/claude_usage/・公開側）に、お客様の社の id（社の名前）を書いていた（--site に outputs.id を渡していた）。

- 上限の知らせを見分け、記事の枠はやり直しをやめて、理由つきの要対応を残す
- 使用量の記録に書く社は公開の id だけ（社の id を渡されても伏せる）・記事の枠は outputs.pub を渡す
- 公開側に残っている使用量の記録に、公開の id 以外の社が無い
"""
import json
import re
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_limit_message_is_recognized():
    import claude_usage as U
    print("\n■ AI の利用の上限の知らせを見分ける")
    check("週の上限", bool(U.limit_hit("You've hit your weekly limit · resets 8am (Asia/Tokyo)")), True)
    check("時間の上限", bool(U.limit_hit("Claude AI usage limit reached|1761900000")), True)
    check("ふつうの出力は上限にしない", U.limit_hit("記事を書きました。limit の説明を足しました"), "")
    check("空", U.limit_hit(""), "")


def test_writer_stops_and_reports_on_limit():
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    body = wf.split("for try in 1 2 3; do", 1)[1].split("done", 1)[0]
    print("\n■ 記事の枠は上限の回にやり直しをやめ、理由つきで知らせる")
    check("出力を残す（自社の回も）", body.count('claude_out_$try.txt') >= 3, True)
    check("上限を見る", "claude_usage.py --limit-hit" in body, True)
    check("要対応に残す", "要対応: AI（Claude のサブスク）の利用の上限" in body and "findings.txt" in body, True)
    check("要対応は公開の id で書く", re.search(r"要対応: AI[^\n]*outputs\.id", body) is None, True)


def test_rewrite_ledger_keeps_the_limit_reason():
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    print("\n■ 書き直しの台帳に、AI が動かなかった理由（上限の知らせは標準出力）を残す")
    check("標準出力も見る", "limit_hit((r.stdout" in src, True)


def test_weekly_kw_refill_resolves_public_id():
    src = (ROOT / "scripts" / "kw_discover.py").read_text(encoding="utf-8")
    main = src.split("def main():", 1)[1]
    print("\n■ 週次の KW 補充は公開の id で呼ばれても社の id に直してから設定を引く（2026-10-26 KeyError）")
    check("site_config の前に resolve", main.find("site_id = _sm.resolve(site_id)") != -1
          and main.find("site_id = _sm.resolve(site_id)") < main.find("site_config(site_id)"), True)
    check("ログには公開の id", re.search(r"print\(f\"  \{site_id\}", main) is None and "site={site_id}" not in main, True)


def test_usage_record_uses_public_id():
    import claude_usage as U
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    print("\n■ 使用量の記録（公開側）に社の id を書かない")
    check("記事の枠は outputs.pub を渡す", "SITE_PUB: ${{ steps.site.outputs.pub }}" in wf, True)
    check("公開の id はそのまま", U.public_site("ai-lab"), "ai-lab")
    check("sites/ に無い名前は伏せる", U.public_site("client-zz"), "?")
    pub = {p.stem for p in (ROOT / "sites").glob("*.json")}
    bad = []
    for f in sorted((ROOT / "data" / "claude_usage").glob("*.json")):
        try:
            s = json.loads(f.read_text(encoding="utf-8")).get("site") or ""
        except ValueError:
            continue
        if s and s != "?" and s not in pub:
            bad.append(f.name)
    check("記録に公開の id 以外の社が無い", bad, [])
