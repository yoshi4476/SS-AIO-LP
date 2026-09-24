# -*- coding: utf-8 -*-
"""「人が判断すること」として残っていた直しを、機械に任せる。

auto_improve は、タイトルの書き換えと検索意図の見直しを人へ回していた。
理由は「正規表現で当てると主張のずれた記事が量産される」から。これは正しい。
ただし記事本体はすでに無人の claude が書いている。同じ仕組みに検算を付ければ、
ここも任せられる。判断は claude がし、**通してよいかは機械が決める**。

流れ:
  1. auto_improve が挙げた対象を1本取る
  2. claude -p に、その1本だけを直させる（何を守るかを渡す）
  3. 検算する。1つでも崩れたら git checkout で元に戻す
  4. 台帳に残す

検算（1つでも外れたら書き込まない）:
  - 触ったファイルがその1本だけか
  - 狙う語（keyword）が変わっていないか
  - タイトルが15〜45字で、狙う語を含むか
  - 本文の数字が増えていないか（**数字を作らせない**。減るのは可）
  - 外部の出典リンクが消えていないか
  - score_check の警告が増えていないか
  - kw_guard が通るか（既存記事との食い合いを作らない）
  - build.py が通るか

  python scripts/auto_rewrite.py              # 何を直すか見る
  python scripts/auto_rewrite.py --write      # 実際に直す（既定3本）
  python scripts/auto_rewrite.py --write --limit 1
"""
import argparse
import collections
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"
TITLE_MIN, TITLE_MAX = 15, 45


def sh(args, timeout=1800, stdin_text=None):
    """外部コマンドを動かす。stdin_text を渡すと標準入力から流し込む。

    **複数行の文字列を引数で渡してはいけない。** Windows では claude が
    claude.CMD（バッチ）に解決されるため、最初の改行で切れる。実測で、
    引数で渡した複数行は1行目しか届かず、書き換えが24本続けて空振りした。
    """
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="ignore", timeout=timeout,
                          input=stdin_text)


def aio_items():
    """1ページ目にいるのに AI Overview に答えを取られている疑いの記事（最優先）。

    ai_citation_check が月ごとに data/ai_citations/YYYY-MM.json に残す。
    順位はあるのにクリックが期待の半分未満＝AIが答えを出し、自社は引用されていない。
    直す手は「そこにしか無い情報」を先頭に置くこと（第8.2章の最高優先度）
    """
    files = sorted((ROOT / "data" / "ai_citations").glob("*.json"))
    if not files:
        return []
    try:
        d = json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return []
    out, seen = [], set()
    for sid, s in (d.get("sites") or {}).items():
        for it in s.get("items") or []:
            slug = (it.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
            if not slug or slug in seen or not (ROOT / "articles" / f"{slug}.md").is_file():
                continue
            seen.add(slug)
            out.append({"kind": "aio", "slug": slug, "site": sid,
                        "why": (f"{it.get('pos', 0):.1f}位・表示{it.get('imp', 0)}・CTR{it.get('ctr', 0)}%"
                                f"（目安{it.get('expected_ctr', 0)}%）｜「{it.get('kw', '')}」でAI Overviewに答えを取られている疑い")})
    return out


def targets():
    """直すべき記事を、効く順に受け取る。

    最優先は「1ページ目にいるのに AI Overview に取られている」記事（aio_items）。
    次に rank_up の「4〜10位でクリックが取れていない」。無ければ auto_improve の一覧。
    """
    # 語の欠落（stuck）を先に置く。aio より成果が確かめやすいため。
    # aio は「1ページ目にいるのにAIに答えを取られている」記事を直す種別だが、
    # 実行すると3本続けて「変更なし（直す必要なしと判断）」を返した。
    # 構造が既に整っている記事が多く、直す余地が無い。一方 stuck は
    # 「需要のある語に答える節が無い」という具体的な欠けで、
    # 直ったかを見出しで機械的に確かめられる（2026-09-22 の実測）
    head = []
    try:
        import rank_rescue as RR
        head = RR.items()                    # 表示が多い順に来る
    except Exception as e:
        print(f"  （rank_rescue から取れません: {str(e)[:50]}）")
    seen0 = {x["slug"] for x in head}
    head = head + [x for x in aio_items() if x["slug"] not in seen0]
    try:
        import rank_up
        items = rank_up.human_items()
        if items or head:
            seen = {x["slug"] for x in head}
            return head + [x for x in items if x["slug"] not in seen]
    except Exception as e:
        print(f"  （rank_up から取れないため auto_improve を使います: {str(e)[:40]}）")
    import auto_improve as ai
    try:
        return ai.human_items()
    except AttributeError:
        # auto_improve が一覧を返さない版のときは、出力から拾う
        r = sh([sys.executable, "scripts/auto_improve.py"])
        out = []
        for m in re.finditer(r"\[(title|review)\]\s+(\S+)\s+(.*)", r.stdout or ""):
            out.append({"kind": m.group(1), "slug": m.group(2), "why": m.group(3).strip()})
        return out


FRESH_DAYS = 180


def fresh_items(limit=4):
    """公開（または更新）から180日以上たった公開記事。古い順"""
    import datetime as _dt
    old = (_dt.date.today() - _dt.timedelta(days=FRESH_DAYS)).isoformat()
    rows = []
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)
        sc = re.search(r"^score:\s*(\d+)", fm, re.M)
        if not sc or int(sc.group(1)) < 90:
            continue
        d = re.search(r"^modified:\s*(\d{4}-\d{2}-\d{2})", fm, re.M) or re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", fm, re.M)
        if not d or d.group(1) > old:
            continue
        rows.append({"kind": "fresh", "slug": p.stem, "site": site_of(p.stem),
                     "why": f"公開・更新から{FRESH_DAYS}日以上（{d.group(1)}）。時点表記と dateModified を更新する"})
    rows.sort(key=lambda r: r["why"])
    return rows[:limit]


def question_items(limit=4):
    """H2に質問形が1本も無い公開記事（表示の多い順は取らず、古い順）"""
    rows = []
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.group(1), m.group(2)
        sc = re.search(r"^score:\s*(\d+)", fm, re.M)
        if not sc or int(sc.group(1)) < 90:
            continue
        h2 = re.findall(r"^##\s+(.+)$", body, re.M)
        if len(h2) < 4 or any(re.search(r"[?？]", h) for h in h2):
            continue
        d = re.search(r"^date:\s*(\S+)", fm, re.M)
        rows.append({"kind": "question", "slug": p.stem, "site": site_of(p.stem),
                     "why": f"H2 {len(h2)}本に質問形が1本も無い（公開 {d.group(1) if d else '-'}）"})
    rows.sort(key=lambda r: r["why"])
    return rows[:limit]


def desc_items(limit=4, days=28):
    """流入している上位の語が description の先頭40字に無い公開記事（表示の多い順）"""
    import gsc_detail as G
    import sites as S
    from datetime import date as _d, timedelta as _td
    end = _d.today() - _td(days=3)
    start = end - _td(days=days)
    try:
        sc = G.client()
    except Exception:
        return []
    metas = {}
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)
        sc_ = re.search(r"^score:\s*(\d+)", fm, re.M)
        cat = re.search(r"^category:\s*(\S+)", fm, re.M)
        if not sc_ or int(sc_.group(1)) < 90 or not cat:
            continue
        metas[p.stem] = {"desc": _desc_of(t), "site": S.find_category_owner(cat.group(1)) or ""}
    rows = []
    for cfg in S.load_all().values():
        by = {}
        for r in G.q(sc, cfg["domain"], str(start), str(end), ["query", "page"], 25000):
            slug = r["keys"][1].rstrip("/").split("/")[-1]
            if slug in metas:
                by.setdefault(slug, []).append((r["keys"][0], int(r["impressions"])))
        for slug, qs in by.items():
            qs.sort(key=lambda x: -x[1])
            top = [q for q, imp in qs[:3] if imp >= 10]
            if not top:
                continue
            head = metas[slug]["desc"][:40].lower()
            toks = [w for w in re.split(r"[\s　]+", top[0].lower()) if len(w) >= 2]
            if toks and all(w in head for w in toks):
                continue
            rows.append({"kind": "desc", "slug": slug, "site": metas[slug]["site"], "queries": top,
                         "imp": sum(imp for _, imp in qs[:3]),
                         "why": f"流入語「{top[0]}」が説明文の先頭に無い（表示{sum(imp for _, imp in qs[:3])}回）"})
    rows.sort(key=lambda r: -r["imp"])
    return rows[:limit]


PROMPT = """articles/{slug}.md を直してください。この1ファイル以外は触らないでください。

直す理由: {why}

{what}

必ず守ること:
- 事実を変えない。数字・社名・出典・年月日は1文字も変えない。**新しい数字を書かない**
- 外部の出典リンク（href="http…"）を消さない
- ですます調。1文は50字を目安、100字を超えない
- フロントマターの keyword は変えない
- 記事の主張をずらさない。読者が求めている答えを先に書く

直したら、変更点を1行で説明して終了してください。"""

WHAT = {
    "title": ("フロントマターの title・description と、H1相当の書き出しを\n"
              "見直してください。検索結果に出るのはタイトルと説明文の両方で、\n"
              "説明文だけを直しても、タイトルだけを直しても効きません。\n"
              "この記事は表示されているのにクリックされていません。検索結果に並ぶ他の\n"
              "ページと同じことを言っているためです。**検索結果に出せないもの**\n"
              "（違反になる例・失敗した事例・自社で実際に測った数字）をタイトルの前半に置いて\n"
              "ください。15〜45字。狙う語（keyword）は必ず残すこと。\n"
              "description は60〜160字。狙う語を含め、タイトルで言っていないことを書く\n"
              "（同じ文言を繰り返すと、検索結果で見える情報量が半分になる）。\n"
              "本文にない内容をタイトルや説明文に書かないこと（書くなら本文にも追記する）。"),
    "aio": ("この記事は検索1ページ目にいるのに、AI Overview（AIによる概要）が答えを出してしまい、\n"
            "クリックされていません。AIが引用するのは「そこにしか無い情報」です。\n"
            "1. 冒頭200字を、下に示す自社の一次情報（実数）を含む断言型の回答に書き直す\n"
            "2. 狙う語に対する答えを、40〜60字の1文＋比較表（または手順表）で本文の最初のH2直下に置く\n"
            "3. 「失敗例・注意点」の見出しに、一次情報から言える具体例を1つ足す\n"
            "4. FAQ の最初の1問を、狙う語そのものの質問にし、回答に一次情報の数字を1つ入れる\n"
            "使ってよい自社の一次情報（**この数字以外の新しい数字は書かない**）:\n{facts}"),
    "desc": ("この記事に実際に流入している検索語が、説明文（description）の前半に入っていません。\n"
             "検索結果に出る説明文に検索語が無いと、Googleが本文から別の文を切り出して並べ、意図が伝わりません。\n"
             "流入している語（多い順）:\n{queries}\n"
             "1. フロントマターの description だけを書き換える（60〜160字）。先頭40字以内に上の語のうち\n"
             "   最も多いものを自然に含める。タイトルと同じ文言の繰り返しは避ける\n"
             "2. 本文・タイトル・keyword・他のフロントマターは1文字も変えない\n"
             "3. 本文に無い数字・事実を書かない"),
    "question": ("この記事のH2見出しは名詞句ばかりで、質問の形がありません。自社の実測で、H2の1〜3割が\n"
                 "質問形の記事は、質問形ゼロの記事より平均4.2位上にいます。AI Overview は質問形の\n"
                 "クエリで64.7%出ます。\n"
                 "1. H2のうち**2〜3本だけ**を、読者がそのまま検索しそうな質問の形（「〜とは？」「〜はいくら？」\n"
                 "   「〜はどう選ぶ？」）に書き換える。まとめ・よくある質問・失敗例の見出しは変えない\n"
                 "2. 見出しの数と順番は変えない。増やさない、減らさない、統合しない\n"
                 "3. 見出しの直下の1文結論は、質問への答えになっているか読み直し、必要なら語順だけ整える\n"
                 "4. 本文・数字・出典・狙う語は変えない"),
    "fresh": ("この記事は公開（または最終更新）から6か月以上たっています。AI検索は鮮度を重視します。\n"
              "1. 「◯年◯月時点」「現在」「最新」など、時点を示す表現をすべて探す\n"
              "2. その記述が**いまも事実として正しいと本文の根拠から判断できる**箇所だけ、時点を「{ym}時点」に更新する\n"
              "3. 制度・料金・機能など、変わった可能性があり本文の根拠だけでは確かめられない箇所は、\n"
              "   数字も文も変えず、その文の直後に「（{ym}時点の再確認中）」とだけ添える\n"
              "4. 冒頭の鮮度表記が無ければ、冒頭ボックスの近くに「この記事は{ym}時点の情報です」を1文足す\n"
              "**新しい数字・新しい事実は書かない。** 年月の更新以外で数字を増やしてはいけない。\n"
              "見出し・狙う語・出典リンクは変えない。"),
    "stuck": ("この記事は検索1ページ目の手前（11〜30位）で止まっています。\n"
              "**実際に検索されている語に、記事が答えていない**のが原因です。\n"
              "下に、その語と順位・表示回数を挙げます。\n"
              "1. その語が扱う内容が、この記事の主題に**本当に含まれるか**を最初に判断する\n"
              "   含まれないなら、何も変えずに終了する（無理に足すと主題がぼやけて、\n"
              "   いま取れている順位まで落ちる）\n"
              "2. 含まれるなら、その語に答える**H2またはH3の節を1つ足す**。\n"
              "   見出しにその語を自然な日本語で入れ、直下に40〜60字の1文結論を置く\n"
              "3. 語を本文にちりばめる直し方はしないこと。読者が読んで意味のある\n"
              "   節になっていなければ順位は動かない\n"
              "4. 既存の見出し・本文は消さない。足すだけにする\n"
              "5. 同義語・言い換え（例: 整骨院と接骨院）なら別々の節を作らず、\n"
              "   1つの節でまとめて扱い、両方の呼び方を本文に書く\n"),
    "review": ("直前の自動修正で表示回数が落ちています。検索意図とずれた可能性があります。\n"
               "冒頭200字と各H2直下の1文結論を読み、狙う語で検索した人が求めている答えに\n"
               "なっているか確かめてください。ずれていれば直してください。\n"
               "ずれていなければ何も変えずに終了してください（無理に直さない）。"),
}


PERM = json.dumps({"permissions": {
    # articles/ の書き換えだけを許す。Bash も外部通信も渡さないので、
    # この工程にできるのは原稿1本の書き換えだけ。
    # 全権限を飛ばす指定は使わない（ゲートが綴りの有無で見張っている）
    "allow": ["Read", "Edit(articles/**)"],
    "defaultMode": "acceptEdits",
}}, ensure_ascii=False)


KW_NOISE = re.compile(r"[\s　のをにはがともへやかでるな・｜|【】\[\]「」（）()？?！!、。,.:：/／-]")


def title_covers_kw(title, kw):
    """タイトルが狙う語を扱っているか。助詞・記号の違いは同じ語とみなす。

    そのまま含まれるかだけで見ると「中小企業助成金」に対する
    「中小企業の助成金とは？」が落ちる。落ちた記事は検算を通らないので、
    どう直しても差し戻され、二度と直せなくなる（実測4本）。
    """
    parts = [w for w in re.split(r"[\s　]+", kw) if len(w) >= 2]
    if not parts:
        return True
    lt = title.lower()
    if any(w.lower() in lt for w in parts):
        return True
    nt, nk = KW_NOISE.sub("", lt), KW_NOISE.sub("", kw.lower())
    if nk and nk in nt:
        return True
    # 自然文の狙う語は丸ごと一致しない。内容語がどれだけ入っているかで見る
    toks = [x for x in re.split(KW_NOISE, kw.lower()) if len(x) >= 2]
    if not toks:
        return False
    hit = sum(1 for x in toks if KW_NOISE.sub("", x) in nt)
    return hit / len(toks) >= 0.7


def claude_bin():
    """claude の実行ファイルを解決する。

    Windows では `claude` は claude.cmd として入るため、名前だけを
    subprocess に渡すと WinError 2 になる（CreateProcess は PATHEXT を
    探さない）。Linux の CI では通るので、手元だけで落ちて気づきにくい。
    """
    import shutil
    return shutil.which("claude") or shutil.which("claude.cmd") or "claude"


# 記事を書く・書き直すときに使うモデル。上から順に、使える最初のものを選ぶ。
# **版が古いと 400 で落ちる**（実測: 2.1.218 は claude-opus-5-5 を
# 「version 2.1.280 or newer is required」で拒否した）。手元とCIで版が違うため、
# 名前を決め打ちにせず、版を見て切り替える
MODELS = [("claude-opus-5-5", (2, 1, 280)), ("claude-opus-5", (0, 0, 0))]


def cli_version():
    try:
        out = subprocess.run([claude_bin(), "--version"], capture_output=True,
                             text=True, timeout=60).stdout
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
        return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)
    except Exception:
        return (0, 0, 0)


def model_args():
    """`--model ...` を返す。使えない版なら1つ下のモデルに落とす"""
    v = cli_version()
    for name, need in MODELS:
        if v >= need:
            return ["--model", name]
    return []


def warns(slug):
    r = sh([sys.executable, "scripts/score_check.py", slug], timeout=300)
    return [l for l in (r.stdout or "").splitlines() if l.startswith("WARN")]


def meta(slug):
    t = (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")
    fm = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
    fm = fm.group(1) if fm else ""
    g = lambda k: (re.search(rf"^{k}:\s*(.+)$", fm, re.M) or [0, ""])[1].strip().strip('"')
    return g("title"), g("keyword"), t


def numbers(s):
    return collections.Counter(re.findall(r"[0-9０-９][0-9０-９,，.．%％]*", s))


def fact_numbers(added, had):
    """増えた数字のうち、事実として扱うべきものだけを返す。

    節を足す直しでは「3つの観点」のような個数が必ず増える。回数の差だけで
    見ると、正しい書き換えまで差し戻されて一本も直せない（実測で2/3が該当）。
    止めたいのは、記事に無かった事実の数字が公開されることだけ。
    """
    out = {}
    for tok, n in added.items():
        brand_new = tok not in had
        figure = ("%" in tok or "％" in tok or "." in tok or "．" in tok
                  or "," in tok or "，" in tok or len(tok) >= 4)
        if brand_new or figure:
            out[tok] = n
    return out


def sources(s):
    return set(re.findall(r'href="(https?://[^"]+)"', s))


def snapshot():
    """articles/ の指紋。「触ったのはこの1本だけか」を、git ではなく直前の状態と比べる。

    週次では link_boost・rank_up・split_paragraphs が先に記事を直し、その分は
    まだコミットされていない。git status と比べると、その未コミットの記事が
    「別の記事まで変わっている」と見なされ、正しい書き換えまで毎回戻していた"""
    import hashlib
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in (ROOT / "articles").glob("*.md")}


def changed_since(snap):
    now = snapshot()
    return sorted(n for n in set(snap) | set(now) if snap.get(n) != now.get(n))


def check(slug, before, before_warns, snap=None, allowed="", terms=()):
    """直した結果を検算する。通らない理由を返す（空なら合格）"""
    if snap is not None:
        other = [c for c in changed_since(snap) if c != f"{slug}.md"]
    else:
        changed = [l[3:].strip() for l in
                   (sh(["git", "status", "--porcelain", "--", "articles"]).stdout or "").splitlines()]
        other = [c for c in changed if c != f"articles/{slug}.md"]
    if other:
        return f"別の記事まで変わっています: {', '.join(other[:3])}"

    title, kw, after = meta(slug)
    _, kw0, _ = before
    if kw != kw0:
        return f"狙う語が変わりました（{kw0} → {kw}）"
    if not (TITLE_MIN <= len(title) <= TITLE_MAX):
        return f"タイトルが{len(title)}字（{TITLE_MIN}〜{TITLE_MAX}字）"
    if not title_covers_kw(title, kw):
        return f"タイトルに狙う語が入っていません（{kw}）"

    b = before[2]
    # 許可した一次情報の数字は、何回使ってもよい。回数で引くと、同じ事実を
    # 2箇所に書いただけで差し戻される（実測で4本が「3,200」で落ちた）
    ok_tokens = set(numbers(allowed or ""))
    added = numbers(after) - numbers(b)
    for tok in ok_tokens:
        added.pop(tok, None)
    new_nums = fact_numbers(added, numbers(b) + numbers(allowed or ""))
    if new_nums:
        return f"本文に無かった数字が増えました: {dict(list(new_nums.items())[:4])}"
    lost = sources(b) - sources(after)
    if lost:
        return f"出典リンクが消えました: {list(lost)[:2]}"

    now = warns(slug)
    if len(now) > len(before_warns):
        return f"警告が増えました（{len(before_warns)} → {len(now)}）"

    # --exclude-slug を必ず渡す。渡さないと、その記事自身が食い合い相手として
    # 数えられ、順位を持つ記事のリライトは100%差し戻される。
    # 実際 kw_guard は「狙う語が既存記事と完全一致: meo-algorithm-kouryaku」と
    # 自分自身を挙げて終了コード2を返していた（2026-09-22 に発見）
    r = sh([sys.executable, "scripts/kw_guard.py", kw, "--site",
            site_of(slug), "--title", title, "--exclude-slug", slug], timeout=600)
    if r.returncode:
        return f"既存記事と食い合います（kw_guard 終了コード{r.returncode}）"

    if terms:
        # 「足した」と言いながら見出しが変わっていないものを通さない。
        # 本文にちりばめるだけの直し方では順位は動かない
        heads = " ".join(re.findall(r"^#{2,4}\s*(.+)$", after, re.M)).lower()
        if not any(x.lower() in heads for x in terms):
            return "狙った語が見出しに入っていません（" + "/".join(terms[:3]) + "）"
        if len(after) < len(b) * 0.98:
            return f"本文が減りました（{len(b)}→{len(after)}字）。足す直しのはずです"

    r = sh([sys.executable, "scripts/build.py"], timeout=1800)
    if r.returncode or "BLOCKED" in (r.stdout or ""):
        return "ビルドが通りません"
    return ""


def site_of(slug):
    import sites as S
    t = (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")
    cat = (re.search(r"^category:\s*(.+)$", t, re.M) or [0, ""])[1].strip()
    return S.find_category_owner(cat) or "ai-lab"


def hub_rewrite_log(item, why):
    """管制塔の「リライトログ」に残す。手元の台帳（auto_fix.jsonl）だけだと、
    シートを見る人には直した記録が1件も見えなかった（4行しか無かった）"""
    try:
        import hub_client
        if not hub_client.enabled():
            return
        m = re.search(r"(\d+(?:\.\d+)?)位", item.get("why", ""))
        hub_client.rewrite_log(item.get("site", ""), item["slug"],
                               reason=f"{item['kind']}: {item.get('why', '')[:60]}",
                               summary=why[:80], pos_before=(m.group(1) if m else ""))
        # rank_up --effect が前後を比べる台帳にも残す。ここに無いと後順位が永遠に空欄のまま
        if m:
            import rank_up
            log = rank_up.load_log()
            log[item["slug"]] = {"at": time.strftime("%Y-%m-%d"), "pos": float(m.group(1)),
                                 "site": item.get("site", ""), "by": "auto_rewrite"}
            rank_up.save_log(log)
    except Exception as e:
        print(f"     （管制塔への記録をスキップ: {str(e)[:60]}）")


LAST = {}      # slug → 直す前後のタイトル・説明文（rewrite_rollback が戻すのに使う）


def _desc_of(text):
    m = re.search(r"^description:\s*(.+)$", text, re.M)
    return m.group(1).strip().strip('"') if m else ""


def note(slug, kind, ok, why):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"),
                            "by": "auto_rewrite", "slug": slug, "kind": kind,
                            "ok": ok, "note": why, **LAST.pop(slug, {})}, ensure_ascii=False) + "\n")


def run_one(item, write):
    slug, kind = item["slug"], item["kind"]
    p = ROOT / "articles" / f"{slug}.md"
    if not p.is_file():
        return False, "記事がありません"
    if write:
        import shutil
        if not (shutil.which("claude") or shutil.which("claude.cmd")):
            return False, "claude が見つかりません（npm install -g @anthropic-ai/claude-code）"
    if not write:
        return True, "（確認のみ）"

    before, before_warns, snap = meta(slug), warns(slug), snapshot()
    allowed = ""
    what = WHAT[kind]
    if kind == "aio":
        import facts as F
        _, fs = F.load_for(item.get("site") or site_of(slug))
        allowed = "\n".join(f"- {f.get('claim', '')}" for f in fs if f.get("claim"))
        what = what.format(facts=allowed or "（登録された一次情報がありません。数字は足さないでください）")
    if kind == "desc":
        what = what.format(queries="\n".join(f"- {q}" for q in item.get("queries") or []))
    if kind == "title":
        # 自社のGSCで実測した「効いた型」を渡す（通説ではなく、このサイトの数字で決める）
        try:
            import title_patterns as TPn
            b = TPn.brief()
            if b:
                what += "\n実測（自社GSC・1〜20位）で分かっているタイトルの型:\n" + b
        except Exception:
            pass
    if kind == "stuck":
        # 上位・引用元の記事が扱っていて、この記事に無い語（cooccur が週次で書く）
        cp = ROOT / "data" / "cooccur" / f"{slug}.json"
        if cp.is_file():
            try:
                miss = json.loads(cp.read_text(encoding="utf-8")).get("missing") or []
                if miss:
                    what += ("\n上位・引用元の記事の見出しにあって、この記事に無い語（扱う価値があるか判断して、"
                             "主題に含まれるものだけ節を足す）:\n" + "／".join(miss[:10]))
            except Exception:
                pass
    if kind == "fresh":
        # 年月の更新だけを許す。今日の年・月・日のトークンは「増えた数字」に数えない
        t = time.localtime()
        ym = f"{t.tm_year}年{t.tm_mon}月"
        what = what.format(ym=ym)
        allowed = f"{t.tm_year} {t.tm_mon} {t.tm_mon:02d} {t.tm_mday:02d} {t.tm_mday}"
    prompt = PROMPT.format(slug=slug, why=item["why"], what=what)
    # 権限を全部飛ばすのではなく、使える道具を読み書きだけに絞る。
    # この工程がやるのは1ファイルの書き換えだけで、コマンド実行も外部通信も要らない
    exe = claude_bin()
    # --permission-mode acceptEdits が無いと、Edit は「承認待ち」で止まり、
    # 何も書き換わらないまま「変更なし」で終わる。実際 16本連続で空振りし、
    # 手で1本動かして初めて「権限の許可が必要です」と出ているのが分かった。
    # 道具は Read,Edit に絞ったままなので、できるのは1ファイルの書き換えだけ。
    # 悪い書き換えは check() が見つけて git checkout で戻す
    # プロンプトは stdin で渡す（引数だと1行目しか届かない）
    r = sh([exe, "-p", "--max-turns", "40",
            *model_args(),
            "--allowedTools", "Read,Edit",
            "--settings", PERM], timeout=1800, stdin_text=prompt)
    if r.returncode and not p.read_text(encoding="utf-8-sig") != before[2]:
        return False, f"claude が動きませんでした（{(r.stderr or '')[:60]}）"

    if p.read_text(encoding="utf-8-sig") == before[2]:
        return True, "変更なし（直す必要なしと判断）"

    if kind == "fresh":
        # 鮮度を更新した記事は dateModified も動かす（検算の前に書き、ビルドまで通す）
        t = p.read_text(encoding="utf-8-sig")
        today = time.strftime("%Y-%m-%d")
        t2 = re.sub(r"^modified:.*$", f"modified: {today}", t, count=1, flags=re.M) if re.search(r"^modified:", t, re.M) \
            else re.sub(r"^(date:.*)$", rf"\1\nmodified: {today}", t, count=1, flags=re.M)
        if t2 != t:
            p.write_text(t2, encoding="utf-8", newline="")

    ng = check(slug, before, before_warns, snap, allowed,
               item.get("terms") or ())
    if not ng and kind == "desc":
        # 説明文だけの直し。本文・タイトルが1文字でも変わっていたら通さない
        strip = lambda t: re.sub(r"^description:.*$", "", t, count=1, flags=re.M)
        after_now = p.read_text(encoding="utf-8-sig")
        d = _desc_of(after_now)
        if strip(after_now) != strip(before[2]):
            ng = "説明文以外が変わりました"
        elif not (60 <= len(d) <= 160):
            ng = f"説明文が{len(d)}字（60〜160字）"
        elif item.get("queries") and not any(w in d[:40].lower() for w in re.split(r"[\s　]+", item["queries"][0].lower()) if len(w) >= 2):
            ng = "流入語が説明文の先頭に入っていません"
        if ng:
            sh(["git", "checkout", "--", f"articles/{slug}.md"])
            sh([sys.executable, "scripts/build.py"], timeout=1800)
            return False, ng
    if not ng and kind == "question":
        # 見出しの本数と順番が変わったら通さない（質問形にする直しは言い換えだけ）
        h_before = re.findall(r"^##\s+", before[2], re.M)
        after_now = p.read_text(encoding="utf-8-sig")
        h_after = re.findall(r"^##\s+(.+)$", after_now, re.M)
        if len(h_before) != len(h_after):
            ng = f"H2の本数が変わりました（{len(h_before)}→{len(h_after)}）"
        elif not any(re.search(r"[?？]", h) for h in h_after):
            ng = "質問形の見出しが1本も入りませんでした"
        if ng:
            sh(["git", "checkout", "--", f"articles/{slug}.md"])
            sh([sys.executable, "scripts/build.py"], timeout=1800)
            return False, ng
    after_text = p.read_text(encoding="utf-8-sig")
    LAST[slug] = {"before_title": before[0], "before_description": _desc_of(before[2]),
                  "after_title": meta(slug)[0], "after_description": _desc_of(after_text)}
    if ng:
        sh(["git", "checkout", "--", f"articles/{slug}.md"])
        sh([sys.executable, "scripts/build.py"], timeout=1800)
        return False, ng
    return True, f"直しました（{before[0][:24]}… → {meta(slug)[0][:24]}…）"


def selftest():
    """検算が本当に効くかを、本番の記事で確かめる。

    claude を呼ばずに、こちらで「やってはいけない書き換え」を当てて、
    検算が止めるかを見る。止まらなければ、その穴から壊れた記事が通る。
    最後は必ず git checkout で元に戻す。
    """
    import auto_improve  # 対象の取り方まで含めて試す
    items = targets()
    if not items:
        print("  対象がないため、記事を1本選んで試します")
        items = [{"kind": "title", "slug": sorted(
            p.stem for p in (ROOT / "articles").glob("*.md"))[0], "why": "自己診断"}]
    # 手を付ける前から検算に落ちる記事を選ぶと、何を当てても同じ理由で止まり、
    # 「6/6を止めた」と出ても何も試していないことになる。実際 ai-kantan-shukyaku は
    # タイトルに狙う語が無いため、5件が同じ理由で止まっていた（2026-09-23）
    slug = ""
    for it in items[:8]:
        s = it["slug"]
        if not (ROOT / "articles" / f"{s}.md").is_file():
            continue
        if not check(s, meta(s), warns(s), None):
            slug = s
            break
        print(f"  --  {s}: 直す前から検算に落ちるため、診断には使いません")
    if not slug:
        print("  NG  検算を試せる記事がありません（全件が手つかずで落ちます）")
        return 1
    p = ROOT / "articles" / f"{slug}.md"
    orig = p.read_text(encoding="utf-8-sig")
    before, before_warns, snap = meta(slug), warns(slug), snapshot()
    title, kw, body = before
    print(f"  診断に使う記事: {slug}" + chr(10))

    # やってはいけない書き換えを、1つずつ当てる
    cases = [
        ("無かった数字を書く", body.replace("。", "。前年比12.7%増です。", 1)),
        ("出典リンクを消す",
         re.sub(r'<a href="https?://[^"]+"[^>]*>(.*?)</a>', r"\1", body, count=1)),
        ("狙う語を変える", body.replace(f"keyword: {kw}", "keyword: 別の語", 1)),
        ("タイトルを短くしすぎる",
         body.replace(f"title: {title}", "title: 短い", 1)),
    ]
    # stuck 種別の検算は terms を渡したときだけ効く。別に試す
    stuck_cases = [
        ("語を本文にちりばめるだけ（見出しに入れない）",
         body + chr(10) + "この記事は接骨院にも当てはまります。" + chr(10), ("接骨院",)),
        ("見出しに入れたが本文を削る",
         body[:len(body) // 2] + chr(10) + "## 接骨院の場合" + chr(10), ("接骨院",)),
    ]
    ok = 0
    try:
        for name, broken, terms in stuck_cases:
            p.write_text(broken, encoding="utf-8", newline="")
            ng = check(slug, before, before_warns, snap, "", terms)
            print(f"  {'OK' if ng else 'NG'}  {name}: "
                  + (f"止めた（{ng[:44]}）" if ng else "素通りしました"))
            ok += bool(ng)
            p.write_text(orig, encoding="utf-8", newline="")
        for name, broken in cases:
            if broken == body:
                print(f"  --  {name}: この記事では試せません")
                continue
            p.write_text(broken, encoding="utf-8", newline="")
            ng = check(slug, before, before_warns, snap)
            print(f"  {'OK' if ng else 'NG'}  {name}: "
                  + (f"止めた（{ng[:44]}）" if ng else "素通りしました"))
            ok += bool(ng)
            p.write_text(orig, encoding="utf-8", newline="")
    finally:
        p.write_text(orig, encoding="utf-8", newline="")
        sh([sys.executable, "scripts/build.py"], timeout=1800)
    total = len(cases) + len(stuck_cases)
    print(f"\n  {ok}/{total} を止めました（記事は元に戻しました）")
    return 0 if ok == total else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=3, help="1回に直す本数")
    # 1本あたり最大30分かかる。本数だけ増やすとCIの時間上限で途中終了し、
    # 直した分がcommitされずに捨てられる。残り時間を見て、次を始めない
    ap.add_argument("--budget-min", type=int, default=0,
                    help="この分数を超えたら、次の記事に着手しない（0=無制限）")
    ap.add_argument("--selftest", action="store_true",
                    help="検算が効くかを本番の記事で確かめる（claudeは呼ばない）")
    ap.add_argument("--kind", default="", help="種別を絞る（fresh は鮮度更新だけを回す）")
    a = ap.parse_args()

    if a.selftest:
        print("■ 検算の自己診断（やってはいけない書き換えを当てて、止まるか見る）\n")
        return selftest()

    if a.kind == "fresh":
        items = fresh_items(max(a.limit, 4))
    elif a.kind == "question":
        items = question_items(max(a.limit, 4))
    elif a.kind == "desc":
        items = desc_items(max(a.limit, 4))
    else:
        items = [x for x in targets() if not a.kind or x["kind"] == a.kind]
    print(f"■ 人の判断に回っていた直し: {len(items)}件"
          + (f"（1回に{a.limit}本まで）\n" if a.write else "\n"))
    if not items:
        print("  対象がありません")
        return 0
    if not a.write:
        for x in items[:12]:
            print(f"  [{x['kind']}] {x['slug'][:36]:<36} {x['why'][:40]}")
        print("\n  --write を付けると claude が直し、機械が検算します"
              "（通らなければ元に戻します）")
        return 0

    ok = ng = 0
    started = time.time()
    for x in items[:a.limit]:
        used = (time.time() - started) / 60
        if a.budget_min and used >= a.budget_min:
            print(f"\n  {used:.0f}分使ったので、ここで止めます"
                  f"（残りは次回。上限{a.budget_min}分）")
            break
        good, why = run_one(x, True)
        print(f"  {'○' if good else '×'} [{x['kind']}] {x['slug'][:34]:<34} {why[:56]}")
        note(x["slug"], x["kind"], good, why)
        if good and why.startswith("直しました"):
            hub_rewrite_log(x, why)
        ok, ng = ok + good, ng + (not good)
    print(f"\n  直した {ok}件 / 戻した {ng}件 / {(time.time() - started) / 60:.0f}分")
    print("  台帳: automation/logs/auto_fix.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
