# -*- coding: utf-8 -*-
"""配信停止の受付（2026-10-08 の点検で運用者が直すと決めたもの）。

補助金サイトの配信停止（lp.7senses.co.jp/unsubscribe/）は type: unsubscribe で管制塔の受付（contact.hub.gs の form_）へ送る。
受付に専用の処理が無く、配信停止が問い合わせの台帳に1行入り、担当へ問い合わせとして通知され、本人には問い合わせ用の
自動返信（「3営業日以内に担当よりご連絡します」と動画の案内）が届いていた。停止はどこにも記録されず、
自動フォロー・ステップメール・測り直しが見る「配信除外」にも入らなかった。
"""
import json

from test_gates import check, ROOT

GAS = ROOT / "automation" / "gas"
NOTIFY_TO = "info.ai@7senses.co.jp"

# Apps Script のサービスの代わり（シートはメモリの中に持つ）
FAKE = """
var __sheets={}, __mail=[];
function __mk(name){var rows=[];return {__rows:rows,
  appendRow:function(r){rows.push(r.slice());},
  getLastRow:function(){return rows.length;},
  getRange:function(r,c,nr,nc){nr=nr||1;nc=nc||1;var R={
    getValues:function(){var o=[];for(var i=0;i<nr;i++){var row=rows[r-1+i]||[],x=[];for(var j=0;j<nc;j++){var v=row[c-1+j];x.push(v===undefined?'':v);}o.push(x);}return o;},
    getValue:function(){var row=rows[r-1]||[];var v=row[c-1];return v===undefined?'':v;},
    setValue:function(v){while(rows.length<r)rows.push([]);rows[r-1][c-1]=v;return R;},
    setValues:function(vs){for(var i=0;i<vs.length;i++){while(rows.length<r+i)rows.push([]);for(var j=0;j<vs[i].length;j++)rows[r-1+i][c-1+j]=vs[i][j];}return R;},
    setFontWeight:function(){return R;},setBackground:function(){return R;},setFontColor:function(){return R;}};return R;},
  setFrozenRows:function(){}};}
var __book={getSheetByName:function(n){return __sheets[n]||null;},insertSheet:function(n){__sheets[n]=__mk(n);return __sheets[n];},
  getSheets:function(){return Object.keys(__sheets).map(function(k){return __sheets[k];});},deleteSheet:function(){},toast:function(){},
  getUrl:function(){return 'https://sheet.example/';}};
SpreadsheetApp={openById:function(){return __book;},getActiveSpreadsheet:function(){return __book;}};
MailApp={sendEmail:function(o){__mail.push({to:o.to,subject:o.subject,body:o.body});}};
UrlFetchApp={fetch:function(){throw new Error('offline');}};
PropertiesService={getScriptProperties:function(){return {getProperty:function(){return null;}};}};
Utilities={formatDate:function(d){return new Date(d).toISOString().slice(0,10);}};
console={log:function(){},error:function(){},warn:function(){}};
Logger={log:function(){}};
"""

# 本物のページと同じ形で送る（unsubscribe/index.html の payload）。2回目は大文字小文字を変える
SCENARIO = """
function rows(n){var s=__sheets[n];return s?s.__rows.slice(1):[];}
function take(){var m=__mail.slice();__mail.length=0;return m;}
var out={};
out.first={ret:form_({type:'unsubscribe',form_type:'unsubscribe',site:'subsidy',email:'Taro@Example.co.jp',website:'',ts:1}),
           ledger:rows('問い合わせ').length, exclude:rows('配信除外'), mails:take()};
out.again={ret:form_({type:'unsubscribe',form_type:'unsubscribe',site:'subsidy',email:'taro@example.co.jp',website:'',ts:1}),
           ledger:rows('問い合わせ').length, exclude:rows('配信除外').length, mails:take()};
out.probe={ret:form_({type:'unsubscribe',site:'subsidy',email:'probe-subsidy-1@pipeline-check.invalid',website:'',ts:1}),
           probe:rows('疎通確認').length, exclude:rows('配信除外').length, mails:take()};
out.contact={ret:form_({type:'contact',form_type:'contact',site:'subsidy',name:'山田',email:'taro@example.co.jp',
             message:'補助金の申請について相談したい',website:'',ts:1}), ledger:rows('問い合わせ').length, mails:take()};
globalThis.__out=out;
"""


def run(src):
    from gates_history_d import node_run
    return node_run(FAKE + "\n" + src, SCENARIO)


def problems(o):
    """配信停止の受付の約束（台帳・通知・自動返信に入れない／配信除外に残す／本人へは停止の確認だけ）から外れたもの"""
    if not isinstance(o, dict):
        return ["実行できない"]
    out = []
    f, a, p, c = o["first"], o["again"], o["probe"], o["contact"]
    if not (f["ret"] or {}).get("ok"):
        out.append("配信停止を受け付けない")
    if f["ledger"]:
        out.append("配信停止が問い合わせの台帳に入る")
    hit = [r for r in f["exclude"] if str(r[0]).lower() == "taro@example.co.jp"]
    if not hit or hit[0][2] != "配信停止":
        out.append("配信除外に「配信停止」として残らない")
    to = [m["to"] for m in f["mails"]]
    if NOTIFY_TO in to:
        out.append("担当へ問い合わせとして通知する")
    mine = [m for m in f["mails"] if str(m["to"]).lower() == "taro@example.co.jp"]
    if len(mine) != 1 or "配信を停止しました" not in mine[0]["body"]:
        out.append("本人へ停止の確認を1通返さない")
    if any(w in m["subject"] + m["body"] for m in mine
           for w in ("お問い合わせいただき", "お問い合わせありがとう", "担当よりご連絡", "/videos/", "/lp/")):
        out.append("本人への確認に問い合わせ用の文面・案内が混ざる")
    if not ((a["ret"] or {}).get("already") and a["exclude"] == len(hit) and not a["mails"] and not a["ledger"]):
        out.append("停止済みのアドレスで、行を増やすか確認メールを送り直す")
    if not (p["probe"] == 1 and p["exclude"] == len(hit) and not p["mails"]):
        out.append("疎通確認の送信が、疎通確認のシートだけに残らない")
    notify = [m for m in c["mails"] if m["to"] == NOTIFY_TO]
    if not ((c["ret"] or {}).get("ok") and c["ledger"] == 1 and len(c["mails"]) == 2 and notify):
        out.append("停止した人のその後の相談が、台帳・通知・自動返信に届かない")
    elif "既存のお客様です" in notify[0]["body"]:
        out.append("停止しただけの人を、通知で「既存のお客様」と書く")
    return out


def test_unsubscribe_is_not_an_inquiry():
    print("\n■ 配信停止は問い合わせにしない。配信除外に残し、本人へは停止の確認だけを返す（2026-10-08）")
    gs = (GAS / "contact.hub.gs").read_text(encoding="utf-8")
    form = gs.split("function form_(body) {", 1)[1].split("\nfunction ", 1)[0]
    i_probe, i_unsub, i_save = form.find("pipeline-check"), form.find("'unsubscribe'"), form.find("leadSave_(")
    check("form_: 配信停止を、疎通確認の見分けの後・台帳への保存より前で分ける", 0 <= i_probe < i_unsub < i_save, True)
    src = "\n".join((GAS / f).read_text(encoding="utf-8") for f in ("hub.gs", "contact.hub.gs"))
    got = run(src)
    if got is None:
        print("  WARN  node が無いため、配信停止の受付の動きは確かめられません")
        return
    check("検出器: 今の受付の前（配信停止を問い合わせとして扱う形）を拾う",
          "配信停止が問い合わせの台帳に入る" in problems(run(src.replace("'unsubscribe'", "'unsubscribe__x'"))), True)
    check("配信停止: 台帳・通知・自動返信に入れず、配信除外に残し、本人へ停止の確認を1通だけ返す", problems(got), [])
    # 補助金サイトのページが送る種別と、受付が見分ける種別が同じ（作業コピーがあるときだけ）
    page = ROOT / ".publish-work" / "subsidy" / "unsubscribe" / "index.html"
    if page.is_file():
        check("補助金サイトの配信停止のページは type: unsubscribe で送る",
              'type:"unsubscribe"' in page.read_text(encoding="utf-8"), True)


if __name__ == "__main__":
    test_unsubscribe_is_not_an_inquiry()
    print(json.dumps(run("\n".join((GAS / f).read_text(encoding="utf-8") for f in ("hub.gs", "contact.hub.gs"))),
                     ensure_ascii=False, indent=1)[:3000])
