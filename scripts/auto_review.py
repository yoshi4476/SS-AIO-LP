# -*- coding: utf-8 -*-
"""自動で当てた修正を見直す。

機械が当てた修正は、当てた瞬間は正しくても、積み上がると記事を壊す。
実測では「関連して、[X]もあわせてご確認ください。」という同じ一文が
491箇所・174記事に入り、1記事に11本並んだものまであった。
1本ずつは正しく、全体で見ると量産の指紋になっていた。

当てる側（auto_improve / link_boost / link_new）は1本ずつしか見ない。
積み上がりを見るのはこちらの役目。毎週の自動修正の直後に必ず通す。

  python scripts/auto_review.py           # 検査だけ
  python scripts/auto_review.py --fix     # 是正する
  python scripts/auto_review.py --log     # 自動修正の台帳を見る
"""
import argparse
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"

# 1記事に置けるリンクだけの段落。これを超えるとリンク集になり、
# 読者は読み飛ばし、AIも文脈ごと拾えなくなる
MAX_LINK_PARA = 4
# 同じ言い回しを1記事で使ってよい回数。3本目からは同じ型が目につく
MAX_SAME_FORM = 2

# リンクだけで成り立つ段落（本文の途中に置かれた関連記事への導線）。
# ここを広く取ると本文を巻き込む。実際、最初の版は < を許したせいで
# figure タグの途中にマッチし、図解とCTAを削った。厳しく閉じておく:
#   ・行にHTMLタグ（< >）を1つも含まない
#   ・リンク先は相対パスの記事URLだけ（http の外部リンク、?付きのCTA、
#     #付きの診断リンクはこの時点で外れる）
#   ・行頭が記号（箇条書き・引用・見出し）でない
LINK_PARA = re.compile(
    r"^(?![-*>|#=])[^\n<>]{0,60}\[[^\]\n<>]+\]\((/[a-z0-9/-]+/)\)[^\n<>]{0,40}$",
    re.M)

# 二重の防御。ここに当たる行は、上の条件を通っても絶対に触らない
KEEP = re.compile(r"contact|diagnosis|shindan|lp\.7senses|cta-button|"
                  r"無料|相談|診断|お問い合わせ|<|>|!\[")


def form_of(line):
    """その段落がどの言い回しか。リンク部分を伏せて型だけを取り出す"""
    return re.sub(r"\[[^\]]*\]\([^)]*\)", "<L>", line).strip()


def body_and_head(path):
    t = io.open(path, encoding="utf-8-sig").read()
    m = re.match(r"^(---\s*\n.*?\n---\s*\n)(.*)$", t, re.S)
    return (m.group(1), m.group(2)) if m else ("", t)


def meta_of(head, key):
    m = re.search(r"^%s:\s*(.+)$" % key, head, re.M)
    return m.group(1).strip() if m else ""


def h2_before(body, pos):
    ms = [m for m in re.finditer(r"^## (.+)$", body, re.M) if m.start() < pos]
    return ms[-1].group(1) if ms else ""


def scan(path):
    """1記事ぶんのリンク段落を、位置・言い回し・直前のH2つきで返す"""
    head, body = body_and_head(path)
    out = []
    cand = [m for m in LINK_PARA.finditer(body) if not KEEP.search(m.group(0))]
    spans = {(m.start(), m.end()) for m in cand}
    for m in cand:
        # 前後が空行（または本文の端、または別のリンク段落）でなければ、
        # 本文の一部。触れない。リンクが空行なしで連続する形は、
        # 積み上がりの最悪の形なのでここで拾う
        before, after = body[:m.start()], body[m.end():]
        prev_end = len(before.rstrip("\n"))           # 直前の行が終わる位置
        next_start = m.end() + len(after) - len(after.lstrip("\n"))
        ok_before = (prev_end == 0 or before.endswith("\n\n")
                     or any(e == prev_end for _, e in spans))
        ok_after = (not after.strip() or after.startswith("\n\n")
                    or any(s == next_start for s, _ in spans))
        if not (ok_before and ok_after):
            continue
        out.append({"start": m.start(), "end": m.end(), "line": m.group(0),
                    "form": form_of(m.group(0)), "h2": h2_before(body, m.start())})
    return head, body, out


def link_lines(path):
    """リンク1本ぶんの行を全部拾う（段落として独立していないものも含む）

    本文に連結した行は「積み上がり」ではないので消さない。ただし同じ一文が
    サイト全体で何百と並べば、それ自体が量産の指紋になる。言い回しだけ
    振り直すために、こちらは条件を緩めて拾う。
    """
    head, body = body_and_head(path)
    out = []
    for m in LINK_PARA.finditer(body):
        if KEEP.search(m.group(0)):
            continue
        out.append({"start": m.start(), "end": m.end(), "line": m.group(0),
                    "form": form_of(m.group(0)), "h2": h2_before(body, m.start())})
    return head, body, out


# 1つの言い回しがサイト全体で占めてよい割合。link_new は8種を持つので
# 均等なら12.5%。ここを超えた分は他の型へ振り直す
MAX_SHARE = 0.16   # サイト全体で1つの言い回しが占める割合
# 型は8種（FORMS 5 + FORMS_SOFT 3）。均等に散らしても1種が12.5%になるため、
# 0.12 は達成できない基準だった（実測12.1〜12.6%で永久に「偏り」と出続けた）。
# 均等配分に3割ぶんの余裕を足した値にする。41.5%を占めていた頃とは桁が違う
MAX_DROP_RATIO = 0.06  # 1回の見直しで削ってよい本文の割合（検算の7%を割らせない）


def spread(paths, write=False):
    """サイト全体で偏った言い回しを、他の型へ散らす。リンクは触らない"""
    import cannibal_check as cc
    import link_new as ln
    share = Counter()
    per = {}
    for p in paths:
        head, body, lines = link_lines(p)
        per[p] = (head, body, lines)
        share.update(x["form"] for x in lines)
    total = sum(share.values()) or 1
    over = {f: int(n - total * MAX_SHARE) for f, n in share.items()
            if n > total * MAX_SHARE}
    if not over:
        return 0, share, total

    done = 0
    for p, (head, body, lines) in per.items():
        edits = []
        for i, x in enumerate(lines):
            if over.get(x["form"], 0) <= 0:
                continue
            m = re.search(r"\[([^\]]+)\]\(([^)]+)\)", x["line"])
            if not m:
                continue
            title, url = m.group(1), m.group(2)
            fit = cc.dice(ln.topic(x["h2"]), ln.topic(title)) if x["h2"] else 0.0
            new = ln.sentence(title, url, hash(p.stem) % 5 + i, fit)
            if form_of(new) == x["form"] or over.get(form_of(new), 0) > 0:
                continue                       # 偏っている型へ戻さない
            edits.append((x["start"], x["end"], new))
            over[x["form"]] -= 1
        if not edits:
            continue
        nb = body
        for s, e, txt in sorted(edits, reverse=True):
            nb = nb[:s] + txt + nb[e:]
        ng = guard(head, body, nb, 0)
        if ng:
            continue
        if write:
            io.open(p, "w", encoding="utf-8", newline="").write(head + nb)
        done += len(edits)
    return done, share, total


def guard(head, before, after, dropped_chars):
    """直した結果が壊れていないかを見る。1つでも崩れたら書き込まない

    機械が当てた修正を機械が検算する。ここを省くと、パターンの取りこぼしが
    そのまま本番の記事を壊す。実際、最初の版は図解とCTAを消した。
    """
    for tag in ("<figure", "</figure>", "<div", "</div>", "<details", "</details>",
                "<span", "</span>", "<a ", "</a>", "<img", "<p ", "<summary"):
        if before.count(tag) != after.count(tag):
            return "HTMLタグ %s の数が変わった（%d→%d）" % (
                tag, before.count(tag), after.count(tag))
    for word in ("cta-button", "contact/?s=", "#diagnosis", "無料"):
        if before.count(word) != after.count(word):
            return "リード導線「%s」の数が変わった（%d→%d）" % (
                word, before.count(word), after.count(word))
    if before.count("## ") != after.count("## "):
        return "見出しの数が変わった"
    # 公開条件を割らせない。内部リンク3本以上は機械ゲートの必須項目
    if len(re.findall(r"\]\(/", after)) < 3 <= len(re.findall(r"\]\(/", before)):
        return "内部リンクが3本を割る"
    if len(re.sub(r"<[^>]+>|\s", "", after)) < len(
            re.sub(r"<[^>]+>|\s", "", before)) * 0.93:
        return "本文が7%以上減った"
    # 削った行のぶん以上に本文が減っていたら、本文を巻き込んでいる
    lost = len(before) - len(after)
    if lost > dropped_chars + 200:
        return "本文が%d字減った（削除予定は%d字）" % (lost, dropped_chars)
    if not after.strip():
        return "本文が空になった"
    return ""


def findings(paths):
    """積み上がりすぎている記事を挙げる"""
    bad = []
    for p in paths:
        head, body, paras = scan(p)
        if not paras:
            continue
        forms = Counter(x["form"] for x in paras)
        over_form = {f: n for f, n in forms.items() if n > MAX_SAME_FORM}
        over_num = len(paras) - MAX_LINK_PARA
        if over_form or over_num > 0:
            bad.append({"slug": p.stem, "paras": paras, "total": len(paras),
                        "over_form": over_form, "over_num": max(0, over_num)})
    bad.sort(key=lambda x: -x["total"])
    return bad


def rewrite(slug, paras, head):
    """同じ言い回しの3本目以降を、別の型に振り直す。リンクは残す"""
    import cannibal_check as cc
    import link_new as ln
    seen = Counter()
    edits = []
    for i, x in enumerate(paras):
        seen[x["form"]] += 1
        if seen[x["form"]] <= MAX_SAME_FORM:
            continue
        m = re.search(r"\[([^\]]+)\]\(([^)]+)\)", x["line"])
        if not m:
            continue
        title, url = m.group(1), m.group(2)
        fit = cc.dice(ln.topic(x["h2"]), ln.topic(title)) if x["h2"] else 0.0
        new = ln.sentence(title, url, hash(slug) % 5 + i, fit)
        if new.strip() != x["line"].strip():
            edits.append((x["start"], x["end"], new))
    return edits


def inbound_count(paths=None):
    """記事ごとの被リンク本数。外してよいかの判断に使う"""
    texts = {p.stem: io.open(p, encoding="utf-8-sig").read()
             for p in (paths or sorted((ROOT / "articles").glob("*.md")))}
    n = Counter()
    for s, t in texts.items():
        for m in re.finditer(r"\]\([^)\s]*?/([a-z0-9-]+)/?[)#]", t):
            if m.group(1) != s and m.group(1) in texts:
                n[m.group(1)] += 1
    return n


def stuck_floor():
    """1ページ目の手前で止まっている記事は、下限を厚くする。

    全記事一律5本にしていたため、link_boost が止まっている記事へ足した分を
    ここが外し、足しては消すの繰り返しになっていた（実測で達成率4.3%）。
    順位で止まっている記事だけ12本まで守る。
    """
    try:
        import rank_rescue as RR
        # 12本には裏づけが無かった（1〜10位の被リンク中央値は5本で、
        # 11〜30位で止まっている記事の9〜10本より少ない）。priority_boost と
        # 同じ8本に寄せる。厚く守りすぎると積み上がりを外せなくなる
        return {r["slug"]: 8 for r in RR.diagnose()[0]}
    except Exception:
        return {}


def fix(path, item, write, inb=None, floor=5, floors=None):
    """言い回しを振り直し、なお多すぎる分は後ろから外す

    外すのは、送り先の被リンクが下限を割らないものだけ。割るものまで外すと、
    次の自動修正が同じ記事へまた足しに来て、足しては消すの繰り返しになる。
    """
    head, body, paras = scan(path)
    edits = rewrite(path.stem, paras, head)
    # 上限を超えた分は、記事の後ろ側（読者が離脱した後）から落とす。
    # ただし1回で削る量には上限を置く。27本を一度に4本まで削ると本文が7%以上減り、
    # 検算で毎回見送られて永久に直らなくなる（実測で4本がその状態だった）。
    # 1回ぶんずつ削れば、週次で回るうちに上限まで収まる。
    budget = int(len(re.sub(r"<[^>]+>|\s", "", body)) * MAX_DROP_RATIO)
    drop = []
    if len(paras) > MAX_LINK_PARA:
        for x in sorted(paras, key=lambda x: -x["start"]):
            if len(paras) - len(drop) <= MAX_LINK_PARA:
                break
            cost = len(re.sub(r"<[^>]+>|\s", "", x["line"]))
            if cost > budget:
                break
            budget -= cost
            m = re.search(r"\]\([^)\s]*?/([a-z0-9-]+)/?[)#]", x["line"])
            tgt = m.group(1) if m else None
            # 送り先が痩せるなら残す。言い回しだけ振り直す
            need = (floors or {}).get(tgt, floor)
            if inb is not None and tgt and inb.get(tgt, 0) - 1 < need:
                continue
            if tgt and inb is not None:
                inb[tgt] -= 1
            drop.append(x)
    dropped = {(d["start"], d["end"]) for d in drop}
    edits = [e for e in edits if (e[0], e[1]) not in dropped]

    new_body = body
    lost = 0
    for s, e in sorted(dropped, reverse=True):
        # その行と、直後の空行1つだけを落とす。前方向へはさかのぼらない。
        # さかのぼると、直前が空行でない場合に本文を巻き込む
        e2 = e
        while new_body[e2:e2 + 1] == "\n":
            e2 += 1
        e2 = min(e2, e + 2)
        lost += e2 - s
        new_body = new_body[:s] + new_body[e2:]
    for s, e, txt in sorted(edits, reverse=True):
        if s >= len(new_body) or new_body[s:e] != body[s:e]:
            continue
        new_body = new_body[:s] + txt + new_body[e:]

    ng = guard(head, body, new_body, lost)
    if ng:
        return 0, 0, ng
    if write and new_body != body:
        io.open(path, "w", encoding="utf-8", newline="").write(head + new_body)
    return len(edits), len(dropped), ""


def log_rows(n=40):
    if not LOG.is_file():
        return []
    rows = []
    for line in io.open(LOG, encoding="utf-8").read().splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows[-n:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="是正する")
    ap.add_argument("--log", action="store_true", help="自動修正の台帳を見る")
    ap.add_argument("--only", default="", help="この記事だけを対象にする（slug）")
    a = ap.parse_args()

    if a.log:
        rows = log_rows()
        print("■ 自動修正の台帳（直近%d件）\n" % len(rows))
        if not rows:
            print("   記録がありません（%s）" % LOG.relative_to(ROOT))
            return 0
        by = defaultdict(list)
        for r in rows:
            by[r.get("when", "?")[:10]].append(r)
        for d in sorted(by, reverse=True):
            print("  %s  %d件" % (d, len(by[d])))
            for r in by[d][:6]:
                print("     %-10s %-30s → %s"
                      % (r.get("by", "?"), r.get("slug", "?")[:30], r.get("what", "")[:40]))
        return 0

    paths = sorted((ROOT / "articles").glob("*.md"))
    paths = [p for p in paths if not a.only or p.stem == a.only]
    bad = findings(paths)
    _, share, total = spread(paths, write=False)
    top = share.most_common(3)
    print("■ サイト全体の言い回し（%d本）" % total)
    for f, n in top:
        mark = "  ← 偏り" if n > total * MAX_SHARE else ""
        print("   %4d本 %4.1f%%  %s%s" % (n, n / max(total, 1) * 100, f[:42], mark))
    print()
    print("■ 自動修正の見直し（%d記事を検査）\n" % len(paths))
    if not bad:
        print("   積み上がりすぎている記事はありません")
        print("   基準: リンク段落 %d本まで / 同じ言い回し %d本まで"
              % (MAX_LINK_PARA, MAX_SAME_FORM))
        print("REVIEW_OK=yes")
        return 0

    print("  %-36s %6s %s" % ("記事", "リンク段落", "内訳"))
    for x in bad[:20]:
        w = []
        if x["over_num"]:
            w.append("上限+%d本" % x["over_num"])
        for f, n in sorted(x["over_form"].items(), key=lambda i: -i[1])[:1]:
            w.append("同じ言い回し%d本「%s」" % (n, f[:22]))
        print("  %-36s %6d  %s" % (x["slug"][:36], x["total"], " / ".join(w)))
    if len(bad) > 20:
        print("  …ほか%d記事" % (len(bad) - 20))

    if not a.fix:
        print("\n  --fix を付けると、言い回しを振り直し、上限を超えた分を外します")
        print("REVIEW_OK=no")
        return 0

    rw = dr = 0
    skipped = []
    inb = inbound_count(paths)
    floors = stuck_floor()          # 止まっている記事は厚く守る
    for x in bad:
        p = ROOT / "articles" / f"{x['slug']}.md"
        r, d, ng = fix(p, x, write=True, inb=inb, floors=floors)
        if ng:
            skipped.append((x["slug"], ng))
            continue
        rw += r
        dr += d
    if skipped:
        print("\n■ 見送った記事（検算で崩れたため書き込んでいません）")
        for s, why in skipped[:10]:
            print("   %-34s %s" % (s[:34], why))
        if len(skipped) > 10:
            print("   …ほか%d本" % (len(skipped) - 10))
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with io.open(LOG, "a", encoding="utf-8", newline="") as f:
        f.write(json.dumps({"when": __import__("datetime").datetime.now().isoformat(),
                            "by": "auto_review", "slug": "(%d記事)" % len(bad),
                            "what": "言い回し%d件を振り直し・%d件を削除" % (rw, dr)},
                           ensure_ascii=False) + "\n")
    sp, share, total = spread(paths, write=True)
    print("\n   記事内の積み上がり: 振り直し%d件 / 削除%d件" % (rw, dr))
    print("   サイト全体の偏り: 振り直し%d件" % sp)

    # 直した結果をビルドの機械ゲートに通す。ここを人任せにすると、
    # 「見直したつもり」で壊れたまま公開される
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py")],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    print("\n■ ビルドの機械ゲート")
    for line in [x for x in (r.stdout or "").splitlines()
                 if not x.startswith("SKIP")][-3:]:
        print("   " + line)
    if r.returncode != 0:
        print("   通りませんでした。git checkout -- articles/ で元に戻せます")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
