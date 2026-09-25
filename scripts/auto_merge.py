# -*- coding: utf-8 -*-
"""食い合う2本を1本に統合する。判断は claude がし、通してよいかは機械が決める。

同じ検索語に自社の2ページが出ていると、Googleはどちらを出すか決めかね、両方の
順位が下がる。「差別化」（切り口を分ける）は薄い記事が2本残るだけで、どちらの
順位も上がらない。負けている側を勝っている側へ吸収し、301で送ると、残った1本に
評価が集まる（第8.1章「統合を基本方針とする」）。

候補の根拠はGSCの実績。タイトルが似ているだけでは統合しない:
  - cannibal_check.serp_overlap: 同じ語に2ページが出て、負けた側が足を引っ張っている
  - 負けた側は28日のクリックが MAX_LOSER_CLICKS 以下、表示も勝った側以下
  - 両方が同じサイトの公開済み記事（articles/ にあり score 90 以上）

流れ:
  1. claude -p に、負けた側（loser）にしか無い中身を勝った側（survivor）へ足させる
  2. 検算。1つでも外れたら統合の直前の中身へ戻す
  3. 通れば loser を articles/_merged/ へ移し、内部リンクを付け替え、301を書く
     AI集客ラボは site/_redirects。他サイトは data/retractions.jsonl に積み、
     retract.py が配信先のリポジトリから外す
  4. 管制塔（リライトログ・KW台帳）と台帳（auto_fix.jsonl / merges.jsonl）に残す

検算（1つでも外れたら書き込まない）:
  - 触ったのが survivor の1本だけか（loser も変えていないか）
  - 狙う語が変わっていないか / タイトルが15〜45字で狙う語を含むか
  - 数字が「2本のどちらにも無かった」ものに増えていないか（数字を作らせない）
  - survivor の出典リンクが消えていないか
  - 本文が減っていないか（統合で減るのはおかしい）
  - loser にしか無かった見出しの語が1つ以上入ったか（吸収した証拠。何もしない統合を通さない）
  - score_check の警告が増えていないか / kw_guard が通るか / build が通るか

  python scripts/auto_merge.py                 # 候補を見る
  python scripts/auto_merge.py --write         # 統合する（既定2組）
  python scripts/auto_merge.py --selftest      # 検算が効くか確かめる（claude は呼ばない）

業種を入れ替えただけの同型記事（scaled_guard の組）も同じ処理で統合する（--scaled）。
候補は同じサイトで本文の重なりが SCALED_MIN_SIM 以上の組。勝ちは28日のクリック→表示で決め、
GSCを引けない組・差がつかない組・負けた側のクリックが MAX_LOSER_CLICKS を超える組は飛ばす。
検算・301・台帳は上と同じ。狙う語は勝った側のまま

  python scripts/auto_merge.py --scaled                  # 同型の組の候補を見る
  python scripts/auto_merge.py --scaled --write --limit 2
  python scripts/auto_merge.py --scaled --selftest       # 同型の組で検算が効くか
"""
import argparse
import json
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import auto_rewrite as AR  # noqa: E402  検算の部品（数字・出典・警告・kw_guard・build）を共有する

ARTICLES = ROOT / "articles"
MERGED = ARTICLES / "_merged"        # 吸収した原稿の置き場。build.py は直下しか見ない
SITE = ROOT / "site"
LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"
MERGES = ROOT / "data" / "merges.jsonl"
RETRACT = ROOT / "data" / "retractions.jsonl"
MAX_LOSER_CLICKS = 3     # これを超えてクリックがある記事は消さない（失うものがある）
MIN_SHARED_IMP = 8       # 同じ語の表示がこれ未満なら誤差
_TERM = re.compile(r"[ァ-ヶー]{2,}|[一-龥]{2,}|[A-Za-z][A-Za-z0-9\-]{2,}")
_FRAME = {"まとめ", "よくある質問", "注意点", "失敗", "手順", "方法", "ポイント", "とは", "選び方", "比較"}


def fm(slug):
    """フロントマターの主な値。無ければ空文字"""
    p = ARTICLES / f"{slug}.md"
    t = p.read_text(encoding="utf-8-sig") if p.is_file() else ""
    m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
    f = m.group(1) if m else ""
    g = lambda k: (re.search(rf"^{k}:\s*(.+)$", f, re.M) or [0, ""])[1].strip().strip('"')
    return {"title": g("title"), "keyword": g("keyword"), "category": g("category"),
            "score": int(g("score") or 0), "text": t}


def is_article(slug):
    return (ARTICLES / f"{slug}.md").is_file()


def body_of(text):
    m = re.match(r"^---\s*\n.*?\n---\s*\n(.*)$", text, re.S)
    return m.group(1) if m else text


def plain_len(text):
    return len(re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", body_of(text))))


def distinct_terms(loser_text, survivor_text):
    """loser の見出しにあって survivor の本文に無い語。吸収の証拠に使う"""
    heads = re.findall(r"^#{2,3}\s+(.+?)\s*$", body_of(loser_text), re.M)
    low = survivor_text.lower()
    out = []
    for h in heads:
        for t in _TERM.findall(h):
            if t in _FRAME or t.lower() in low or t in out:
                continue
            out.append(t)
    return out


def page_stats(site_ids):
    """サイトごとに、ページ別の 表示・クリック・順位（28日）"""
    from datetime import timedelta
    import sites as S
    out = {}
    try:
        import gsc_detail as G
        sc = G.client()
    except Exception:
        return out
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=27)
    for sid in site_ids:
        cfg = S.load_all().get(sid)
        if not cfg:
            continue
        try:
            rows = G.q(sc, cfg["domain"], str(start), str(end), ["page"], 2000)
        except Exception:
            continue
        out[sid] = {}
        for r in rows:
            slug = r["keys"][0].rstrip("/").rsplit("/", 1)[-1]
            d = out[sid].setdefault(slug, {"imp": 0, "clicks": 0, "pos": r["position"]})
            d["imp"] += r["impressions"]
            d["clicks"] += r["clicks"]
    return out


MIN_TITLE_SIM = 0.30    # 同じ語が1つだけのとき、題名か構成がこの程度は似ていること
MIN_H2_OVERLAP = 0.15


def related(pair, arts=None):
    """2本が同じ主題か。記事を1本消す操作なので、根拠は厚く取る。

    同じ語が2つ以上出ていること（1語だけの重なりは偶然が多い。実際「農業機械補助金」と
    「農業用倉庫の補助金」が「農業用倉庫 補助金」1語で挙がった）。そのうえで、題名か構成が
    似ているか、負けた側の狙う語を勝った側が既に扱っていること"""
    pair.setdefault("title_sim", 0.0)
    pair.setdefault("h2_overlap", 0.0)
    if len(pair.get("kws") or []) < 2:
        pair["why_not"] = "同じ語が1つだけ（偶然の重なりが多い）"
        return False
    import cannibal_check as CC
    arts = arts or {a["slug"]: a for a in CC.load_articles()}
    a, b = arts.get(pair["survivor"]), arts.get(pair["loser"])
    if not (a and b):
        pair["why_not"] = "記事を読めません"
        return False
    pair["title_sim"] = round(CC.dice(a["title"], b["title"]), 2)
    pair["h2_overlap"] = round(CC.h2_overlap(a, b), 2)
    covered = a["title"] + " " + a.get("kw", "") + " " + " ".join(a.get("h2", []))
    tokens = [t for t in re.split(r"[\s　]+", b.get("kw", "")) if len(t) >= 2]
    kw_covered = bool(tokens) and all(t.lower() in covered.lower() for t in tokens)
    if pair["title_sim"] >= MIN_TITLE_SIM or pair["h2_overlap"] >= MIN_H2_OVERLAP or kw_covered:
        return True
    pair["why_not"] = f"題名の似かた{pair['title_sim']}・構成の重なり{pair['h2_overlap']}・狙う語も未カバー"
    return False


def judge(pair, stats, reverse_imp=0, arts=None):
    """統合してよい組かを、実績で判定する。通らない理由を pair['skip'] に書く"""
    st = stats.get(pair["site"]) or {}
    s, l = st.get(pair["survivor"], {}), st.get(pair["loser"], {})
    pair["survivor_stat"], pair["loser_stat"] = s, l
    if not st:
        pair["skip"] = "GSCを引けませんでした"
    elif l.get("clicks", 0) > MAX_LOSER_CLICKS:
        pair["skip"] = f"負けた側にクリックがある（{l.get('clicks')}回。消すと失う）"
    elif l.get("imp", 0) > s.get("imp", 0):
        pair["skip"] = "負けた側の方が表示が多い（勝たせる向きが逆）"
    elif reverse_imp > pair["imp"]:
        pair["skip"] = "逆向きの組の方が強い"
    elif not related(pair, arts):
        pair["skip"] = f"主題が違う（{pair.get('why_not', '')}）"
    elif fm(pair["survivor"])["score"] < 90 or fm(pair["loser"])["score"] < 90:
        pair["skip"] = "未公開の記事を含む"
    elif AR.site_of(pair["survivor"]) != AR.site_of(pair["loser"]):
        pair["skip"] = "別サイトの記事どうし（統合しない）"
    else:
        pair["skip"] = ""
    return pair


def candidates(site=""):
    """GSCで同じ語に出ている2本のうち、負けた側を勝った側へ寄せる組"""
    import cannibal_check as CC
    pairs = {}
    for h in CC.serp_overlap(min_imp=MIN_SHARED_IMP):
        if site and h["site"] != site:
            continue
        win = h["win"][0]
        if not is_article(win):
            continue
        for d in h["drag"]:
            if d[0] == win or not is_article(d[0]):
                continue
            p = pairs.setdefault((h["site"], win, d[0]), {
                "site": h["site"], "survivor": win, "loser": d[0], "kws": [], "imp": 0})
            p["kws"].append({"kw": h["kw"], "imp": h["imp"], "win_pos": h["win"][1], "lose_pos": d[1]})
            p["imp"] += h["imp"]
    stats = page_stats({p["site"] for p in pairs.values()})
    arts = {a["slug"]: a for a in CC.load_articles()}
    out = []
    for (sid, win, lose), p in pairs.items():
        rev = pairs.get((sid, lose, win))
        out.append(judge(p, stats, rev["imp"] if rev else 0, arts))
    return sorted(out, key=lambda p: (bool(p["skip"]), -p["imp"]))


# 同型の組（scaled_guard）を統合する基準。scaled_guard が知らせるのは18%からだが、
# 18〜25%には「IT補助金の運送業と建設業のAI活用」のように主題の違う組が混ざる。
# 実測（2026-09-26・同じサイトの組36）: 25%以上は13組・15本で、全部が補助金サイトの
# 業種違いの連作（事業再構築の事例・AI補助金の対象要件・ものづくり補助金 など）。
# 週2組なら7週で片付く量なので、ここから始める
SCALED_MIN_SIM = 0.25


def scaled_candidates(site="", min_sim=SCALED_MIN_SIM):
    """業種を入れ替えただけの同型記事（scaled_guard の組）を、実績の多い側へ寄せる組。

    勝ちはGSCの28日の実績で決める（クリック→表示の順）。サイトのGSCを引けなかった組と、
    実績で差がつかない組は飛ばす（取れなかった値を0と扱って勝ち負けを決めない）"""
    import scaled_guard as SG
    arts = SG.corpus()
    keys = sorted(arts)
    raw = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            j = SG.jaccard(arts[a]["grams"], arts[b]["grams"])
            if j < min_sim:
                continue
            sa, sb = AR.site_of(a), AR.site_of(b)
            if sa != sb or (site and sa != site):
                continue          # サイトをまたぐ組は統合しない（301 で送れない）
            raw.append((j, sa, a, b))
    stats = page_stats({r[1] for r in raw})
    out = []
    for j, sid, a, b in raw:
        st = stats.get(sid)
        pair = {"site": sid, "kind": "scaled", "sim": round(j, 3), "kws": [], "imp": 0}
        if not st:
            pair.update(survivor=a, loser=b, skip="GSCを引けませんでした")
            out.append(pair)
            continue
        # page 次元はクリックか表示が1回でもあるページを全部返す。無い行は28日で表示0
        sa, sb = st.get(a, {"imp": 0, "clicks": 0}), st.get(b, {"imp": 0, "clicks": 0})
        ka, kb = (sa["clicks"], sa["imp"]), (sb["clicks"], sb["imp"])
        win, lose = (a, b) if ka >= kb else (b, a)
        pair.update(survivor=win, loser=lose, survivor_stat=st.get(win, {}), loser_stat=st.get(lose, {}),
                    imp=sa["imp"] + sb["imp"])
        ls = pair["loser_stat"]
        if ka == kb:
            pair["skip"] = f"実績で勝ちが決まらない（どちらもクリック{ka[0]}・表示{ka[1]}）"
        elif ls.get("clicks", 0) > MAX_LOSER_CLICKS:
            pair["skip"] = f"負けた側にクリックがある（{ls.get('clicks')}回。消すと失う）"
        elif fm(win)["score"] < 90 or fm(lose)["score"] < 90:
            pair["skip"] = "未公開の記事を含む"
        else:
            pair["skip"] = ""
        out.append(pair)
    return sorted(out, key=lambda p: (bool(p["skip"]), -p["sim"]))


PROMPT = """articles/{survivor}.md に、articles/{loser}.md の中身を統合してください。
編集するのは articles/{survivor}.md の1ファイルだけです。articles/{loser}.md は読むだけで、変更しないでください。

{reason}

やること:
- {loser} にしか無い見出し（H2/H3）・具体例・出典つきの数字・FAQ を、{survivor} の流れに合う位置へ足す。丸ごと貼らず、{survivor} の文脈に合わせて書き直す
- 重複する説明は1つにまとめる。{survivor} の既存の内容は消さない（本文は増える）
- {loser} へ向く内部リンク（{loser_url}）があれば外し、文章だけ残す
- 冒頭の1文結論・各H2直下の1文結論・FAQ（5問以上）の形は保つ
{extra}
必ず守ること:
- 数字・社名・出典・年月日は、2本のどちらかにあるものだけ。**新しい数字を書かない**
- 外部の出典リンク（href="http…"）を消さない。{loser} の出典は移す
- フロントマターの keyword・category・slug は変えない。title は変えてよいが15〜45字で狙う語（{keyword}）を含める
- description は60〜160字
- ですます調。1文は50字を目安、100字を超えない

終わったら、足した見出しを1行で説明して終了してください。"""

REASON = """理由: 同じ検索語（{kws}）で両方が検索結果に出て、評価が割れています（28日で表示{imp}回）。
{loser} は {loser_pos}位・クリック{loser_clicks}回。{survivor} は {survivor_pos}位。
薄い側を吸収して、{survivor} を1本の強い記事にします。"""

# 同型の組。業種を入れ替えただけの2本は、Google の「大量生成コンテンツの悪用」の指紋になる
REASON_SCALED = """理由: 2本は業種を入れ替えただけの同型記事です（本文の{sim}%が重なる）。
量産の指紋になるため1本にまとめます。28日の実績は {survivor} が表示{survivor_imp}回・クリック{survivor_clicks}回、
{loser} が表示{loser_imp}回・クリック{loser_clicks}回です。"""

EXTRA_SCALED = """- 統合後は複数の業種を扱う記事になる。業種ごとに違う事情（対象・事例・数字・注意点）は、業種別の見出しか表に分けて並べる
- 業種ごとの事情は、2本の本文にあったものだけを使う。どちらにも無い業種・事例・効果を書き足さない
"""


def url_of(site, slug):
    """サイト内の記事パス（301 と内部リンクの付け替えに使う）"""
    import sites as S
    cfg = S.load(site)
    prefix = cfg.get("url_prefix")
    return f"{prefix}/{slug}/" if prefix else f"/{fm(slug)['category']}/{slug}/"


def check(pair, before, before_warns, loser_text, snap):
    """統合の結果を検算する。通らない理由を返す（空なら合格）"""
    s = pair["survivor"]
    # 直前の指紋と比べる（loser を含め、survivor 以外が変わっていたら戻す）
    other = [c for c in AR.changed_since(snap) if c != f"{s}.md"]
    if other:
        return f"別の記事まで変わっています: {', '.join(other[:3])}"

    title, kw, after = AR.meta(s)
    if kw != before[1]:
        return f"狙う語が変わりました（{before[1]} → {kw}）"
    if not (AR.TITLE_MIN <= len(title) <= AR.TITLE_MAX):
        return f"タイトルが{len(title)}字（{AR.TITLE_MIN}〜{AR.TITLE_MAX}字）"
    parts = [w for w in re.split(r"[\s　]+", kw) if len(w) >= 2]
    if parts and not any(w.lower() in title.lower() for w in parts):
        return f"タイトルに狙う語が入っていません（{kw}）"

    b = before[2]
    new_nums = AR.numbers(after) - AR.numbers(b) - AR.numbers(loser_text)
    if new_nums:
        return f"2本のどちらにも無かった数字が増えました: {dict(list(new_nums.items())[:4])}"
    lost = AR.sources(b) - AR.sources(after)
    if lost:
        return f"出典リンクが消えました: {list(lost)[:2]}"
    if plain_len(after) < plain_len(b):
        return f"本文が減りました（{plain_len(b)} → {plain_len(after)}字）"
    distinct = distinct_terms(loser_text, b)
    if distinct and not any(t.lower() in after.lower() for t in distinct):
        return f"吸収した形跡がありません（{', '.join(distinct[:3])} のどれも入っていない）"

    now = AR.warns(s)
    if len(now) > len(before_warns):
        return f"警告が増えました（{len(before_warns)} → {len(now)}）"
    r = AR.sh([sys.executable, "scripts/kw_guard.py", kw, "--site", pair["site"], "--title", title], timeout=600)
    if r.returncode:
        return f"既存記事と食い合います（kw_guard 終了コード{r.returncode}）"
    r = AR.sh([sys.executable, "scripts/build.py"], timeout=1800)
    if r.returncode or "BLOCKED" in (r.stdout or ""):
        return "ビルドが通りません"
    return ""


def _append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def relink(site, from_url, to_url, survivor):
    """全記事の内部リンクを付け替える。survivor 自身へのリンクは文章に戻す"""
    import sites as S
    dom = S.load(site)["domain"]
    n = 0
    for p in ARTICLES.glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        # 絶対URLは絶対URLのまま付け替える。相対にすると、他サイトの記事から張った
        # https://corp…/blog/x/ が /blog/y/ になり、そのサイトのドメインで404になる
        u = t.replace(f"https://{dom}{from_url}", f"https://{dom}{to_url}").replace(from_url, to_url)
        if p.stem == survivor:
            u = re.sub(rf'<a href="(?:https://{re.escape(dom)})?{re.escape(to_url)}"[^>]*>(.*?)</a>', r"\1", u)
            u = re.sub(rf"\[([^\]]+)\]\((?:https://{re.escape(dom)})?{re.escape(to_url)}\)", r"\1", u)
        if u != t:
            p.write_text(u, encoding="utf-8", newline="")
            n += 1
    return n


def apply(pair, why):
    """検算を通った統合を、ファイル・301・管制塔に反映する"""
    import sites as S
    site, s, l = pair["site"], pair["survivor"], pair["loser"]
    from_url, to_url = url_of(site, l), url_of(site, s)
    today = date.today().isoformat()

    # 1. 吸収した原稿を退避（履歴と再生成の材料。build.py の対象からは外れる）
    MERGED.mkdir(exist_ok=True)
    t = (ARTICLES / f"{l}.md").read_text(encoding="utf-8-sig")
    t = t.replace("---\n", f"---\nmerged_into: {s}\nmerged_at: {today}\n", 1)
    (MERGED / f"{l}.md").write_text(t, encoding="utf-8", newline="")
    (ARTICLES / f"{l}.md").unlink()

    # 2. 内部リンクの付け替え
    n = relink(site, from_url, to_url, s)

    # 3. 301。自サイトは _redirects に直接、他サイトは retract.py が配信先で行う
    if site == S.primary():
        stale = SITE / (from_url.strip("/").split("/")[0]) / l
        if stale.exists():
            shutil.rmtree(stale)
        rd = SITE / "_redirects"
        line = f"{from_url}  {to_url}  301"
        cur = rd.read_text(encoding="utf-8") if rd.is_file() else ""
        if line not in cur:
            rd.write_text(cur.rstrip("\n") + f"\n# 統合（{today}）: {l} → {s}\n{line}\n", encoding="utf-8", newline="\n")
        llms = SITE / "llms.txt"
        if llms.is_file():
            keep = [x for x in llms.read_text(encoding="utf-8").splitlines() if from_url not in x]
            llms.write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")
    else:
        _append(RETRACT, {"site": site, "slug": l, "from": from_url, "to": to_url,
                          "at": today, "reason": f"統合: {s} に吸収"})

    AR.sh([sys.executable, "scripts/build.py"], timeout=1800)

    # 4. 台帳と管制塔
    rec = {"at": today, "site": site, "survivor": s, "loser": l, "from": from_url, "to": to_url,
           "kws": [k["kw"] for k in pair["kws"]], "imp": pair["imp"], "relinked": n, "note": why[:120]}
    if pair.get("kind") == "scaled":
        rec.update(kind="scaled", sim=pair["sim"])
    _append(MERGES, rec)
    pos = pair.get("survivor_stat", {}).get("pos", "")
    # 順位の台帳は手元のもの。管制塔の有無に関係なく残す（無い回に記録ごと消えていた）
    if pos:
        try:
            import rank_up
            log = rank_up.load_log()
            log[s] = {"at": today, "pos": float(pos), "site": site, "by": "auto_merge"}
            rank_up.save_log(log)
        except Exception as e:
            print(f"     （順位の台帳への記録をスキップ: {str(e)[:60]}）")
    try:
        import hub_client
        if hub_client.enabled():
            reason = (f"統合: {l} を吸収（同型・本文の重なり{round(pair['sim'] * 100)}%）"
                      if pair.get("kind") == "scaled" else
                      f"統合: {l} を吸収（同じ語{len(pair['kws'])}・表示{pair['imp']}）")
            hub_client.rewrite_log(site, s, reason=reason,
                                   summary=why[:80], pos_before=(round(pos, 1) if pos else ""))
            lkw = fm_merged(l)["keyword"]
            if lkw:
                hub_client.retire_kw(site, [lkw], f"統合で {s} に吸収", force=True)
    except Exception as e:
        print(f"     （管制塔への記録をスキップ: {str(e)[:60]}）")
    return rec


def fm_merged(slug):
    p = MERGED / f"{slug}.md"
    t = p.read_text(encoding="utf-8-sig") if p.is_file() else ""
    m = re.search(r"^keyword:\s*(.+)$", t, re.M)
    return {"keyword": (m.group(1).strip().strip('"') if m else "")}


def note(pair, ok, why):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "by": "auto_merge",
                            "slug": pair["survivor"],
                            "kind": "merge-scaled" if pair.get("kind") == "scaled" else "merge",
                            "loser": pair["loser"],
                            "ok": ok, "note": why}, ensure_ascii=False) + "\n")


def run_one(pair, write):
    s, l = pair["survivor"], pair["loser"]
    if not (is_article(s) and is_article(l)):
        return False, "記事がありません"
    if not write:
        return True, "（確認のみ）"
    raw = (ARTICLES / f"{s}.md").read_bytes()
    before, before_warns, snap = AR.meta(s), AR.warns(s), AR.snapshot()
    loser_text = fm(l)["text"]
    ls, ss = pair.get("loser_stat", {}), pair.get("survivor_stat", {})
    if pair.get("kind") == "scaled":
        reason = REASON_SCALED.format(
            survivor=s, loser=l, sim=round(pair["sim"] * 100),
            survivor_imp=ss.get("imp", 0), survivor_clicks=ss.get("clicks", 0),
            loser_imp=ls.get("imp", 0), loser_clicks=ls.get("clicks", 0))
        extra = EXTRA_SCALED
    else:
        reason = REASON.format(
            survivor=s, loser=l, kws="「" + "」「".join(k["kw"] for k in pair["kws"][:4]) + "」",
            imp=pair["imp"], loser_pos=round(ls.get("pos", 0), 1), loser_clicks=ls.get("clicks", 0),
            survivor_pos=round(ss.get("pos", 0), 1))
        extra = ""
    prompt = PROMPT.format(survivor=s, loser=l, reason=reason, extra=extra,
                           loser_url=url_of(pair["site"], l), keyword=before[1])
    # 実行ファイルの解決と書き込み承認は auto_rewrite と揃える。
    # どちらが欠けても、統合は静かに「変更なし」で終わる
    # プロンプトは stdin で渡す（引数だと1行目しか届かない）
    r = AR.sh([AR.claude_bin(), "-p", "--max-turns", "60",
               *AR.model_args(),
               "--allowedTools", "Read,Edit",
               "--settings", AR.PERM], timeout=2400, stdin_text=prompt)
    p = ARTICLES / f"{s}.md"
    if r.returncode and p.read_text(encoding="utf-8-sig") == before[2]:
        return False, f"claude が動きませんでした（{(r.stderr or '')[:60]}）"
    if p.read_text(encoding="utf-8-sig") == before[2]:
        return False, "変更なし（統合されませんでした）"
    ng = check(pair, before, before_warns, loser_text, snap)
    if ng:
        # survivor を統合の直前の中身へ戻す。HEAD へ戻すと、先に走った工程の未コミットの直しまで消える
        p.write_bytes(raw)
        AR.sh([sys.executable, "scripts/build.py"], timeout=1800)
        return False, ng
    why = f"統合しました（{l} → {s}、本文 {plain_len(before[2])} → {plain_len(p.read_text(encoding='utf-8-sig'))}字）"
    apply(pair, why)
    return True, why


def selftest(scaled=False):
    """検算が本当に効くかを、本番の記事で確かめる（claude は呼ばない）。
    やってはいけない統合を当てて止まるかを見る。最後は必ず元に戻す。
    scaled=True は同型の組（業種違いの連作）で試す。GSCは引かない"""
    import cannibal_check as CC
    pairs = []
    if scaled:
        import scaled_guard as SG
        sarts = SG.corpus()
        keys = sorted(sarts)
        pairs = sorted(((SG.jaccard(sarts[a]["grams"], sarts[b]["grams"]), a, b)
                        for i, a in enumerate(keys) for b in keys[i + 1:]
                        if AR.site_of(a) == AR.site_of(b)), reverse=True)[:1]
        pairs = [(a, b) for j, a, b in pairs if j >= SCALED_MIN_SIM]
        if not pairs:
            print("  同型の組がありません（統合するものが無いので検算も要りません）")
            return 0
        s, l = pairs[0]
        print(f"  試す組: {l} → {s}\n")
    else:
        arts = CC.load_articles()
        pairs = CC.find_pairs(arts)
        if pairs:
            s, l = pairs[0]["a"]["slug"], pairs[0]["b"]["slug"]
        else:
            s, l = arts[0]["slug"], arts[1]["slug"]
    pair = {"site": AR.site_of(s), "survivor": s, "loser": l, "kws": [{"kw": "自己診断"}], "imp": 0}
    p = ARTICLES / f"{s}.md"
    orig = p.read_bytes()
    before, before_warns, snap = AR.meta(s), AR.warns(s), AR.snapshot()
    title, kw, body = before
    loser_text = fm(l)["text"]
    fake = next(n for n in ("98.76%", "1,234,567円", "77.7倍") if n not in body and n not in loser_text)
    half = body[: len(body) * 3 // 5]
    cases = [
        ("2本のどちらにも無い数字を書く", body.replace("。", f"。前年比{fake}増です。", 1)),
        ("出典リンクを消す", re.sub(r'<a href="https?://[^"]+"[^>]*>(.*?)</a>', r"\1", body, count=1)),
        ("本文を減らす", half),
        ("狙う語を変える", body.replace(f"keyword: {kw}", "keyword: 別の語", 1)),
    ]
    if scaled and distinct_terms(loser_text, body):
        # 業種違いの統合で起きやすい失敗: 自分の文を繰り返して本文だけ増やし、
        # 負けた側の業種の事情が1つも入らない（何もしない統合）
        own = next((x + "。" for x in re.split(r"。", body_of(body))
                    if len(x.strip()) >= 20 and not re.search(r"[0-9０-９#<>\[\]|*]", x)), "")
        if own:
            cases.append(("負けた側の中身を入れずに本文だけ増やす", body.replace(own, own + own.strip(), 1)))
    ok = 0
    try:
        for name, broken in cases:
            if broken == body:
                print(f"  --  {name}: この記事では試せません")
                continue
            p.write_text(broken, encoding="utf-8", newline="")
            ng = check(pair, before, before_warns, loser_text, snap)
            print(f"  {'OK' if ng else 'NG'}  {name}: " + (f"止めた（{ng[:44]}）" if ng else "素通りしました"))
            ok += bool(ng)
            p.write_bytes(orig)
    finally:
        p.write_bytes(orig)
        AR.sh([sys.executable, "scripts/build.py"], timeout=1800)
    print(f"\n  {ok}/{len(cases)} を止めました（記事は元に戻しました）")
    return 0 if ok == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=2, help="1回に統合する組数")
    ap.add_argument("--budget-min", type=int, default=0, help="この分数を超えたら次の組に着手しない（0=無制限）")
    ap.add_argument("--selftest", action="store_true", help="検算が効くかを本番の記事で確かめる")
    ap.add_argument("--scaled", action="store_true",
                    help=f"業種を入れ替えただけの同型の組（scaled_guard・重なり{SCALED_MIN_SIM:.0%}%以上）を統合する")
    a = ap.parse_args()
    if a.selftest:
        print("■ 統合の検算の自己診断" + ("（同型の組）" if a.scaled else "") + "\n")
        return selftest(a.scaled)

    if a.scaled:
        pairs = scaled_candidates(a.site)
        ready = [p for p in pairs if not p["skip"]]
        print(f"■ 業種を入れ替えただけの同型の組（重なり{SCALED_MIN_SIM:.0%}以上）: {len(pairs)}（統合できる {len(ready)}）"
              + (f"（1回に{a.limit}組まで）" if a.write else "") + "\n")
        for p in pairs[:20]:
            ss, ls = p.get("survivor_stat") or {}, p.get("loser_stat") or {}
            print(f"  {'○' if not p['skip'] else '－'} [{p['site']}] {p['sim']:.0%} "
                  f"{p['loser'][:34]:<34} → {p['survivor'][:34]:<34} "
                  f"クリック{ls.get('clicks', 0)}/{ss.get('clicks', 0)} 表示{ls.get('imp', 0)}/{ss.get('imp', 0)}"
                  + (f"  ｜{p['skip']}" if p["skip"] else ""))
    else:
        pairs = candidates(a.site)
        ready = [p for p in pairs if not p["skip"]]
        print(f"■ 同じ語で食い合っている組: {len(pairs)}（統合できる {len(ready)}）"
              + (f"（1回に{a.limit}組まで）" if a.write else "") + "\n")
        for p in pairs[:15]:
            mark = "○" if not p["skip"] else "－"
            print(f"  {mark} [{p['site']}] {p['loser'][:30]:<30} → {p['survivor'][:30]:<30} "
                  f"同じ語{len(p['kws'])} 表示{p['imp']}"
                  + (f"  ｜{p['skip']}" if p["skip"] else f"  例:「{p['kws'][0]['kw']}」"))
    if not ready:
        print("\n  統合できる組はありません")
        return 0
    if not a.write:
        print("\n  --write を付けると claude が統合し、機械が検算します（通らなければ元に戻します）")
        return 0

    ok = ng = 0
    started = time.time()
    gone = {}                      # この回で吸収された記事 → 生き残り
    for p in ready[: a.limit]:
        used = (time.time() - started) / 60
        if a.budget_min and used >= a.budget_min:
            print(f"\n  {used:.0f}分使ったので、ここで止めます（残りは次回）")
            break
        if p["loser"] in gone:
            print(f"  － {p['loser'][:28]} は既に {gone[p['loser']]} に吸収済み")
            continue
        if p["loser"] in gone.values():
            # 今回吸収したばかりの記事をさらに別の記事へ吸収すると、301 が2段になり、
            # 検算も1段目の中身を見ないまま通る。次回、実績を取り直してから決める
            print(f"  － {p['loser'][:28]} は今回ほかの記事を吸収したので次回")
            continue
        while p["survivor"] in gone:   # 生き残りが先に別の記事へ吸収されていたら、その先へ
            p["survivor"] = gone[p["survivor"]]
        good, why = run_one(p, True)
        if good:
            gone[p["loser"]] = p["survivor"]
        print(f"  {'○' if good else '×'} {p['loser'][:28]} → {p['survivor'][:28]}  {why[:60]}")
        note(p, good, why)
        ok, ng = ok + good, ng + (not good)
    print(f"\n  統合した {ok}組 / 戻した {ng}組 / {(time.time() - started) / 60:.0f}分")
    print("  台帳: data/merges.jsonl / automation/logs/auto_fix.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
