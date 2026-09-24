# -*- coding: utf-8 -*-
"""レポートに書いた改善点を、発行した直後に機械が実行し、見直し、残った分だけ人に知らせる。

**なぜ要るか**: 月次レポートは「改善プラン」「来月つくるもの」「次にやること」を
数字から導いて書いていた。しかし書いたあと、実行するのは人だった。
今回、私が手でレポートを読み、auto_improve と auto_rewrite を回した。
月初のCIには、その手が無い。レポートが出るたびに同じことを機械が行う。

流れ（1回の実行）:
  1. 導く   … レポートと同じ材料（structure_plan・site_diagnosis）から改善項目を作る
  2. 当てる … 機械で直せる項目は、既存の道具（auto_rewrite・auto_merge・link_boost …）で当てる
  3. 検算   … build.py と tests/test_gates.py。通らなければその回の変更を捨てる
  4. 見直す … 1〜3 をもう一度。項目が減らなくなるか、上限回数（既定3）で止める
  5. 届ける … 人にしかできない項目と、機械では解消しなかった項目だけをメールする

**新しい直し方をここに書かない。** 当てるのは全部、既にある道具（それぞれ検算を持つ）。
ここで文章を書き換えると、検算の無い直しが本番に入る（8.6節）。

  python scripts/report_actions.py                 # 何を当てるかを見る（当てない）
  python scripts/report_actions.py --apply         # 当てて、見直して、知らせる
  python scripts/report_actions.py --apply --rounds 2 --budget-min 40
  python scripts/report_actions.py --selftest      # 導出と対応表が壊れていないか

出す印: ACTIONS_OK=yes/no（機械の分が全部通ったか） / HUMAN=<人の手が要る件数>
台帳: automation/logs/report_actions.jsonl
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOG = ROOT / "automation" / "logs" / "report_actions.jsonl"
OUTDIR = ROOT / "automation" / "logs" / "report_actions"
PY = sys.executable

# 種別 → 当てる道具。どの道具も自分の検算を持ち、通らなければ書かない。
# 順番は「効く順」。同じ道具は1回の見直しで1度しか動かさない
RUNNERS = {
    "rewrite":  [["auto_rewrite.py", "--write", "--limit", "4", "--budget-min", "12"]],
    "rank":     [["rank_up.py", "--write"], ["priority_boost.py", "--write"]],
    "links":    [["link_boost.py", "{site}", "--rescue", "--write"],
                 ["link_boost.py", "{site}", "--write"]],
    "merge":    [["auto_merge.py", "--selftest"],
                 ["auto_merge.py", "--write", "--limit", "2", "--budget-min", "10"]],
    "kw_stock": [["kw_discover.py", "--site", "{site}", "--append"]],
    "hub":      [["build.py"]],
    "cta":      [["cta_fill.py", "--write"]],
    "nav":      [["sync_nav.py", "--apply"]],
    "review":   [["auto_review.py", "--fix"]],
}
# 人にしかできない種別。メールで知らせる
HUMAN = {"measure": "計測の権限・設定（サービスアカウントの付与）",
         "lp": "LPのCTA位置・文言（判断が要る）",
         "hub_external": "配信先サイトに業種ハブの仕組みが無い（テンプレート側の対応が要る）",
         "finding": "導出そのものが動かなかった（実行ログを確認）"}
LOW_STOCK = 40
GATE_TIMEOUT = 20 * 60


def _log(**row):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now().isoformat(timespec="seconds"), **row}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _sites(only=""):
    import sites as S
    return {k: v for k, v in S.load_all().items() if not only or k == only}


# ── 1. 導く ────────────────────────────────────────────
def derive(site_ids):
    """改善項目を、レポートと同じ材料から作る。[{kind, site, finding, action, auto}]"""
    items = []
    import sites as S
    primary = S.primary()

    def add(kind, site, finding, action):
        items.append({"kind": kind, "site": site, "finding": finding[:120],
                      "action": action[:120], "auto": kind in RUNNERS})

    for sid in site_ids:
        # 来月つくるもの（盤面・ハブ・書き足し・統合）
        try:
            import structure_plan as SP
            for p in SP.plan(sid):
                k = p.get("kind", "")
                if k == "新しい記事":
                    add("article_new", sid, f'{p["what"]}: {p["why"]}', "台帳へ語を積む（日次の執筆が書く）")
                elif k == "新しいハブ":
                    # 業種ハブを作れるのは本リポジトリの静的サイトだけ。配信先の
                    # サイトには仕組みが無いので、build.py を回しても何も起きない
                    if sid == primary:
                        add("hub", sid, f'{p["what"]}: {p["why"]}', "build.py が業種ハブを作る")
                    else:
                        add("hub_external", sid, f'{p["what"]}: {p["why"]}', HUMAN["hub_external"])
                elif k == "書き足し":
                    add("rewrite", sid, f'{p["what"]}: {p["why"]}', "auto_rewrite（stuck）で節を足す")
                elif k == "統合の検討":
                    add("merge", sid, f'{p["what"]}: {p["why"]}', "auto_merge で統合（検算つき）")
        except Exception as e:
            add("finding", sid, f"来月つくるものを導けません: {str(e)[:60]}", "structure_plan を確認")

        # 現在地（順位帯・在庫・導線・要対応）
        try:
            import site_diagnosis as SD
            d = SD.diagnose(sid)
            b = d.get("bands") or {}
            cfg = _sites(sid).get(sid, {})
            if b is None or (d.get("funnel") is None and cfg.get("ga4_property_id")):
                add("measure", sid, "GSC または GA4 のデータが取れていません", HUMAN["measure"])
            gap10 = sum(v.get("gap", 0) for k, v in b.items() if k in ("4〜10位", "1〜3位"))
            gap20 = b.get("11〜20位", {}).get("gap", 0)
            if gap10 >= 5:
                add("rewrite", sid, f"1ページ目の記事が順位相応より {gap10:.0f}クリック少ない",
                    "タイトル・説明文の書き換え（auto_rewrite title）")
            if gap20 >= 5:
                add("rank", sid, f"11〜20位に {gap20:.0f}クリック分の伸びしろ", "rank_up / priority_boost")
                add("links", sid, "11〜20位の記事の内部リンクを下限まで集める", "link_boost --rescue")
            st = d.get("stock")
            if st and st.get("todo", 0) < LOW_STOCK:
                add("kw_stock", sid, f'対策キーワードの在庫 {st["todo"]}本（{LOW_STOCK}本未満）', "kw_discover --append")
            fun = d.get("funnel")
            if fun and fun[0][1] >= 50 and fun[1][1] / max(fun[0][1], 1) < 0.03:
                add("lp", sid, f"CTA押下率 {fun[1][1] / max(fun[0][1], 1) * 100:.1f}%（記事到達 {fun[0][1]}）",
                    HUMAN["lp"])
            # 週次検査の「要対応」は findings.py が週次で届けている。ここで
            # サイトごとに繰り返すと、同じ10件が3回並んで本当の項目が埋もれる
        except Exception as e:
            add("finding", sid, f"現在地を診断できません: {str(e)[:60]}", "site_diagnosis を確認")

        # 構成の整備は毎回（何も無ければ道具が何もしない）
        add("links", sid, "被リンクの少ない記事へ話題の合う記事から足す", "link_boost")
    add("cta", "all", "CTAが2箇所未満の記事を埋める", "cta_fill")
    add("nav", "all", "固定ページのナビを build.py の定義に揃える", "sync_nav --apply")
    add("review", "all", "自動修正の積み上がり（同じ言い回し・リンク段落）を均す", "auto_review --fix")
    return items


def enqueue_gaps(items, budget=6):
    """盤面の空きマスの語を、食い合い審査を通ったものだけ台帳へ積む。

    「新しい記事」は日次の執筆が書く。ここでは書かず、語を積むだけ。
    審査は kw_guard（機械判定）。LLMの目視で代替しない。
    """
    try:
        import kw_guard as KG
        import hub_client as HC
    except Exception:
        return 0
    if not HC.enabled():
        return 0
    have = {re.sub(r"[\s　]", "", str(k.get("keyword", k) if isinstance(k, dict) else k)).lower()
            for k in HC.all_kw()}
    n = 0
    for it in items:
        if it["kind"] != "article_new" or n >= budget:
            continue
        kw = it["finding"].split(":")[0].replace(" × ", " ").strip()
        if not kw or re.sub(r"[\s　]", "", kw).lower() in have:
            continue
        try:
            level, _ = KG.judge(kw, it["site"])
        except Exception:
            continue
        if level == 0:
            try:
                HC.add_kw(it["site"], [kw])
                n += 1
                _log(step="enqueue", site=it["site"], kw=kw)
            except Exception:
                pass
    return n


# ── 2. 当てる ──────────────────────────────────────────
def run(cmd, timeout=GATE_TIMEOUT):
    t0 = time.time()
    try:
        p = subprocess.run([PY, str(ROOT / "scripts" / cmd[0]), *cmd[1:]], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
        out, rc = (p.stdout + p.stderr), p.returncode
    except subprocess.TimeoutExpired:
        out, rc = "timeout", 124
    tail = out.strip().splitlines()[-3:]
    _log(step="run", cmd=" ".join(cmd), rc=rc, sec=round(time.time() - t0), tail=tail)
    return rc, out


def gate():
    """直したあとで基準を割っていないか。割っていれば捨てる"""
    for cmd in (["build.py"], ["../tests/test_gates.py"]):
        rc, out = run(cmd)
        if rc != 0:
            subprocess.run(["git", "checkout", "--", "articles/", "site/"], cwd=ROOT)
            _log(step="gate", ok=False, cmd=cmd[0], tail=out.strip().splitlines()[-5:])
            return False, cmd[0]
    _log(step="gate", ok=True)
    return True, ""


def apply_round(items, budget_min, spent):
    """機械で直せる項目を、道具ごとに1回ずつ当てる。使った分（分）を返す"""
    seen, ran = set(), []
    for it in items:
        if not it["auto"]:
            continue
        for cmd in RUNNERS[it["kind"]]:
            c = [x.replace("{site}", it["site"]) for x in cmd]
            if "{site}" in " ".join(cmd) and it["site"] == "all":
                continue
            key = " ".join(c)
            if key in seen:
                continue
            seen.add(key)
            if spent >= budget_min:
                _log(step="budget", skipped=key)
                continue
            t0 = time.time()
            rc, out = run(c)
            spent += (time.time() - t0) / 60
            ran.append((key, rc))
            # selftest が通らない道具は、その次（--write）を飛ばす（検算が壊れたまま書かせない）
            if "--selftest" in c and rc != 0:
                seen.add(key.replace("--selftest", "--write"))
                _log(step="selftest_failed", cmd=key)
                break
    return ran, spent


def fingerprint(items):
    return sorted({(i["kind"], i["site"], i["finding"][:40]) for i in items if i["auto"]})


# ── 5. 届ける ──────────────────────────────────────────
def body(human, unresolved, gate_fail, rounds_done):
    lines = ["月次レポートの改善項目を機械で実行しました（見直し%d回）。" % rounds_done, ""]
    if gate_fail:
        lines += ["🚨 検算（%s）が通らず、その回の変更を捨てました。実行ログを確認してください。" % gate_fail, ""]
    if human:
        lines.append("■ 人の手が要るもの（%d件）" % len(human))
        for it in human:
            lines.append(f"・[{it['site']}] {it['finding']} → {it['action']}")
        lines.append("")
    if unresolved:
        lines.append("■ 機械で当てても残っているもの（%d件・翌週の週次が続けます）" % len(unresolved))
        for it in unresolved[:12]:
            lines.append(f"・[{it['site']}] {it['finding']}")
        lines.append("")
    if not human and not unresolved and not gate_fail:
        lines.append("人の手が要る項目はありません。")
    lines.append("台帳: automation/logs/report_actions.jsonl")
    return "\n".join(lines)


def notify(text, force):
    args = [PY, str(ROOT / "scripts" / "notify_slack.py")]
    if force:
        args.append("--force")
    subprocess.run(args + [text], cwd=ROOT)


# ── 入口 ────────────────────────────────────────────────
def selftest():
    bad = []
    for k, cmds in RUNNERS.items():
        for c in cmds:
            if not (ROOT / "scripts" / c[0]).is_file():
                bad.append(f"{k}: scripts/{c[0]} が無い")
    items = derive([])          # サイト無しでも構成の整備3件は出る
    if len([i for i in items if i["auto"]]) < 3:
        bad.append("導出が空")
    txt = body([{"site": "x", "finding": "f", "action": "a"}], [], "", 1)
    if "人の手が要る" not in txt:
        bad.append("通知文に人の項目が出ない")
    for b in bad:
        print("  ★", b)
    print(f"SELFTEST_OK={'no' if bad else 'yes'}")
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--site", default="")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--budget-min", type=int, default=60, help="道具を動かす合計時間の上限（分）")
    ap.add_argument("--force", action="store_true", help="手元からでも通知を送る")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    sids = list(_sites(a.site))
    items = derive(sids)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / f"{date.today().isoformat()}.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    human = [i for i in items if i["kind"] in HUMAN]
    print(f"■ 改善項目 {len(items)}件（機械 {sum(i['auto'] for i in items)} / 人 {len(human)}）")
    for it in items:
        print(f"   {'機械' if it['auto'] else ('進行' if it['kind'] == 'article_new' else '人 ')} "
              f"[{it['site']:<9}] {it['kind']:<11} {it['finding'][:60]}")
    if not a.apply:
        print(f"HUMAN={len(human)}")
        return 0

    n = enqueue_gaps(items)
    if n:
        print(f"   台帳へ {n}語を積みました（空いているマス）")
    spent, gate_fail, done, prev = 0.0, "", 0, None
    for r in range(1, a.rounds + 1):
        if r > 1:
            items = derive(sids)
        fp = fingerprint(items)
        if fp == prev:
            print(f"   見直し{r}: 項目が変わらないため止めます")
            break
        prev = fp
        print(f"── 見直し {r}/{a.rounds}（機械 {len(fp)}件）")
        ran, spent = apply_round(items, a.budget_min, spent)
        for key, rc in ran:
            print(f"   {'○' if rc == 0 else '×'} {key}")
        ok, failed = gate()
        done = r
        if not ok:
            gate_fail = failed
            print(f"   ★ 検算 {failed} が通らず、この回の変更を捨てました")
            break
        if spent >= a.budget_min:
            print(f"   予算 {a.budget_min}分を使い切りました")
            break

    final = derive(sids)
    unresolved = [i for i in final if i["auto"] and i["kind"] in ("rewrite", "rank", "merge", "kw_stock")]
    human = [i for i in final if i["kind"] in HUMAN]
    text = body(human, unresolved, gate_fail, done)
    print(text)
    if human or gate_fail:
        notify(text, a.force)
    _log(step="done", rounds=done, human=len(human), unresolved=len(unresolved), gate_fail=gate_fail)
    print(f"ACTIONS_OK={'no' if gate_fail else 'yes'}")
    print(f"HUMAN={len(human)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
