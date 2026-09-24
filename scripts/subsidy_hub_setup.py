# -*- coding: utf-8 -*-
"""補助金サイト（配信先 seven-HPunyou）に業種ハブの仕組みを入れる。

配信先のCIは push のたびに tools/gen_blog_pages.py（一覧の再生成）→ make_dist.py
（配信物の生成）を回す。そこに「業種ハブ」を足せば、記事が増えるたびに勝手に
厚くなり、こちらの手は要らない。

  python dist_hub.py          # 同期 → 直す → 手元で生成して確かめる（押さない）
  python dist_hub.py --push   # 配信先へ commit + push
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\user\Desktop\システム開発\SSオウンドメディア（AIO）")
sys.path.insert(0, str(ROOT / "scripts"))

HUB_BLOCK = '''
# ---- 業種ハブ (/industry/<slug>/) ----
# 手法（補助金）ではなく業種から探す入口。定義は blog-system/data/industries.json
# （パイプライン側 data/industries.json の写し。配信のたびに同期される）。
# 記事が _min_articles 本たまった業種だけページを作る（薄い一覧はサイトの評価を下げる）
import json as _json
IND_FILE = ROOT / "blog-system" / "data" / "industries.json"
hub_pairs = []
if IND_FILE.is_file():
    _ind = _json.loads(IND_FILE.read_text(encoding="utf-8"))
    _min = int(_ind.get("_min_articles") or 5)

    def _detect(a):
        key = (a["title"] + " " + a["desc"]).lower()
        for ind in _ind.get("industries", []):           # 定義の順（具体的なものが先）
            if any(w.lower() in key for w in ind.get("synonyms", [])):
                return ind["slug"]
        return None

    _g = {}
    for a in arts:
        s = _detect(a)
        if s:
            _g.setdefault(s, []).append(a)
    hub_pairs = [(i, _g[i["slug"]]) for i in _ind.get("industries", [])
                 if len(_g.get(i["slug"], [])) >= _min]
    def _faq(ia):
        """記事HTMLの FAQ（details/summary）を集める。答えは記事のまま、新しい文は作らない"""
        pairs = []
        for a in ia:
            f = ROOT / "blog" / a["slug"] / "index.html"
            if not f.is_file():
                continue
            c = f.read_text(encoding="utf-8")
            for q, ans in re.findall(r'<details[^>]*>\\s*<summary>(.*?)</summary>\\s*<div class="a">(.*?)</div>', c, re.S):
                q, ans = re.sub("<[^>]+>", "", q).strip(), re.sub("<[^>]+>", "", ans).strip()
                if q and ans:
                    pairs.append((q, ans, a))
        return pairs[:60]

    hub_faqs = {}
    for ind, ia in hub_pairs:
        out = ROOT / "industry" / ind["slug"]
        out.mkdir(parents=True, exist_ok=True)
        lead = (f'{ind["name"]}で使える補助金と申請の実務について書いた記事を、'
                f'{len(ia)}本まとめました。自社に近い記事から読めます。')
        fq = _faq(ia)
        if len(fq) >= 5:
            hub_faqs[ind["slug"]] = fq
        hub_html = ('  <div class="hub">補助金が使えるかは業種より「導入するツールと事業計画」で決まります。'
                    '自社の場合は<a href="/#diagnosis">3分の無料診断（8問・登録不要）</a>で確かめられます。'
                    + (f' <a href="/industry/{ind["slug"]}/faq/">{ind["name"]}のよくある質問（{len(fq)}問）</a>' if len(fq) >= 5 else "")
                    + '</div>')
        jsonld_extra = f',\\n      {{ "@type": "ListItem", "position": 3, "name": "{ind["name"]}" }}'
        (out / "index.html").write_text(page(
            f"/industry/{ind['slug']}/",
            f"{ind['name']}の補助金・AI導入の記事({len(ia)}本)|セブンセンシズ株式会社",
            f"{ind['name']}向けの補助金活用・申請実務の記事一覧。全{len(ia)}記事。",
            f"<span style='color:#7a5b14'>{ind['name']}</span>の補助金・AI導入",
            lead, "\\n".join(card(a) for a in ia), "all",
            f'<a href="/industry/">業種から探す</a> › {ind["name"]}', hub_html, jsonld_extra),
            encoding="utf-8")
        print(f"生成: industry/{ind['slug']}/index.html ({len(ia)}本)")
    if hub_pairs:
        lis = "".join(f'<li><a class="filter" href="/industry/{i["slug"]}/">{i["name"]}（{len(v)}本）</a></li>'
                      for i, v in hub_pairs)
        coming = [i for i in _ind.get("industries", []) if 0 < len(_g.get(i["slug"], [])) < _min]
        note = ("" if not coming else
                '<p style="font-size:13px;color:var(--dim);margin-top:18px">記事が' + str(_min)
                + '本たまった業種からページを作ります。準備中: '
                + "、".join(f'{i["name"]}（{len(_g[i["slug"]])}本）' for i in coming) + "</p>")
        idx_html = ('<div class="hub">業種ごとに、補助金の対象になりやすいツールと申請の注意点をまとめています。'
                    f'</div>\\n  <ul class="filters" style="list-style:none">{lis}</ul>{note}')
        outi = ROOT / "industry"
        (outi / "index.html").write_text(page(
            "/industry/", f"業種から探す({len(hub_pairs)}業種)|AI導入補助金ブログ|セブンセンシズ株式会社",
            "補助金・AI導入の記事を業種別にまとめた入口。同じ業種の記事を横断して読めます。",
            "業種から探す", "手法ではなく、自分の業種から記事を探せる入口です。",
            "", "all", "業種から探す", idx_html), encoding="utf-8")
        print(f"生成: industry/index.html ({len(hub_pairs)}業種)")
    # 業種×よくある質問。質問形のクエリは AI Overview 表示率64.7%。答えは記事の FAQ そのまま
    for ind, ia in hub_pairs:
        fq = hub_faqs.get(ind["slug"])
        if not fq:
            continue
        outq = ROOT / "industry" / ind["slug"] / "faq"
        outq.mkdir(parents=True, exist_ok=True)
        items = "".join(f'<details style="margin:10px 0;padding:12px 16px;background:#fff;border:1px solid var(--line);border-radius:10px">'
                        f'<summary style="cursor:pointer;font-weight:700">{q}</summary>'
                        f'<p style="margin:10px 0 6px">{a}</p><p style="font-size:12.5px"><a href="/blog/{m["slug"]}/">→ {m["title"][:48]}</a></p></details>'
                        for q, a, m in fq)
        ld = _json.dumps({"@context": "https://schema.org", "@type": "FAQPage",
                          "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                                         for q, a, _ in fq]}, ensure_ascii=False)
        faq_html = (f'<div class="hub">{ind["name"]}の記事{len(ia)}本から、よくある質問と答えを1か所に集めました。'
                    f'答えは各記事に書いたものと同じです。</div>{items}'
                    f'<script type="application/ld+json">{ld}</script>')
        (outq / "index.html").write_text(page(
            f"/industry/{ind['slug']}/faq/",
            f"{ind['name']}の補助金のよくある質問({len(fq)}問)|セブンセンシズ株式会社",
            f"{ind['name']}向けの補助金・AI導入について、記事{len(ia)}本のよくある質問{len(fq)}問と答え。",
            f"<span style='color:#7a5b14'>{ind['name']}</span>の補助金 よくある質問",
            "記事に書いた質問と答えを、業種ごとに1か所へ集めています。", "", "all",
            f'<a href="/industry/">業種から探す</a> › <a href="/industry/{ind["slug"]}/">{ind["name"]}</a> › よくある質問',
            faq_html), encoding="utf-8")
        print(f"生成: industry/{ind['slug']}/faq/index.html ({len(fq)}問)")
'''

SITEMAP_ADD = '''for a in arts:
    pr = "0.9" if a["slug"] == "ai-hojokin-guide-2026" else "0.7"
    urls.append(f"  <url>\\n    <loc>{DOMAIN}/blog/{a['slug']}/</loc>\\n    <lastmod>{a['date']}</lastmod>\\n    <priority>{pr}</priority>\\n  </url>")
'''
SITEMAP_NEW = SITEMAP_ADD + '''if hub_pairs:
    urls.append(f"  <url>\\n    <loc>{DOMAIN}/industry/</loc>\\n    <lastmod>{arts[0]['date']}</lastmod>\\n    <priority>0.6</priority>\\n  </url>")
    for i, v in hub_pairs:
        urls.append(f"  <url>\\n    <loc>{DOMAIN}/industry/{i['slug']}/</loc>\\n    <lastmod>{v[0]['date']}</lastmod>\\n    <priority>0.6</priority>\\n  </url>")
        if i["slug"] in hub_faqs:
            urls.append(f"  <url>\\n    <loc>{DOMAIN}/industry/{i['slug']}/faq/</loc>\\n    <lastmod>{v[0]['date']}</lastmod>\\n    <priority>0.6</priority>\\n  </url>")
'''
LLMS_OLD = '''              f"- [補助金の記事一覧]({DOMAIN}/blog/category/hojokin/)", ""]
'''
LLMS_NEW = '''              f"- [補助金の記事一覧]({DOMAIN}/blog/category/hojokin/)", ""]
    if hub_pairs:
        lines += ["## 業種から探す", ""] + [
            f"- [{i['name']}の補助金・AI導入]({DOMAIN}/industry/{i['slug']}/): {len(v)}本" for i, v in hub_pairs] + [
            f"- [{i['name']}のよくある質問]({DOMAIN}/industry/{i['slug']}/faq/): {len(hub_faqs[i['slug']])}問"
            for i, v in hub_pairs if i["slug"] in hub_faqs] + [""]
'''
SIDEBAR_OLD = '      <li><a href="/blog/category/hojokin/">補助金の記事一覧</a></li>\n'
SIDEBAR_NEW = SIDEBAR_OLD + '      <li><a href="/industry/">業種から探す</a></li>\n'
DIST_OLD = '"youkou", "images"]'
DIST_NEW = '"youkou", "images", "industry"]'


def patch(path, pairs):
    t = path.read_text(encoding="utf-8")
    for old, new in pairs:
        if new in t:
            continue
        assert old in t, f"{path.name}: 差し込み位置が見つかりません: {old[:40]!r}"
        t = t.replace(old, new, 1)
    path.write_text(t, encoding="utf-8", newline="\n")


def main():
    import publish
    import sites as S
    cfg = S.load("subsidy")
    dest = publish.ensure_clone(cfg, publish._push_token())      # 配信先の最新に揃える
    gen = dest / "tools" / "gen_blog_pages.py"
    # 前に入れたハブの塊は一度外してから入れ直す（2回目以降も同じ結果になる）
    import re as _re
    t = gen.read_text(encoding="utf-8")
    t2 = _re.sub(r"\n# ---- 業種ハブ.*?(?=\n# ---- sitemap\.xml ----)", "", t, count=1, flags=_re.S)
    t2 = t2.replace(SITEMAP_NEW, SITEMAP_ADD).replace(LLMS_NEW, LLMS_OLD)
    # 1回目に入れた（FAQ無しの）版も外す
    old_sm = SITEMAP_ADD + '''if hub_pairs:
    urls.append(f"  <url>\\n    <loc>{DOMAIN}/industry/</loc>\\n    <lastmod>{arts[0]['date']}</lastmod>\\n    <priority>0.6</priority>\\n  </url>")
    for i, v in hub_pairs:
        urls.append(f"  <url>\\n    <loc>{DOMAIN}/industry/{i['slug']}/</loc>\\n    <lastmod>{v[0]['date']}</lastmod>\\n    <priority>0.6</priority>\\n  </url>")
'''
    old_ll = LLMS_OLD + '''    if hub_pairs:
        lines += ["## 業種から探す", ""] + [
            f"- [{i['name']}の補助金・AI導入]({DOMAIN}/industry/{i['slug']}/): {len(v)}本" for i, v in hub_pairs] + [""]
'''
    t2 = t2.replace(old_sm, SITEMAP_ADD).replace(old_ll, LLMS_OLD)
    if t2 != t:
        gen.write_text(t2, encoding="utf-8", newline="\n")
    patch(gen, [("\n# ---- sitemap.xml ----", HUB_BLOCK + "\n# ---- sitemap.xml ----"),
                (SITEMAP_ADD, SITEMAP_NEW), (LLMS_OLD, LLMS_NEW), (SIDEBAR_OLD, SIDEBAR_NEW)])
    patch(dest / "tools" / "make_dist.py", [(DIST_OLD, DIST_NEW)])
    patch(dest / "blog" / "_template.html", [(SIDEBAR_OLD, SIDEBAR_NEW)])
    (dest / "blog-system" / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "data" / "industries.json", dest / "blog-system" / "data" / "industries.json")
    print("直しました:", ", ".join(["tools/gen_blog_pages.py", "tools/make_dist.py",
                                  "blog/_template.html", "blog-system/data/industries.json"]))

    r = subprocess.run([sys.executable, "tools/gen_blog_pages.py"], cwd=dest,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-1200:], r.stderr[-600:])
    if r.returncode != 0:
        raise SystemExit("配信先の生成が通りません。押しません")
    hubs = sorted(p.parent.name for p in (dest / "industry").glob("*/index.html"))
    print("ハブ:", hubs)

    if "--push" not in sys.argv:
        print("押していません（--push で配信）")
        return
    files = ["tools/gen_blog_pages.py", "tools/make_dist.py", "blog/_template.html",
             "blog-system/data/industries.json"]
    subprocess.run(["git", "add", *files], cwd=dest, check=True)
    subprocess.run(["git", "-c", "user.name=AIO Pipeline Bot", "-c", "user.email=noreply@7senses.co.jp",
                    "commit", "-m", "業種ハブ（/industry/）を一覧の生成に足す。記事がたまった業種から自動で作る"],
                   cwd=dest, check=True)
    env = publish.git_auth(publish._push_token())
    auth_url = f"https://x-access-token@github.com/{cfg['repo']}.git"
    r = subprocess.run(["git", "push", auth_url, f"HEAD:{cfg['branch']}"], cwd=dest, env=env,
                       capture_output=True, text=True)
    print("push:", "OK" if r.returncode == 0 else "NG")
    if r.returncode != 0:
        print(r.stderr[-400:].replace(publish._push_token() or "@@", "***"))


if __name__ == "__main__":
    main()
