# -*- coding: utf-8 -*-
"""公開した記事へ、既存記事から内部リンクを送る

毎日2本公開しているため、放っておくと「どこからもリンクされていない記事」が
increase し続ける。手作業で整えても数日で元に戻る。公開のたびに送るしかない。

リンクを受けていないページは、読者にもクローラーにもたどり着かれにくい。
実測では3サイトとも公開1〜2日の記事が被リンク0本で残っていた。

置き場所は、その記事の話題にいちばん近いH2の直後。まとめ・FAQは避ける。
近さが足りないときは踏み込んだ書き方をせず、繋がる相手がいなければ何もしない。

使い方:
    python scripts/link_new.py <site_id> <slug>          # 1本ぶん送る
    python scripts/link_new.py <site_id> --all           # 不足している記事すべて
    python scripts/link_new.py <site_id> --all --dry     # 変更せず確認だけ
"""
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import cannibal_check as cc  # noqa: E402
import inbound_links as il  # noqa: E402

WANT = 2            # 1記事が受けるリンクの下限
MAX_OUT = 8         # 1記事が出すリンクの上限（増やすほど1本の重みが薄まる）
MIN_H2_FIT = 0.14   # H2との近さ。これ未満の位置に置くと文脈が切れる
MIN_TOPIC_FIT = 0.15  # 記事同士の話題の近さ。無関係な記事を無理に繋がない

SKIP_H2 = re.compile(r"まとめ|よくある質問|FAQ|Q&A|運営者情報|関連記事|この記事")

# 「5つの手順」「【2026年】」はどの記事にもある。そのまま比べると
# 無関係な記事同士でも類似度が高く出るため、話題語だけを残して測る。
BOILER = re.compile(r"\d+[つ大選]の?|【[^】]*】|[0-9]{4}年(最新|版)?|とは[？?]?|"
                    r"わかりやすく|徹底|完全|解説|まとめ|一覧|方法|手順|ステップ|"
                    r"ポイント|コツ|基本|注意点|やり方|の違い")

FORMS = [
    "{lead}は、[{title}]({url})で解説しています。",
    "{lead}については、[{title}]({url})にまとめています。",
    "{lead}は[{title}]({url})で整理しています。",
    "{lead}を先に押さえるなら、[{title}]({url})が参考になります。",
    "{lead}は[{title}]({url})でも扱っています。",
]
# H2との関係が薄いところで「実際の進め方は」と書くと話が飛んで読める。
FORMS_SOFT = [
    "あわせて[{title}]({url})もご覧ください。",
    "関連する内容として[{title}]({url})も公開しています。",
    "近い論点を[{title}]({url})で扱っています。",
]
LEAD_BY_KIND = [
    (r"費用|相場|料金|いくら|価格", "費用の目安"),
    (r"手順|ステップ|やり方|方法|進め方|流れ", "実際の進め方"),
    (r"選び方|比較|違い|どちら|使い分け", "選ぶときの基準"),
    (r"事例|実例|パターン|例文", "実際の例"),
    (r"デメリット|失敗|注意|リスク|落とし穴|対象外", "つまずきやすい点"),
    (r"対象|条件|要件|範囲", "対象になる範囲"),
    (r"とは|基本|入門|わかる", "前提となる考え方"),
]


def topic(t):
    return BOILER.sub("", t or "")


def similarity(a, b):
    return cc.dice(topic(a["title"]), topic(b["title"])) + cc.dice(a["kw"], b["kw"])


def body_of(slug):
    return re.match(r"^---\s*\n.*?\n---\s*\n(.*)$",
                    (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig"),
                    re.S).group(1)


def h2_list(body):
    return [(m.start(), m.group(1)) for m in re.finditer(r"^## (.+)$", body, re.M)
            if not SKIP_H2.search(m.group(1))]


def sentence(title, url, seed, fit):
    if fit < 0.25:
        return FORMS_SOFT[seed % len(FORMS_SOFT)].format(title=title, url=url)
    lead = next((v for pat, v in LEAD_BY_KIND if re.search(pat, title)), "関連する内容")
    return FORMS[seed % len(FORMS)].format(lead=lead, title=title, url=url)


def send_links(site_id, targets=None, want=WANT, dry=False, quiet=False):
    """targets（新記事のslug）へリンクを送る。編集した記事のslug一覧を返す"""
    arts = il.load_articles(site_id)
    inb = {s: 0 for s in arts}
    out_n = {}
    for s, x in arts.items():
        n = [t for t in x["out"] if t in inb]
        out_n[s] = len(n)
        for t in n:
            inb[t] += 1

    if targets is None:
        targets = [s for s, v in inb.items() if v < want]
    targets = [t for t in targets if t in arts]

    edits = {}
    for tgt in targets:
        y = arts[tgt]
        need = want - inb[tgt]
        if need <= 0:
            continue
        cands = []
        for s, x in arts.items():
            if s == tgt or tgt in x["out"] or out_n[s] + len(edits.get(s, [])) >= MAX_OUT:
                continue
            sc = similarity(x, y)
            if sc >= MIN_TOPIC_FIT:
                cands.append((sc + inb[s] / 100, s))   # 読まれている記事から送る
        cands.sort(key=lambda c: -c[0])

        got = 0
        for _, s in cands:
            if got >= need:
                break
            used = {e["h2"] for e in edits.get(s, [])}
            hs = [(p, h) for p, h in h2_list(body_of(s)) if h not in used]
            if not hs:
                continue
            fit, pos, h = max((cc.dice(topic(h), topic(y["title"]))
                               + cc.dice(topic(h), y["kw"]), p, h) for p, h in hs)
            if fit < MIN_H2_FIT:
                continue
            edits.setdefault(s, []).append(
                {"title": y["title"], "url": y["url"], "h2": h, "pos": pos, "fit": fit})
            got += 1
        if got < need and not quiet:
            print(f"    {tgt} へは{got}/{need}本（話題の近い記事が足りません）")

    if dry:
        for s, picks in edits.items():
            for p in picks:
                print(f"    {s} / H2「{p['h2'][:24]}」")
                print(f"      {sentence(p['title'], p['url'], 0, p['fit'])[:90]}")
        return list(edits)

    for s, picks in edits.items():
        p = ROOT / "articles" / f"{s}.md"
        c = io.open(p, encoding="utf-8-sig").read()
        for k, pk in enumerate(sorted(picks, key=lambda x: -x["pos"])):
            i = c.index(f'## {pk["h2"]}')
            j = c.index("\n\n", c.index("\n", i) + 1)
            c = c[:j] + "\n\n" + sentence(pk["title"], pk["url"],
                                          hash(s) % 5 + k, pk["fit"]) + c[j:]
        io.open(p, "w", encoding="utf-8", newline="").write(c)
    return list(edits)


def dedupe(site_id, slugs):
    """同じ記事の中で同じ先へ2回以上リンクしている分を、テキストに戻す

    Googleは同じページへの複数リンクのうち最初のアンカーしか評価しない。
    2本目以降はリンクの重みを分散させるだけになる。生成された記事は本文と
    まとめの両方で同じ記事に触れがちで、実測で53本たまっていた。
    本文は削らず、リンクだけを外す。
    """
    import sites as sites_mod
    dom = {sites_mod.load(s)["domain"]: s
           for s in ("ai-lab", "corporate", "subsidy")}
    pat = re.compile(r"\[([^\]\[]+)\]\((?:https?://([^/)]+))?(/[a-z-]+/[a-z0-9-]+/)\)")
    removed = 0
    for slug in slugs:
        f = ROOT / "articles" / f"{slug}.md"
        if not f.is_file():
            continue
        c = io.open(f, encoding="utf-8-sig").read()
        seen, out, last = set(), [], 0
        for m in pat.finditer(c):
            key = (dom.get(m.group(2), site_id) if m.group(2) else site_id, m.group(3))
            if key in seen:
                out.append(c[last:m.start()] + m.group(1))   # 文は残しリンクだけ外す
                last = m.end()
                removed += 1
            else:
                seen.add(key)
        if out:
            io.open(f, "w", encoding="utf-8", newline="").write("".join(out) + c[last:])
    return removed


def main():
    if len(sys.argv) < 3:
        raise SystemExit("使い方: python scripts/link_new.py <site_id> <slug|--all> [--dry]")
    site_id = sys.argv[1]
    dry = "--dry" in sys.argv
    tgt = None if "--all" in sys.argv else [sys.argv[2]]
    ed = send_links(site_id, tgt, dry=dry)
    print(f"  {site_id}: {len(ed)}記事にリンクを追加"
          + ("（確認のみ・未変更）" if dry else ""))
    for s in ed:
        print(f"      {s}")


if __name__ == "__main__":
    main()
