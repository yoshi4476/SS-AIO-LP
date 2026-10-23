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
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    today = today or date.today().isoformat()
    name = display_name(site)
    rows = rows_for(site, requests_of(site))
    wb = Workbook()
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
    ws.append(COLS)
    thin = Side(style="thin", color="BBBBBB")
    for c in ws[4]:
        c.font = Font(name="Arial", bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color="1F3A5F")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for i, (_, lab, q, hint) in enumerate(rows, 1):
        ws.append([i, lab, q, hint, "", "", "", ""])
    for row in ws.iter_rows(min_row=5, max_row=4 + len(rows)):
        for c in row:
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(vertical="top", wrap_text=True)
            c.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        row[3].font = Font(name="Arial", size=9, color="666666")
        row[4].fill = PatternFill("solid", start_color="FFF8D6")
    for col, w in zip("ABCDEFGH", (5, 22, 58, 40, 50, 16, 16, 14)):
        ws.column_dimensions[col].width = w
    for r in range(5, 5 + len(rows)):
        ws.row_dimensions[r].height = 80
    ws.freeze_panes = "A5"
    meta = wb.create_sheet(META)
    meta.append(["site", site])
    meta.append(["made", today])
    for i, (key, *_x) in enumerate(rows, 1):
        meta.append([i, key])
    meta.sheet_state = "hidden"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", name)
    p = out_dir / f"材料の質問シート_{safe}_{today}.xlsx"
    wb.save(p)
    return p, len(rows)


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
    return {n.replace(",", "") for n in NUM.findall(str(text or ""))}


def invented(text, answer):
    """答え（答え・時期・件数の欄）に無い数字。補いの答えは、質問に載せた今の文の数字も使ってよい"""
    allowed = _nums(answer["answer"]) | _nums(answer["period"]) | _nums(answer["count"])
    if str(answer.get("key", "")).startswith("fact:"):
        allowed |= _nums(answer["question"])
    return sorted(_nums(text) - allowed)


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
        answers="\n\n".join(f"[{a['no']}] {a['item']}" + (f"（補う id: {a['key'][5:]}）" if a["key"].startswith("fact:") else "")
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
            if kind == "fact" and a["key"].startswith("fact:"):
                it = dict(it, replaces=a["key"][5:])     # 補いは元の一次情報を書き換える（同じ事実を2つ並べない）
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
            old["source"] = f"{old.get('source', '')}／補い（質問シート {today}）".lstrip("／")
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
    a = ap.parse_args()
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
