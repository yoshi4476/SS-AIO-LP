# -*- coding: utf-8 -*-
"""CI のログで、お客様の守秘の語を伏せる（各ジョブの最初に ::add-mask:: を出す）。

管制塔は public のリポジトリなので、CI のログも誰でも読める（90日残る）。お客様の社について工程が出す行は
件数だけにしてある（kw_plan・rank 系・compete・findings・publish 系。2026-10-10）が、取りこぼしの保険として
お客様の守秘の語を GitHub に伏せさせる。呼ぶのは .github/actions/private-data（非公開のデータを取った直後）と
.github/actions/client-private の restore（キャッシュの記録を戻した直後）。

伏せる語（お客様の社ごと。非公開の置き場 private_store とキャッシュから戻した記録から集める）:
  - 記事の材料（brief.json）の文言: 狙う語・狙わない語・競合・事例・声・売り物と料金・読者の困りごと・FAQ
  - 一次情報（facts.json の文）
  - まだ公開していない会社情報（company.json の住所・電話・代表者・メール・監修者の名前と資格と登録番号など）
  - サイト設定の戦略の部分（site_private.json の読者・テーマ・売り物・禁止語・地域・競合）
  - キーワードの台帳と計画（clients/<id>/kw.md、キャッシュから戻した docs/kw-plan-<id>.md・data/ai_kw/<id>.json・
    data/ranks/<id>.json の語）
伏せない語（伏せるとログが読めなくなる）:
  - 2文字以下・英数だけで7文字以下・英数1語（「expo」を伏せると「export」、「development」を伏せると npm の出力まで化ける）・
    数字や日付だけの語
  - 自社3サイトの記事の題・狙う語・説明・見出しと自社の設定に出てくる語（伏せると自社の記事名まで消える）
  - 6文字以下で自社の記事の本文に出てくる語（「事務局」「要件定義」のような一般語）
  - 社の id・ドメイン・社名・サイト名・カテゴリと、先方のドメインの URL（公開側の sites/<id>.json にあり、先方のサイトで
    公開済み）。運用会社（当社）の名前

  python scripts/ci_mask.py            # CI: ::add-mask:: を出す（手元では件数だけ出す。語は出さない）
  python scripts/ci_mask.py --count    # 社ごとの伏せる語の数
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

MAX_WORDS = 800          # 1ジョブで伏せる語の上限（ログの1行ごとに全部の語を照らすので、多すぎると遅くなる）
MAX_RANK_WORDS = 300     # 順位の記録（GSC の検索語）から取る語の上限（表示の多い順）
SKIP_COMPANY = ("name", "name_en", "_readme")
NUMERIC = re.compile(r"^[\d\s.,:/%\-+年月日時分〜~()（）]+$")


def _leaves(o):
    """JSON の中の文字列を全部（キーの説明 _readme・_note は除く）"""
    if isinstance(o, dict):
        for k, v in o.items():
            if not str(k).startswith("_"):
                yield from _leaves(v)
    elif isinstance(o, list):
        for v in o:
            yield from _leaves(v)
    elif isinstance(o, str):
        for ln in o.splitlines():
            yield ln


def _read(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


BODY_CAP = 4_000_000     # 一般語を見分けるのに読む自社の本文の上限（字）
SHORT = 6                # これ以下の長さの語は、自社の本文に出てくれば一般語として伏せない


def own_corpus():
    """(自社3サイトの記事の題・狙う語・説明・見出しと自社の設定の文言, 自社の記事の本文)。
    前に出てくる語は記事名を消さないために伏せない。後は短い一般語を見分けるのに使う"""
    import sites as S
    own = set(S.own_ids())
    cats = {c: sid for sid, cfg in S.load_all().items() for c in (cfg.get("categories") or {})}
    parts, body, size = [], [], 0
    for p in sorted((ROOT / "articles").glob("*.md")):
        try:
            t = p.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        m = re.search(r"^category:\s*[\"']?([\w-]+)", t[:3000], re.M)
        if not m or cats.get(m.group(1)) not in own:
            continue
        parts += re.findall(r"^(?:title|keyword|description):\s*[\"']?(.+?)[\"']?\s*$", t[:3000], re.M)
        parts += re.findall(r"^#{2,4}\s+(.+)$", t, re.M)
        if size < BODY_CAP:
            body.append(t)
            size += len(t)
    for sid in own:
        parts += list(_leaves(S.load(sid)))
    head = "\n".join(parts).lower()
    return head, "\n".join(body).lower(), re.sub(r"[ \u3000]+", "", head)


def usable(w, corpus, public):
    w = w.strip()
    if len(w) <= 2 or NUMERIC.match(w):
        return False
    if w.isascii() and (len(w) <= 7 or (" " not in w and "@" not in w)):
        return False             # 英数1語（development・copilot など）は一般の語。伏せるとログが読めなくなる
    low = w.lower()
    if any(low == p or (len(p) >= 3 and low in p) for p in public):
        return False
    if low.startswith("http") and any(p in low for p in public if "." in p):
        return False             # 先方のサイトの公開済みの URL
    head, body, head_ns = corpus if isinstance(corpus, tuple) else (corpus, "", corpus)
    if low in head or re.sub(r"[ \u3000]+", "", low) in head_ns:     # 「AIO 対策」と「AIO対策」は同じ語
        return False
    return not (len(low) <= SHORT and low in body)


def _plan_words(text):
    """キーワード計画（Markdown）の語。表の「キーワード」の列と、「**…**: a / b」の行"""
    out = []
    for ln in text.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if ln.startswith("|") and len(cells) >= 2 and not set(cells[1]) <= set(":-") and cells[1] != "キーワード":
            out.append(cells[1])
        m = re.match(r"^\*\*(.+?)\*\*\s*[:：]\s*(.+)$", ln.strip())
        if m:
            out += [x.strip() for x in m.group(2).split("/")]
    return out


def site_words(sid, corpus=None):
    """お客様の社1つの伏せる語（重要なものから並べる）"""
    import private_store as PS
    import sites as S
    corpus = own_corpus() if corpus is None else corpus
    cfg = S.load_all().get(sid) or {}
    comp = PS.read_json(sid, "company.json", {}) or {}
    # 公開してよい語: 社の id・ドメイン・社名・サイト名・カテゴリ（公開側の sites/<id>.json）と、運用会社（当社）の名前
    public = {str(x).lower().replace("www.", "") for x in
              (sid, cfg.get("domain"), cfg.get("name"), comp.get("name"), comp.get("name_en"),
               *(cfg.get("categories") or {}).keys(), *(cfg.get("categories") or {}).values(),
               *S.OPERATOR_MARKS, "セブンセンシズ株式会社") if x}
    cand = []
    cand += list(_leaves({k: v for k, v in comp.items() if k not in SKIP_COMPANY}))
    cand += list(_leaves((PS.read_json(sid, "facts.json", {}) or {}).get("facts") or []))
    cand += list(_leaves(PS.read_json(sid, "brief.json", {}) or {}))
    cand += list(_leaves(PS.site_private(sid)))
    cand += _plan_words(PS.read_text(sid, "kw.md"))
    for rel in (f"docs/kw-plan-{sid}.md",):
        try:
            cand += _plan_words((ROOT / rel).read_text(encoding="utf-8"))
        except OSError:
            pass
    ai = _read(ROOT / "data" / "ai_kw" / f"{sid}.json") or {}
    cand += [str(x.get("kw") or "") for x in ai.get("items") or [] if isinstance(x, dict)]
    ranks = _read(ROOT / "data" / "ranks" / f"{sid}.json") or {}
    if ranks:
        last = ranks[sorted(ranks)[-1]] or []
        cand += [r.get("kw", "") for r in sorted(last, key=lambda r: -int(r.get("imp") or 0))[:MAX_RANK_WORDS]]
    out = []
    for w in cand:
        w = str(w).strip()
        if w and w not in out and usable(w, corpus, public):
            out.append(w)
    return out


def words():
    """伏せる語の全部（社ごとに重要なものから、上限まで）"""
    import sites as S
    clients = [s for s in S.load_all() if S.is_client(s)]
    if not clients:
        return {}
    corpus = own_corpus()
    per = {sid: site_words(sid, corpus) for sid in clients}
    # 上限を社に順に配る（1社が上限を食い切らないように）
    out, i = {sid: [] for sid in per}, 0
    total = 0
    while total < MAX_WORDS and any(i < len(v) for v in per.values()):
        for sid, ws in per.items():
            if i < len(ws) and total < MAX_WORDS:
                out[sid].append(ws[i])
                total += 1
        i += 1
    return out


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    try:
        got = words()
    except Exception as e:                 # 伏せる語を作れなくても、ジョブは止めない（工程の側は件数だけ出す）
        print(f"CI_MASK=error（{type(e).__name__}）")
        return 0
    n = sum(len(v) for v in got.values())
    if os.environ.get("GITHUB_ACTIONS") and "--count" not in a:
        for ws in got.values():
            for w in ws:
                print(f"::add-mask::{w}")
    for sid, ws in got.items():
        print(f"  {sid}: 伏せる語 {len(ws)}語")
    print(f"CI_MASK={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
