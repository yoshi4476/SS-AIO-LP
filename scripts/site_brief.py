# -*- coding: utf-8 -*-
"""対象サイトの執筆ブリーフを1画面で出す（記事パイプラインの最初に実行する）

使い方: python scripts/site_brief.py corporate

サイトのテーマ・読者・担当領域・書いてはいけない領域・カテゴリ・次に書くKWをまとめて表示する。
記事を書くAIがサイト設定を探し回らずに済むようにし、担当領域の取り違えを防ぐのが目的。
"""
import re
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_client  # noqa: E402
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def local_next_kw(cfg, limit=5):
    """管制塔が使えないときのフォールバック（KW計画ファイルから未執筆を拾う）"""
    import re
    from cannibal_check import load_articles
    plan = ROOT / cfg.get("kw_plan", "")
    if not plan.exists():
        return []
    corpus = [f"{a['slug']} {a['title']} {a['desc']}" for a in load_articles()]
    out = []
    for line in plan.read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"^\*\*(.+?)\*\*\s*[:：]\s*(.+)$", line.strip())
        if not m:
            continue
        aim = re.sub(r"（.*?）", "", m.group(1)).strip()
        for kw in m.group(2).split("/"):
            kw = kw.strip()
            if not kw:
                continue
            tokens = [t for t in re.split(r"[\s　]+", kw) if t]
            if any(all(t in doc for t in tokens) for doc in corpus):
                continue
            out.append({"keyword": kw, "aim": aim})
            if len(out) >= limit:
                return out
    return out



def show_brief(site_id):
    """ヒアリングシートで集めた執筆材料を出す。

    ここが埋まっているほど「その会社にしか書けない記事」になる。
    逆に空の項目を憶測で埋めると、事実と違う記事が公開される。
    書いていないことは書かない、という前提で読ませる。
    """
    f = ROOT / "data" / "clients" / site_id / "brief.json"
    if not f.is_file():
        return
    try:
        b = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        # ここで落とすと記事が1本も書けなくなる。材料が読めないことだけ伝える
        print()
        print(f"■ 執筆材料を読めませんでした（{f.name}: {e}）")
        print("  材料なしで書くと一般論の記事になります。ファイルを直してください")
        return
    if not isinstance(b, dict):
        print()
        print(f"■ 執筆材料の形式が不正です（{f.name}）")
        return

    def block(title, rows):
        rows = [(k, v) for k, v in rows if v]
        if not rows:
            return
        print(f"\n■ {title}")
        for k, v in rows:
            if isinstance(v, list):
                print(f"  {k}:")
                for x in v:
                    print(f"    ・{x}")
            else:
                print(f"  {k}: {v}")

    tg = b.get("target") or {}
    block("ターゲット（この人に向けて書く）", [
        ("いちばん来てほしい人", tg.get("persona")),
        ("次に来てほしい層", tg.get("second")),
        ("商圏", tg.get("area")), ("検討の段階", tg.get("stage")),
        ("決め手", tg.get("decide"))])

    kw = b.get("keyword") or {}
    block("狙う語", [
        ("メインキーワード", kw.get("main")),
        ("サブキーワード", kw.get("sub")),
        ("地域を付けて狙う語", kw.get("area_word")),
        ("狙わない語（主題にしない）", kw.get("exclude"))])

    subs = b.get("subjects") or []
    if subs:
        print()
        print("■ 主題の候補（メイン×サブ×意図から生成）")
        for x in subs[:18]:
            print(f"    ・{x['keyword']}  〔{x['from']}〕")
        if len(subs) > 18:
            print(f"    …ほか{len(subs) - 18}件")
        print("    ※ ここから選ぶ前に kw_guard（食い合い）と "
              "kw_intent（開く理由）を必ず通すこと")

    s = b.get("service") or {}
    block("売っているもの（記事の結論はここへ着地させる）", [
        ("提供するもの", s.get("list")), ("価格帯", s.get("price")),
        ("提供エリア", s.get("area")), ("他社と違う点", s.get("strength")),
        ("依頼から開始まで", s.get("flow"))])

    c = b.get("customer") or {}
    block("読者が困っていること（記事の入口に使う）", [
        ("困りごと", c.get("problem")),
        ("よく聞かれる質問（FAQにそのまま使える）", c.get("faq")),
        ("相談のきっかけ", c.get("trigger")), ("よくある誤解", c.get("ng"))])

    a = b.get("author") or {}
    block("記事の書き手（著者情報に入れる）", [
        ("著者", a.get("name")), ("肩書き", a.get("title")),
        ("資格・経歴", a.get("credential")), ("監修", a.get("supervisor"))])

    t = b.get("tone") or {}
    block("書き方のきまり", [
        ("自社の呼び方", t.get("person")), ("文体", t.get("style")),
        ("専門用語", t.get("level")), ("使わない表現", t.get("avoid"))])

    for name, sec in (b.get("industry_detail") or {}).items():
        block(f"業種の詳細（{name}）", list(sec.items()))

    bl = b.get("backlink") or {}
    block("外部との接点（記事で触れると自然にリンクが生まれる相手）", [
        ("加盟団体", bl.get("orgs")), ("掲載中の媒体", bl.get("portals")),
        ("取引先・提携", bl.get("partners")), ("受賞・認定", bl.get("awards")),
        ("取材実績", bl.get("press")), ("公的機関との関わり", bl.get("gov")),
        ("代表者の発信", bl.get("person"))])

    cp = b.get("compete") or {}
    block("競合", [("競合サイト", cp.get("sites")), ("競合にない強み", cp.get("diff"))])

    print("\n  ※ ここに書かれていないことは書かないこと。"
          "憶測で補うと、事実と違う記事が公開されます。")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("使い方: python scripts/site_brief.py <site_id>\n" + sites_mod.summary())
    cfg = sites_mod.load(sys.argv[1])

    print("=" * 68)
    print(f"■ 対象サイト: {cfg['name']}（{cfg['id']}）")
    print(f"  ドメイン : {cfg['domain']}")
    print(f"  テーマ   : {cfg['theme']}")
    print(f"  読者     : {cfg.get('audience', '（未設定）')}")
    print("=" * 68)

    # 何を売る記事なのかを先に置く。ここが定まらないと、読まれても
    # 「調べて終わり」で帰る読者ばかりになり、記事が売上につながらない
    offer = cfg.get("main_offer")
    if offer:
        print("\n■ このサイトで売るもの（記事はここへ送るために書く）")
        print(f"  → {offer}")
        print("  ※ 主題が主力から離れる記事は、読まれても売上につながりません。")

    print("\n■ 書いてはいけない領域（他サイトの担当。主題にしない）")
    for a in cfg.get("avoid", []):
        print(f"  × {a}")

    print("\n■ 使えるカテゴリ（この中から必ず選ぶ）")
    for slug, name in cfg.get("categories", {}).items():
        print(f"  - {slug:14s} {name}")

    # 狙う配分と現在地。指定が無いと、書きやすい領域に寄って偏る。
    # 実際MEOとAIOがほぼ同数になり、主戦場に置いたはずのAIOが埋もれていた
    mix = {k: v for k, v in (cfg.get("category_mix") or {}).items()
           if not k.startswith("_")}
    if mix:
        import collections
        now = collections.Counter()
        for f in (ROOT / "articles").glob("*.md"):
            m = re.search(r"^category:\s*(.+)$",
                          f.read_text(encoding="utf-8", errors="replace")[:1200], re.M)
            if m and m.group(1).strip() in cfg.get("categories", {}):
                now[m.group(1).strip()] += 1
        total = sum(now.values()) or 1
        print("\n■ カテゴリの配分（狙い / いま）")
        short = []
        for slug in mix:
            pct = now[slug] / total * 100
            diff = mix[slug] - pct
            mark = "  ← 不足" if diff >= 5 else ("  （多い）" if diff <= -5 else "")
            print(f"  {slug:14s} 狙い{mix[slug]:3d}%  いま{pct:5.1f}%（{now[slug]}本）{mark}")
            if diff >= 5:
                short.append((diff, slug))
        if short:
            short.sort(reverse=True)
            print(f"\n  次に書くなら: {short[0][1]}"
                  f"（狙いに対して{short[0][0]:.0f}ポイント不足しています）")

    # カテゴリが1つのサイトは、記事の主題（制度）で配分を見る。
    # 補助金サイトは hojokin 1つしか無く、カテゴリ別では偏りが見えない
    smix = {k: v for k, v in (cfg.get("scheme_mix") or {}).items()
            if not k.startswith("_")}
    if smix:
        import collections
        pats = [("AI導入補助金", r"ai(導入)?補助金|ai-hojokin"),
                ("IT導入補助金", r"it導入補助金|it-hojokin"),
                ("ものづくり", r"ものづくり|monozukuri"),
                ("持続化", r"持続化|jizokuka"),
                ("事業再構築", r"事業再構築|saikouchiku")]
        now = collections.Counter()
        for f in (ROOT / "articles").glob("*.md"):
            raw = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^category:\s*(.+)$", raw[:1200], re.M)
            if not m or m.group(1).strip() not in cfg.get("categories", {}):
                continue
            head = (raw[:800] + f.stem).lower()
            for name, pat in pats:
                if re.search(pat, head):
                    now[name] += 1
                    break
            else:
                now["その他"] += 1
        total = sum(now.values()) or 1
        print("\n■ 制度の配分（狙い / いま）")
        short = []
        for name in smix:
            pct = now[name] / total * 100
            diff = smix[name] - pct
            mark = "  ← 不足" if diff >= 5 else ("  （多い）" if diff <= -5 else "")
            print(f"  {name:14s} 狙い{smix[name]:3d}%  いま{pct:5.1f}%（{now[name]}本）{mark}")
            if diff >= 5:
                short.append((diff, name))
        if short:
            short.sort(reverse=True)
            print(f"\n  次に書くなら: {short[0][1]}"
                  f"（狙いに対して{short[0][0]:.0f}ポイント不足しています）")

    # 内部リンクの方針も設定で1か所に持つ。旧テーマの記事へリンクすると導線が逸れる
    pol = cfg.get("link_policy")
    if pol:
        print("\n■ 内部リンクの方針")
        print(f"  {pol}")

    cta = cfg.get("cta")
    if cta:
        print("\n■ 記事のCTA（この行き先で統一する）")
        print(f"  → {cta.get('label', '')}")
        if cta.get("note"):
            print(f"     {cta['note']}")

    print("\n■ 次に書くKW")
    nxt = hub_client.next_kw(cfg["id"])
    if nxt and nxt.get("keyword"):
        print(f"  → 「{nxt['keyword']}」")
        if nxt.get("aim"):
            print(f"     狙い: {nxt['aim']}")
        print(f"     台帳の残り: {nxt.get('remaining', '?')}件 / "
              f"補充要否: {'必要' if nxt.get('need_replenish') else '不要'}")
        print("  ※ 管制塔の台帳から取得（執筆開始時に「執筆中」へ変わります）")
    else:
        cands = local_next_kw(cfg)
        if not cands:
            print("  候補なし。python scripts/kw_discover.py --append でKWを補充すること")
        else:
            print(f"  → 「{cands[0]['keyword']}」（ローカルのKW計画から）")
            print(f"     狙い: {cands[0]['aim']}")
            for c in cands[1:]:
                print(f"     次点: {c['keyword']}")
        print("  ※ 管制塔が未接続のためローカルのKW計画を使用")

    # 一次情報を毎回目に入れる。ブリーフに出ないと外部統計の引き写しだけになり、
    # どのサイトでも書ける記事＝引用先に選ばれない記事になる
    print("\n■ この記事に入れる一次情報（最低1つ）")
    try:
        import subprocess
        kwtxt = (nxt or {}).get("keyword", "") if isinstance(nxt, dict) else ""
        r = subprocess.run([sys.executable, "scripts/facts.py", cfg["id"], kwtxt],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore")
        for line in r.stdout.splitlines()[1:]:
            print(line)
    except Exception as e:
        print(f"  （一次情報を取得できませんでした: {e}）")

    show_brief(cfg["id"])

    print("\n■ 公開の流れ")
    if cfg["type"] == "self-static":
        print("  articles/<slug>.md に保存 → python scripts/publish_flow.py "
              f"{cfg['id']} <slug>")
    else:
        print(f"  articles/<slug>.md に保存 → python scripts/publish_flow.py {cfg['id']} <slug>")
        print(f"  （{cfg['repo']} の {cfg['branch']} へ配信されます）")
    print()


if __name__ == "__main__":
    main()
