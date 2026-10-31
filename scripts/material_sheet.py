# -*- coding: utf-8 -*-
"""材料の質問シートを社ごとに機械で作り、返ってきたシートを一次情報・体験として登録する。

採点で一次性が足りない記事には、quality_loop が「何を教えてほしいか」の依頼（material_requests.json）を残す。
これまでは依頼を人が読んで質問シートに書き直していた（2026-10-21）。ここでは依頼の質問と、採点で何度も出る
足りないもの（事例カード・失敗の件数・判断の基準の根拠・費用の実例・お客様の声・確認の一覧・担当者の経歴）を
1枚にまとめる。返ってきたシートは intake/ に置けば intake_watch.py が拾う（隠しタブ「材料の質問」で見分ける）。

**登録で守ること**:
- 答えに無い数字は登録しない（AI が文に直すときに数字を作ると、事実と違う記事が公開される）
- 既存の記録と食い違う答えは登録せず保留にして知らせる（2026-10-21 のお客様の社の答えで、12件の費用の幅と
  34件の原因が既存の記録と食い違った。そのまま記事に載せると読者にも採点にも矛盾として読まれる）
- 「記事に出してよいか」が不可の答えと、お客様の声（掲載の許可の確認が要る）は登録しない

  python scripts/material_sheet.py --make [--site <id>] [--out <フォルダ>]   # 依頼のある社の質問シート（既定はデスクトップ）
  python scripts/material_sheet.py --apply <xlsx> [--write]                    # 返ってきたシートを登録（--write なしは見るだけ）
  python scripts/material_sheet.py --book [--site <id>,<id>] [--out <フォルダ>]
      # 社ごとの1冊: 今まで出した一次情報の台帳・図表にした数字・追加のヒアリング（質問のタブは --apply でそのまま登録できる）
  python scripts/material_sheet.py --measure <site> <URL> <YYYY-MM-DD> --what "<やったこと>" [--write]
      # 自社サイトでやったことの前と後の28日（Search Console の表示・平均順位）を一次情報の文にする
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

TAB, META = "質問", "材料の質問"
OWN_FACTS = ROOT / "data" / "first_party_facts.json"
OWN_EXPS = ROOT / "data" / "experiences.json"
COLS = ["No", "記事・項目", "質問", "書き方の目安", "答え（ここに記入）", "時期・期間", "件数・母数", "記事に出してよいか（可・不可）"]

# 採点で何度も足りないと言われる材料（2026-10-21 の採点の記録から）。client_only はお客様の社だけに聞く
TEMPLATE = [
    ("case1", "事例カード", "支援した事例を1件。業種・規模・始めた月・やったこと（何を何本・何を作ったか）・前と後の数字・期間",
     "例の書き方: 2025年◯月／製造業・従業員◯名／◯◯を◯本作った／問い合わせ 月◯件→月◯件（◯か月）", False),
    ("case2", "事例カード", "もう1件、別の業種か規模の事例を、上と同じ形で", "同上", False),
    ("fail", "失敗の件数と理由", "全体の何件のうち、何件がうまくいかなかったか。それぞれの理由",
     "例の書き方: ◯年◯月〜◯年◯月の◯件のうち◯件。理由: ◯◯が◯件・◯◯が◯件", False),
    ("rule", "判断の基準の根拠", "記事で使っている判断の目安（「3か月で見直す」「8割以上なら」など）を、なぜその数字にしたか。元になった件数",
     "例の書き方: ◯件のうち◯件が◯か月以内に◯◯だったので、◯か月を目安にした", False),
    ("price", "費用の実例", "案件の金額の幅と中央値（いつからいつまでの何件か）",
     "例の書き方: ◯年〜◯年の◯件で、◯万円〜◯万円・中央値◯万円", True),
    ("check", "確認の一覧", "実際に使っている確認の一覧（業者に聞く質問・契約で確かめる条項・依頼の前に用意するもの）",
     "社内で使っている文をそのまま貼ってください", False),
    ("staff", "担当者の経歴", "記事を監修する担当者の資格・年数・担当した件数", "例の書き方: ◯◯の資格・◯年・担当◯件", False),
    ("voice", "お客様の声", "掲載してよいお客様の声と、前と後の数字（本人が書いたか、本人が内容を確かめて掲載を許可したものだけ）",
     "声は機械では登録しません。実績の記入シート（jisseki_intake）で登録します", False),
]
NUM = re.compile(r"\d+(?:[.,]\d+)*")
# よく使われている一次情報に足りないもの（一次性の採点の弱点に「母数」173回・「件数」109回・「期間」71回と出た。2026-10-22）。
# 1つの一次情報を補えば、それを使う記事が全部厚くなる（記事ごとに聞くより効く。運用者「よく使う材料に母数・期間を足す」）
FACT_ROWS = 8
# 「担当した9社では」は母数がある。採点が突くのはその先（数え方・規模やばらつき）なので、母数は件数の有無で見る
GAPS = (("母数（何社・何件のうちか）", re.compile(r"のうち|中\d|\d[\d,]*(?:社|件|名|人|店|院)")),
        ("内訳・ばらつき（会社の規模、最小と最大など）", re.compile(r"最も|最小|最大|中央値|内訳|規模|\d+(?:名|人)以下|〜\d|～\d")),
        ("期間（いつからいつまで）", re.compile(r"\d{4}年\d{1,2}月.{0,12}(?:まで|〜|～|から)|\d{4}[-/年]\d{1,2}.{0,3}[〜～-]")),
        ("数え方（誰が・何で数えたか）", re.compile(r"数え|集計|台帳|記録|測|計測|調べ|調査")))
UNIT = re.compile(r"\d[\d,.]*(?:社|件|名|人|本|日|か月|時間|円|万円|%|％|割|回)")


# ── 対象 ─────────────────────────────────────────────────────────────

def requests_of(site):
    import material as M
    return M._load_requests(site) or {}


def display_name(site):
    import private_store as P
    import sites as S
    if P.is_client(site):
        c = P.read_json(site, "company.json", {}) or {}
        if c.get("name"):
            return str(c["name"])
    return str((S.load(site) or {}).get("name") or site)


def targets(only=""):
    import sites as S
    return [s for s in S.load_all() if (not only or s == only) and (requests_of(s) or fact_gaps(s))]


# ── 作る ─────────────────────────────────────────────────────────────

def fact_gaps(site, limit=FACT_ROWS, bodies=None):
    """記事でよく使われているのに、母数・期間・数え方のどれかが無い一次情報。[(id, 文, 使っている記事の数, 足りないもの)]"""
    import daily_audit as D
    import facts as F
    try:
        _, fs = F.load_for(site)
    except Exception:  # noqa: BLE001
        return []
    if bodies is None:
        bodies = []
        for a in D.articles_by_site().get(site, []):
            try:
                bodies.append((ROOT / "articles" / f"{a['slug']}.md").read_text(encoding="utf-8-sig"))
            except OSError:
                pass
    out = []
    for f in fs or []:
        fid, claim = str(f.get("id") or ""), str(f.get("claim") or "")
        marks = UNIT.findall(claim)
        if not fid or not marks or fid.startswith(("own-", "q-")):
            continue                 # 機械で作った一次情報（自社の実測・検索の実績）は人に聞かない
        need = max(1, (len(marks) + 1) // 2)
        used = sum(1 for b in bodies if sum(1 for m in set(marks) if m in b) >= need)
        # 記事に出るのは文（claim）だけ。期間の欄・出どころの欄（「2023-04〜2026-09」「運用者の申告」）を数えると、
        # 文に無いばらつき・数え方まで「ある」と見てしまう。期間だけは期間の欄も見る
        miss = [name for name, rx in GAPS
                if not rx.search(claim + (" " + str(f.get("period") or "") if name.startswith("期間") else ""))]
        if used >= 2 and miss:
            out.append((fid, claim, used, miss))
    return sorted(out, key=lambda x: (-x[2], x[0]))[:limit]


def rows_for(site, reqs):
    """(key, 項目, 質問, 目安) の並び。依頼の記事ごとの質問を先に、よく使う一次情報の補いを次に、決まった質問を後に"""
    import private_store as P
    out = []
    for slug, r in sorted(reqs.items(), key=lambda x: str(x[1].get("since", ""))):
        why = "／".join(str(w)[:110] for w in (r.get("scorer") or [])[:2])
        for i, q in enumerate(r.get("questions") or []):
            out.append((f"req:{slug}:{i}", f"記事「{r.get('keyword', slug)}」", q,
                        ("記事で足りないと言われている点: " + why) if (i == 0 and why) else ""))
    for fid, claim, used, miss in fact_gaps(site):
        out.append((f"fact:{fid}", f"一次情報の補い（記事{used}本で使用）",
                    f"次の一次情報に「{'・'.join(miss)}」を足してください。今の文: 「{claim}」",
                    "例の書き方: 2025年4月〜2026年9月に支援した42社のうち／請求書の台帳を担当者が月末に集計"))
    client = P.is_client(site)
    out += [(f"tpl:{k}", lab, q, hint) for k, lab, q, hint, only_client in TEMPLATE if client or not only_client]
    return out


def make(site, out_dir, today=None):
    from openpyxl import Workbook
    today = today or date.today().isoformat()
    name = display_name(site)
    rows = rows_for(site, requests_of(site))
    wb = Workbook()
    question_tab(wb, site, name, today, rows)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", name)
    p = out_dir / f"材料の質問シート_{safe}_{today}.xlsx"
    wb.save(p)
    return p, len(rows)


def question_tab(wb, site, name, today, rows, extra_head=()):
    """質問のタブと隠しタブ。rows は (key, 項目, 質問, 目安, *読むだけの欄)。--apply は A〜H 列と隠しタブだけを読む"""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    ws = wb.active
    ws.title = TAB
    import private_store as P
    client = P.is_client(site)
    ws["A1"] = f"記事の材料の質問シート（{name}{' 様' if client else ''}・{today}）"
    ws["A1"].font = Font(name="Arial", size=14, bold=True)
    ws["A2"] = (("記事の中身を、御社にしかない実例と数字で厚くするための質問です。" if client else
                 "自社の記事の中身を、当社にしかない実例と数字で厚くするための質問です。")
                + "本当にあったことだけを書いてください。分からない欄は空欄で構いません。社名やお客様の名前は記事に出しません。"
                + "書き終えたら intake/ に置いてください（機械が一次情報として登録します）。")
    ws["A2"].font = Font(name="Arial", size=10)
    ws["A2"].alignment = Alignment(wrap_text=True)
    ws.merge_cells("A2:H2")
    ws.row_dimensions[2].height = 32
    ws.append([])
    ws.append(COLS + list(extra_head))
    thin = Side(style="thin", color="BBBBBB")
    for c in ws[4]:
        c.font = Font(name="Arial", bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color="1F3A5F")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for i, (_, lab, q, hint, *more) in enumerate(rows, 1):
        ws.append([i, lab, q, hint, "", "", "", ""] + list(more)[:len(extra_head)])
    for row in ws.iter_rows(min_row=5, max_row=4 + len(rows)):
        for c in row:
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(vertical="top", wrap_text=True)
            c.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        row[3].font = Font(name="Arial", size=9, color="666666")
        row[4].fill = PatternFill("solid", start_color="FFF8D6")
    for col, w in zip("ABCDEFGHIJKLMN", (5, 22, 58, 40, 50, 16, 16, 14, 9, 30, 28, 22, 14, 10)):
        ws.column_dimensions[col].width = w
    for r in range(5, 5 + len(rows)):
        ws.row_dimensions[r].height = 80
    ws.freeze_panes = "C5"
    if extra_head:
        ws.auto_filter.ref = f"A4:{chr(64 + len(COLS) + len(extra_head))}{4 + len(rows)}"
    meta = wb.create_sheet(META)
    meta.append(["site", site])
    meta.append(["made", today])
    for i, (key, *_x) in enumerate(rows, 1):
        meta.append([i, key])
    meta.sheet_state = "hidden"
    return ws


# ── 読む・登録する ────────────────────────────────────────────────────

def read(src):
    from openpyxl import load_workbook
    wb = load_workbook(src, read_only=True, data_only=True)
    try:
        meta = {str(r[0]): str(r[1]) for r in wb[META].iter_rows(values_only=True) if r and r[0] is not None}
        answers = []
        for r in wb[TAB].iter_rows(min_row=5, values_only=True):
            if not r or r[0] is None:
                continue
            no = str(r[0]).strip()
            ans = str(r[4] or "").strip()
            if not ans:
                continue
            answers.append({"no": no, "key": meta.get(no, ""), "item": str(r[1] or ""), "question": str(r[2] or ""),
                            "answer": ans, "period": str(r[5] or "").strip(), "count": str(r[6] or "").strip(),
                            "ok": str(r[7] or "").strip()})
        return meta.get("site", ""), answers
    finally:
        wb.close()


def existing(site):
    """今の一次情報（id と文）と体験"""
    import facts as F
    import originality
    try:
        _, fs = F.load_for(site)
    except Exception:  # noqa: BLE001
        fs = []
    return ([(str(f.get("id")), str(f.get("claim") or "")) for f in fs or []],
            [str(r.get("text") or "") for r in originality.load_experiences(site)])


PROMPT = """あなたは記事の一次情報の台帳の係です。お客様が質問シートに書いた答えを、記事に使える一次情報の文と体験の文に直します。
答えに書かれていないことは一切書かないでください（数字・期間・業種・結果を作らない）。

# 決まり
- 一次情報（facts）: 1つの答えから数字のある事実を1〜3文。1文は100字以内。期間（いつからいつまで）と母数（何件のうち）を文の中に入れる。
  「【記入例】」などの印は外す。数字は答えのまま（約・前後の言い方も変えない）
- 体験（experiences）: 何が起き・どう判断し・どうなったかの話は体験にする。key は text の中にそのまま出る8〜16字の語
- 食い違い（conflicts）: 下の「今の記録」と同じ対象（同じ件数のまとまり・同じ選び方の集計など）について数字や内訳が違う答えは、
  文にせず conflicts に入れる（どの記録と何が違うかを書く）。迷ったら conflicts に入れる
- 記事に出してよいかが「不可」の答え、お客様の声の答えは、文にしない
- 補い（項目が「一次情報の補い」・質問に今の文がある答え）: 今の文に、答えの母数・期間・数え方を足した文に書き直し、
  facts の項目に "replaces": "その一次情報の id"（答えの番号の行の「補う id」）を付ける。今の文の数字は変えない。
  答えの数字が今の文と違うときだけ conflicts に入れる
- 更新（項目が「一次情報の更新」・質問に前回値がある答え）: 今の文を、答えの新しい数字と時点で書き直し、facts の項目に
  "replaces": "その一次情報の id"（答えの番号の行の「更新する id」）を付ける。前回値と数字が違っても conflicts にしない
  （新しい時点の値として書く）。答えが「変わらず」なら今の文の数字のまま書く

# 今の記録
{existing}

# 答え
{answers}

# 返す形（JSON だけ。説明は書かない）
{{"facts": [{{"no": "答えの番号", "claim": "文", "topic": ["語", "語"], "period": "YYYY-MM〜YYYY-MM か空", "denominator": 数字か null}}],
 "experiences": [{{"no": "答えの番号", "key": "語", "text": "文", "when": "時期"}}],
 "conflicts": [{{"no": "答えの番号", "existing": "記録の id", "why": "何が違うか"}}]}}
"""


def _nums(text):
    # 「2023-04」の 04 と文の「4月」を同じ数字として見る（前の0で別の数字と数えると、正しい文を保留にする）
    return {str(int(n)) if n.isdigit() else n for n in (x.replace(",", "") for x in NUM.findall(str(text or "")))}


def invented(text, answer):
    """答え（答え・時期・件数の欄）に無い数字。補いの答えは、質問に載せた今の文の数字も使ってよい"""
    allowed = _nums(answer["answer"]) | _nums(answer["period"]) | _nums(answer["count"])
    if _refill(answer.get("key", "")):
        allowed |= _nums(answer["question"])
    return sorted(_nums(text) - allowed)


def _refill(key):
    """補い（fact:）と更新（upd:）の答えが書き換える一次情報の id。それ以外は空"""
    kind, _, fid = str(key or "").partition(":")
    return fid if kind in ("fact", "upd") else ""


def _ask(prompt):
    """読むだけの claude を1回呼ぶ（門ではこれを差し替える）"""
    import auto_rewrite as A
    import quality_loop as Q
    with tempfile.TemporaryDirectory() as tmp:
        r = A.sh(Q.scorer_args(), timeout=900, stdin_text=prompt, cwd=tmp)
    return r.stdout or ""


def _json(raw):
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def plan(site, answers, ask=None):
    """登録する一次情報・体験と、保留にするもの（理由つき）"""
    use = [a for a in answers if a["ok"] not in ("不可", "×") and not a["key"].endswith(":voice") and "お客様の声" not in a["item"]]
    held = [(a["no"], "記事に出さない答え・お客様の声（機械では登録しない）") for a in answers if a not in use]
    if not use:
        return [], [], held
    facts, exps = existing(site)
    now = "\n".join([f"- {i}: {c}" for i, c in facts] + [f"- 体験: {t}" for t in exps]) or "（なし）"
    prompt = PROMPT.format(
        existing=now,
        answers="\n\n".join(f"[{a['no']}] {a['item']}"
                            + (f"（{'更新する' if a['key'].startswith('upd:') else '補う'} id: {_refill(a['key'])}）"
                               if _refill(a["key"]) else "")
                            + f"\n質問: {a['question']}\n答え: {a['answer']}\n時期: {a['period']}\n件数: {a['count']}"
                            for a in use))
    got = _json((ask or _ask)(prompt))
    by_no = {a["no"]: a for a in use}
    clash = {str(c.get("no")): c for c in got.get("conflicts") or []}
    held += [(n, f"今の記録 {c.get('existing', '?')} と食い違い: {c.get('why', '')}") for n, c in clash.items()]
    out_f, out_e = [], []
    for kind, items, field in (("fact", got.get("facts") or [], "claim"), ("exp", got.get("experiences") or [], "text")):
        for it in items:
            n = str(it.get("no"))
            a = by_no.get(n)
            text = str(it.get(field) or "").strip()
            if not a or n in clash or not text:
                continue
            bad = invented(text, a)
            if bad:
                held.append((n, f"答えに無い数字が入ったので登録しません（{'・'.join(bad[:3])}）: {text[:60]}"))
                continue
            if kind == "fact" and _refill(a["key"]):
                # 補い・更新は元の一次情報を書き換える（同じ事実を2つ並べない）。更新は時点も新しくする
                it = dict(it, replaces=_refill(a["key"]), updated=a["key"].startswith("upd:"))
            if kind == "exp" and str(it.get("key") or "") not in text:
                held.append((n, f"体験の目印の語が文に無いので登録しません: {text[:60]}"))
                continue
            (out_f if kind == "fact" else out_e).append(it)
    return out_f, out_e, held


def write(site, facts, exps, today=None):
    """一次情報・体験を書き足す。お客様の社は非公開の置き場、自社は data/"""
    import private_store as P
    today = today or date.today().isoformat()
    tag = today.replace("-", "")
    src = f"自社実績（質問シート {today}）"
    if P.is_client(site):
        fd = P.read_json(site, "facts.json", {"facts": []}) or {"facts": []}
        ed = P.read_json(site, "experiences.json", {"experiences": []}) or {"experiences": []}
    else:
        fd = json.loads(OWN_FACTS.read_text(encoding="utf-8"))
        ed = json.loads(OWN_EXPS.read_text(encoding="utf-8"))
    have = {str(x.get("id")) for x in fd.get("facts", [])} | {str(x.get("id")) for x in ed.get("experiences", [])}
    n = 0
    byid = {str(x.get("id")): x for x in fd.get("facts", [])}
    for it in facts:
        old = byid.get(str(it.get("replaces") or ""))
        if old is not None:
            old["claim"] = str(it["claim"]).strip()
            old["source"] = f"{old.get('source', '')}／{'更新' if it.get('updated') else '補い'}（質問シート {today}）".lstrip("／")
            if it.get("updated"):
                old["as_of"] = today[:7]
            if it.get("period"):
                old["period"] = str(it["period"])
            if isinstance(it.get("denominator"), (int, float)) and not isinstance(it.get("denominator"), bool):
                old["denominator"] = it["denominator"]
            continue
        n += 1
        fid = f"{site}-m{tag}-{n}"
        while fid in have:
            n += 1
            fid = f"{site}-m{tag}-{n}"
        row = {"id": fid, "sites": [site], "topic": [str(t) for t in (it.get("topic") or [])][:6],
               "claim": str(it["claim"]).strip(), "source": src, "as_of": today[:7], "verifiable": True}
        if it.get("period"):
            row["period"] = str(it["period"])
        if isinstance(it.get("denominator"), (int, float)) and not isinstance(it.get("denominator"), bool):
            row["denominator"] = it["denominator"]
        fd.setdefault("facts", []).append(row)
        have.add(fid)
    for it in exps:
        n += 1
        ed.setdefault("experiences", []).append({"id": f"{site}-m{tag}-{n}", "sites": [site], "key": str(it["key"]),
                                                 "text": str(it["text"]).strip(), "when": str(it.get("when") or ""),
                                                 "added": today})
    if P.is_client(site):
        P.write_json(site, "facts.json", fd)
        P.write_json(site, "experiences.json", ed)
    else:
        OWN_FACTS.write_text(json.dumps(fd, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        OWN_EXPS.write_text(json.dumps(ed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def apply(src, do_write=False, ask=None):
    """intake_watch から呼ぶ。(登録できたか, 説明)"""
    import private_store as P
    try:
        site, answers = read(src)
    except Exception as e:  # noqa: BLE001
        return False, f"読めません（{str(e)[:80]}）"
    if not site:
        return False, "どの社のシートか分かりません（隠しタブ「材料の質問」が無い）"
    if not answers:
        return False, f"{'（お客様の社）' if P.is_client(site) else site}: 答えが1つもありません"
    f, e, held = plan(site, answers, ask)
    who = "（お客様の社）" if P.is_client(site) else site
    msg = f"{who}: 一次情報 {len(f)}件・体験 {len(e)}件を登録{'' if do_write else 'できます（--write で実行）'}、保留 {len(held)}件"
    if do_write and (f or e):
        write(site, f, e)
        # 答えのあった記事の下書きがしまわれていれば戻す（材料が届いたので、次の回が採点し直す）
        import quality_loop as Q
        back = [s for s in dict.fromkeys(a["key"].split(":")[1] for a in answers if a["key"].startswith("req:"))
                if Q.unshelve(s)]
        if back:
            msg_back = f"しまっていた下書き {len(back)}本を戻しました"
            print(msg_back)
        if P.is_client(site):
            P.push(f"質問シートの答えを一次情報 {len(f)}件・体験 {len(e)}件として登録")
    if do_write:
        vd = voice_draft(site, answers)
        if vd:
            msg += f"。お客様の声は下書き {vd.relative_to(ROOT).as_posix()} に写しました（お客様に確かめて「可」にし、intake/ へ移すと登録）"
    if held:
        note = "保留にした答え（直して intake/ に戻すか、運用者が確かめてください）:\n" + "\n".join(f"  - 問{n}: {w}" for n, w in held)
        print(note)
        if do_write:
            Path(src).with_suffix(".保留.txt").write_text(note + "\n", encoding="utf-8", newline="")
    return bool(f or e), msg


# ── 自社サイトでやったことの前と後 ──────────────────────────────────────

def measure(site, url, day, what, days=28):
    """やった日の前の days 日と、後の days 日（やった日の翌日から）の表示・平均順位。Search Console が無ければ None"""
    import gsc_detail as G
    import sites as S
    d = date.fromisoformat(day)
    dom = (S.load(site) or {}).get("domain", "")
    sc = G.client()
    body = lambda a, b: {"startDate": a.isoformat(), "endDate": b.isoformat(), "dimensions": ["page"],
                         "dimensionFilterGroups": [{"filters": [{"dimension": "page", "operator": "equals", "expression": url}]}]}
    out = []
    for a, b in ((d - timedelta(days=days), d - timedelta(days=1)), (d + timedelta(days=1), d + timedelta(days=days))):
        rows = sc.searchanalytics().query(siteUrl=f"https://{dom}/", body=body(a, b)).execute().get("rows", [])
        imp = sum(r["impressions"] for r in rows)
        pos = round(sum(r["position"] * r["impressions"] for r in rows) / imp, 1) if imp else None
        out.append((imp, pos))
    (i1, p1), (i2, p2) = out
    y, m, dd = d.year, d.month, d.day
    pos_text = f"、平均順位は{p1}位から{p2}位" if p1 and p2 else ""
    claim = (f"{y}年{m}月{dd}日に{what}ページは、前の{days}日の表示{i1}回から、後の{days}日の表示{i2}回"
             f"{pos_text}になりました（Search Console）")
    return {"claim": claim, "topic": ["自社サイト", "実測"], "period": f"{(d - timedelta(days=days)).isoformat()[:7]}〜{(d + timedelta(days=days)).isoformat()[:7]}"}


# 書き直しの種類 → 一次情報の文に書く「やったこと」。台帳（data/rewrite_effect.json）の種類だけを使い、中身を作らない
KIND_WHAT = {"title": "記事の題を書き直した", "desc": "検索結果に出る説明文を書き直した",
             "aio": "冒頭の答えと見出しの直下の1文を書き直した", "question": "見出しを質問の形に直した",
             "fresh": "記事の時点の表記を新しくした", "stuck": "足りない見出しと内容を足した",
             "compete": "ほかのサイトにあって自社に無い節を足した", "serp": "検索上位のページにある論点を足した",
             "stock": "決まり文句の言い回しを直した", "quality": "採点で足りない所を直した"}
MEASURED = ROOT / "data" / "measured_changes.json"
MIN_IMP = 30      # 前と後のどちらかの表示がこれ未満なら、数字が小さすぎて一次情報にしない


def auto_measure(limit=3, today=None, measure_fn=None):
    """書き直しから31日（後の28日＋Search Console の遅れ3日）たった自社の記事の前と後を測り、一次情報にする。
    運用者「施策の前と後を自動で測る」（2026-10-21）。お客様の社は測らない（お客様の数字を自社の一次情報にしない）"""
    import private_store as P
    import sites as S
    today = today or date.today()
    try:
        items = json.loads((ROOT / "data" / "rewrite_effect.json").read_text(encoding="utf-8")).get("items") or []
    except (OSError, ValueError):
        items = []
    try:
        done = json.loads(MEASURED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        done = {}
    made = []
    for it in sorted(items, key=lambda x: str(x.get("at", ""))):
        if len(made) >= limit:
            break
        slug, at, kind = str(it.get("slug", "")), str(it.get("at", "")), str(it.get("kind", ""))
        key = f"{slug}|{at}|{kind}"
        if key in done or kind not in KIND_WHAT or not at or date.fromisoformat(at) > today - timedelta(days=31):
            continue
        art = ROOT / "articles" / f"{slug}.md"
        if not art.is_file():
            continue
        import quality_loop as Q
        meta = Q.meta_of(art.read_text(encoding="utf-8-sig"))
        site = Q.site_of(slug)
        if P.is_client(site) or meta.get("noindex"):
            continue
        url = S.article_url(S.load(site) or {}, {"slug": slug, "category": meta.get("category", "")})
        try:
            got = (measure_fn or measure)(site, url, at, KIND_WHAT[kind])
        except Exception as e:  # noqa: BLE001  Search Console が読めない回は次の週に測る（記録しない）
            print(f"  測れませんでした（{type(e).__name__}）: {slug}")
            continue
        imp = [int(n) for n in re.findall(r"表示(\d+)回", got["claim"])]
        if len(imp) < 2 or max(imp) < MIN_IMP:
            done[key] = "small"
            continue
        if imp[0] == 0:
            # 前の28日が0回なのは、記事がまだ検索に出ていなかっただけ。直した効果として書くと事実と違う（2026-10-21 の試しで0→218回）
            done[key] = "new"
            continue
        write(site, [got], [])
        done[key] = "fact"
        made.append(got["claim"])
    MEASURED.write_text(json.dumps(done, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"MEASURE_FACTS={len(made)}")
    for c in made:
        print("  " + c)
    return made


def voice_draft(site, answers, out_dir=None, today=None):
    """質問シートのお客様の声を、実績の記入シートの下書きに写す（掲載可否は「要確認」。お客様に確かめて「可」にし、
    intake/ へ移すと jisseki_intake が登録する）。機械は声を掲載しない（本人の確認が要る。ステルスマーケティング規制）"""
    rows = [a for a in answers if (a["key"].endswith(":voice") or "お客様の声" in a["item"]) and a["ok"] not in ("不可", "×")]
    if not rows:
        return None
    import jisseki_intake as J
    from openpyxl import load_workbook
    today = today or date.today().isoformat()
    out_dir = Path(out_dir or (ROOT / "intake" / "下書き"))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"お客様の声_{site}_{today}.xlsx"
    J.make_sheet(path)
    wb = load_workbook(path)
    ws = wb["お客様の声"]
    for r in range(3, ws.max_row + 1):          # 雛形の空行（掲載可否「可」が入っている）を空にする
        for c in range(1, len(J.VOICE_COLS) + 1):
            ws.cell(row=r, column=c).value = None        # cell(..., value=None) は「変えない」扱いで消えない
    for i, a in enumerate(rows, 3):
        ws.cell(row=i, column=1, value="要確認")
        ws.cell(row=i, column=6, value=a["answer"][:240])
        ws.cell(row=i, column=10, value=a["period"])
        ws.cell(row=i, column=11, value=site)
    wb.save(path)
    return path


MAIL_STATE = ROOT / "data" / "material_mail.json"


def _req_hash(site):
    import hashlib
    reqs = requests_of(site)
    body = json.dumps({k: (v.get("keyword"), v.get("questions")) for k, v in sorted(reqs.items())}, ensure_ascii=False)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]


def mail(out_dir, send=None):
    """週次: 材料の依頼が新しく出た・変わった社の質問シートを作り、1通のメールに添付して運用者へ送る。
    デスクトップに作るだけでは開き忘れる（運用者「質問シートを毎週メールで届ける」2026-10-21）。変わらない週は送らない
    （うまくいった報告は送らない決まり。CLAUDE.md 8.7）。ログには社名を出さず件数だけ出す"""
    import base64
    import urllib.request
    import sites as S
    try:
        prev = json.loads(MAIL_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prev = {}
    changed = [s for s in targets() if prev.get(S.public_id(s)) != _req_hash(s)]
    if not changed:
        print("MATERIAL_MAIL=none")
        return 0
    files = [make(s, out_dir)[0] for s in changed]
    key = os.environ.get("RESEND_API_KEY", "")
    to = os.environ.get("NOTIFY_TO_EMAIL") or os.environ.get("LEAD_TO_EMAIL", "")
    if not key or not to:
        print(f"MATERIAL_MAIL=unset（{len(files)}社分を作ったが、送り先か鍵が無い）")
        return 0
    payload = {
        "from": os.environ.get("LEAD_FROM_EMAIL", ""), "to": [to],
        "subject": f"【記事の材料】質問シート {len(files)}社分（{date.today().isoformat()}）",
        "text": ("採点で材料が足りないと出た記事の質問シートです。答えを書いて intake/ に置くと、次の回に一次情報として登録します"
                 "（python scripts/intake_watch.py --apply）。答えに無い数字・既存と食い違う答えは登録せずに知らせます。\n\n"
                 + "\n".join(f"・{f.name}" for f in files)),
        "attachments": [{"filename": f.name, "content": base64.b64encode(f.read_bytes()).decode()} for f in files],
    }
    if send:
        send(payload)
    else:
        req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                              "User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"})
        with urllib.request.urlopen(req, timeout=60) as res:
            if res.status >= 300:
                raise SystemExit(f"送れませんでした（{res.status}）")
    for s in changed:
        prev[S.public_id(s)] = _req_hash(s)
    MAIL_STATE.write_text(json.dumps(prev, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"MATERIAL_MAIL=sent {len(files)}")
    return len(files)


# ── 一冊（今まで出した一次情報の台帳・図表にした数字・追加のヒアリング）──────────────────
# 運用者「今まで出していたデータを反映させたスプシを社ごとに・過去に図表にした数字も・止まる要素が無いほど追加のヒアリングを」
# （2026-10-31）。質問のタブは --make と同じ列と隠しタブなので、答えを書いて intake/ に置けば --apply がそのまま登録する。
# 質問のタブの I 列から後（優先度・前回値…）と、ほかのタブは読むだけ（read は A〜H 列しか読まない）

EXTRA = ["優先度（1が先）", "優先の根拠", "対象（記事・語のまとまり・一次情報）", "前回値", "前回の時点", "検索数（控え）"]
TIER = {1: "材料待ちで止まっている記事", 2: "よく使う一次情報の更新", 3: "採点で何度も足りないと言われた点",
        4: "在庫の語（これから書く記事）", 5: "一次情報の更新", 6: "決まった質問"}
# 語のまとまりごとに聞くこと。price はお客様の社だけ（自社の答えは公開側の台帳に入り、当社の料金を公開側に書かない）
KW_KINDS = [
    ("num", "主題の数字", "{g}そのものについて、当社で数えた数字（全体で何件のうち何件か・いつからいつまでか）",
     "例の書き方: ◯年◯月〜◯年◯月の◯件のうち◯件が◯◯だった（数えた人・台帳: ◯◯）", True),
    ("case", "事例カード", "{g}の事例1件。業種・規模・始めた月・やったこと・前と後の数字・期間",
     "例の書き方: ◯年◯月／◯◯業・従業員◯名／◯◯を◯本作った／◯◯が月◯件→月◯件（◯か月）", True),
    ("fail", "失敗の件数と理由", "{g}で、うまくいかなかった・問題になった件数と理由（全体の何件のうち）",
     "例の書き方: ◯件のうち◯件。理由: ◯◯が◯件・◯◯が◯件", True),
    ("rule", "判断の基準の根拠", "{g}で読者に勧める判断の目安（「◯か月で見直す」など）と、その数字にした元の件数",
     "例の書き方: ◯件のうち◯件が◯か月以内に◯◯だったので、◯か月を目安にした", False),
    ("term", "期間の実例", "{g}で、始めてから結果が出るまで（または作業にかかった）期間の最短・最長・中央値と件数",
     "例の書き方: ◯件で最短◯日・最長◯か月・中央値◯か月", False),
    ("price", "費用の実例", "{g}の案件の金額の幅と中央値（いつからいつまでの何件か）",
     "例の書き方: ◯年〜◯年の◯件で、◯万円〜◯万円・中央値◯万円", False),
    ("check", "確認の一覧", "{g}で実際に使っている確認の一覧（聞く質問・確かめる項目・用意するもの）",
     "社内で使っている文をそのまま貼ってください", False),
    ("staff", "担当者", "{g}を担当した人の役割・資格・年数・担当した件数", "例の書き方: ◯◯の資格・◯年・担当◯件", False),
    ("voice", "お客様の声", "{g}のお客様の声と前と後の数字（本人が書いたか、本人が内容を確かめて掲載を許可したものだけ）",
     "声は機械では登録しません。実績の記入シート（jisseki_intake）で登録します", False),
]
# 一次性の採点の指摘の分類（1つの指摘が複数に入る）。質問はその分類を全体で潰すもの
WEAK_CATS = [
    ("base", "母数（何件のうちか）", r"母数|のうち|分母|小さな|少数|件数が(?:無|な|少)|\d+件だけ|\d+社だけ",
     "記事で使う自社の数字の母数（全体で何社・何件を見たか）。数字ごとに「何件のうち」を",
     "例の書き方: 「◯◯」の数字は、◯年◯月〜◯年◯月に担当した◯社のうち◯社"),
    ("period", "期間・時点", r"期間|時期|時点|いつ|何か月|年月",
     "自社の数字ごとの期間（いつからいつまで数えたか）と、数えた時点", "例の書き方: ◯年◯月〜◯年◯月（◯年◯月時点で集計）"),
    ("method", "数え方・出どころ", r"数え方|集計|出典|出どころ|根拠|検証|確か|測り方|どう測|申告",
     "自社の数字の数え方（誰が・何の台帳や道具で・どう数えたか）", "例の書き方: 担当者が◯◯の台帳を月末に集計／◯◯のツールの記録"),
    ("result", "前と後の数字・結果", r"結果|前と後|前後|どう変わ|どれだけ|効果|成果|伸び|改善|その後",
     "支援の前と後で変わった数字（何が・いくつから・いくつに・何か月で）", "例の書き方: ◯◯が月◯件→月◯件（◯か月・◯件のうち◯件）"),
    ("case", "事例の具体（業種・規模・やったこと）", r"事例|業種|規模|具体|実例|案件|どんな会社",
     "事例ごとの業種・規模・やったことの具体（何を何本・何を作ったか）", "例の書き方: ◯◯業・従業員◯名／◯◯を◯本／◯か月"),
    ("rule", "判断の基準の根拠", r"判断|基準|目安|なぜ|理由",
     "記事で勧める判断の基準の、元になった件数と結果", "例の書き方: ◯件のうち◯件が◯◯だったので、◯◯を基準にした"),
    ("price", "費用・金額", r"費用|金額|料金|万円|単価|価格|コスト",
     "費用・金額の実例（何件の幅と中央値・いつからいつまで）", "例の書き方: ◯件で◯万円〜◯万円・中央値◯万円"),
    ("fail", "失敗・うまくいかなかった件数", r"失敗|うまくいかな|問題にな|トラブル|リスク|つまず",
     "うまくいかなかった件数と理由（全体の何件のうち）", "例の書き方: ◯件のうち◯件。理由: ◯◯が◯件"),
    ("staff", "担当者・監修・経歴", r"担当者|監修|経歴|資格|著者|誰が",
     "担当者・監修者の資格・年数・担当した件数", "例の書き方: ◯◯の資格・◯年・担当◯件"),
    ("own", "自社の数字が無い・一般論", r"一般論|一般的|どこでも|他社でも|教科書|汎用|自社の(?:数字|データ|経験)|一次情報|独自",
     "その記事の主題について、当社で数えた数字か、当社でしか言えない実例（無ければ「無し」）", "例の書き方: ◯年◯月〜◯年◯月の◯件のうち◯件が◯◯"),
]
FIG_HEAD = ["slug", "記事の題", "種類", "図・表の名前（題）", "見出し・列", "項目", "数字", "単位", "注記・出典", "元データの置き場"]
_NOTES = []      # 取れなかった置き場（集めた置き場のタブに書く）


def _articles(site):
    """{slug: (題, 本文, フロントマター)}。公開側の articles/ と、お客様の記事の非公開の置き場（private/articles）"""
    import private_store as P
    import sites as S
    import yaml
    out = {}
    for base in (ROOT / "articles", P.base() / "articles"):
        for p in sorted(base.glob("*.md")):
            if p.stem in out:
                continue
            try:
                m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", p.read_text(encoding="utf-8-sig"), re.S)
                meta = (yaml.safe_load(m.group(1)) or {}) if m else {}
                owner = S.find_category_owner(meta.get("category", ""))
            except Exception:  # noqa: BLE001  読めない記事は台帳に入れない
                continue
            if owner == site:
                out[p.stem] = (str(meta.get("title") or p.stem), m.group(2), meta)
    return out


def _used(text, arts):
    """その文の数字（単位つき）を半分以上含む記事の slug"""
    marks = set(UNIT.findall(str(text or "")))
    if not marks:
        key = re.sub(r"\s+", "", str(text or ""))[:14]
        return [s for s, (_, b, _m) in arts.items() if len(key) >= 8 and key in b]
    need = max(1, (len(marks) + 1) // 2)
    return [s for s, (_, b, _m) in arts.items() if sum(1 for m in marks if m in b) >= need]


def _slugs(slugs, arts, limit=40):
    lines = [f"{s}：{arts[s][0]}" for s in slugs[:limit] if s in arts]
    return "\n".join(lines) + (f"\n…ほか{len(slugs) - limit}本" if len(slugs) > limit else "")


def _jl(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── 台帳のタブ ──

def ledger_facts(site, arts):
    import facts as F
    import private_store as P
    try:
        _, fs = F.load_for(site)
    except Exception as e:  # noqa: BLE001
        _NOTES.append(("一次情報（facts.load_for）", f"読めませんでした（{type(e).__name__}）"))
        fs = []
    client = P.is_client(site)
    kinds = (("own-", "自社サイトの実測（機械）"), ("q-", "検索の実績（機械）"), ("dataset-", "公開データのページ"))
    rows = []
    for f in fs or []:
        fid, claim = str(f.get("id") or ""), str(f.get("claim") or "")
        used = _used(claim, arts)
        kind = next((k for p_, k in kinds if fid.startswith(p_)), "登録した一次情報")
        ok = ("要確認（出典を示せない）" if f.get("verifiable") is False else
              "お客様の記事だけ（社名は伏せる）" if client else "可")
        rows.append([fid, kind, claim, "・".join(dict.fromkeys(UNIT.findall(claim))), f.get("denominator", ""),
                     str(f.get("period") or ""), str(f.get("as_of") or ""), str(f.get("source") or ""),
                     str(f.get("added") or f.get("as_of") or ""), len(used), _slugs(used, arts), ok])
    if not client:
        for x in (_jl(OWN_FACTS) or {}).get("pending") or []:
            rows.append(["（保留）", "登録を待っている一次情報", str(x.get("note") or ""), "", "", "", "", str(x.get("owner") or ""),
                         "", 0, "", "不可（集計できるまで書かない）"])
    head = ["id", "種類", "文", "数字", "母数", "期間", "時点", "出典", "登録日", "使っている記事の数", "使っている記事（slug：題）", "公開可否"]
    return head, rows, (18, 16, 60, 18, 8, 16, 9, 24, 10, 9, 50, 16)


def ledger_exps(site, arts):
    import originality
    import private_store as P
    rows = []
    for r in originality.load_experiences(site):
        key = str(r.get("key") or "")
        used = [s for s, (_, b, _m) in arts.items() if key and key in b]
        rows.append([str(r.get("id") or ""), "登録した体験", key, str(r.get("text") or ""), str(r.get("when") or ""),
                     str(r.get("industry") or ""), str(r.get("kind") or ""), str(r.get("added") or ""), len(used),
                     _slugs(used, arts), "可"])
    if P.is_client(site):
        brief = P.read_json(site, "brief.json", {}) or {}
        for i, c in enumerate(brief.get("cases") or [], 1):
            text = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
            used = _used(text, arts)
            rows.append([f"brief-case-{i}", "ヒアリングシートの事例", "", text, "", "", "", "", len(used), _slugs(used, arts),
                         "ヒアリングシートの掲載可否のとおり"])
    head = ["id", "種類", "目印の語", "文", "時期", "業種", "分類", "登録日", "使っている記事の数", "使っている記事（slug：題）", "公開可否"]
    return head, rows, (18, 16, 16, 70, 12, 12, 10, 10, 9, 50, 14)


def ledger_voices(site, arts):
    import private_store as P
    rows = []
    for v in _jl(ROOT / "data" / "voices.json") or []:
        if site not in (v.get("sites") or []):
            continue
        n = v.get("number") or {}
        used = _used(str(v.get("quote") or ""), arts)
        rows.append(["お客様の声の台帳", str(v.get("who") or ""), str(v.get("industry") or ""), str(v.get("quote") or ""),
                     str(n.get("metric") or ""), str(n.get("before") or ""), str(n.get("after") or ""), str(n.get("period") or ""),
                     str(v.get("as_of") or ""), len(used), _slugs(used, arts), "可（掲載の許可を得て登録したもの）"])
    if P.is_client(site):
        for c in (P.read_json(site, "brief.json", {}) or {}).get("voices") or []:
            text = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
            used = _used(text, arts)
            rows.append(["ヒアリングシート", "", "", text, "", "", "", "", "", len(used), _slugs(used, arts), "ヒアリングシートの掲載可否のとおり"])
    head = ["元", "誰", "業種", "声", "指標", "前", "後", "期間", "時点", "使っている記事の数", "使っている記事（slug：題）", "公開可否"]
    return head, rows, (14, 18, 10, 70, 16, 10, 10, 10, 9, 9, 40, 18)


def ledger_survey(site, arts):
    import client_private as CP
    rows = []
    for slug, (title, body, _m) in sorted(arts.items()):
        d = _jl(CP.site_file(site, f"data/own_survey/{slug}.json"))
        if not d:
            continue
        used = "使っている" if any(str(c)[:20] in body for c in d.get("claims") or []) else "本文に見当たらない"
        base = [slug, title, str(d.get("date") or ""), "・".join(d.get("engines") or []), d.get("answers", "")]
        for t in d.get("topics") or []:
            rows.append(base + ["論点", str(t.get("topic") or ""), "・".join(t.get("words") or []), t.get("hits", ""), t.get("of", ""), used])
        for dim, n in (d.get("dims") or {}).items():
            rows.append(base + ["答えに出た観点", dim, "", n, d.get("answers", ""), used])
        for c in d.get("claims") or []:
            rows.append(base + ["記事に書く文", str(c), "", "", "", used])
        if d.get("questions"):
            rows.append(base + ["AIに聞いた問い", "\n".join(d["questions"]), "", "", "", used])
    head = ["slug", "記事の題", "調べた日", "聞いたAI", "答えの数", "行の種類", "問い・論点・文", "触れているか見た語", "触れた数", "母数", "記事で"]
    return head, rows, (22, 30, 11, 16, 8, 14, 60, 18, 8, 8, 14)


def ledger_citations(site):
    import client_private as CP
    rows = []
    for name in CP.citation_months():
        d = CP.load_citations(name) or {}
        est = (d.get("sites") or {}).get(site) or {}
        for it in est.get("items") or []:
            rows.append([name[:7], f"推定（{d.get('method', '')}）", it.get("kw", ""), it.get("url", ""), it.get("pos", ""),
                         it.get("imp", ""), it.get("clicks", ""), it.get("ctr", ""), it.get("expected_ctr", ""), it.get("ratio", ""), ""])
        meas = ((d.get("measured") or {}).get("sites") or {}).get(site) or {}
        for it in meas.get("items") or []:
            eng = it.get("engines") or {}
            cited = "・".join(e for e, v in eng.items() if (v or {}).get("cited")) or "無し"
            rows.append([name[:7], f"AIに直接聞いた（{(d.get('measured') or {}).get('date', '')}）", it.get("kw", ""), "", "", "", "",
                         "", "", "", f"引用したAI: {cited}（{len(eng)}つに聞いた）"])
    head = ["月", "測り方", "語", "URL", "平均順位", "表示", "クリック", "CTR(%)", "期待CTR(%)", "期待との比", "AIの引用"]
    return head, rows, (9, 26, 24, 40, 8, 8, 8, 8, 9, 9, 30)


def ledger_rewrites(site, arts):
    rows = []
    for it in (_jl(ROOT / "data" / "rewrite_effect.json") or {}).get("items") or []:
        if it.get("slug") in arts:
            rows.append([it["slug"], arts[it["slug"]][0], str(it.get("at") or ""), KIND_WHAT.get(str(it.get("kind")), str(it.get("kind") or "")),
                         str(it.get("status") or "")])
    for key, state in (_jl(MEASURED) or {}).items():
        slug, at, kind = (key.split("|") + ["", "", ""])[:3]
        if slug in arts:
            rows.append([slug, arts[slug][0], at, KIND_WHAT.get(kind, kind), f"前と後の測定: {state}"])
    head = ["slug", "記事の題", "直した日", "やったこと", "状態・測定"]
    return head, rows, (24, 40, 11, 36, 24)


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def figures(site, arts):
    """記事で図・表にした数字。図は記事の宣言（diagrams。make_diagram が描く元データ）、表は本文の表。
    宣言の無い画像（元データが無い）は「取れなかった」と行に書く。公開データのページの表も載せる"""
    rows = []
    for slug, (title, body, meta) in sorted(arts.items()):
        names = set()
        for dg in meta.get("diagrams") or []:
            if not isinstance(dg, dict):
                continue
            names.add(str(dg.get("name") or ""))
            labels = dg.get("labels") or []
            for i, item in enumerate(dg.get("items") or []):
                if not NUM.search(str(item)):
                    continue
                parts = str(item).split("|")
                nums = [p for p in parts[1:] if NUM.search(p)] or ([parts[0]] if NUM.search(parts[0]) else [])
                for n in nums:
                    rows.append([slug, title, f"図（{dg.get('type')}）", str(dg.get("title") or dg.get("name") or ""),
                                 str(labels[i]) if i < len(labels) else str(dg.get("root") or ""), parts[0], n.strip(),
                                 str(dg.get("unit") or ""), str(dg.get("note") or ""), "記事の宣言（diagrams）"])
        lines = body.splitlines()
        for i, ln in enumerate(lines):
            if not re.match(r"^\|[-: |]+\|\s*$", ln) or i == 0:
                continue
            head = _cells(lines[i - 1])
            for ln2 in lines[i + 1:]:
                if not ln2.strip().startswith("|"):
                    break
                cells = _cells(ln2)
                for j, c in enumerate(cells):
                    if NUM.search(c):
                        rows.append([slug, title, "表", " / ".join(head)[:80], head[j] if j < len(head) else "", cells[0], c, "", "",
                                     "記事の本文の表"])
        for src in re.findall(r'<img[^>]*src="([^"]+)"', body) + re.findall(r"!\[[^\]]*\]\(([^)\s]+)", body):
            stem = src.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            if stem != "eyecatch" and stem not in names:
                rows.append([slug, title, "画像", src.rsplit("/", 1)[-1], "", "", "", "", src,
                             "取れなかった（記事に図の宣言が無く、画像だけ。数字の元データは見つからない）"])
    import facts as F
    try:
        ids = {str(f.get("id")) for f in F.load_for(site)[1] or []}
    except Exception:  # noqa: BLE001
        ids = set()
    for folder in ("datasets", "datasets_hidden"):
        for p in sorted((ROOT / "data" / folder).glob("*.json")):
            d = _jl(p) or {}
            if f"dataset-{d.get('slug', p.stem)}" not in ids or not isinstance(d.get("rows"), list):
                continue
            for r in d["rows"]:
                vals = list(r.values()) if isinstance(r, dict) else (r if isinstance(r, list) else [r])
                keys = list(r.keys()) if isinstance(r, dict) else [""] * len(vals)
                for k, v in zip(keys[1:], vals[1:]):
                    if NUM.search(str(v)):
                        rows.append([f"data/{d.get('slug', p.stem)}", str(d.get("title") or ""), "公開データのページ（グラフ）",
                                     str(d.get("title") or ""), str(k), str(vals[0]), str(v), str(d.get("unit") or ""),
                                     f"{d.get('period', '')} {d.get('method', '')}".strip()[:120], f"data/{folder}/{p.name}"])
    return FIG_HEAD, rows, (22, 30, 14, 30, 18, 24, 12, 8, 30, 30)


def report_tables(site):
    """月次レポート（非公開の置き場）の表の数字。小さな折れ線（線だけで数字の無い図）は「取れなかった」と書く"""
    import html as H
    import private_store as P
    import sites as S
    rows = []
    try:
        primary = S.primary()
    except Exception:  # noqa: BLE001
        primary = ""
    pat = (re.compile(r"^\d{4}-\d{2}$") if site == primary else
           re.compile(r"^\d{4}-\d{2}-(?:%s|%s)$" % (re.escape(site), re.escape(str(S.public_id(site))))))
    base = P.reports_dir()
    strip = lambda s: H.unescape(re.sub(r"<[^>]+>", " ", s)).split()  # noqa: E731
    for d in sorted(base.glob("*")) if base.is_dir() else []:
        f = d / "report.html"
        if not (d.is_dir() and pat.match(d.name) and f.is_file()):
            continue
        sec, nt = "", 0
        for m in re.finditer(r"<h2[^>]*>(.*?)</h2>|<table.*?</table>|<svg.*?</svg>", f.read_text(encoding="utf-8"), re.S):
            if m.group(1) is not None:
                sec = " ".join(strip(m.group(1)))
                continue
            if m.group(0).startswith("<svg"):
                text = " ".join(strip(m.group(0)))
                rows.append([d.name[:7], sec, "図", "", "取れなかった（線だけの図。数字は同じ節の表を見る）" if not NUM.search(text) else text[:200]])
                continue
            nt += 1
            for i, tr in enumerate(re.findall(r"<tr.*?</tr>", m.group(0), re.S), 1):
                cells = [" ".join(strip(c)) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
                rows.append([d.name[:7], sec, f"表{nt}", i] + cells[:10])
    head = ["月", "節", "表・図", "行"] + [f"列{i}" for i in range(1, 11)]
    return head, rows, (9, 26, 7, 5) + (18,) * 10


# ── 追加のヒアリング ──

def weak_of(site):
    """一次性の採点で足りないと言われた文 [(slug, 文)]。採点の記録と材料の依頼の両方から（同じ文は1つ）"""
    import client_private as CP
    out = []
    for ln in CP.read_lines(ROOT / "data" / "quality_loop.jsonl"):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("site") == site:
            out += [(str(r.get("slug") or ""), str(w)) for w in ((r.get("weak") or {}).get("originality") or [])]
    for slug, r in requests_of(site).items():
        out += [(slug, str(w)) for w in r.get("scorer") or []]
    return list(dict.fromkeys(out))


def classify(weak):
    """{分類の key: [(slug, 文)]}。どれにも当たらない指摘は other"""
    out = {}
    for slug, w in weak:
        hit = [k for k, _l, rx, _q, _h in WEAK_CATS if re.search(rx, w)] or ["other"]
        for k in hit:
            out.setdefault(k, []).append((slug, w))
    return out


def _stuck(site, arts, weak, reqs):
    """採点で一次性が80点に届かず止まっている記事（材料の依頼が無いもの）。[(slug, 狙う語, 指摘, 見出し)]"""
    import client_private as CP
    last = {}
    for ln in CP.read_lines(ROOT / "data" / "quality_loop.jsonl"):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("site") == site and r.get("slug"):
            last[r["slug"]] = r
    out = []
    for slug, r in sorted(last.items()):
        orig = (r.get("axes") or {}).get("originality")
        if slug in reqs or slug not in arts or r.get("ok") or r.get("state") == "passed" or not isinstance(orig, (int, float)) or orig >= 80:
            continue
        title, body, meta = arts[slug]
        heads = re.findall(r"^##\s+(.+)$", body, re.M)
        out.append((slug, str(meta.get("keyword") or title), [w for s, w in weak if s == slug][-4:], heads))
    return out


def _todo(site):
    """台帳の未着手の語（kw_plan.stock と同じく、新しく書けない語は除く）。台帳が読めなければ空"""
    try:
        import hub_client
        import kw_fit
        return [r for r in hub_client.all_kw(strict=True)
                if r.get("site") == site and str(r.get("status", "")).strip() == "未着手" and r.get("keyword")
                and kw_fit.judge_new(str(r["keyword"]), site)[0] < 2]
    except Exception as e:  # noqa: BLE001
        _NOTES.append(("KWの台帳（管制塔の未着手の語）", f"読めませんでした（{type(e).__name__}）。語のまとまりの質問は出していません"))
        return []


def _volumes():
    raw = _jl(ROOT / "data" / "rakko_volume.json") or {}
    return {re.sub(r"\s+", "", str(k).lower()): v.get("vol") for k, v in raw.items() if isinstance(v, dict) and v.get("vol") is not None}


def kw_groups(rows, skip="", big=10):
    """語のまとまり {名前: [語]}。2語以上に出る語（全体の4割未満。サービス名のように多くに出る語は外す）で束ね、残りは1語ずつ。
    big 語を超えるまとまりは、束ねた語を除いてもう一段分ける（「経費精算」の数十語に1つの問いでは名指しにならない）"""
    import material as M
    kws = list(dict.fromkeys(str(r.get("keyword") or "") for r in rows if r.get("keyword")))
    flat = {k: re.sub(r"\s+", "", k.lower()) for k in kws}
    has = {t: {k for k in kws if t in flat[k]} for k in kws for t in M.tokens(k) if not (skip and (skip in t or t in skip))}
    n = len(kws) or 1
    cand = sorted((t for t, ks in has.items() if len(ks) >= 2 and (n < 5 or len(ks) / n < 0.4)),
                  key=lambda t: (-len(has[t]), -len(t), t))
    out, done = {}, set()
    for t in cand:
        ks = [k for k in kws if k in has[t] and k not in done]
        if len(ks) >= 2:
            out[t] = ks
            done |= set(ks)
    for k in kws:
        if k not in done:
            out[k] = [k]
    if skip or not big:
        return out
    split = {}
    for name, ks in out.items():
        if len(ks) <= big:
            split[name] = ks
            continue
        for sub, sks in kw_groups([{"keyword": k} for k in ks], skip=name).items():
            split[f"{name}／{sub}" if len(sks) > 1 else sub] = sks
    return split


def hearing(site, arts):
    """追加のヒアリングの行 [(key, 項目, 質問, 目安, 優先度, 根拠, 対象, 前回値, 前回の時点, 検索数)] を優先の高い順に。
    答えの数字は作らない（例の書き方は ◯）"""
    import facts as F
    import material as M
    import private_store as P
    client = P.is_client(site)
    reqs = requests_of(site)
    weak = weak_of(site)
    out = []          # (優先度, 並べる値, 行)

    def add(tier, w, key, item, q, hint, why, target="", prev="", at="", vol=""):
        out.append((tier, w, (key, item, q, hint, tier, f"{TIER[tier]}（{why}）" if why else TIER[tier], target, prev, at, vol)))

    for n, (slug, r) in enumerate(sorted(reqs.items(), key=lambda x: str(x[1].get("since", "")))):
        why = "／".join(str(w)[:110] for w in (r.get("scorer") or [])[:2])
        for i, q in enumerate(r.get("questions") or []):
            add(1, n, f"req:{slug}:{i}", f"記事「{r.get('keyword', slug)}」", q,
                ("記事で足りないと言われている点: " + why) if (i == 0 and why) else "例の書き方: ◯年◯月〜◯年◯月の◯件のうち◯件",
                f"材料の依頼 {r.get('since', '')}〜", f"{slug}：{arts.get(slug, (r.get('keyword', ''),))[0]}")
    for n, (slug, kw, ws, heads) in enumerate(_stuck(site, arts, weak, reqs)):
        for i, q in enumerate(M.questions(kw, ws, heads)):
            add(1, 1000 + n, f"req:{slug}:{i}", f"記事「{kw}」", q,
                ("記事で足りないと言われている点: " + "／".join(w[:110] for w in ws[:2])) if (i == 0 and ws) else
                "例の書き方: ◯年◯月〜◯年◯月の◯件のうち◯件", "一次性が80点未満のまま", f"{slug}：{arts[slug][0]}")
    try:
        _, fs = F.load_for(site)
    except Exception:  # noqa: BLE001
        fs = []
    for f in fs or []:
        fid, claim = str(f.get("id") or ""), str(f.get("claim") or "")
        marks = list(dict.fromkeys(UNIT.findall(claim)))
        if not fid or not marks or fid.startswith(("own-", "q-", "dataset-")):
            continue                 # 機械で作った一次情報と公開データのページは、それぞれの工程が更新する
        used = _used(claim, arts)
        miss = [name for name, rx in GAPS
                if not rx.search(claim + (" " + str(f.get("period") or "") if name.startswith("期間") else ""))]
        at = "・".join(x for x in (str(f.get("as_of") or ""), str(f.get("period") or "")) if x)
        q = (f"次の一次情報を最新の数字に更新してください（前回値：{'・'.join(marks)}、時点：{at or '不明'}）。"
             f"変わっていなければ「変わらず」と書いてください。" + (f"あわせて「{'・'.join(miss)}」も足してください。" if miss else "")
             + f"今の文: 「{claim}」")
        add(2 if len(used) >= 2 else 5, -len(used), f"upd:{fid}", f"一次情報の更新（記事{len(used)}本で使用）", q,
            "例の書き方: ◯年◯月時点で◯社のうち◯社（◯年◯月〜◯年◯月・担当者が◯◯の台帳で集計）",
            f"記事{len(used)}本で使用", fid, "・".join(marks), at)
    groups = classify(weak)
    for k, label, _rx, q, hint in WEAK_CATS:
        hits = groups.get(k) or []
        if hits:
            add(3, -len(hits), f"gap:{k}", f"採点の指摘「{label}」", q + "（記事の題ごとに分けて書いてください）", hint,
                f"{len(hits)}回・記事{len({s for s, _w in hits})}本", label)
    todo = _todo(site)
    vols = _volumes()
    prio = {str(r.get("keyword")): str(r.get("priority") or "").strip() for r in todo}
    grouped = kw_groups(todo)

    def weight(ks):
        vol = sum(vols.get(re.sub(r"\s+", "", k.lower())) or 0 for k in ks)
        return (-sum(1 for k in ks if prio.get(k) == "A"), -vol, -len(ks)), vol
    order = sorted(grouped.items(), key=lambda x: (weight(x[1])[0], x[0]))
    for n, (name, ks) in enumerate(order):
        w, vol = weight(ks)
        g = f"「{name}」の語（{'・'.join(ks[:4])}{' ほか' + str(len(ks) - 4) + '語' if len(ks) > 4 else ''}）" if len(ks) > 1 else f"「{name}」"
        for kind, label, q, hint, core in KW_KINDS:
            if kind == "price" and not client:
                continue
            if len(ks) == 1 and not core:
                continue          # 1語だけのまとまりは主題の数字・事例・失敗だけを聞く（同じ問いが何百行にもなる）
            add(4, (n, [k[0] for k in KW_KINDS].index(kind)), f"kw:{n + 1}:{kind}", f"{label}（{name}）", q.format(g=g), hint,
                f"在庫の語{len(ks)}本" + (f"・優先度Aが{-w[0]}本" if w[0] else ""), "・".join(ks), "", "", vol or "")
    for k, lab, q, hint, only_client in TEMPLATE:
        if client or not only_client:
            add(6, 0, f"tpl:{k}", lab, q, hint, "")
    out.sort(key=lambda x: (x[0], x[1]))
    return [r for *_x, r in out], groups


def _tab(wb, title, head, rows, widths):
    from openpyxl.styles import Alignment, Font, PatternFill
    ws = wb.create_sheet(title)
    ws.append(head)
    for c in ws[1]:
        c.font = Font(name="Arial", bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color="1F3A5F")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for r in rows:
        ws.append([v if isinstance(v, (int, float)) or v is None else str(v)[:32000] for v in r])
    for row in ws.iter_rows(min_row=2, max_row=1 + len(rows)):
        for c in row:
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(vertical="top", wrap_text=True)
    from openpyxl.utils import get_column_letter
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "B2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(head))}{1 + len(rows)}"
    return ws


def book(site, out_dir, today=None):
    """社ごとの1冊。(パス, {タブ: 行数})"""
    from openpyxl import Workbook
    today = today or date.today().isoformat()
    del _NOTES[:]
    name = display_name(site)
    arts = _articles(site)
    qrows, groups = hearing(site, arts)
    wb = Workbook()
    question_tab(wb, site, name, today, qrows, EXTRA)
    counts = {TAB: len(qrows)}
    no = {r[0]: i for i, r in enumerate(qrows, 1)}
    labels = {k: label for k, label, *_x in WEAK_CATS}
    cls = [[labels.get(k, "その他"), len(v), len({s for s, _w in v}), v[0][1][:300], v[1][1][:300] if len(v) > 1 else "",
            no.get(f"gap:{k}", "")] for k, v in sorted(groups.items(), key=lambda x: -len(x[1]))]
    tabs = [("採点の指摘の分類", (["分類", "指摘の数", "記事の数", "指摘の例1（採点者の言葉）", "指摘の例2", "この分類を潰す質問の No"],
                           cls, (26, 9, 9, 70, 70, 12)))]
    tabs += [("一次情報（事実・数字）", ledger_facts(site, arts)), ("体験・事例", ledger_exps(site, arts)),
             ("台帳_お客様の声", ledger_voices(site, arts)), ("当社調べ（AIへの質問）", ledger_survey(site, arts)),
             ("AI引用の実測", ledger_citations(site)), ("書き直しの前後", ledger_rewrites(site, arts)),
             ("図表の数字", figures(site, arts)), ("月次レポートの数字", report_tables(site))]
    for title, (head, rows, widths) in tabs:
        _tab(wb, title, head, rows, widths)
        counts[title] = len(rows)
    srcs = [["記事（articles/ と非公開の private/articles）", len(arts), "使っている記事・図・表を探した本文"],
            ["一次情報 facts.load_for（data/first_party_facts.json・お客様の facts.json・自社の実測）", counts["一次情報（事実・数字）"], ""],
            ["体験 originality.load_experiences（data/experiences.json・お客様の experiences.json）＋ヒアリングシートの事例", counts["体験・事例"], ""],
            ["お客様の声 data/voices.json ＋ヒアリングシートの声", counts["台帳_お客様の声"], ""],
            ["当社調べ data/own_survey/<slug>.json（お客様の社は非公開の置き場）", counts["当社調べ（AIへの質問）"], "行は論点・観点・文・問いの数"],
            ["AI引用 data/ai_citations/YYYY-MM.json（推定と、AIに直接聞いた記録）", counts["AI引用の実測"], ""],
            ["書き直しの台帳 data/rewrite_effect.json・前と後の測定 data/measured_changes.json", counts["書き直しの前後"], ""],
            ["図 記事の diagrams（make_diagram の元データ）・本文の表・data/datasets", counts["図表の数字"], "画像だけで元データの無い図は「取れなかった」の行"],
            ["月次レポート（非公開の置き場 reports/）の表", counts["月次レポートの数字"], "小さな折れ線は数字が無いので「取れなかった」の行"],
            ["採点の記録 data/quality_loop.jsonl・材料の依頼 material_requests.json", sum(len(v) for v in groups.values()), "分類ごとの指摘の延べ数"]]
    srcs += [[a, "", b] for a, b in _NOTES]
    _tab(wb, "集めた置き場", ["置き場", "行数", "メモ"], srcs, (70, 9, 60))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", name)
    p = out_dir / f"一次情報の台帳と追加ヒアリング_{safe}_{today}.xlsx"
    wb.save(p)
    return p, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--site", default="")
    ap.add_argument("--out", default=str(Path.home() / "Desktop"))
    ap.add_argument("--apply", default="")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--measure", nargs=3, metavar=("SITE", "URL", "DAY"))
    ap.add_argument("--what", default="")
    ap.add_argument("--auto-measure", type=int, default=0, help="書き直しから31日たった自社の記事の前と後を N 本測る（週次）")
    ap.add_argument("--mail", action="store_true", help="依頼が変わった社の質問シートをメールで送る（週次・CI だけ）")
    ap.add_argument("--book", action="store_true", help="社ごとの1冊（一次情報の台帳・図表の数字・追加のヒアリング）を作る")
    a = ap.parse_args()
    if a.book:
        if os.environ.get("GITHUB_ACTIONS"):
            print("MATERIAL_BOOK=skip（CI では作らない。お客様の語が成果物とログに載る）")
            return 0
        import sites as S
        for s in [x.strip() for x in a.site.split(",") if x.strip()] or list(S.load_all()):
            p, counts = book(s, a.out)
            print(f"  {p}: " + "・".join(f"{k} {v}" for k, v in counts.items()))
        return 0
    if a.make:
        if os.environ.get("GITHUB_ACTIONS"):
            print("MATERIAL_SHEET=skip（CI では作らない。手元で作る）")
            return 0
        ts = targets(a.site)
        for s in ts:
            p, n = make(s, a.out)
            print(f"  {p.name}: 質問{n}問")
        print(f"MATERIAL_SHEET={len(ts)}")
        return 0
    if a.mail:
        if not os.environ.get("GITHUB_ACTIONS"):
            print("MATERIAL_MAIL=skip（手元からは送らない。手元では --make でデスクトップに作る）")
            return 0
        mail(Path(tempfile.mkdtemp()))
        return 0
    if a.auto_measure:
        auto_measure(a.auto_measure)
        return 0
    if a.apply:
        ok, msg = apply(Path(a.apply), a.write)
        print(msg)
        return 0
    if a.measure:
        if not a.what:
            raise SystemExit("--what にやったことを書いてください（例: 「よくある質問を約30問載せた」）")
        if not a.what.endswith("た"):
            raise SystemExit("--what は「〜した」の形で書いてください（例: 「よくある質問を約30問載せた」）")
        got = measure(*a.measure, what=a.what)
        print(got["claim"])
        if a.write:
            write(a.measure[0], [got], [])
            print("一次情報に登録しました")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
