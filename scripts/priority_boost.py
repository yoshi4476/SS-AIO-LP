# -*- coding: utf-8 -*-
"""あと少しで1ページ目に届く記事を、こちらでやれることだけで押し上げる。

順位そのものは約束できない。決めるのはGoogleで、反映にも数ヶ月かかる。
できるのは「こちら側でやれることを、漏れなく、毎週続ける」ことだけ。
ここではその中身を固定し、毎回同じ水準まで引き上げる。

やること（すべて機械で確認できるもの）:
  1. 被リンクを下限まで集める      … 内部の評価が集まらないと順位は動かない
  2. 狙う語がタイトルに入っているか … 入っていないページは、内容が合っていても出ない
  3. 構造化データが揃っているか    … AI検索に抜き出される前提
  4. 検索エンジンへ再通知          … 直したことを知らせないと反映が遅れる

  python scripts/priority_boost.py            # 今の状態を見る
  python scripts/priority_boost.py --write    # 足りない分を埋める
"""
import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sites as S  # noqa: E402

# 主力商材に直結する語。ここが取れないと、読まれても相談につながらない
MAIN_PATTERN = {
    # サイト名が「AI集客ラボ」で、主力商材は AI を使った集客そのもの。
    # それなのに ai集客・集客代行 の語が入っておらず、実測で表示118回・
    # 11.3位の「aiかんたん集客」が対象から外れていた。
    # 士業・業種名での集客も同じ商材なので拾う
    "ai-lab": (r"aio|llmo|ai検索|ai\s*overview|生成ai|meo|seo|"
               r"ai集客|ai.{0,4}集客|集客代行|集客ツール|集客支援|"
               r"かんたん集客|指名検索"),
    "corporate": r"経理|記帳|月次決算|バックオフィス|請求書|bpo|アウトソ|代行",
    "subsidy": r"補助金|助成金|申請|採択|交付",
}
# 11〜30位。以前は 20.5 までしか見ておらず、21〜30位が丸ごと対象外だった。
# 実測（2026-08-23〜09-19）で21〜30位に138語・表示801回・クリック0が溜まっていた。
# この帯の記事も、やることは同じ（被リンク・タイトル・構造化データ・再通知）
NEAR = (10.5, 30.5)
MIN_IMP = 5              # これ未満の語は需要が読めない
INBOUND_FLOOR = 12       # 被リンクの下限。上位の記事はこのくらい持っている


def near_page1(days=28):
    """GSCから「あと少しで1ページ目」の記事を、主力の語に絞って拾う"""
    import collections
    import gsc_detail as G
    sc = G.client()
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days - 1)
    out = collections.defaultdict(lambda: {"kw": [], "imp": 0, "pos": 99.0})
    for sid, cfg in S.load_all().items():
        pat = re.compile(MAIN_PATTERN.get(sid, ""), re.I)
        try:
            # 既定の q は失敗を [] で返し、下の except に届かない（「対象なし」に化ける）
            rows = G.q(sc, cfg["domain"], str(start), str(end), ["query", "page"], 25000,
                       raise_errors=True)
        except Exception as e:
            print(f"  {sid}: GSCから取れません（{str(e)[:40]}）")
            continue
        for r in rows:
            kw, url = r["keys"][0], r["keys"][1]
            if not pat.search(kw) or r["impressions"] < MIN_IMP:
                continue
            if not (NEAR[0] < r["position"] <= NEAR[1]):
                continue
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            d = out[(sid, slug)]
            d["kw"].append((kw, r["position"], r["impressions"]))
            d["imp"] += r["impressions"]
            d["pos"] = min(d["pos"], r["position"])
    return out


def load_articles():
    return {p.stem: p.read_text(encoding="utf-8", errors="replace")
            for p in (ROOT / "articles").glob("*.md")}


def inbound(slug, texts):
    return sum(1 for k, t in texts.items() if k != slug and
               re.search(r"\]\((?:https?://[^/)]+)?/[a-z0-9/-]*" + re.escape(slug) + r"/?\)", t))


def send_links(tgt, words, want, texts):
    """話題の近い記事から、その記事へリンクを送る"""
    import auto_review as ar
    import cannibal_check as cc
    import link_new as ln
    if tgt not in texts:
        return 0
    fm = re.match(r"^---\s*\n(.*?)\n---", texts[tgt], re.S).group(1)
    title = (re.search(r"^title:\s*(.+)$", fm, re.M) or [0, ""])[1].strip()
    cat = (re.search(r"^category:\s*(.+)$", fm, re.M) or [0, ""])[1].strip()
    site = S.find_category_owner(cat)
    # corporate・subsidy は /blog/<slug>/ で配信する。カテゴリ形式で書くと配信先で404になる
    pre = S.load_all().get(site, {}).get("url_prefix")
    url = f"{pre.rstrip('/')}/{tgt}/" if pre else f"/{cat}/{tgt}/"
    cands = []
    for s, t in texts.items():
        if s == tgt or tgt in t:
            continue
        c2 = (re.search(r"^category:\s*(.+)$", t, re.M) or [0, ""])[1].strip()
        if S.find_category_owner(c2) != site:
            continue
        hit = sum(t.count(w) for w in words)
        if hit >= 3:
            cands.append((hit, s))
    cands.sort(reverse=True)
    done = 0
    for _, s in cands:
        if done >= want:
            break
        fm2, body = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", texts[s], re.S).groups()
        best, pos = 0, None
        for m in re.finditer(r"^## (.+)$", body, re.M):
            if re.search(r"まとめ|よくある質問|FAQ", m.group(1)):
                continue
            e = body.find("\n## ", m.end())
            seg = body[m.start():e if e > 0 else len(body)]
            h = sum(seg.count(w) for w in words)
            if h > best:
                after = body[m.end():]
                para = re.search(r"\n\n", after.lstrip("\n"))
                best = h
                pos = m.end() + (para.end() if para else 0) + (len(after) - len(after.lstrip("\n")))
        if pos is None:
            continue
        fit = cc.dice(ln.topic(ar.h2_before(body, pos)), ln.topic(title))
        line = ln.sentence(title, url, abs(hash(s + tgt)) % 8, fit)
        # 改行1つだと、直後の番号リストや箇条書きと1段落に繋がる。
        # 実測で306字の塊になり、検査が「1文」として数えていた
        nb = body[:pos] + "\n\n" + line + "\n\n" + body[pos:]
        nb = re.sub(r"\n{3,}", "\n\n", nb)
        (ROOT / "articles" / f"{s}.md").write_text(f"---\n{fm2}\n---\n{nb}",
                                                   encoding="utf-8", newline="")
        texts[s] = f"---\n{fm2}\n---\n{nb}"
        done += 1
    return done


def topic_words(slug, kws, texts):
    """リンク元を探すための語を作る。

    検索語を空白で割るだけだと、空白の無い日本語の語が1つの塊のまま残る。
    実測で「aiかんたん集客」は分割されず、その文字列を3回以上含む記事が
    0本だったため、11.3位・表示88回のページに1本もリンクを送れなかった。

    記事のタイトルとカテゴリからも語を取る。リンク元は「話題が近い記事」で
    あればよく、検索語と完全に一致している必要はない。
    """
    words = []
    for kw, _, _ in kws[:3]:
        words += [w for w in re.split(r"[\s　]+", kw) if len(w) >= 2]
    t = texts.get(slug, "")
    fm = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
    if fm:
        title = (re.search(r"^title:\s*(.+)$", fm.group(1), re.M) or [0, ""])[1]
        # タイトルは「｜」「？」で区切られる。飾りを落として話題語だけ残す
        head = re.split(r"[｜|？?]", title)[0]
        words += [w for w in re.split(
            r"[\s　のとをにはがでへや・、,。（）()【】\[\]0-9０-９]+", head) if len(w) >= 2]
    # 長い語から順に使う。短い語だけだと無関係な記事まで当たる
    return sorted(dict.fromkeys(w for w in words if len(w) >= 2), key=len, reverse=True)[:8]


def title_has(slug, kws, texts):
    """狙う語がタイトルに入っているか。入っていなければ順位が伸びない"""
    fm = re.match(r"^---\s*\n(.*?)\n---", texts[slug], re.S).group(1)
    title = (re.search(r"^title:\s*(.+)$", fm, re.M) or [0, ""])[1].lower()
    miss = []
    for kw, _, _ in kws[:3]:
        parts = [w for w in re.split(r"[\s　]+", kw.lower()) if len(w) >= 2]
        if parts and not all(w in title for w in parts):
            miss.append(kw)
    return miss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="足りない分を埋める")
    a = ap.parse_args()

    print("■ あと少しで1ページ目の記事（主力の語のみ）\n")
    near = near_page1()
    if not near:
        print("  対象がありません")
        return 0
    texts = load_articles()
    rows = sorted(near.items(), key=lambda x: (x[1]["pos"], -x[1]["imp"]))

    added = notes = 0
    print(f"  {'順位':>5}{'表示':>6}{'被ﾘﾝｸ':>6}  {'記事':<32} 狙う語")
    print("  " + "-" * 76)
    for (sid, slug), d in rows:
        if slug not in texts:
            continue
        inb = inbound(slug, texts)
        kws = sorted(d["kw"], key=lambda x: x[1])
        top = kws[0][0] if kws else ""
        need = max(0, INBOUND_FLOOR - inb)
        mark = f"  ←{need}本不足" if need else ""
        print(f"  {d['pos']:>5.1f}{d['imp']:>6}{inb:>6}  {slug[:32]:<32} {top[:22]}{mark}")
        if a.write and need:
            n = send_links(slug, topic_words(slug, kws, texts), need, texts)
            added += n
        miss = title_has(slug, kws, texts)
        if miss:
            notes += 1
            print(f"         ! タイトルに入っていない語: {miss[0][:30]}"
                  "（人が判断して直す）")

    print(f"\n  対象 {len(rows)}本")
    if a.write:
        print(f"  内部リンクを {added}本 足しました")
        print("  次: python scripts/auto_review.py --fix で積み上がりを見直す")
        print("      python scripts/notify_indexnow.py で検索エンジンへ再通知する")
    else:
        print("  --write を付けると、被リンクの不足を埋めます")
    if notes:
        print(f"  タイトルの調整が要るもの: {notes}本（文章の判断なので自動化しない）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
