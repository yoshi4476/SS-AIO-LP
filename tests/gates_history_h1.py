# -*- coding: utf-8 -*-
"""問い合わせ台帳の営業メール・古い「要対応」・食い合い検査の判定不能（2026-10-04）。

3つとも「動いていないもの・古いものを、今の問題として読ませた」誤り。
営業メールに相談と同じ通知と自動返信を出す／10日前の findings.txt を今週の要対応として読ませる／
GSC を読めない日の kw_guard を「既存記事と食い合います」と書く。
"""
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_gates import check, ROOT

GS = ROOT / "automation" / "gas" / "contact.hub.gs"


def _sales_patterns():
    """contact.hub.gs の SALES_PATTERNS を Python の正規表現に移す（同じ式で判定するため）。"""
    src = GS.read_text(encoding="utf-8")
    body = src.split("const SALES_PATTERNS = [", 1)[1].split("];", 1)[0]
    return [re.compile(p) for p in re.findall(r"/((?:[^/\\\n]|\\.)+)/", body)]


def test_sales_inquiries_are_kept_but_silent():
    print("\n■ 問い合わせフォームの営業メールは、台帳に残して通知・自動返信・フォローを止める")
    src = GS.read_text(encoding="utf-8")
    check("SALES_PATTERNS がある", "const SALES_PATTERNS" in src, True)
    form = src.split("function form_(body) {", 1)[1].split("\nfunction ", 1)[0]
    i_probe = form.find("@pipeline-check")
    i_sales = form.find("isSales_(")
    i_save = form.find("leadSave_(")
    i_notify = form.find("leadNotify_(")
    check("form_: 疎通確認の後・記録の前に営業を判定する", 0 <= i_probe < i_sales < i_save, True)
    check("form_: 通知より前に営業を判定する", 0 <= i_sales < i_notify, True)
    check("form_: 営業なら温度を「営業」にする", "sales ? '営業'" in form, True)
    check("form_: 営業なら通知と自動返信を止める（silent に含める）",
          bool(re.search(r"const silent = sales \|\|", form)), True)
    follow = src.split("function followUp() {", 1)[1].split("\nfunction ", 1)[0]
    check("followUp: 営業の行に送らない", "temp === '営業'" in follow, True)
    tool = src.split("function toolFollow_(", 1)[1].split("\nfunction ", 1)[0]
    check("toolFollow_: 営業の行に送らない", "'営業'" in tool, True)

    pats = _sales_patterns()
    check("SALES_PATTERNS を読み取れる", len(pats) >= 10, True)
    is_sales = lambda s: any(p.search(s) for p in pats)
    samples = [
        ("突然のご連絡失礼いたします。弊社では現在、AI受託開発の新しい取り組みを進めており…", True),
        ("貴社サービスが当社主催のテーマイベントにマッチすると考え、ご連絡しました。"
         "登壇・リード獲得（リード単価4,000円〜）のご案内です。", True),
        ("新事業進出ものづくり商業サービス補助金の申請についてご相談させてください。", False),
    ]
    for text, want in samples:
        check("営業の判定: " + text[:24], is_sales(text), want)


def test_findings_drops_stale_carry_over():
    print("\n■ findings.txt: 古いファイルの「要対応」を今の問題として持ち越さない")
    import findings as FD
    jst = timezone(timedelta(hours=9))
    now = datetime(2026, 10, 4, 10, 0, tzinfo=jst)
    old = now - timedelta(days=11)
    check("鮮度: 11日前の記録に印を付ける", FD.stale_note(old, now), "（古い記録・2026-09-23 時点）")
    check("鮮度: 2日前の記録には付けない", FD.stale_note(now - timedelta(days=2), now), "")
    check("鮮度: 時刻が分からなければ付けない", FD.stale_note(None, now), "")

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "findings.txt"
        p.write_text("# 生成: 2026-09-23 16:51 JST（この時点で検査を回し直した結果）\n"
                     "要対応: 生成AIの表示回数（手動の取り込み）\n"
                     "   2026-08 ぶんが未取込です: ai-lab\n"
                     "要対応: ラッコキーワードのクレジットが尽きました\n", encoding="utf-8")
        check("生成時刻を先頭の行から読む", FD.written_at(p),
              datetime(2026, 9, 23, 16, 51, tzinfo=jst))
        ts = old.timestamp()
        os.utime(p, (ts, ts))
        prev, note = FD.carry_over(p, set(), now)
        check("11日前のファイルからは持ち越さない", (prev, note), ([], "（古い記録・2026-09-23 時点）"))
        fresh = now - timedelta(hours=3)
        os.utime(p, (fresh.timestamp(),) * 2)
        prev, note = FD.carry_over(p, {"要対応: 生成AIの表示回数（手動の取り込み）"}, now)
        check("同じ回の追記は持ち越す（検査自身の行は除く）",
              (prev, note), (["要対応: ラッコキーワードのクレジットが尽きました"], ""))
    src = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    check("findings.txt の先頭に生成時刻を書く", '"# 生成: %s JST' in src, True)
    check("findings.py は常に0で終わる", "return 0   # 知らせるのが仕事" in src, True)


def test_kw_guard_unknown_when_gsc_missing():
    print("\n■ kw_guard: GSC の鍵が無い日は「判定不能（3）」を返し、「要差別化（1）」と書かない")
    import auto_rewrite as AR
    import kw_guard as KG
    real = KG.CRED
    try:
        KG.CRED = ROOT / "存在しない鍵-zqx.json"
        lv, reasons = KG.judge("門の試験用の存在しない語 zqx", "ai-lab", use_gsc=True)
        failed = KG.gsc_rows.failed
    finally:
        KG.CRED = real
    check("鍵が無いと判定不能（3）を返す", lv, KG.UNKNOWN)
    check("判定不能の値は3", KG.UNKNOWN, 3)
    check("鍵が無いことを理由に出す", "鍵ファイルがありません" in failed, True)
    check("照合できなかった理由を出す", any(r[0] == "要確認" for r in reasons), True)
    lv0, _ = KG.judge("門の試験用の存在しない語 zqx", "ai-lab", use_gsc=False)
    check("--no-gsc では従来どおり照合なしで判定する", lv0, 0)
    src = (ROOT / "scripts" / "kw_guard.py").read_text(encoding="utf-8")
    check("判定の表示に「判定不能（GSCを読めません）」がある", "判定不能（GSCを読めません）" in src, True)

    m1, m3 = AR.guard_message(1), AR.guard_message(3)
    check("auto_rewrite: 1は食い合い", "既存記事と食い合います" in m1, True)
    check("auto_rewrite: 3は検査が動かなかったと書く",
          ("食い合いの検査が動きませんでした（鍵・通信を確認）" in m3, "既存記事と食い合います" in m3), (True, False))
    merge = (ROOT / "scripts" / "auto_merge.py").read_text(encoding="utf-8")
    check("auto_merge も同じ書き分けを使う", "AR.guard_message(r.returncode)" in merge, True)
    gate = (ROOT / "scripts" / "kw_gate.py").read_text(encoding="utf-8")
    check("kw_gate: 判定不能で語を退避・記事を隔離しない",
          ("level < 2 or level == 3" in gate, "if level == 2:" in gate), (True, True))
