# -*- coding: utf-8 -*-
"""学びの台帳。やって分かったことを記録し、次の記事に効かせる。

いままで学びは kpi_feedback.md に文章で積むだけで、36件・11.7KBまで膨らんでいた。
記事を書くたびに全部読ませており、(1)関係ない学びまで毎回読む (2)古い学びが消えない
(3)機械で守れるはずの学びを人とAIが覚え続ける、という3つの無駄があった。
クライアントのサイトが増えれば、この方式は破綻する。

**考え方: 学びは3つに仕分ける。**

| 仕分け | 置き場 | 次からどうなる |
|:--|:--|:--|
| 機械で守れる | ゲート・検査スクリプト（`gate` に名前を書く） | **プロンプトから外す**。機械が止めるので誰も覚えなくてよい |
| 判断が要る | この台帳（`gate` が空） | 記事を書く直前に、関係するものだけ読ませる |
| 事実の誤り | 記事の修正・一次情報の登録 | 直したら `retired` にする |

  python scripts/lessons.py                       # 一覧
  python scripts/lessons.py --brief ai-lab        # 記事を書く前に読ませる分（これだけ渡す）
  python scripts/lessons.py --add ...             # 学びを足す（実行中のAIが呼ぶ）
  python scripts/lessons.py --review              # 棚卸し（ゲート化済み・古い・重複を洗う）
  python scripts/lessons.py --import-md           # kpi_feedback.md の既存分を取り込む（移行用・1回）

台帳: data/lessons.jsonl（1行1件）。サイトを指定しない学びは全サイト（クライアント含む）に効く。
お客様の社の学び（sites にお客様の社）は data/clients/<id>/private/data/lessons.jsonl に置き（public に
置かない。CI はキャッシュで持ち越す）、全社の学びに入ったお客様の名前・ドメイン・記事の題と slug は伏せる
（門 h77・log_leak_check と同じ照らし方）。伏せる語が取れない回は、新しい行・書き換えた行を公開の台帳へ書かない。
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SRC = ROOT / "data" / "lessons.jsonl"
FEEDBACK = ROOT / "kpi_feedback.md"
BRIEF_MAX = 12          # 記事を書く前に読ませる上限（増やすほど1本あたりの手間が増える）
BRIEF_CHARS = 2600
STALE_DAYS = 120        # これより古く、一度も参照されていない学びは棚卸しの候補
PHASES = ("kw", "research", "design", "writing", "quality", "publish", "analysis", "ops")


def load():
    """public の台帳に、お客様の社の置き場の行を合わせたもの（client_private.read_lines）"""
    import client_private as CP
    out = []
    for line in CP.read_lines(SRC):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def _owner(row):
    """お客様の社の学び（sites にお客様の社がある）なら、その社。検索語・表示の数が詳細に入るので public に置かない"""
    import client_private as CP
    return next((s for s in row.get("sites") or [] if CP.is_private(s)), None)


ART, SITE = "お客様の記事", "お客様のサイト"
TEXT = ("rule", "detail", "source", "gate")
SAFE = ("hits", "status")   # 書き換わってもお客様の語が入らない項目
PUBLIC = SRC                # 公開側で追跡している台帳（門が差し替える一時の台帳は公開されない）
HELD = []                   # この実行で保存しなかった行（同じ実行の中で同じ学びを二重に積まない）


def _unresolved():
    """sites/ にお客様の印があるのに、非公開のデータから設定が読めない社の数（読めない社の語は伏せられない）"""
    import sites as S
    stubs = set()
    for p in S.SITES_DIR.glob("*.json"):
        try:
            if json.loads(p.read_text(encoding="utf-8-sig")).get("client"):
                stubs.add(p.stem)
        except (OSError, ValueError):
            pass
    return len(stubs - {c.get("public_id") or sid for sid, c in S.load_all().items()})


def _terms():
    """お客様の伏せる語の (正規表現, {語の小文字: 置き換え})。お客様の社が無ければ (None, {})。
    語が取れない（非公開のデータが無い・読めない社がある・例外）ときは None。

    照らし方は門と同じで、大文字小文字を問わない。記事の題・slug は CI のログの見張りと同じ部品
    （log_leak_check.word_rx: 英数の語は前後の境目を見る）で、門 h77 の照らしより広い（日本語に続く slug も伏せる）。
    名前・ドメインは門 h77 と同じく部分一致（門が部分一致で数えるので、境目を見ると門に引っかかる）。
    2026-10-11: 大文字小文字を区別する単純な置き換えで、大文字の slug が伏せ漏れになっていた"""
    try:
        import ci_mask
        import log_leak_check as LL
        ident = ci_mask.identity_terms()
        if _unresolved():
            return None
    except Exception:
        return None
    repl = {}
    for names, arts, dom in ident.values():
        for words, to, rx in ((arts, ART, LL.word_rx), (list(names) + [dom], SITE, re.escape)):
            for w in words:
                w = str(w or "").strip()
                if len(w) >= LL.MIN_LEN:
                    repl.setdefault(w.lower(), (to, rx(w)))
    if not repl:
        return None, {}
    # 長い語を先に（題の中の社名・URL の中のドメインを、長い方の1か所として伏せる）
    rx = re.compile("|".join(f for _w, (_t, f) in sorted(repl.items(), key=lambda kv: -len(kv[0]))), re.I)
    return rx, {w: t for w, (t, _f) in repl.items()}


def _client_article(src):
    import client_private as CP
    import private_store as PS
    return PS.client_slug(src) or CP.is_private(CP.owner_of_slug(src))


def _scrub(row, terms):
    """全社に効く学びは public に残し、お客様の名前・ドメイン・記事の題と slug は伏せる"""
    import client_private as CP
    r = dict(row)
    rx, repl = terms or (None, {})
    for k in TEXT:
        if isinstance(r.get(k), str) and r[k]:
            v = rx.sub(lambda m: repl.get(m.group(0).lower(), ART), r[k]) if rx else r[k]
            r[k] = CP.redact(v)
    if row.get("source") and _client_article(str(row["source"])):
        r["source"] = ART
    return r


def _body(r):
    return json.dumps({k: v for k, v in r.items() if k not in SAFE}, ensure_ascii=False, sort_keys=True)


def _hold(rows):
    """伏せる語が取れない回に、公開の台帳へ書いてよい行だけを残す。(残す行, 保存しなかった件数)

    公開の台帳にある文のままの行は書く（新しく出るものが無い）。新しい行と文を書き換えた行は、お客様の語を含みうるので
    書かない（書き換えた行は公開の台帳の文のまま残す）。お客様の記事が source の行も書かない"""
    disk = []
    for line in (SRC.read_text(encoding="utf-8").splitlines() if SRC.is_file() else []):
        try:
            disk.append(json.loads(line))
        except ValueError:
            pass
    bodies = {_body(x) for x in disk}
    by_id = {}
    for x in disk:
        by_id.setdefault(x.get("id"), x)
    out, held = [], 0
    for r in rows:
        if _owner(r):                                   # お客様の社の行は置き場へ（公開の台帳には書かない）
            out.append(r)
            continue
        if r.get("source") and _client_article(str(r["source"])):
            held += 1
            HELD.append(r)
            continue
        if _body(r) in bodies:
            out.append(r)
            continue
        held += 1
        if r.get("id") in by_id:
            out.append(dict(by_id[r["id"]], **{k: r[k] for k in SAFE if k in r}))
        else:
            HELD.append(r)
    return out, held


def save(rows):
    """台帳を書き直す。返り値は保存しなかった行の数（伏せる語が取れない回だけ。件数を出す）"""
    import client_private as CP
    terms = _terms()
    held = 0
    if terms is None and SRC.resolve() == PUBLIC.resolve():
        rows, held = _hold(rows)
        if held:
            print(f"学びの台帳: お客様の伏せる語を取れないため、{held}件を保存しませんでした"
                  "（非公開のデータが読めない回。新しい行・書き換えた行は書かず、読める回に積み直す）", file=sys.stderr)
    CP.save_jsonl(SRC, rows, _owner, scrub=lambda r: _scrub(r, terms))
    return held


def _id(rows):
    n = max((int(r["id"][1:]) for r in rows if re.fullmatch(r"L\d+", r.get("id", ""))), default=0)
    return f"L{n + 1:04d}"


def add(kind, phase, rule, detail="", sites=None, gate="", source="", rows=None):
    """学びを1件積む。rule は「次からこうする」を1文で"""
    rows = load() if rows is None else rows
    rule = rule.strip()
    for r in rows + HELD:               # 同じ内容を二重に積まない（保存しなかった行も、同じ実行の中では数える）
        if r.get("rule", "").strip() == rule and r.get("status") != "retired":
            return r, False
    rec = {"id": _id(rows), "at": date.today().isoformat(), "kind": kind, "phase": phase,
           "sites": sites or [], "rule": rule, "detail": detail.strip(), "gate": gate.strip(),
           "source": source.strip(), "status": "active", "hits": 0}
    rows.append(rec)
    save(rows)
    return rec, True


def for_site(rows, site):
    """そのサイトに効く学び。サイト指定の無いものは全サイトに効く"""
    return [r for r in rows
            if r.get("status") == "active"
            and not r.get("gate")                      # 機械が守るものは読ませない
            and (not r.get("sites") or site in r["sites"])]


def brief(site, limit=BRIEF_MAX, count=True):
    """記事を書く直前に渡す文章。短く保つことが目的（長いほど守られない）

    count=False は読まれた回数を数えない（検査から呼ぶと hits が水増しされ、棚卸しの判定が狂う）"""
    rows = load()
    live = for_site(rows, site)
    # 失敗の学びを先に。同じ工程が並ばないよう、工程ごとに新しい順で拾う
    live.sort(key=lambda r: (r.get("kind") != "failure", r.get("at", "")), reverse=False)
    # 公開後の実測から学んだもの（learn.py・source=learn:*）を最優先にする。
    # 書きながらの気づきより根拠が厚く、成功の学びだと失敗の後ろに回されて読まれなかった
    live.sort(key=lambda r: (not str(r.get("source", "")).startswith("learn:"),
                             r.get("kind") != "failure", -_ord(r.get("at", ""))))
    out, used, seen_phase = [], 0, {}
    for r in live:
        p = r.get("phase", "ops")
        if seen_phase.get(p, 0) >= 3:                  # 1工程からは3件まで（偏りを防ぐ）
            continue
        line = f'- [{p}] {r["rule"]}'
        if used + len(line) > BRIEF_CHARS or len(out) >= limit:
            break
        out.append(line)
        used += len(line)
        seen_phase[p] = seen_phase.get(p, 0) + 1
        r["hits"] = int(r.get("hits", 0)) + 1
    if count:
        save(rows)
    if not out:
        return "（この工程で気をつけることは、いまありません）"
    return ("これまでに分かっていること。ここに書かれたことは必ず守る。\n"
            "（機械の検査で止められるものは載せていない。ここにあるのは判断が要るものだけ）\n"
            + "\n".join(out))


def _ord(s):
    try:
        return datetime.fromisoformat(s).toordinal()
    except Exception:
        return 0


def review():
    """棚卸し。ためるだけの台帳は読まれなくなるので、減らす仕組みを持つ"""
    rows = load()
    today = date.today().toordinal()
    gated = [r for r in rows if r.get("status") == "active" and r.get("gate")]
    stale = [r for r in rows if r.get("status") == "active" and not r.get("gate")
             and int(r.get("hits", 0)) == 0 and today - _ord(r.get("at", "")) > STALE_DAYS]
    live = [r for r in rows if r.get("status") == "active"]
    return {"total": len(rows), "active": len(live), "gated": gated, "stale": stale,
            "no_gate": [r for r in live if not r.get("gate")]}


def import_md():
    """kpi_feedback.md の 成功/失敗パターンを台帳へ移す（移行用）"""
    if not FEEDBACK.is_file():
        return 0
    t = FEEDBACK.read_text(encoding="utf-8")
    rows = load()
    n = 0
    for head, kind in (("## 成功パターン", "success"), ("## 失敗パターン", "failure")):
        m = re.search(rf"{re.escape(head)}.*?(?=\n## |\Z)", t, re.S)
        if not m:
            continue
        for item in re.findall(r"^- (.+?)(?=\n- |\n\n|\Z)", m.group(0), re.S | re.M):
            body = re.sub(r"\s+", " ", item).strip()
            if len(body) < 20:
                continue
            body = re.sub(r"^【新パターン】", "", body)
            rule = best_rule(body)
            _, made = add(kind, _guess_phase(body), rule, detail=body,
                          source="kpi_feedback.md（移行）", rows=rows)
            n += made
    return n


ACTION = ("次回", "こと。", "ことで", "すること", "確認", "回避", "使う", "避け", "分割", "追加", "変える", "止める", "落とす", "進む")


def best_rule(text):
    """「次からこうする」に当たる一文を選ぶ。学びの本文は経緯が長く、
    先頭を切り出すと途中で切れて読めない。対処は文末側にあることが多い"""
    sents = [x.strip() for x in re.split(r"(?<=。)", text) if len(x.strip()) > 12]
    if not sents:
        return text[:150]
    acts = [x for x in sents if any(k in x for k in ACTION)]
    pick = (acts[-1] if acts else sents[0])
    if len(pick) > 170:                       # 長い一文は読点で切る
        pick = pick[:170].rsplit("、", 1)[0] + "…"
    return pick


def refresh_rules():
    rows = load()
    n = 0
    for r in rows:
        if not r.get("detail"):
            continue
        new = best_rule(r["detail"])
        if new and new != r.get("rule"):
            r["rule"] = new
            n += 1
    save(rows)
    return n


def _guess_phase(text):
    for kw, p in (("kw_guard", "kw"), ("KW", "kw"), ("カニバリ", "kw"), ("台帳", "kw"),
                  ("research", "research"), ("一次情報", "research"), ("YouTube", "research"),
                  ("構成", "design"), ("H2", "design"), ("見出し", "design"),
                  ("FAQ", "writing"), ("本文", "writing"), ("文字数", "writing"),
                  ("採点", "quality"), ("score", "quality"), ("品質", "quality"),
                  ("公開", "publish"), ("publish", "publish"), ("画像", "publish"),
                  ("GSC", "analysis"), ("順位", "analysis"), ("表示", "analysis")):
        if kw in text:
            return p
    return "ops"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", metavar="SITE", help="記事を書く前に読ませる分")
    ap.add_argument("--add", action="store_true", help="学びを足す")
    ap.add_argument("--kind", default="failure", choices=["success", "failure"])
    ap.add_argument("--phase", default="ops", choices=list(PHASES))
    ap.add_argument("--rule", default="", help="次からこうする（1文）")
    ap.add_argument("--detail", default="", help="何が起きたか（数字つきで）")
    ap.add_argument("--sites", default="", help="効くサイト（カンマ区切り。空なら全サイト）")
    ap.add_argument("--gate", default="", help="機械検査の名前（あればプロンプトから外れる）")
    ap.add_argument("--source", default="")
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--import-md", action="store_true")
    ap.add_argument("--retire", metavar="ID")
    ap.add_argument("--refresh-rules", action="store_true", help="本文から「次からこうする」を取り直す")
    a = ap.parse_args()

    if a.brief:
        print(brief(a.brief))
        return 0
    if a.refresh_rules:
        print(f"取り直し: {refresh_rules()}件")
        return 0
    if a.import_md:
        print(f"取り込み: {import_md()}件 → {SRC.relative_to(ROOT).as_posix()}")
        return 0
    if a.retire:
        rows = load()
        for r in rows:
            if r["id"] == a.retire:
                r["status"] = "retired"
        save(rows)
        print(f"{a.retire} を退役にしました")
        return 0
    if a.add:
        if not a.rule:
            raise SystemExit("--rule（次からこうする）が要ります")
        # 学びは以後の記事の AI が「必ず守ること」として読む。外の文章（字幕・検索上位）に仕込まれた宛先を学びにさせない
        if re.search(r"://|www\.", a.rule + " " + a.detail):
            raise SystemExit("学びに URL は書けません（宛先は記事の出典として書く）")
        # 記事の回（SITE_ID がある）で社を指定せずに足した学びは、その社にだけ効かせる。全社に効かせると、1社の回で
        # 仕込まれた指示がお客様の社も含む全部の記事に効き、お客様の社の学びが公開側に残った（2026-10-24 の点検）
        sites = [s for s in a.sites.split(",") if s] or ([os.environ["SITE_ID"]] if os.environ.get("SITE_ID") else [])
        rec, made = add(a.kind, a.phase, a.rule, a.detail, sites, a.gate, a.source)
        if any(r is rec for r in HELD):
            # 文はお客様の語を含みうるので出さない（このログも public）
            print(f'保存しませんでした: {rec["id"]} [{rec["phase"]}]（お客様の伏せる語を取れない回）')
            return 0
        print(("追加: " if made else "既にあります: ") + f'{rec["id"]} [{rec["phase"]}] {rec["rule"][:60]}')
        if made and _owner(rec) and not os.environ.get("GITHUB_ACTIONS"):
            # 置き場は CI のキャッシュでしか CI に渡らない。手元で積んだお客様の学びは CI の記事に効かない
            print(f"   注意: お客様の社の学びは public に置かず、この端末の置き場に入りました（CI には届きません）。"
                  f"記事に必ず効かせる決まりは data/clients/{_owner(rec)}/brief.json に書いてください")
        return 0
    if a.review:
        r = review()
        print(f"■ 学びの台帳 {r['total']}件（生きている {r['active']}件）")
        print(f"   機械が守る（プロンプトから外れている）: {len(r['gated'])}件")
        for x in r["gated"][:6]:
            print(f"     {x['id']} {x['gate']}: {x['rule'][:54]}")
        print(f"   判断が要る（毎回読ませる候補）: {len(r['no_gate'])}件")
        print(f"   {STALE_DAYS}日以上だれにも読まれていない: {len(r['stale'])}件")
        for x in r["stale"][:6]:
            print(f"     {x['id']} ({x['at']}) {x['rule'][:54]}")
        if r["stale"]:
            print("   → 効いているか分からない学びは、退役させるか機械検査に変える")
        print("LESSONS_OK=" + ("no" if len(r["no_gate"]) > 40 else "yes"))
        if len(r["no_gate"]) > 40:
            print(f"   ::warning::判断が要る学びが{len(r['no_gate'])}件あります。"
                  "多すぎると読まれません。機械検査に変えるか退役させてください")
        return 0

    rows = load()
    print(f"■ 学びの台帳 {len(rows)}件")
    for r in rows:
        if r.get("status") != "active":
            continue
        mark = "機械" if r.get("gate") else "判断"
        tgt = ",".join(r.get("sites") or []) or "全サイト"
        print(f"  {r['id']} [{mark}] [{r['phase']:<8}] {tgt:<10} {r['rule'][:62]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
