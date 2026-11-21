# -*- coding: utf-8 -*-
"""AI集客ラボの記事の相場・価格の表記の判定（門 gates_history_e・機械採点 score_check・公開前の直し quality_loop の1か所）。

AIO・SEO・LLMO対策の相場は data/price_ranges.json だけを正とする。外部委託の月額を数十万円より下に書かない。
当社の価格（本当の額は非公開の sales/prices.json）も書かない。
門だけが見ていて公開前の機械採点に無かったため、決まりに外れた要約の文が公開された（2026-11-21 費用の記事）。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRICE = json.loads((ROOT / "data" / "price_ranges.json").read_text(encoding="utf-8"))
FLOOR = PRICE["outsource_min_yen"]


def _own_price_man():
    """当社の月額（万円）。本当の額は非公開の sales/prices.json にだけ置く（public のリポジトリに当社の料金を書かない。
    2026-10-20 の点検で、price_ranges.json の注記とこの門の例に本当の額が書かれていた）。読めなければ
    price_ranges.json の架空の値（門の例は動くが、記事に本当の額が書かれていても拾えない）"""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import private_store as PS
        monthly = str(((PS.sales_json("prices.json") or {}).get("aio_media") or {}).get("monthly") or "")
        m = re.search(r"([0-9]+)\s*万", monthly)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return PRICE["own_price_yen"] // 10000


OWN_PRICE_MAN = _own_price_man()

# 対象は AI集客ラボの AIO・SEO・AIマーケティング（MEO は別の商材なので外す）
CATS = {"aio", "seo", "ai-marketing"}

OUT = re.compile(r"外注|代行|委託|コンサル|専門会社|制作会社|支援会社|代理店|業者|フリーランス|部分支援|運用支援|サポート型|依頼|顧問|(?<![か月ヶ年])契約(?!時)|相場")
OUT_AFTER = re.compile(r"外注|代行|委託|コンサル|専門会社|制作会社|支援会社|代理店|業者|フリーランス|依頼|相場")
# 1記事・1文字・1回あたりの単価は月額の相場と別の単位
PER = re.compile(r"文字単価|字の|1記事|1本|記事単価|あたり|1回|単発|スポット")
INH = re.compile(r"内製|自社対応|自社で|自分で|社内|ツール|無料")
INH_SUBJ = re.compile(r"(?:内製|自社対応)[^、，。外注代行委託]{0,10}の相場")
SVC = re.compile(r"AIO|SEO|LLMO|GEO|AI検索|AI Overview|AIモード|記事制作|コンテンツ", re.I)
# 別の商材・別の単位の金額（MEO・反響対応・HP制作・セミナー・広告費・ツールのドル建て・初期費用・記事単価）
# 記事作成ツールは data/price_ranges.json の article_tool（月4〜5万円前後）。外部委託の額ではない
OTHER = re.compile(r"記事作成ツール|MEO|G-ran|Googleビジネスプロフィール|反響|追客|ホームページ制作|HP制作|サイト制作|セミナー|広告費|リスティング|ドル|初期|1記事|1本|記事単価|あたり|単発|スポット")
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
                # 金額のすぐ後ろが内製・ツールなら、その額は内製の額（「月数万円台なら内製＋ツールで」）
                after = re.split(r"[、，。]", u[m.end():])[0]
                if not is_row and INH.search(after) and not OUT_AFTER.search(after):
                    continue
                li = max([x.end() for x in INH.finditer(pre)] or [-1])
                # 「相場」は主語ではない。節が内製の語で始まる「内製＋有料ツールの相場は月数万〜」は内製の相場（2026-11-19）。
                # 「外注と内製の相場」「社内に担当がいない場合の相場」「…、相場は」は外注の相場として拾う
                seg = re.split(r"[、，。]", pre)[-1].strip().lstrip("|").strip()
                inh_subj = bool(INH_SUBJ.match(seg)) and "ない" not in seg
                lo = max([x.end() for x in OUT.finditer(pre) if not (x.group() == "相場" and inh_subj)] or [-1])
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


def applies(category):
    return str(category or "").strip() in CATS


def ranges_note():
    """直しの指示に渡す相場（data/price_ranges.json の区分と額）"""
    return "、".join(f"{r['label']}は{r['range']}" for r in PRICE["ranges"])
