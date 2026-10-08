# -*- coding: utf-8 -*-
"""雛形・サイト設定が変わった社だけ、公開済みの記事を全部描き直す（publish_rerender.py を呼ぶ）。

**なぜ要るか**: 描き直しの道具（publish_rerender.py）はあったが、どの工程からも呼ばれていなかった。
CTA の文言・雛形・会社の表記を変えても、publish_changed は「原稿が変わった記事」しか配信しないので、
既存の記事は古い描き方のまま何か月も残り、変えた効果も測れない。

社ごとに「描き方を決める材料」の指紋を取り、前の回と違う社だけ描き直す。材料:
  - sites/<id>.json（CTA・導線・言語・接頭辞など。KW の種のように描き方に関係しない項目は除く）
  - data/clients/<id>/company.json・template.html（著者・監修の表示、FTP の社の見た目）
  - templates/ のうち、その方式が使う雛形（FTP の社の汎用の雛形、Next.js のまとめのページ）
  - Git の社の配信先リポジトリにある雛形（cfg["template"]。site_change で先方の見た目を変えた回）

初めて見る社は指紋を記録するだけ（描き直さない）。描き直しが失敗した社は指紋を進めず、次の回にやり直す。

  python scripts/rerender_watch.py            # どの社が変わったかを見るだけ
  python scripts/rerender_watch.py --push     # 変わった社を描き直して配信し、指紋を記録する（週次）
  python scripts/rerender_watch.py --push --site <id> --force   # 指紋に関係なく1社を描き直す

終了コードは検査が動けば0（RERENDER_OK=yes/no と明細で知らせる）。
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STATE = ROOT / "data" / "rerender_state.json"
# 描き直しの対象。self-static は build.py が毎回全部描く。external-md は先方のビルドが描く。zip は新規受付なし
TYPES = ("external-html", "nextjs-json", "ftp", "wordpress")
# サイト設定のうち、記事の描き方に関係しない項目（変えても描き直さない）。
# lead_hub は問い合わせの突き合わせ（lead_reconcile・data_sanity）だけが読む。入っていなかったため、
# 補助金の lead_hub を false→true にしただけで全記事を描き直すところだった（2026-10-08）
IGNORE_KEYS = {"_path", "kw_seeds", "kw_plan", "drop_kw", "_drop_kw_note", "compete", "audience", "avoid", "owns",
               "priority", "category_mix", "scheme_mix", "x_tags", "youtube", "social", "note", "notes",
               "ga4_property_id", "facts_allow", "ng_terms", "lead_hub", "_comment_lead_hub", "aggregate_skip_note"}


def _h(b: bytes):
    return hashlib.sha1(b).hexdigest()[:12]


def inputs(cfg, dest=None):
    """描き方を決める材料 {名前: 指紋}。dest は Git の社の配信先リポジトリ（あれば雛形も見る）"""
    sid, t = cfg["id"], cfg.get("type")
    conf = {k: v for k, v in cfg.items() if k not in IGNORE_KEYS}
    out = {"sites": _h(json.dumps(conf, ensure_ascii=False, sort_keys=True).encode("utf-8"))}
    cdir = ROOT / "data" / "clients" / sid
    for name in ("company.json", "template.html"):
        if (cdir / name).is_file():
            out[f"clients/{name}"] = _h((cdir / name).read_bytes())
    tpls = []
    if t == "ftp" and not (cdir / "template.html").is_file():
        tpls.append(ROOT / "templates" / "external_article.html")
    if t == "nextjs-json":
        tpls += sorted((ROOT / "templates").glob("nextjs_*"))
    for p in tpls:
        if p.is_file():
            out[f"templates/{p.name}"] = _h(p.read_bytes())
    if t == "external-html" and dest is not None and cfg.get("template"):
        p = Path(dest) / cfg["template"]
        if p.is_file():
            out["dest/template"] = _h(p.read_bytes())
    return out


def fingerprint(parts):
    return _h(json.dumps(parts, sort_keys=True).encode("utf-8"))


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8")) if STATE.is_file() else {}
    except ValueError:
        return {}


def save_state(st):
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def judge(prev, parts):
    """(描き直すか, 理由)。初めて見る社は記録だけ"""
    if not prev:
        return False, "初めて見る社（指紋を記録するだけ）"
    if prev.get("fp") == fingerprint(parts):
        return False, "変わっていない"
    was = prev.get("parts") or {}
    diff = sorted(k for k in set(was) | set(parts) if was.get(k) != parts.get(k))
    return True, "変わった材料: " + "・".join(diff)


def rerender(sid):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "publish_rerender.py"), "--site", sid, "--push"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    for line in tail[-6:]:
        print(f"     {line}")
    return r.returncode == 0


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="変わった社を描き直して配信し、指紋を記録する")
    ap.add_argument("--site", default="")
    ap.add_argument("--force", action="store_true", help="指紋に関係なく描き直す（--site と使う）")
    a = ap.parse_args()
    st = load_state()
    targets = {sid: c for sid, c in S.load_all().items()
               if c.get("type") in TYPES and sid != "sample" and (not a.site or sid == a.site)}
    if not targets:
        print("RERENDER_OK=unset（描き直しの対象の方式の社がありません）")
        return 0
    bad = []
    for sid, cfg in targets.items():
        dest = None
        if cfg.get("type") == "external-html" and a.push:
            try:
                import publish
                dest = publish.ensure_clone(cfg, publish._push_token())
            except (SystemExit, Exception) as e:
                bad.append(f"要対応: {cfg.get('name', sid)} の配信先を取れません（{str(e)[:60]}）")
                continue
        elif cfg.get("type") == "external-html":
            p = ROOT / ".publish-work" / sid
            dest = p if p.is_dir() else None
        parts = inputs(cfg, dest)
        go, why = judge(st.get(sid), parts)
        if a.force:
            go, why = True, "--force"
        print(f"■ {sid}（{cfg['type']}）: {'描き直す' if go else '描き直さない'} … {why}")
        if not a.push:
            continue
        if go and not rerender(sid):
            bad.append(f"要対応: {cfg.get('name', sid)} の描き直しに失敗しました（次の週次でやり直します）")
            continue
        st[sid] = {"fp": fingerprint(parts), "parts": parts,
                   "at": date.today().isoformat() if go or sid not in st else st[sid].get("at", "")}
    if a.push:
        save_state(st)
    for b in bad:
        print(b)
    print("RERENDER_OK=" + ("no" if bad else "yes"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
