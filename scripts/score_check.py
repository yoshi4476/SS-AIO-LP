# -*- coding: utf-8 -*-
"""Phase 5 機械採点（LLM採点の前に走らせる決定的チェック）

数えられる項目はLLMに採点させず、このスクリプトが白黒つける。
全PASSになってから6エージェントのLLM採点（定性項目）に進むこと。

使い方: python scripts/score_check.py <slug>
終了コード: 0=全PASS / 1=FAILあり
"""
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _link_patterns():
    """全サイト（sites/*.json）のカテゴリ・ドメインから内部リンク判定パターンを組み立てる。

    新しいサイト（例: corporate）の1本目の記事は自サイトに公開済み記事がまだ無いため、
    姉妹サイト（同じ会社の別サイト）への絶対URLリンクも内部リンクとして扱う。
    """
    cats, domains, prefixes = set(), set(), set()
    for cfg in sites_mod.load_all().values():
        cats.update(cfg.get("categories", {}).keys())
        domains.add(cfg["domain"])
        if cfg.get("url_prefix"):
            prefixes.add(cfg["url_prefix"].strip("/"))
    cat_pat = "|".join(re.escape(c) for c in sorted(cats))
    domain_pat = "|".join(re.escape(d) for d in sorted(domains))
    # url_prefix型サイト（corporate/subsidy）の実URLは /blog/{slug}/ のようにカテゴリを含まないため、
    # カテゴリパスとprefixパスの両方を内部リンクとして認識する（前者だけだと自サイトへのリンクが
    # 一切カウントされず、姉妹サイトへのリンクしか通らないという誤検出になる）。
    prefix_pat = "|".join(re.escape(p) for p in sorted(prefixes))
    path_pat = "|".join(p for p in (cat_pat, prefix_pat) if p)
    internal_re = re.compile(
        rf"\]\((?:https?://(?:{domain_pat}))?(/(?:{path_pat})/[^)]+)\)")
    return internal_re, domains


def main():
    slug = sys.argv[1]
    p = ROOT / "articles" / f"{slug}.md"
    if not p.exists():
        raise SystemExit(f"articles/{slug}.md が見つかりません")
    text = p.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        raise SystemExit(f"articles/{slug}.md にフロントマターがありません")
    meta, body = yaml.safe_load(m.group(1)), m.group(2)
    # コードブロック内はH2・文言カウントの対象外（プロンプト例の ## 等を誤検出しない）
    body_nc = re.sub(r"```.*?```", "", body, flags=re.S)

    plain = re.sub(r"\s|<[^>]+>", "", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body))
    checks = []

    def add(name, ok, detail):
        checks.append((name, ok, detail))

    # --- 量・装飾 ---
    add("本文5,000字以上", len(plain) >= 5000, f"{len(plain):,}字")
    markers = len(re.findall(r"\*\*[^*]+\*\*", body)) + len(re.findall(r"==[^=]+==", body))
    add("強調12〜18箇所（最低8）", markers >= 8, f"{markers}箇所" + ("（推奨帯外）" if not 12 <= markers <= 18 else ""))

    # --- AIO構造 ---
    first_para = next((ln for ln in body.splitlines() if ln.strip() and not ln.startswith(("<", "#"))), "")
    add("冒頭が断言型（**で開始・80字以上）", first_para.startswith("**") and len(first_para) >= 80,
        f"{len(first_para)}字")
    add("対象読者の限定文言", 'class="target-reader"' in body, "target-reader div")
    add("鮮度表記（◯年◯月時点）", bool(re.search(r"\d{4}年\d{1,2}月時点", body)), "")
    add("定義ブロック", 'class="definition-box"' in body, "definition-box div")
    add("比較テーブルあり", bool(re.search(r"^\|.+\|\s*$", body, re.M)), "")
    add("失敗例・注意点セクション", bool(re.search(r"caution-box|失敗|NG|注意点", body)), "")

    # --- H2構造 ---
    h2s = re.findall(r"^## (.+)$", body_nc, re.M)
    core_h2 = [h for h in h2s if "よくある質問" not in h and not h.startswith("まとめ")]
    add("H2が6〜12個（FAQ・まとめ除く）", 6 <= len(core_h2) <= 12, f"{len(core_h2)}個")
    bad_lead = []
    lines = body_nc.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("## ") and "よくある質問" not in ln:
            nxt = next((x.strip() for x in lines[i + 1:] if x.strip()), "")
            # 記号+空白のリスト/表のみを検出（**太字**始まりの1文結論を誤検出しない）
            if nxt.startswith(("| ", "|-", "- ", "* ", "<figure", "<div", "```", "#", "1. ")):
                bad_lead.append(ln[3:])
    add("全H2直下がリード文（表・リスト直置きなし）", not bad_lead, "、".join(bad_lead[:3]))

    # --- FAQ ---
    faq = meta.get("faq") or []
    add("FAQ 5問以上", len(faq) >= 5, f"{len(faq)}問")
    bad_a = [f["q"][:12] for f in faq if not 30 <= len(f["a"]) <= 75]
    add("FAQ回答が40〜60字目安（許容30〜75）", not bad_a, "、".join(bad_a[:3]))
    body_faq = body.count("<details>")
    add("本文FAQとfrontmatter数が一致", body_faq == len(faq), f"本文{body_faq} / meta{len(faq)}")

    # --- リンク ---
    internal_re, own_domains = _link_patterns()
    internal = set(internal_re.findall(body))
    add("内部リンク3本以上", len(internal) >= 3, f"{len(internal)}本")
    external = set(re.findall(r'href="(https?://[^"]+)"', body))
    external = {u for u in external if not any(d in u for d in own_domains) and "x.com" not in u}
    add("外部権威リンク（出典）2本以上", len(external) >= 2, f"{len(external)}本")

    # --- 読みやすさ ---
    # CLAUDE.md の「段落3行 or 150字以内」「1文50字以下」は規定だけあって検査がなく、
    # 300字を超える段落がそのまま公開されていた。画面では改行のない壁のような塊に見える。
    paras = [p.strip() for p in re.split(r"\n\s*\n", body_nc)
             if p.strip() and not p.strip().startswith(("#", "-", "*", "|", "<", ">", "```", "1."))]
    # HTMLタグとURLは読者が読む文字ではないので、数える前に落とす。
    # 落とさないと <a href="…長いURL…"> が1文としてカウントされ、誤検出になる
    def _plain(p):
        p = re.sub(r"<[^>]+>", "", p)                       # タグを除去
        p = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", p)      # Markdownリンクは表示文だけ残す
        return re.sub(r"[*_=`]", "", p)

    plain_paras = [_plain(p) for p in paras]
    long_paras = [p for p in plain_paras if len(p) > 180]
    add("段落が180字以内（規定150字＋余裕30字）", not long_paras,
        f"{len(long_paras)}箇所が超過" + (f"（最長{max(len(p) for p in plain_paras)}字）" if plain_paras else ""))

    sentences = [s for p in plain_paras for s in re.split(r"(?<=[。！？])", p) if s.strip()]
    long_sents = [s for s in sentences if len(s.strip()) > 70]
    add("1文が70字以内（規定50字＋余裕20字）", len(long_sents) <= 2,
        f"{len(long_sents)}文が超過" + (f"（最長{max(len(s.strip()) for s in sentences)}字）" if sentences else ""))

    # --- 人間味 ---
    first_person = len(re.findall(r"私たち|私も|私は|私が|当社|弊社", body_nc))
    add("一人称の体験・観察2箇所以上", first_person >= 2, f"{first_person}箇所")
    koreni = body_nc.count("これにより")
    add("「これにより」ゼロ", koreni == 0, f"{koreni}回")
    juyou = body_nc.count("重要です")
    add("「重要です」3回以下", juyou <= 3, f"{juyou}回")

    fails = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} | {name}" + (f" | {detail}" if detail else ""))
    print(f"\n機械採点: {len(checks) - len(fails)}/{len(checks)} PASS"
          + ("" if not fails else " → FAILを修正してからLLM採点に進むこと"))
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
