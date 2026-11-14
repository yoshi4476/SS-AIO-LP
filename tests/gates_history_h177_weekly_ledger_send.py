"""1位を狙う語の台帳の数字は、要対応の無い週も毎週の知らせで送る（2026-11-15 運用者の決定「毎週送る」）。
定時の知らせは要対応の語が無いと送らない決まりで、台帳の行は「情報」の欄にあるため、要対応の無い週は届かなかった"""
from test_gates import check


def test_weekly_notice_sends_ledger_every_week():
    import notify_slack as N
    head = "🔧 週次最適化: success\n"
    ledger = (f"{N.INFO_MARK}\n情報: 1位を狙う語の台帳（ai-lab・140語・36組）: 1〜3位 2語／4〜10位 9語／11〜30位 20語／圏外 109語\n")
    other = f"{N.INFO_MARK}\n情報: 集中モードの順位帯\n"
    print("\n■ 毎週の知らせ: 台帳の数字だけの週も送る")
    check("台帳の行がある定時の知らせは、要対応が無くても送る", N.worth_sending(head + ledger, True), True)
    check("台帳の行も要対応も無い定時の知らせは、今までどおり送らない", N.worth_sending(head + other, True), False)
    check("要対応のある週は今までどおり送る", N.worth_sending(head + "要対応: x\n" + other, True), True)
