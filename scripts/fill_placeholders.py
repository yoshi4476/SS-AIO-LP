# -*- coding: utf-8 -*-
"""書き出した一式の `{{ }}` を、サイト設定の値で埋める

export_template.py は自社の値を `{{COMPANY_NAME}}` のような印に置き換えて
渡す。印のままだと、記事のタイトル・構造化データ・レポート・定期実行の
どれもがその文字列を出す。ページには出るので気づけるが、構造化データや
デプロイ先の指定は目に見えないところで壊れる。

sites/<id>.json と data/company_profile.json から埋める。
ビルド時に差し込まれる印（{{TITLE}} など）には触らない。

使い方:
    python scripts/fill_placeholders.py <site_id>          # 何が埋まるか見る
    python scripts/fill_placeholders.py <site_id> --write  # 実際に埋める
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = {".py", ".gs", ".yml", ".yaml", ".json", ".md", ".txt", ".html", ".css",
       ".js", ".example"}
SKIP_DIR = {".git", "__pycache__", "node_modules", "articles", "reports"}
# この道具自身は書き換えない（印の一覧を文字列として持っているため）
SKIP_FILE = {"fill_placeholders.py", "export_template.py"}


def runtime_keys():
    """ビルドが記事ごとに差し込む印。ここを埋めると全記事が同じ内容になる"""
    bp = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    return set(re.findall(r'"\{\{([A-Z_]+)\}\}"\s*:', bp)) | {"NAV", "FOOTER_NAV"}


def short(name):
    """「株式会社○○」から会社の呼び名だけを取り出す"""
    return re.sub(r"(株式会社|有限会社|合同会社|一般社団法人)", "", name or "").strip()


def mapping(cfg, prof, env):
    c = cfg.get("company", {})
    dom = cfg.get("domain", "")
    name = c.get("name") or prof.get("name", "")
    addr = c.get("address") or prof.get("address", "")
    m = {
        "MEDIA_NAME": cfg.get("name", ""),
        "LP_NAME": cfg.get("name", ""),
        "SITE_NAME": cfg.get("name", ""),
        # 3サイト運用が前提の印。1サイトなら全部同じドメインでよい
        "MEDIA_DOMAIN": dom, "DOMAIN": dom, "MAIN_DOMAIN": dom,
        "CORP_DOMAIN": dom, "LP_DOMAIN": dom,
        "COMPANY_NAME": name,
        "COMPANY_SHORT": short(name),
        "COMPANY_EN": short(name),
        "COMPANY_KANA": short(name),
        "COMPANY_SLUG": cfg.get("id", ""),
        "CORPORATE_NUMBER": c.get("corporate_number") or prof.get("corporate_number", ""),
        "REPRESENTATIVE": c.get("representative") or prof.get("ceo", ""),
        "ADDRESS": addr,
        "ADDRESS_SHORT": re.sub(r"^〒[\d-]+\s*", "", addr),
        "CITY": (re.search(r"([^\s〒\d-]+?[市区町村])", addr).group(1)
                 if re.search(r"([^\s〒\d-]+?[市区町村])", addr) else ""),
        "TEL": c.get("tel") or prof.get("tel", ""),
        "FAX": "",
        "NOTIFY_EMAIL": c.get("email") or prof.get("email", ""),
        # 自社にしかないサービス名。無ければ社名で代用する
        "OWN_SERVICE": (cfg.get("facts") or [short(name)])[-1][:20] if cfg.get("facts") else short(name),
        "PAGES_PROJECT": cfg.get("id", ""),
        "HUB_REPO": cfg.get("repo", ""),
        "SITE_REPO_1": cfg.get("repo", ""),
        "SITE_REPO_2": cfg.get("repo", ""),
        "GITHUB_OWNER": (cfg.get("repo", "").split("/")[0] if "/" in cfg.get("repo", "") else ""),
        "SHARED_SECRET": env.get("HUB_SECRET", ""),
        "SERVICE_ACCOUNT": env.get("SERVICE_ACCOUNT", ""),
        "GCP_PROJECT": cfg.get("id", ""),
        "RESEND_UNSUBSCRIBE_URL": ("https://" + dom + "/unsubscribe/") if dom else "",
    }
    return {k: v for k, v in m.items() if v}


def read_env():
    out = {}
    p = ROOT / ".env"
    if p.is_file():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("使い方: python scripts/fill_placeholders.py <site_id> [--write]")
    sid = args[0]
    cf = ROOT / "sites" / (sid + ".json")
    if not cf.is_file():
        raise SystemExit(f"{cf} がありません。先に setup_from_sheet.py を実行してください")
    cfg = json.loads(cf.read_text(encoding="utf-8"))
    pf = ROOT / "data" / "company_profile.json"
    prof = json.loads(pf.read_text(encoding="utf-8")) if pf.is_file() else {}

    keep = runtime_keys()
    table = mapping(cfg, prof, read_env())
    write = "--write" in sys.argv

    hit, left, files = {}, {}, 0
    for f in sorted(ROOT.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in EXT:
            continue
        if f.name in SKIP_FILE or SKIP_DIR & set(f.parts):
            continue
        try:
            t = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found = set(re.findall(r"\{\{([A-Z_]+)\}\}", t))
        if not found - keep:
            continue
        new = t
        for k in found - keep:
            if k in table:
                new = new.replace("{{" + k + "}}", table[k])
                hit[k] = hit.get(k, 0) + 1
            else:
                left.setdefault(k, []).append(str(f.relative_to(ROOT)))
        if new != t:
            files += 1
            if write:
                f.write_text(new, encoding="utf-8", newline="")

    print(f"■ {'埋めました' if write else '埋まる予定'}: {len(hit)}種 / {files}ファイル")
    for k, n in sorted(hit.items(), key=lambda x: -x[1]):
        print(f"   {{{{{k}}}}}".ljust(28) + f"{n:>2}ファイル → {table[k][:44]}")
    if left:
        print(f"\n■ 値が無く、印のまま残るもの: {len(left)}種")
        for k, v in sorted(left.items()):
            print(f"   {{{{{k}}}}}".ljust(28) + ", ".join(v[:3]))
        print("\n  sites/<id>.json の repo などを埋めてから、もう一度実行してください")
    if not write:
        print("\n  確認のみ（--write を付けると書き換えます）")


if __name__ == "__main__":
    main()
