# -*- coding: utf-8 -*-
"""過去の誤りの棚卸しから作った門（相場・価格の表記）。

AIO・SEO・LLMO対策の相場は data/price_ranges.json だけを正とする。
記事ごとに別の相場（外注で月3万円台から、月10万〜30万円 など）を書くと、同じサイトの中で
数字が食い違い、当社の見立てとも矛盾する。当社の価格（月20万円）も書かない。

検出器は「悪い例を拾う」「良い例を拾わない」を先に確かめてから記事に当てる（CLAUDE.md 0.1）。
"""
import json
import re

from test_gates import check, ROOT

PRICE = json.loads((ROOT / "data" / "price_ranges.json").read_text(encoding="utf-8"))
FLOOR = PRICE["outsource_min_yen"]
OWN_PRICE_MAN = PRICE["own_price_yen"] // 10000

# 対象は AI集客ラボの AIO・SEO・AIマーケティング（MEO は別の商材なので外す）
CATS = {"aio", "seo", "ai-marketing"}

OUT = re.compile(r"外注|代行|委託|コンサル|専門会社|制作会社|支援会社|代理店|業者|フリーランス|部分支援|運用支援|サポート型|依頼|顧問|(?<![か月ヶ年])契約(?!時)|相場")
OUT_AFTER = re.compile(r"外注|代行|委託|コンサル|専門会社|制作会社|支援会社|代理店|業者|フリーランス|依頼|相場")
# 1記事・1文字・1回あたりの単価は月額の相場と別の単位
PER = re.compile(r"文字単価|字の|1記事|1本|記事単価|あたり|1回|単発|スポット")
INH = re.compile(r"内製|自社対応|自社で|自分で|社内|ツール|無料")
SVC = re.compile(r"AIO|SEO|LLMO|GEO|AI検索|AI Overview|AIモード|記事制作|コンテンツ", re.I)
# 別の商材・別の単位の金額（MEO・反響対応・HP制作・セミナー・広告費・ツールのドル建て・初期費用・記事単価）
OTHER = re.compile(r"MEO|G-ran|Googleビジネスプロフィール|反響|追客|ホームページ制作|HP制作|サイト制作|セミナー|広告費|リスティング|ドル|初期|1記事|1本|記事単価|あたり|単発|スポット")
AMT = re.compile(r"十数万|数千円|数万|[0-9][0-9,.]*\s*万|[0-9][0-9,]{3,}\s*円"
                 r"|(?<![0-9,.])[0-9][0-9,.]*(?=\s*[〜~～\-－]\s*[0-9][0-9,.]*\s*万)")
OWN = re.compile(r"当社|弊社|私たち|AI集客ラボ|セブンセンス|Seven Senses", re.I)
OWN_AMT = re.compile(rf"(?<![0-9.,]){OWN_PRICE_MAN}\s*万")
ZEN = str.maketrans("０１２３４５６７８９，．〜", "0123456789,.〜")


def plain(s):
    s = re.sub(r"<[^>]+>", "", s.translate(ZEN))
    return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)


RANGE_TO_MAN = re.compile(r"^\s*[〜~～\-－]\s*[0-9][0-9,.]*\s*万")
MONEY_AFTER = re.compile(r"^[^、。|業社人件店名本回]{0,16}円")


def yen(t, after):
    """金額でなければ None（「13万2,291業者」のような件数を拾わない）"""
    t = t.replace(" ", "")
    if not (t.endswith("円") or MONEY_AFTER.match(after)):
        return None
    if t in ("十数万", "数千円", "数万"):
        return {"十数万": 150000, "数千円": 5000, "数万": 50000}[t]
    num = float(re.sub(r"[^0-9.]", "", t.replace(",", "")) or 0)
    return num * 10000 if "万" in t or RANGE_TO_MAN.match(after) else num


def low_claims(text):
    """外部委託の月額を数十万円より下に書いている箇所 [(行番号, 抜粋)]"""
    hits, heading, table_ctx, prev_para, prev_unit = [], "", "", "", ""
    kw = " ".join(re.findall(r"^(?:keyword|title):(.*)$", text, re.M))
    for i, raw in enumerate(text.splitlines(), 1):
        line = plain(raw)
        st = line.strip()
        if st.startswith("#"):
            heading, table_ctx = st, ""
            continue
        is_row = st.startswith("|")
        if is_row:
            if not table_ctx:
                table_ctx = prev_para + " " + st
            units = [st]
        else:
            if st:
                prev_para, table_ctx = st, ""
            units = re.split(r"(?<=[。！？])", st)
        for u in units:
            cells = [c.strip() for c in u.strip("|").split("|")] if is_row else []
            for m in AMT.finditer(u):
                v = yen(m.group(), u[m.end():])
                if v is None or v >= FLOOR:
                    continue
                if is_row:
                    label = cells[0]
                    cell = next((c for c in cells if m.group() in c), "")
                    pre, clause = label, label + " " + cell
                else:
                    pre = u[:m.start()]
                    clause = re.split(r"[、，]", pre)[-1] + m.group() + re.split(r"[、，。]", u[m.end():])[0]
                if OTHER.search(clause) and not SVC.search(clause):
                    continue
                # 単価の語は、この金額より前と同じ節だけで見る（後ろの「スポット型は…」で前の月額を見逃さない）
                if PER.search(clause if is_row else pre + clause):
                    continue
                lo = max([x.end() for x in OUT.finditer(pre)] or [-1])
                li = max([x.end() for x in INH.finditer(pre)] or [-1])
                if lo < 0 and li < 0 and not is_row and OUT_AFTER.search(re.split(r"[、，。]", u[m.end():])[0]):
                    lo = 0
                if lo < 0 and li < 0:
                    # 主語が書かれていない金額は、表なら表の前の段落と見出し、文なら見出しで決める
                    # FAQ の答えは直前の問い（「費用相場はいくらですか？」）が主語になる
                    ctx = (table_ctx + " " + heading) if is_row else (heading + " " + prev_unit)
                    if OUT.search(ctx) and not INH.search(heading + " " + prev_unit):
                        lo = 0
                if lo < 0 or li > lo:
                    continue
                if not SVC.search(" ".join((u, table_ctx, heading, kw))):
                    continue
                hits.append((i, u[:90]))
                break
            if u.strip():
                prev_unit = u
    return hits


def own_price(text):
    out = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = plain(raw)
        for m in OWN_AMT.finditer(line):
            if OWN.search(line[max(0, m.start() - 40):m.end() + 40]):
                out.append((i, line[max(0, m.start() - 30):m.end() + 20]))
    return out


def ai_lab_articles():
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8")
        m = re.search(r"^category:\s*(\S+)", t, re.M)
        if m and m.group(1) in CATS:
            yield p, t


def test_hist_price_ranges_consistent():
    print("\n■ 相場の表記が data/price_ranges.json と食い違わない")
    bad = ["AIO対策の外部委託は月3万円台から始められます。",
           "SEOの外注費用は月10万〜30万円が目安です。",
           "| 部分外注（記事のみ） | 3万〜8万円 |",
           "AIO対策を代行会社に任せると数千円〜数万円です。",
           "SEOコンサルは月額十数万円が中心です。",
           "SEOは自社対応中心で月1〜5万円、外注では月10〜30万円が目安です。",
           "| フルサポート型 | 月15万〜30万円 | MEO・SEO・AI検索を一括で任せたい医院 |",
           "  - q: SEOコンサルの費用相場はいくらですか？\n    a: 月額5万〜20万円が目安です。"]
    good = ["内製＋有料ツールは月数万〜数十万円です。",
            "AIO対策は、内製＋有料ツールなら月数万〜数十万円、外部委託・部分支援は月数十万円〜です。",
            "| 内製＋有料ツール併用 | 数万〜数十万円＋担当者の人件費 |",
            "DolphinX は月額99ドルのツールで、AI引用を自動で記録します。",
            "無料の次の一歩は、月25ドルから月3万円台の入門プランです。",
            "MEO対策の代行（G-ran）は月3万円です。",
            "SEOの外部委託は月数十万〜数百万円が目安です。",
            "SEOの競合は宅地建物取引業者13万2,291業者です。",
            "SEOを自社対応中心で進めると月1〜5万円です。",
            "月30,000円は6か月契約時の価格で、12か月契約なら月27,000円に下がります。",
            "SEO記事の外注は、3,000字の記事であれば1,500〜6,000円です。"]
    for s in bad:
        check(f"相場: 悪い例を拾う「{s[:24]}」", bool(low_claims("## AIO対策の費用\n" + s)), True)
    for s in good:
        check(f"相場: 良い例を拾わない「{s[:24]}」", low_claims("## AIO対策の費用\n" + s), [])
    check("当社の価格: 悪い例を拾う", bool(own_price("当社のAIO対策は月20万円です。")), True)
    check("当社の価格: 良い例を拾わない", own_price("当社の見立てでは月数十万円〜です。厚労省の統計では120万円です。"), [])

    low, own = [], []
    for p, t in ai_lab_articles():
        low += [f"{p.stem}:{i} {s}" for i, s in low_claims(t)]
        own += [f"{p.stem}:{i} {s}" for i, s in own_price(t)]
    for x in low + own:
        print("    " + x)
    check("AI集客ラボの記事: 外部委託の月額を数十万円より下に書かない", low, [])
    check("AI集客ラボの記事: 当社の価格（月20万円）を書かない", own, [])
