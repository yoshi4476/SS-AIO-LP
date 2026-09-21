# -*- coding: utf-8 -*-
"""サイトの現在地と、次にやることを、レポート用にまとめる。

週次・月次レポートは数字の推移は出していたが、「いまどこが弱く、次に何を
するか」が読み手に委ねられていた。ここで同じ材料から機械的に組み立てる。
判断の根拠は全部、既にある道具（rank_up・funnel・brand_search・台帳・findings）。

    python scripts/site_diagnosis.py            # 3サイトぶんを文字で出す
    python scripts/site_diagnosis.py --site corporate

外部への問い合わせ（GSC・GA4・管制塔）は失敗しても落とさず、その欄だけ
「取得できません」と出す。レポートは毎週必ず届くことが先。
"""
import argparse
import html as _html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

FINDINGS = ROOT / "automation" / "logs" / "findings.txt"
LOW_STOCK = 40          # 未着手がこれ未満なら「在庫が薄い」（20日分）


def esc(s):
    return _html.escape(str(s if s is not None else ""))


def _try(fn, default):
    try:
        return fn()
    except Exception as e:
        return default if not callable(default) else default(e)


# ── 材料 ──────────────────────────────────────────────

def rank_bands(domain, days=28):
    """順位帯ごとの ページ数・表示・クリック と、順位相応なら取れたクリック"""
    import rank_up
    d = rank_up.fetch(domain, days)
    out = {}
    for url, v in d.items():
        b = rank_up.band_of(v["pos"])[0]          # (名前, やること) の名前だけ
        o = out.setdefault(b, {"pages": 0, "imp": 0, "clicks": 0, "gap": 0.0})
        o["pages"] += 1
        o["imp"] += v["imp"]
        o["clicks"] += v["clicks"]
        o["gap"] += max(0.0, v["imp"] * rank_up.expected_ctr(v["pos"]) / 100.0 - v["clicks"])
    return out


def funnel_counts(prop, days=28):
    import funnel
    ev = funnel.events(prop, days)
    return [(label, sum(ev.get(x, 0) for x in names)) for label, names in funnel.STEPS]


def brand(site_id, days=28):
    import brand_search
    got = brand_search.collect(days).get(site_id)
    if not got:
        return None
    return {"prev": got["prev"]["imp"], "cur": got["cur"]["imp"],
            "growth": brand_search.growth(got["prev"]["imp"], got["cur"]["imp"])}


def stock(site_id):
    import hub_client
    st = hub_client.status(site_id) or {}
    a = 0
    try:
        import kw_plan
        a = sum(1 for v in kw_plan.plan_metrics(site_id).values() if v[2] == "A")
    except Exception:
        pass
    return {"todo": int(st.get("todo") or 0), "doing": int(st.get("doing") or 0),
            "done": int(st.get("done") or 0), "A": a}


def findings():
    if not FINDINGS.exists():
        return []
    return [ln.strip() for ln in FINDINGS.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith("要対応")]


def fixes(site_id, n=5):
    import rank_up
    return [x for x in rank_up.human_items(site_id) if x.get("site") == site_id][:n]


# ── 組み立て ───────────────────────────────────────────

def diagnose(site_id, days=28):
    import sites as S
    cfg = S.load(site_id)
    bands = _try(lambda: rank_bands(cfg["domain"], days), None)
    fun = _try(lambda: funnel_counts(cfg.get("ga4_property_id"), days)
               if cfg.get("ga4_property_id") else None, None)
    br = _try(lambda: brand(site_id, days), None)
    st = _try(lambda: stock(site_id), None)
    fx = _try(lambda: fixes(site_id), [])
    return {"site": site_id, "name": cfg["name"], "domain": cfg["domain"], "days": days,
            "bands": bands, "funnel": fun, "brand": br, "stock": st, "fixes": fx,
            "findings": findings()}


def next_actions(d):
    """診断から、次にやることを機械的に出す。順番は効く順"""
    acts = []
    b = d.get("bands") or {}
    gap10 = sum(v["gap"] for k, v in b.items() if k in ("4〜10位", "1〜3位"))
    gap20 = b.get("11〜20位", {}).get("gap", 0)
    if gap10 >= 5:
        acts.append(("自動", f"1ページ目にいる記事のタイトル・説明文を直す（順位相応なら +{gap10:.0f}クリック/{d['days']}日）。"
                            "週次の auto_rewrite が上から順に処理中"))
    if gap20 >= 5:
        acts.append(("自動", f"11〜20位の記事に内部リンクと一次情報を足して1ページ目へ（+{gap20:.0f}クリック相当）。"
                            "週次の rank_up が処理中"))
    for x in d.get("fixes") or []:
        acts.append(("自動", f"{x['slug']}: {x['why'][:38]}"))
    st = d.get("stock")
    if st and st["todo"] < LOW_STOCK:
        acts.append(("自動", f"対策キーワードの在庫が {st['todo']} 本（{LOW_STOCK}本未満）。月次の kw_plan が組み直す"))
    fun = d.get("funnel")
    if fun and fun[0][1] >= 50:
        view, cta = fun[0][1], fun[1][1]
        if cta / max(view, 1) < 0.03:
            acts.append(("人", f"CTAの押下率が {cta / max(view, 1) * 100:.1f}%（記事到達 {view}）。"
                              "記事中盤のCTAの位置と文言を見直す"))
    for f in d.get("findings") or []:
        acts.append(("人", f.replace("要対応:", "").strip()))
    if not acts:
        acts.append(("—", "今週、機械が見つけた手当ては無し"))
    return acts


def html_block(d):
    """1サイトぶんの診断と次にやることを、レポートに貼れる形で返す"""
    h = []
    h.append(f'<h3 style="margin:10px 0 4px">{esc(d["name"])}（{esc(d["domain"])}・直近{d["days"]}日）</h3>')
    b = d.get("bands")
    if b:
        order = ["1〜3位", "4〜10位", "11〜20位", "21〜50位", "51位以下"]
        rows = "".join(
            f'<tr><td>{k}</td><td class="num">{b[k]["pages"]}</td><td class="num">{b[k]["imp"]:,}</td>'
            f'<td class="num">{b[k]["clicks"]:,}</td><td class="num">+{b[k]["gap"]:.0f}</td></tr>'
            for k in order if k in b)
        h.append('<table><tr><th>順位帯</th><th style="width:12%">ページ</th><th style="width:16%">表示</th>'
                 '<th style="width:16%">クリック</th><th style="width:22%">順位相応なら増える</th></tr>' + rows + "</table>")
    else:
        h.append('<p class="note">検索の順位帯: 取得できません（Search Console の認証を確認）</p>')
    cells = []
    st = d.get("stock")
    if st:
        cells.append(f"対策キーワードの在庫 <b>{st['todo']}本</b>（うち優先A {st['A']}）／執筆中 {st['doing']}／公開済み {st['done']}")
    br = d.get("brand")
    if br:
        cells.append(f"指名検索の表示 <b>{br['cur']}</b>（前期 {br['prev']}・{br['growth']}）")
    fun = d.get("funnel")
    if fun:
        cells.append("導線: " + " → ".join(f"{k} {v}" for k, v in fun))
    if cells:
        h.append('<p style="font-size:9.5pt">' + "／".join(cells) + "</p>")
    acts = next_actions(d)
    rows = "".join(f'<tr><td style="width:10%">{esc(who)}</td><td>{esc(what)}</td></tr>' for who, what in acts)
    h.append('<table><tr><th>誰が</th><th>次にやること（効く順）</th></tr>' + rows + "</table>")
    return "\n".join(h)


def html(site_ids, days=28):
    return "\n".join(html_block(diagnose(s, days)) for s in site_ids)


def text(site_ids, days=28):
    out = []
    for s in site_ids:
        d = diagnose(s, days)
        out.append(f"■ {d['name']}")
        for k, v in (d.get("bands") or {}).items():
            out.append(f"   {k:8s} {v['pages']:3d}ページ 表示{v['imp']:6,} クリック{v['clicks']:4,} 相応なら +{v['gap']:.0f}")
        st = d.get("stock")
        if st:
            out.append(f"   在庫 {st['todo']}本（A {st['A']}）/ 執筆中 {st['doing']} / 公開済み {st['done']}")
        for who, what in next_actions(d):
            out.append(f"   [{who}] {what}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--days", type=int, default=28)
    a = ap.parse_args()
    import sites as S
    ids = [a.site] if a.site else sorted(S.load_all())
    print(text(ids, a.days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
