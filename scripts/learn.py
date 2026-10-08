# -*- coding: utf-8 -*-
"""公開した後の結果から学び、記事を書く工程が読む台帳（data/lessons.jsonl）へ毎週書き戻す

**なぜ要るか**: 書く工程は学びの台帳（lessons.py --brief）を読んでから書くが、台帳に積まれるのは
書いている最中に起きた失敗だけだった。公開した後に分かったこと —
どの題の型がクリックされたか、別工程の採点で何が足りなかったか、記事を増やした分が伸びたか、
直した手が戻されたか — は週次のデータとして出ていたのに、次の記事に一度も届いていなかった。

学びの形（CLAUDE.md 0.2 の仕分けを守る）:
  - 学びごとに鍵（source = "learn:<名前>"）を1つ持ち、毎週**最新の数字で書き換える**（積み増さない）
  - 根拠が消えたら**退役**させる（古い学びが残り続けない）
  - 数字の母数が足りないときは学びにしない（少ない数で方針を変えない）
  - 機械で守れることは学びにせず検査にする。ここに来るのは判断が要るものだけ

    python scripts/learn.py            # 何を学ぶか見る
    python scripts/learn.py --write    # 台帳へ書き戻す（週次）
出す印: LEARN_OK=yes（動いた）／学び・退役の件数
"""
import argparse
import json
import re
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DATA = ROOT / "data"


def title_signal():
    """題の型ごとの実測CTR（title_patterns が週次で書く）。寄せる型・避ける型を新しい記事の題にも効かせる"""
    p = DATA / "title_patterns.md"
    if not p.is_file():
        return []
    t = p.read_text(encoding="utf-8")
    good = re.search(r"寄せる型:\s*(.+)", t)
    bad = re.search(r"避ける型:\s*(.+)", t)
    tot = re.search(r"表示([\d,]+)回", t)
    if not (good or bad) or not tot or int(tot.group(1).replace(",", "")) < 1000:
        return []
    rule = "新しい記事の題は"
    if good:
        rule += f"「{good.group(1).strip()}」の型を優先し"
    if bad:
        rule += f"、「{bad.group(1).strip()}」の型は避ける"
    rule += "（狙う語と題の15〜45字の決まりは守る）"
    return [("learn:title", "success", "design", [], rule,
             f"自社3サイト1〜20位の実測CTR（{re.search(r'（(.+?)）', t).group(1) if re.search(r'（(.+?)）', t) else ''}"
             f"・表示{tot.group(1)}回）。data/title_patterns.md")]


def originality_signal():
    """別工程の採点（score_audit・今の基準）で一次性が低いなら、書く前の材料の集め方を変える"""
    p = DATA / "score_audit.json"
    if not p.is_file():
        return []
    try:
        import rubric as R
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    cur = [v["audit"] for v in d.values() if (v.get("audit") or {}).get("version") == R.VERSION]
    o = [a["axes"]["originality"] for a in cur if (a.get("axes") or {}).get("originality") is not None]
    if len(o) < 4:
        return []
    med = statistics.median(o)
    if med >= 80:
        return []
    return [("learn:originality", "failure", "research", [],
             "書く前に site_brief の一次情報と research.py の字幕引用から、本文に使う事実を3つ以上決める。"
             "決められない語は着手せず次の語へ回す（無い事実は書かない）",
             f"別工程の採点で一次性の中央値が{med:.0f}/100（{len(o)}本）。自己採点は全記事90点以上だった")]


def yield_signal():
    """記事を増やした分が伸びていないサイト（content_yield の判定）。狙う語の選び方を変える"""
    import client_private as CP
    out = []
    # お客様の社の判定は置き場にある（client_private）。合わせて読み、学びはその社の置き場へ入る（lessons._owner）
    for sid, st in CP.load_dict("data/yield_state.json", pub=DATA / "yield_state.json").items():
        if isinstance(st, dict) and (st.get("flagged") or st.get("throttle")):
            why = "／".join(st.get("reasons") or [])[:160]
            out.append((f"learn:yield:{sid}", "failure", "kw", [sid],
                        "既存記事の狙う語・見出しと重なる語は新しく書かず、既存記事の書き足しに回す"
                        "（kw_guard が1でも、近い既存記事があれば差別化の切り口を題と冒頭で先に示す）",
                        f"content_yield: {why}"))
    return out


def rollback_signal():
    """直した手が28日後に戻された割合（rewrite_rollback の判定）。戻されがちな直し方は避ける"""
    import client_private as CP
    d = CP.load_dict("data/rollback_decisions.json", pub=DATA / "rollback_decisions.json")
    # 形式は rewrite_rollback が書く {"<slug>@<日付>": {"ratio", "control", "pos_gain", "rolled_back", "control_n", "kind"}}。
    # 学びの文は題の直しのことなので題の判定だけを数える（early・compete は本文も変える）。
    # control_n の無い判定は、公開からの日数が違う記事とページを対照にした頃のもので、
    # 公開から日の浅い記事の自然な落ち込みを「戻すべき」と読んでいた。数に入れない
    decided = [r for r in (d.values() if isinstance(d, dict) else [])
               if isinstance(r, dict) and "rolled_back" in r and r.get("control_n")
               and r.get("kind", "title") == "title"]
    if len(decided) < 6:
        return []
    back = sum(1 for r in decided if r["rolled_back"])
    if back / len(decided) < 0.5:
        return []
    return [("learn:rollback", "failure", "quality", [],
             "題を書き換えるときは、いま表示が取れている語（GSCの上位語）を題から外さない",
             f"直した題の{back}/{len(decided)}本が28日後に表示8割を割り、元に戻された（rewrite_rollback）")]


SIGNALS = (title_signal, originality_signal, yield_signal, rollback_signal)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    import lessons as L
    found = {}
    for f in SIGNALS:
        try:
            for key, kind, phase, sites, rule, detail in f():
                found[key] = (kind, phase, sites, rule, detail)
        except Exception as e:
            print(f"  （{f.__name__} を読めません: {str(e)[:60]}）")
    rows = L.load()
    mine = {r.get("source"): r for r in rows if str(r.get("source", "")).startswith("learn:") and r.get("status") == "active"}
    added = updated = retired = 0
    print("■ 結果から学ぶ（書く工程が読む台帳へ）\n")
    for key, (kind, phase, sites, rule, detail) in found.items():
        cur = mine.get(key)
        if cur and cur.get("rule") == rule:
            if cur.get("detail") != detail:
                cur["detail"], cur["at"] = detail, date.today().isoformat()
                updated += 1
            print(f"   そのまま {key}: {rule[:70]}")
            continue
        if cur:
            cur.update(rule=rule, detail=detail, kind=kind, phase=phase, sites=sites, at=date.today().isoformat())
            updated += 1
            print(f"   書き換え {key}: {rule[:70]}")
        else:
            rows.append({"id": L._id(rows), "at": date.today().isoformat(), "kind": kind, "phase": phase,
                         "sites": sites, "rule": rule, "detail": detail, "gate": "", "source": key,
                         "status": "active", "hits": 0})
            added += 1
            print(f"   追加 {key}: {rule[:70]}")
    for key, r in mine.items():
        if key not in found:
            r["status"] = "retired"
            r["detail"] = (r.get("detail", "") + f"｜{date.today().isoformat()} 根拠が消えたため退役").strip("｜")
            retired += 1
            print(f"   退役 {key}（根拠のデータが条件を満たさなくなった）")
    if a.write and (added or updated or retired):
        L.save(rows)
    elif not a.write:
        print("\n   --write を付けると台帳へ書き戻します")
    print(f"\nLEARN_OK=yes\nLEARN_ADDED={added}\nLEARN_UPDATED={updated}\nLEARN_RETIRED={retired}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
