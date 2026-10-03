# -*- coding: utf-8 -*-
"""業種別「AI検索対策チェックリスト」（PDF）を作る。/download/ でメールと引き換えに配る。

    python scripts/checklist_make.py            # 5業種ぶん作る（site/download/checklist-<業種>.pdf）

数字は調査（industry_ai_sources.headline）からだけ取る。チェック項目は、30秒診断（audit.js）で測る項目・
業種別LPの「当社が行うこと」・各業種の広告の決まりから作る。事実として言えないことは書かない。
"""
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "site" / "download"

TECH = [
    "AIのクローラー（GPTBot・ClaudeBot・PerplexityBot など）を robots.txt で拒否していない",
    "CDN・セキュリティの設定で、AIのクローラーを弾いていない",
    "常時SSL（https）になっている",
    "検索に出さない設定（noindex）が、公開したいページに残っていない",
    "ページごとに題（title）と説明文（description）が付いている",
    "見出し（h1）がページに1つある",
    "会社情報（電話番号・所在地）が、画像ではなく文字で書いてある",
    "構造化データ（会社・パンくず・よくある質問）が正しく入っている",
]
INDUSTRIES = {
    "dental": {"label": "歯科医院", "research": "dental", "lp": "medical",
               "topics": ["治療ごとの費用の目安と、保険が使えるかどうか", "治療法の選び方（インプラント・入れ歯・ブリッジなど）",
                          "症状ごとの受診の目安", "初診の流れ・予約・診療時間", "院長・歯科医師の経歴と専門", "実際にある設備と、その設備でできること"],
               "rule": "医療広告ガイドラインにふれない書き方になっている（体験談・他院との比較・効果の保証を書かない）"},
    "clinic": {"label": "クリニック", "research": "clinic", "lp": "medical",
               "topics": ["診療内容と、症状ごとの受診の目安", "検査・自費診療の費用", "予約・待ち時間・オンライン診療の有無",
                          "医師の経歴と専門医の資格", "初診の流れと持ち物", "健康診断・予防接種の案内"],
               "rule": "医療広告ガイドラインにふれない書き方になっている（体験談・他院との比較・効果の保証を書かない）"},
    "fudosan": {"label": "不動産会社", "research": "fudosan", "lp": "fudosan",
                "topics": ["売却・購入・賃貸それぞれの費用（仲介手数料・諸費用）", "手続きの流れと期間", "対応エリアと得意な物件・取引",
                           "査定の考え方", "相続・空き家などの相談への対応", "担当者・宅地建物取引士の紹介"],
                "rule": "掲載物件を最新に保ち、取引できない物件を載せたままにしない（おとり広告にしない）"},
    "koumuten": {"label": "工務店・リフォーム会社", "research": "koumuten", "lp": "koumuten",
                 "topics": ["費用の考え方（坪単価・総額・諸費用）", "工法と性能（断熱・耐震）", "施工事例（地域・費用帯・工期つき）",
                            "家づくり・リフォームの流れと期間", "保証とアフターサービス", "対応エリア"],
                 "rule": "施工事例の費用・工期は、実際の数字で書いている"},
    "shigyou": {"label": "士業事務所", "research": "shigyou", "lp": "shigyou",
                "topics": ["料金の考え方（顧問料・報酬の目安）", "相談テーマごとの解説（相続・設立・労務・許認可など）",
                           "手続きの流れと期間", "資格者と専門分野", "対応エリアとオンライン対応", "よくある質問と答え"],
                "rule": "各士業会の広告に関する規程にそった書き方になっている"},
}


def page(key):
    import industry_ai_sources as IAS
    c = INDUSTRIES[key]
    hl = IAS.headline(c["research"])
    e = html.escape
    T = hl["T"]
    if hl["verdict"] == "portal":
        first = f'{hl["lp"]}%', f'{T["owner"]}を探す質問で、AIの出典が{T["portal"]}だった割合（{T["owner_site"]}は{hl["lc"]}%）'
    elif hl["verdict"] == "owner":
        first = f'{hl["lc"]}%', f'{T["owner"]}を探す質問で、AIの出典が{T["owner_site"]}だった割合'
    else:
        first = f'{hl["lp"]}%／{hl["lc"]}%', f'{T["owner"]}を探す質問で、出典になった{T["portal"]}と{T["owner_site"]}（ほぼ同じ）'
    box = lambda items: "".join(f'<li><span class="b"></span>{e(x)}</li>' for x in items)
    seek = [f"{t}を説明したページがある" for t in c["topics"]]
    find = [f"主な{T['portal']}の掲載情報（営業時間・料金・写真・住所）が最新になっている",
            "社名・住所・電話番号の書き方が、自社サイトと各サイトで同じになっている",
            f"{T['portal']}に寄せられた口コミ・質問に、規約の範囲で返信している"]
    facts = ["その会社にしか無い事実（実績の数・事例）を、期間と母数をつけて書いている",
             "記事やページに、監修者・執筆者の名前と資格を載せている",
             "更新日を載せ、古くなった情報を直している", c["rule"]]
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><title>AI検索対策チェックリスト｜{e(c['label'])}版</title>
<style>
@page{{size:A4;margin:14mm 14mm 14mm}}
body{{font-family:"Hiragino Kaku Gothic ProN","Yu Gothic","Meiryo",sans-serif;color:#10203a;font-size:9.6pt;line-height:1.7;margin:0}}
h1{{font-size:19pt;margin:0;color:#0b2447;letter-spacing:.02em}}
.sub{{color:#5b6b84;font-size:8.6pt;margin:1mm 0 5mm}}
.data{{background:#0b2447;color:#fff;border-radius:3mm;padding:4mm 5mm;display:grid;grid-template-columns:1fr 1fr;gap:5mm;margin-bottom:5mm}}
.data b{{display:block;font-size:20pt;line-height:1.2}}
.data p{{margin:0;font-size:8.4pt;color:rgba(255,255,255,.88)}}
.data .src{{grid-column:1/-1;font-size:7.6pt;color:rgba(255,255,255,.7)}}
h2{{font-size:11.5pt;margin:5mm 0 2mm;padding-left:2.5mm;border-left:1.2mm solid #2563eb;color:#0b2447}}
.why{{margin:0 0 2mm;color:#5b6b84;font-size:8.6pt}}
ul{{list-style:none;margin:0;padding:0;display:grid;gap:1.4mm}}
li{{display:flex;gap:2.4mm;align-items:flex-start}}
.b{{flex:none;width:3.6mm;height:3.6mm;border:.35mm solid #2563eb;border-radius:.6mm;margin-top:.9mm}}
.foot{{margin-top:6mm;border-top:.3mm solid #e3eaf3;padding-top:3mm;font-size:8.4pt;color:#5b6b84}}
.foot b{{color:#0b2447}}
.cut{{break-before:page}}
</style></head><body>
<h1>AI検索対策チェックリスト｜{e(c['label'])}版</h1>
<p class="sub">セブンセンシズ株式会社（AI集客ラボ）・{hl['date'][:4]}年{int(hl['date'][5:7])}月版 ／ 当てはまるものに印をつけてください</p>
<div class="data"><div><b>{e(first[0])}</b><p>{e(first[1])}</p></div>
<div><b>{hl['oa']}%</b><p>{e(T['other_short'])}を調べる質問で、回答が{e(T['owner_site'])}を1つ以上出典にしていた割合</p></div>
<p class="src">出典: セブンセンシズ株式会社の調査（{hl['questions']}問を {hl['engines_text']} に質問・{hl['date']}）{hl['url']}</p></div>
<h2>1. AIと検索に読まれる状態か</h2><p class="why">ここが欠けると、内容が良くてもAIの答えに使われません。</p><ul>{box(TECH)}</ul>
<h2>2.「探される」場面（{e(T['owner'])}を探す人）</h2><p class="why">探す質問では、AIは{e(T['portal'])}も出典にします。掲載情報の古さはそのまま答えに出ます。</p><ul>{box(find)}</ul>
<h2 class="cut">3.「調べられる」場面（自社の解説ページ）</h2><p class="why">費用・手続きなどを調べる質問では、AIは{e(T['owner_site'])}を出典にしていました。次のテーマに答えるページがあるかを確かめてください。</p><ul>{box(seek)}</ul>
<h2>4. 事実と書き方</h2><p class="why">AIが根拠に選ぶのは、そこにしか無い事実です。</p><ul>{box(facts)}</ul>
<div class="foot"><b>確かめる（無料）</b><br>
・AIにどう紹介されているか無料チェック: https://ai.7senses.co.jp/tools/ai-check/<br>
・サイトが読まれているかの30秒診断: https://ai.7senses.co.jp/lp/{c['lp']}/<br>
<b>相談する</b>: {e(T['lp_name'])} https://ai.7senses.co.jp/lp/{c['lp']}/ ／ TEL 06-4305-7547（平日9:00〜20:00）<br>
セブンセンシズ株式会社 〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902</div>
</body></html>"""


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        for key in INDUSTRIES:
            pg.set_content(page(key), wait_until="load")
            out = OUT / f"checklist-{key}.pdf"
            pg.pdf(path=str(out), format="A4", print_background=True)
            print(f"  {out.name}（{out.stat().st_size // 1024}KB）")
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
