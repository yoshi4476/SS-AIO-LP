# -*- coding: utf-8 -*-
"""調査ページの「この調査を引用する方へ」の枠と、貼れる図（PNG）。

**なぜ要るか**: AI検索での見え方は被リンクより言及で決まる（YouTube 0.71・リンク無しの言及 0.66 ＞ 被リンク 0.22。
CLAUDE.md 0.3節）。引用する人が出典の書き方を考えずに済めば、社名とURLが正しい形で外に出る回数が増える。

使う場所（3サイト・すべての調査ページ）:
  AI集客ラボ   業種別の調査（industry_ai_sources.render）・ランキング（ai_ranking.body）・/research/ai-answers/
  補助金       /research/ai-hojokin/（subsidy/research.py の html_body）
  コーポレート /research/ai-answers（research_publish.py が JSON に cite を入れ、tsx が描く）

**図の数字は渡された値だけ**（業種別は headline() の lp・lc・oa、ランキングは集計の n/answered）。
ここで割合を計算し直さない（ページ・LP・提案書と食い違わないため）。
"""
import html
import io

ORG = "セブンセンシズ株式会社"
LAB = "AI集客ラボ"
LAB_URL = "https://ai.7senses.co.jp"
CONTACT_URL = LAB_URL + "/contact/"
# 運用者が決めた引用の条件（2026-10-05）。条件を変えるときはここだけを直す（ページ・Dataset・お知らせが同じ文を使う）
TERMS = ("出典（社名・調査名・URL）を明記していただければ、記事・資料・SNSなどで自由に引用できます。"
         "AIの答えは日によって変わるため、調査の年月もあわせて書いてください。")
ANCHOR = "cite"


def org_label(site_name=""):
    return f"{ORG}（{site_name}）" if site_name else ORG


def ym_text(d):
    """「2026-10-02」→「2026年10月」"""
    return f"{int(d[:4])}年{int(d[5:7])}月"


def cite_line(org, title, d, url):
    """そのまま貼れる出典の1行"""
    return f"出典: {org}『{title}』{ym_text(d)} {url}"


def usage_url(page_url):
    """Dataset の usageInfo。引用の条件は各ページの枠（#cite）に書いてある"""
    return page_url.split("#")[0] + "#" + ANCHOR


def license_url(page_url):
    """Dataset の license（Search Console が「license がありません」と知らせるため。2026-10-07）。
    引用の条件は運用者が決めた TERMS（出典の明記で引用可）なので、CC BY などに広げず、その条件の枠を指す"""
    return usage_url(page_url)


STYLE = ("<style>.cite-box{border:1px solid #d3e0f0;border-radius:16px;padding:1.1rem 1.3rem;background:#f5f8fc;display:grid;gap:.8rem}"
         ".cite-box h3{font-size:1rem;margin:0}.cite-text{background:#fff;border:1px solid #d3e0f0;border-radius:10px;"
         "padding:.7rem .9rem;margin:0;font-size:.92rem;line-height:1.7;word-break:break-all}"
         ".cite-row{display:flex;flex-wrap:wrap;gap:.5rem;align-items:flex-start}.cite-row>.cite-text{flex:1 1 18em}"
         ".cite-copy{border:1px solid #2563eb;background:#fff;color:#2563eb;border-radius:999px;padding:.45rem 1rem;"
         "font-weight:700;cursor:pointer;font-size:.88rem}.cite-copy:hover{background:#eaf2fe}"
         ".cite-terms{font-size:.88rem;margin:0}.cite-fig img{max-width:100%;height:auto;border:1px solid #d3e0f0;border-radius:10px}"
         ".cite-fig textarea{width:100%;font-family:ui-monospace,monospace;font-size:.8rem;border:1px solid #d3e0f0;"
         "border-radius:10px;padding:.6rem;box-sizing:border-box}</style>")

# ボタンを押すと文をコピーする。JS が無くても文はそのまま選んでコピーできる（文は常に表示）。
# 同じページで2回読み込んでも1回だけ動くように印を付ける
SCRIPT = ("<script>(function(){if(window.__citeCopy)return;window.__citeCopy=1;"
          "document.addEventListener('click',function(e){var b=e.target&&e.target.closest?e.target.closest('.cite-copy'):null;"
          "if(!b)return;var t=document.getElementById(b.getAttribute('data-copy'));if(!t)return;"
          "var s=t.tagName==='TEXTAREA'?t.value:t.textContent;var o=b.textContent;"
          "function ok(){b.textContent='コピーしました';setTimeout(function(){b.textContent=o},2000);"
          "if(window.gtag)gtag('event','cta_click',{cta_id:'cite_copy_'+b.getAttribute('data-copy'),page_path:location.pathname});}"
          "function fb(){var a=document.createElement('textarea');a.value=s;document.body.appendChild(a);a.select();"
          "try{document.execCommand('copy');}catch(x){}document.body.removeChild(a);ok();}"
          "if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(s).then(ok,fb);}else{fb();}"
          "});})();</script>")

FIG_START, FIG_END = "<!--cite-fig-->", "<!--/cite-fig-->"


def embed_html(img_url, page_url, alt, caption, w, h):
    """他のサイトに貼るための HTML（図と出典リンク）"""
    E = lambda s: html.escape(s, quote=True)
    return (f'<figure><img src="{E(img_url)}" alt="{E(alt)}" width="{w}" height="{h}" loading="lazy">'
            f'<figcaption>出典: <a href="{E(page_url)}">{E(caption)}</a></figcaption></figure>')


def box_html(line, summary="", fig=None):
    """「この調査を引用する方へ」の枠。fig は (img_src, embed_html, alt, w, h)。
    図は FIG_START〜FIG_END で囲む（フォントが無く画像を作れなかったとき、build がこの区間を外す）"""
    E = html.escape
    parts = [STYLE, f'<div class="cite-box" id="{ANCHOR}"><h3>この調査を引用する方へ</h3>',
             f'<p class="cite-terms">{E(TERMS)}</p>',
             '<p class="cite-terms"><b>そのまま貼れる出典の書き方</b></p>',
             f'<div class="cite-row"><p class="cite-text" id="cite-line">{E(line)}</p>'
             '<button type="button" class="cite-copy" data-copy="cite-line">コピー</button></div>']
    if summary:
        parts.append('<p class="cite-terms"><b>要点の文（出典つき）</b></p>'
                     f'<div class="cite-row"><p class="cite-text" id="cite-summary">{E(summary)}</p>'
                     '<button type="button" class="cite-copy" data-copy="cite-summary">コピー</button></div>')
    if fig:
        src, emb, alt, w, h = fig
        parts.append(f'{FIG_START}<div class="cite-fig"><p class="cite-terms"><b>貼れる図</b>（数字は上の集計と同じです）</p>'
                     f'<img src="{E(src)}" alt="{E(alt)}" width="{w}" height="{h}" loading="lazy">'
                     '<p class="cite-terms">この図を貼る（HTML）</p>'
                     f'<textarea id="cite-embed" rows="4" readonly>{E(emb)}</textarea>'
                     '<p><button type="button" class="cite-copy" data-copy="cite-embed">HTMLをコピー</button></p></div>'
                     f'{FIG_END}')
    parts.append("</div>" + SCRIPT)
    return "".join(parts)


def strip_fig(page):
    """画像を作れなかったページから図の区間を外す（壊れた画像を貼らせない）"""
    import re
    return re.sub(re.escape(FIG_START) + ".*?" + re.escape(FIG_END), "", page, flags=re.S)


# ---- 図（Pillow）。色は make_diagram / checklist_make と同じ ----
W = 1200
PAD = 56
ROW_H = 64
HEAD_H = 170
GROUP_H = 58
FOOT_H = 96


def industry_spec(hl):
    """業種別の調査の図の中身。数字は headline() の lp・lc・oa をそのまま使う"""
    T = hl["T"]
    return {"title": f"{hl['name']}の質問に、AIは何を出典に答えるか",
            "sub": f"{ym_text(hl['date'])}調査・{hl['questions']}問・{hl['engines_text']}",
            "groups": [(f"{T['owner']}を探す質問：出典の件数に占める割合",
                        [(T["portal"], hl["lp"], 100, f"{hl['lp']}%"), (T["owner_site"], hl["lc"], 100, f"{hl['lc']}%")]),
                       (f"{T['other_short']}の質問：{T['owner_site']}を出典に含んだ回答の割合",
                        [(T["owner_site"], hl["oa"], 100, f"{hl['oa']}%")])],
            "foot": f"出典: {org_label(LAB)}　{hl['url']}"}


def ranking_spec(cur, names, url):
    """ランキングの図。各業種の1位のサイトが、出典つきで答えた質問のうち何問の出典になったか（集計のまま）"""
    rows = []
    for ind, d in cur["industries"].items():
        if not d.get("top"):
            continue
        dom, _, n = d["top"][0]
        rows.append((f"{names.get(ind, ind)}　1位 {dom}", n, d["answered"], f"{n}/{d['answered']}問"))
    return {"title": "AIが出典にするサイト：各業種の1位",
            "sub": f"{ym_text(cur['date'])}調べ・{cur['engine']}・「{cur['group']}」の質問",
            "groups": [("1位のサイトが出典になった質問の数（出典つきで答えた質問のうち）", rows)],
            "foot": f"出典: {org_label(LAB)}　{url}"}


def spec_values(spec):
    """図に描く数字（門で headline・集計と突き合わせる）"""
    return [v for _, rows in spec["groups"] for _, v, _, _ in rows]


def size(spec):
    n = sum(len(r) for _, r in spec["groups"])
    return W, HEAD_H + GROUP_H * len(spec["groups"]) + ROW_H * n + FOOT_H


def _fit(draw, text, maxw, sz, font):
    while sz > 14:
        f = font(sz)
        if draw.textlength(text, font=f) <= maxw:
            return f
        sz -= 1
    return font(14)


def png(spec):
    """PNG のバイト列。日本語フォントが無ければ SystemExit（make_diagram.font の決まり）"""
    from PIL import Image, ImageDraw
    import make_diagram as MD
    w, h = size(spec)
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, 10], fill=MD.BLUE)
    d.text((PAD, 40), spec["title"], font=_fit(d, spec["title"], w - PAD * 2, 44, MD.font), fill=MD.NAVY)
    d.text((PAD, 108), spec["sub"], font=_fit(d, spec["sub"], w - PAD * 2, 24, MD.font), fill=(91, 100, 116))
    y = HEAD_H
    label_w, val_w = 400, 150
    track_x0, track_x1 = PAD + label_w, w - PAD - val_w
    for gtitle, rows in spec["groups"]:
        d.text((PAD, y + 14), gtitle, font=_fit(d, gtitle, w - PAD * 2, 26, MD.font), fill=MD.NAVY)
        y += GROUP_H
        for label, v, vmax, txt in rows:
            d.text((PAD, y + 16), label, font=_fit(d, label, label_w - 20, 24, MD.font), fill=(30, 41, 59))
            d.rounded_rectangle([track_x0, y + 18, track_x1, y + 46], radius=14, fill=MD.SKY)
            fw = max(int((track_x1 - track_x0) * min(v / max(vmax, 1), 1)), 28)
            d.rounded_rectangle([track_x0, y + 18, track_x0 + fw, y + 46], radius=14, fill=MD.BLUE)
            d.text((track_x1 + 16, y + 12), txt, font=_fit(d, txt, val_w - 16, 30, MD.font), fill=MD.NAVY)
            y += ROW_H
    d.line([PAD, h - FOOT_H + 20, w - PAD, h - FOOT_H + 20], fill=MD.LINE, width=2)
    d.text((PAD, h - FOOT_H + 38), spec["foot"], font=_fit(d, spec["foot"], w - PAD * 2, 22, MD.font), fill=(91, 100, 116))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def write_png(spec, path):
    """図を書く。中身が同じなら書かない（ビルドのたびに画像の差分を出さない）。作れなければ False"""
    try:
        data = png(spec)
    except (SystemExit, OSError, ImportError) as e:
        print(f"WARN: 貼れる図を作れません（{str(e)[:60]}）。図の枠は外します")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_bytes() != data:
        path.write_bytes(data)
    return True
