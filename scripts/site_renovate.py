# -*- coding: utf-8 -*-
"""指示の一文で、お客様のサイト（Git・FTP・WordPress）を改修する入口。

site_change.py は「取る・差分・反映・戻す」を持つが、作業場所のファイルは人が直す前提だった。
WordPress や FTP の社でも記事だけでなくサイトの改修まで管制塔から行うため（運用者の依頼 2026-10-07）、
直す役を Claude に任せ、**通してよいかは機械が決める**（auto_rewrite と同じ考え方）。

  python scripts/site_change.py   --site <id> --ask "<指示>"          # 下と同じ（入口を1つにするための別名）
  python scripts/site_renovate.py --site <id> --ask "<指示>"          # 取る→直す→検査→写真→止まる
  python scripts/site_renovate.py --site <id> --ask "<指示>" --yes    # 検査が通れば反映→確認→だめなら自動で戻す
  python scripts/site_renovate.py --site <id> --apply                 # 止めておいた変更を、写真を見た後に反映する
  python scripts/site_renovate.py --site <id> --discard               # 止めておいた変更を捨てる
  python scripts/site_renovate.py --report                            # 直近7日の戻し・確かめられなかった回（RENOVATE_OK=）

流れ: 取る（site_change の --pull と同じ）→ Claude が作業場所の中だけを直す（道具は読み書きと検索だけ）
→ 差分 → 検査 → 画面の写真（変更前後）→ 確認 → 反映 → 反映後の確認（トップと変えたページが200・
ナビ・フッター・問い合わせの導線が残る）→ 外れたら自動で戻す → 台帳（automation/logs/renovate.jsonl）。

**検査（1つでも外れたら反映しない）**: タグの開閉・JSON-LD が読める・内部リンクが切れない（作業場所の中で
解決できるもの）・速度の方針（日本語Webフォント・先に読む計測タグを足さない）・表現（legal_claims があれば）・
許可していない script（外のドメイン・インライン・on* 属性・javascript:）・鍵や個人情報らしき文字列・
サーバーの設定ファイル・変えたファイルの数（既定20）と削った量（全体の5%・1ファイルの4割）。

**自動で反映してよいのは小さな直しだけ**: sites/<id>.json の "renovate_auto" に "css"（CSS だけ）・
"text"（タグの並びが同じで文言だけ）を書いた社のうち、その種類だけの変更（5ファイルまで）。既定は無効。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import site_change as SC  # noqa: E402

LOG = ROOT / "automation" / "logs" / "renovate.jsonl"
MAX_FILES = 20
MAX_REMOVED = 0.05          # 削った量は作業場所の全体の5%まで
MIN_REMOVED_BYTES = 2000
MAX_SHRINK = 0.4           # 1ファイルの中身が4割以上減る直しは通さない（2KB 以上のファイル）
AUTO_MAX_FILES = 5
TEXT_EXT = (".html", ".htm", ".php", ".css", ".js", ".mjs", ".json", ".txt", ".xml", ".md", ".mdx", ".svg",
            ".ts", ".tsx", ".jsx", ".yml", ".yaml", ".toml", ".astro", ".vue", ".njk", ".liquid")
HTML_EXT = (".html", ".htm")
# サーバーの設定・鍵。壊すとサイト全体が止まるか、鍵が漏れる。指示があっても自動の改修では触らない
NEVER_TOUCH = (".htaccess", ".htpasswd", "wp-config.php", ".user.ini", "php.ini", ".env", "web.config", "_headers")
# script src を許すドメイン（橋渡しのプラグインの SSB_SCRIPT_HOSTS と同じ。門がそろっているかを見る）
SCRIPT_HOSTS = ("challenges.cloudflare.com", "www.google.com", "www.gstatic.com", "static.cloudflareinsights.com")
# WordPress の head・フッターの追記（design/head.json・footer.json）の項目。プラグインの定数と同じ
ITEM_KEYS = ("t", "a", "json", "src", "async", "defer")
LINK_ATTRS = ("rel", "href", "as", "type", "crossorigin", "media", "sizes", "hreflang", "title")
LINK_RELS = ("canonical", "alternate", "preconnect", "dns-prefetch", "preload", "icon", "apple-touch-icon",
             "manifest", "author", "me", "license")
META_ATTRS = ("name", "property", "content")
CSS_BAD = re.compile(r"</style|<script|<!--|expression\s*\(|javascript:|fonts\.googleapis\.com", re.I)

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr",
        "command", "keygen"}
# 閉じタグを省いてよい要素（数えると、元から省いているサイトで毎回外れる）
OPTIONAL_END = {"p", "li", "dt", "dd", "tr", "td", "th", "thead", "tbody", "tfoot", "option", "optgroup", "colgroup",
                "rt", "rp", "html", "head", "body", "caption"}
SECRET = re.compile(r"sk-[A-Za-z0-9_-]{20,}|sk_live_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|"
                    r"github_pat_[A-Za-z0-9_]{30,}|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35}|"
                    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
                    r"(?i:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\d-])0\d{1,4}-\d{1,4}-\d{3,4}(?![\d-])|(?<!\d)0[789]0\d{8}(?!\d)")
PHP_BAD = re.compile(r"\b(?:eval|assert|system|exec|shell_exec|passthru|popen|proc_open|create_function)\s*\(|"
                     r"base64_decode\s*\(|\$_(?:GET|POST|REQUEST|COOKIE)\s*\[")
LD = re.compile(r"<script\b[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I)
SCRIPT_TAG = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S | re.I)
SRC = re.compile(r"\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
HREF = re.compile(r"\b(?:href|src)\s*=\s*[\"']([^\"'#][^\"']*)[\"']", re.I)
ON_ATTR = re.compile(r"<[a-zA-Z][^>]*\son[a-z]+\s*=", re.I)
FONTS = re.compile(r"fonts\.googleapis\.com|fonts\.gstatic\.com", re.I)

MARKERS = {
    "ナビ": re.compile(r"<nav\b|role=[\"']navigation[\"']", re.I),
    "フッター": re.compile(r"<footer\b|role=[\"']contentinfo[\"']", re.I),
    "問い合わせの導線": re.compile(r"href=[\"'](?:tel:|mailto:|[^\"']*(?:contact|inquiry|toiawase|otoiawase|/lp/|form|"
                                   r"reserve|yoyaku|soudan|consult))", re.I),
}


# ---------------------------------------------------------------- 方式ごとの作業場所

def is_git(cfg):
    return cfg["type"] in SC.GIT_TYPES


def workdir(cfg):
    return SC.WORK / cfg["id"] if is_git(cfg) else SC.mirror(cfg)


def base_rev(cfg):
    """取った時点。Git の社は配信先の HEAD、それ以外は site_change の remote の印"""
    return "HEAD" if is_git(cfg) else "remote"


def wgit(w: Path, *a, check=True):
    """作業場所の git。site_change.mgit と同じく、必ずその場所の .git を名指しする（親の管制塔へさかのぼらない）"""
    return SC.mgit(w, *a, check=check)


def preview_dir(cfg):
    d = SC.mirror(cfg) / "_preview"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_path(cfg):
    return SC.WORK / f"{cfg['id']}-renovate.json"


def pull(cfg):
    if is_git(cfg):
        import publish
        publish.ensure_clone(cfg, publish._push_token())
        return "配信先リポジトリを取りました"
    if cfg["type"] == "ftp":
        return SC.ftp_pull(cfg)
    if cfg["type"] == "wordpress":
        return SC.wp_pull(cfg)
    raise SystemExit("この方式は先方のサーバーを取れないため、指示での改修はできません（ftp か Git の方式へ切り替えてください）")


def pending(cfg):
    """取った時点から今の作業場所までの変化: [(A/M/D, 相対パス)]"""
    w = workdir(cfg)
    if not (w / ".git").exists():
        return []
    if is_git(cfg):
        wgit(w, "add", "-A")
        out = wgit(w, "diff", "--cached", "--name-status", "--no-renames", "HEAD")
        return [tuple(l.split("\t", 1)) for l in out.splitlines() if "\t" in l]
    return SC.changes(w)


def before_bytes(cfg, f):
    w = workdir(cfg)
    r = subprocess.run(["git", f"--git-dir={w / '.git'}", "show", f"{base_rev(cfg)}:{f}"], cwd=w, capture_output=True)
    return r.stdout if r.returncode == 0 else b""


def apply(cfg, ch):
    if is_git(cfg):
        return SC.git_push(cfg)
    return SC.push_mirror(cfg, ch)


def rollback(cfg):
    """直前の反映の前へ戻す（site_change --rollback と同じ動き）"""
    if is_git(cfg):
        SC.git(*SC.BOT, "revert", "--no-edit", "HEAD", cwd=workdir(cfg))
        return SC.git_push(cfg, committed=True)
    SC.restore(cfg, "remote~1")
    return SC.push_mirror(cfg, SC.changes(SC.mirror(cfg)))


def discard(cfg):
    """反映しない変更を捨て、作業場所を取った時点に戻す（写真の _preview/ は残る）"""
    w = workdir(cfg)
    if (w / ".git").exists():
        wgit(w, "reset", "-q", "--hard", base_rev(cfg))
        wgit(w, "clean", "-fdq")
    state_path(cfg).unlink(missing_ok=True)


# ---------------------------------------------------------------- Claude に直させる

PROMPT = """あなたは Web サイトの改修担当です。いまの作業フォルダは「{name}」のサイトの写しです（{kind}）。
次の指示どおりに、このフォルダの中のファイルを直してください。

指示: {ask}

守ること:
- 直してよいのはこのフォルダの中のファイルだけ。.git と _preview には触れない
- 指示に関係しないページ・ファイルは変えない。変えるファイルは少なく（{max_files} まで）。大きく消さない
- 文言を足すときは、このサイトに既に書いてある事実だけを使う。数字・実績・料金・お客様の声を新しく作らない
- 運用会社（当社）の採択率・支援社数、申請書類の作成代行を書かない
- 日本語の Web フォント（Google Fonts）と、計測タグの同期読み込みを足さない
- <script> は足さない（構造化データの application/ld+json だけは可）。on〜 属性・javascript: も使わない
- ナビ・フッター・問い合わせの導線を消さない。リンク先は、このフォルダに実在するページにする
- 鍵・パスワード・個人のメールアドレスや電話番号を書かない
{type_note}
終わったら、何をどう変えたかを3行以内で書いて終了してください。直す必要が無ければ何も変えずに終了してください。"""

TYPE_NOTE = {
    "ftp": "- サーバーのファイルの写しです。HTML・CSS を直してください（WordPress 本体・アップロード画像は入っていません）",
    "wordpress": ("- WordPress の中身を JSON に取ったものです。固定ページ・テンプレート等は <資源>/<id>.json の content"
                  "（ブロックの HTML）を直します。新しい固定ページは pages/new-<名前>.json で作れます\n"
                  "- 追加CSSは design/custom.css、head とフッターの追記は design/head.json・footer.json です。項目は"
                  " {{\"t\":\"link\",\"a\":{{…}}}} / {{\"t\":\"meta\",\"a\":{{…}}}} / {{\"t\":\"ld\",\"json\":{{…}}}} の形だけ使えます"
                  "（design/ が無いサイトでは使えません）\n"
                  "- theme/ はテーマの PHP（ある社だけ）。PHP の処理は変えず、表示の HTML だけを直してください"),
    "git": "- 配信先リポジトリです。雛形・CSS・固定ページを直してください。記事の原稿（管制塔が配信するもの）は触らない",
}


def perm_settings():
    # 書けるのは作業フォルダ（cwd）の中だけ。Bash・外部通信は渡さない。.git と写真は読み書きさせない
    return json.dumps({"permissions": {
        "allow": ["Read", "Glob", "Grep", "Edit(./**)", "Write(./**)"],
        "deny": ["Read(./.git/**)", "Edit(./.git/**)", "Write(./.git/**)", "Edit(./_preview/**)", "Write(./_preview/**)"],
        "defaultMode": "acceptEdits",
    }}, ensure_ascii=False)


def ask_claude(cfg, w: Path, ask):
    """claude -p に作業場所を直させる。呼び方は auto_rewrite と同じ（プロンプトは stdin・モデルは版で選ぶ）"""
    import shutil
    import auto_rewrite as AR
    if not (shutil.which("claude") or shutil.which("claude.cmd")):
        raise SystemExit("claude が見つかりません（npm install -g @anthropic-ai/claude-code）")
    kind = "git" if is_git(cfg) else cfg["type"]
    prompt = PROMPT.format(name=cfg.get("name", cfg["id"]), kind={"git": "配信先リポジトリ", "ftp": "サーバーのファイル",
                                                                  "wordpress": "WordPress の中身"}[kind],
                           ask=ask, max_files=max_files(cfg), type_note=TYPE_NOTE[kind]
                           + ("\n- 次のページには触れない（お客様の指定）: " + "・".join(cfg["renovate_protect"])
                              if cfg.get("renovate_protect") else ""))
    r = AR.sh([AR.claude_bin(), "-p", "--max-turns", "60", *AR.model_args(),
               "--allowedTools", "Read,Edit,Write,Glob,Grep", "--settings", perm_settings()],
              timeout=3600, stdin_text=prompt, cwd=w)
    return (r.stdout or r.stderr or "").strip()[-600:]


def tower_status():
    """管制塔の作業ツリーの状態。Claude の前後で変われば、作業場所の外を触った疑い"""
    r = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=all"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return set(r.stdout.splitlines())


# ---------------------------------------------------------------- 検査

class _Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bal = Counter()
        self.sig = []

    def handle_starttag(self, tag, attrs):
        self.sig.append((tag, tuple(sorted((k, v or "") for k, v in attrs))))
        if tag not in VOID:
            self.bal[tag] += 1

    def handle_startendtag(self, tag, attrs):
        self.sig.append((tag, tuple(sorted((k, v or "") for k, v in attrs))))

    def handle_endtag(self, tag):
        self.sig.append(("/" + tag, ()))
        if tag not in VOID:
            self.bal[tag] -= 1


def _parse(html):
    p = _Tags()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return p


def imbalance(html):
    """閉じ忘れ・閉じすぎのタグ（閉じタグを省いてよい要素は数えない）"""
    return {k: v for k, v in _parse(html).bal.items() if v and k not in OPTIONAL_END}


def tag_signature(html):
    return _parse(html).sig


def broken_ld(html):
    n = 0
    for body in LD.findall(html):
        try:
            json.loads(body)
        except ValueError:
            n += 1
    return n


def script_srcs(html):
    return [s for attrs, _ in SCRIPT_TAG.findall(html) for s in SRC.findall(attrs)]


def inline_scripts(html):
    """中身のある script（構造化データ以外）"""
    return sum(1 for attrs, body in SCRIPT_TAG.findall(html)
               if body.strip() and "application/ld+json" not in attrs.lower() and not SRC.search(attrs))


def host_ok(cfg, url):
    """script src の読み込み先が許可の内か（同じサイト・SCRIPT_HOSTS・sites/<id>.json の renovate_script_hosts）"""
    u = url.strip()
    if u.startswith("//"):
        u = "https:" + u
    if not re.match(r"^[a-z][a-z0-9+.-]*:", u, re.I):
        return True                     # 相対パス・/ で始まるパスは同じサイト
    if not u.lower().startswith("https://"):
        return False
    host = (urlsplit(u).hostname or "").lower()
    own = (cfg.get("domain") or "").lower()
    return host in SCRIPT_HOSTS or host in [h.lower() for h in cfg.get("renovate_script_hosts") or []] \
        or (own and (host == own or host.endswith("." + own)))


def design_problems(items):
    """WordPress の head・フッターの追記（design/*.json）を、プラグインと同じ決まりで検める"""
    if not isinstance(items, list):
        return ["項目の一覧（配列）ではありません"]
    bad = []
    for i, it in enumerate(items):
        why = ""
        if not isinstance(it, dict) or set(it) - set(ITEM_KEYS):
            why = "知らないキーがあります"
        elif it.get("t") in ("link", "meta"):
            a = it.get("a")
            allow = LINK_ATTRS if it["t"] == "link" else META_ATTRS
            if not isinstance(a, dict) or not a or any(k not in allow or not isinstance(v, str) for k, v in a.items()):
                why = f"{it['t']} に使えない属性があります"
            elif it["t"] == "link" and (str(a.get("rel", "")).lower() not in LINK_RELS
                                        or not re.match(r"^(?:/(?![/\\])|https://)", a.get("href", ""))
                                        or FONTS.search(a.get("href", ""))):
                why = "link の rel・href が許可の外です"
            elif it["t"] == "meta" and ("content" not in a or not ({"name", "property"} & set(a))):
                why = "meta は name か property と content が要ります"
        elif it.get("t") == "ld":
            if not isinstance(it.get("json"), (dict, list)) or not it.get("json"):
                why = "ld の json がオブジェクトではありません"
        elif it.get("t") == "script":
            src = it.get("src") or ""
            if not src.startswith("https://") or (urlsplit(src).hostname or "").lower() not in SCRIPT_HOSTS:
                why = "script の読み込み先が許可したドメインではありません"
        else:
            why = "使えない種類です（link・meta・ld・script だけ）"
        if why:
            bad.append(f"{i}番目: {why}")
    return bad


def _texts_of(f, raw):
    """検査にかける文字列。WordPress の JSON は中の文字列（content など）を並べる"""
    t = raw.decode("utf-8", errors="replace")
    if f.endswith(".json"):
        try:
            v = json.loads(t or "null")
        except ValueError:
            return t
        out = []

        def walk(x):
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict):
                for y in x.values():
                    walk(y)
            elif isinstance(x, list):
                for y in x:
                    walk(y)
        walk(v)
        return "\n".join(out)
    return t


def static_root(cfg, w: Path):
    """作業場所のうち、そのまま配信される静的なファイルの根（リンクを解決し、手元で写真を撮れる場所）。
    WordPress を FTP で置いている社（index.php がある）や、ビルドで作る Git の社は None"""
    if cfg["type"] == "wordpress":
        return None
    cands = [w] if cfg["type"] == "ftp" else [w / c for c in (cfg.get("static_dir"), "public", "site", "dist", "out", "docs", ".") if c]
    for c in cands:
        if (c / "index.html").is_file() and not (c / "index.php").is_file() and not (c / "wp-config.php").is_file():
            return c
    return None


def _resolves(root: Path, page: Path, url, cfg):
    u = url.strip()
    if re.match(r"^(?:mailto:|tel:|javascript:|data:|#)", u, re.I):
        return True
    sp = urlsplit(u)
    own = (cfg.get("domain") or "").lower()
    if sp.scheme in ("http", "https") or u.startswith("//"):
        if (sp.hostname or "").lower() not in (own, "www." + own) or not own:
            return True          # 外のサイトは手元では確かめない
    path = unquote(sp.path)
    if not path:
        return True
    target = (root / path.lstrip("/")) if path.startswith("/") else (page.parent / path)
    for c in (target, target / "index.html", target.with_name(target.name + ".html")):
        try:
            if c.resolve().is_file() and c.resolve().is_relative_to(root.resolve()):
                return True
        except (OSError, ValueError):
            pass
    return False


def protected(cfg, f, data=b""):
    """作業場所のファイル f が、お客様が「触ってはいけない」としたページ（sites/<id>.json の renovate_protect）か。
    当たれば指定のパスを返す。静的なファイルはパス（/recruit/ → recruit/index.html・pages/recruit.astro）で、
    WordPress の JSON は中の link・slug で見る"""
    path = "/" + f.rsplit(".", 1)[0] + "/"
    link = ""
    if f.endswith(".json") and data:
        try:
            d = json.loads(data.decode("utf-8"))
            if isinstance(d, dict):
                link = urlsplit(str(d.get("link") or "")).path or ("/" + str(d.get("slug") or "") + "/")
        except ValueError:
            pass
    for p in cfg.get("renovate_protect") or []:
        seg = "/" + str(p).strip("/") + "/"
        if seg != "//" and (seg in path or (link and seg in (link if link.endswith("/") else link + "/"))):
            return p
    return ""


def max_files(cfg):
    return int(cfg.get("renovate_max_files") or MAX_FILES)


def legal():
    """別の担当が作る表現の検出器（当社の採択率・支援社数・作成代行）。無ければ None（報告に書く）"""
    try:
        import legal_claims
        return legal_claims
    except ImportError:
        return None


def inspect_changes(cfg, ch, ask=""):
    """(外れた理由, 添える注記, 変更の種類 {css, text, other})。外れた理由が1つでもあれば反映しない"""
    import speed_fix
    w = workdir(cfg)
    ng, notes, kinds = [], [], set()
    if len(ch) > max_files(cfg):
        ng.append(f"変えたファイルが多すぎます（{len(ch)} > {max_files(cfg)}）")
    root = static_root(cfg, w)
    LC = legal()
    if LC is None:
        notes.append("表現の検査（legal_claims.py）がまだ無いため飛ばしました")
    # 既にサイトに載っているメール・電話（会社の窓口）は新しい個人情報に数えない
    known = set(EMAIL.findall(ask)) | set(PHONE.findall(ask))
    for p in [ROOT / "sites" / f"{cfg['id']}.json", ROOT / "data" / "clients" / cfg["id"] / "company.json"]:
        if p.is_file():
            t = p.read_text(encoding="utf-8", errors="replace")
            known |= set(EMAIL.findall(t)) | set(PHONE.findall(t))
    changed = {f for _, f in ch}
    for p in w.rglob("*"):
        rel = p.relative_to(w).as_posix()
        if p.is_file() and p.suffix in HTML_EXT + (".json",) and rel not in changed and not rel.startswith((".git/", "_preview/")):
            t = p.read_text(encoding="utf-8", errors="replace")
            known |= set(EMAIL.findall(t)) | set(PHONE.findall(t))

    removed = 0
    total = sum(int(l.split()[3]) for l in wgit(w, "ls-tree", "-r", "-l", base_rev(cfg)).splitlines()
                if len(l.split()) > 3 and l.split()[3].isdigit()) or 1
    for st, f in ch:
        name = f.rsplit("/", 1)[-1]
        if name in NEVER_TOUCH:
            ng.append(f"{f}: サーバーの設定・鍵のファイルは自動の改修で触りません")
            continue
        if cfg["type"] == "ftp" and any(f == s or f.startswith(s + "/") for s in SC.FTP_SKIP):
            ng.append(f"{f}: WordPress 本体・アップロード画像は触りません")
            continue
        before = before_bytes(cfg, f) if st != "A" else b""
        hit = protected(cfg, f, before or ((w / f).read_bytes() if st != "D" else b""))
        if hit:
            ng.append(f"{f}: 触ってはいけないページ（{hit}。ヒアリングシートの指定・renovate_protect）です")
            continue
        after = (w / f).read_bytes() if st != "D" else b""
        ext = Path(f).suffix.lower()
        if st == "D":
            removed += len(before)
        elif ext == ".json":
            # JSON は整形の違い（字下げ）で大きさが変わる。中の文字の量で比べる
            removed += max(0, len(_texts_of(f, before).encode("utf-8")) - len(_texts_of(f, after).encode("utf-8")))
        else:
            removed += max(0, len(before) - len(after))
        if ext not in TEXT_EXT:
            kinds.add("other")
            if len(after) > SC.FTP_MAX:
                ng.append(f"{f}: {SC.FTP_MAX // 1024 // 1024}MB を超えるファイルは置きません")
            continue
        if st == "M" and len(before) >= 2000 and len(after) < len(before) * (1 - MAX_SHRINK):
            ng.append(f"{f}: 中身が {round(100 - 100 * len(after) / len(before))}% 減っています（大きく消す直しは通しません）")
        if st == "D":
            if root and ext in HTML_EXT + (".css", ".js", ".png", ".jpg", ".jpeg", ".webp", ".svg"):
                url = "/" + (Path(f).relative_to(root.relative_to(w)).as_posix() if root != w else f)
                url = url[:-len("index.html")] if url.endswith("/index.html") else url
                users = [p.relative_to(w).as_posix() for p in root.rglob("*.html")
                         if url in p.read_text(encoding="utf-8", errors="replace")]
                if users:
                    ng.append(f"{f}: 消したファイルへのリンクが残っています（{', '.join(users[:3])}）")
            kinds.add("other")
            continue
        bt, at = _texts_of(f, before), _texts_of(f, after)
        if ext == ".json":
            try:
                json.loads(after.decode("utf-8") or "null")
            except ValueError:
                ng.append(f"{f}: JSON として読めません")
                continue
            if f.startswith(SC.DESIGN_DIR + "/") and f.endswith(".json") and cfg["type"] == "wordpress":
                ng += [f"{f}: {x}" for x in design_problems(json.loads(after.decode("utf-8") or "[]"))]
        html_like = ext in HTML_EXT or (cfg["type"] == "wordpress" and ext == ".json")
        if html_like:
            ib, ia = imbalance(bt), imbalance(at)
            if ia != ib:
                diff = {k: ia.get(k, 0) - ib.get(k, 0) for k in set(ia) | set(ib) if ia.get(k, 0) != ib.get(k, 0)}
                ng.append(f"{f}: タグの開閉が崩れています（{', '.join(f'{k} {v:+d}' for k, v in sorted(diff.items()))}）")
        if broken_ld(at) > broken_ld(bt):
            ng.append(f"{f}: 構造化データ（JSON-LD）が JSON として読めません")
        new_src = [s for s in script_srcs(at) if s not in script_srcs(bt) and not host_ok(cfg, s)]
        if new_src:
            ng.append(f"{f}: 許可していないドメインの script を足しています（{new_src[0][:80]}）")
        if inline_scripts(at) > inline_scripts(bt):
            ng.append(f"{f}: インラインの script を足しています（中身を検められないので通しません）")
        if len(ON_ATTR.findall(at)) > len(ON_ATTR.findall(bt)) or at.lower().count("javascript:") > bt.lower().count("javascript:"):
            ng.append(f"{f}: on〜 属性か javascript: を足しています")
        if ext == ".php" and len(PHP_BAD.findall(at)) > len(PHP_BAD.findall(bt)):
            ng.append(f"{f}: 危険な PHP の関数・入力の直接読みを足しています")
        if ext == ".css" or f == f"{SC.DESIGN_DIR}/custom.css":
            if len(CSS_BAD.findall(at)) > len(CSS_BAD.findall(bt)):
                ng.append(f"{f}: CSS に使えない記述（</style>・<script>・expression・javascript:・Google Fonts）を足しています")
        if len(FONTS.findall(at)) > len(FONTS.findall(bt)):
            ng.append(f"{f}: Google Fonts を足しています（速度の方針: 日本語Webフォントは使わない）")
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "b").mkdir()
            (Path(td) / "a").mkdir()
            (Path(td) / "b" / "x.html").write_text(bt, encoding="utf-8")
            (Path(td) / "a" / "x.html").write_text(at, encoding="utf-8")
            lb = Counter(k for _, k in speed_fix.leftovers(Path(td) / "b"))
            la = Counter(k for _, k in speed_fix.leftovers(Path(td) / "a"))
        worse = [k for k in la if la[k] > lb.get(k, 0)]
        if worse:
            ng.append(f"{f}: 速度の方針に反します（{', '.join(worse)}）")
        if len(SECRET.findall(at)) > len(SECRET.findall(bt)):
            ng.append(f"{f}: 鍵・パスワードらしき文字列を入れています")
        pii = sorted({x for x in EMAIL.findall(at) + PHONE.findall(at)
                      if x not in bt and x not in known})
        if pii:
            ng.append(f"{f}: サイトに無かったメールアドレス・電話番号を入れています（{len(pii)}件）")
        if LC is not None:
            hb = {s for _, s in LC.find(bt)}
            hits = [(k, s) for k, s in LC.find(at) if s not in hb]
            if hits:
                ng.append(f"{f}: 載せない表現があります（{hits[0][0]}: {hits[0][1][:40]}）")
        if root and ext in HTML_EXT and (w / f).resolve().is_relative_to(root.resolve()):
            new_links = set(HREF.findall(at)) - set(HREF.findall(bt))
            dead = sorted(u for u in new_links if not _resolves(root, w / f, u, cfg))
            if dead:
                ng.append(f"{f}: 作業場所に無いページへのリンクがあります（{', '.join(dead[:3])}）")
        elif ext in HTML_EXT or cfg["type"] == "wordpress":
            notes.append(f"{f}: 内部リンクは作業場所で解決できないため、反映後の確認で見ます")
        # 変更の種類（自動で反映してよいかの判断に使う）
        if ext == ".css" or f == f"{SC.DESIGN_DIR}/custom.css":
            kinds.add("css")
        elif st == "M" and html_like and _same_structure(f, before, after):
            kinds.add("text")
        else:
            kinds.add("other")
    # 小さなサイトでは数百字の削除でも5%を超える。2KB 未満の削除は量では止めない（1ファイルの4割の決まりは別に効く）
    if removed > MIN_REMOVED_BYTES and removed / total > MAX_REMOVED:
        ng.append(f"削った量が作業場所の全体の {removed / total:.0%} です（{MAX_REMOVED:.0%} まで）")
    return ng, sorted(set(notes)), kinds


def _same_structure(f, before, after):
    """タグの並び（属性まで）が同じで、文字だけが変わったか。WordPress の JSON は content 以外の項目も同じか"""
    if f.endswith(".json"):
        try:
            b, a = json.loads(before.decode("utf-8")), json.loads(after.decode("utf-8"))
        except ValueError:
            return False
        if not (isinstance(a, dict) and isinstance(b, dict)) or set(a) != set(b):
            return False
        if any(a[k] != b[k] for k in a if k not in ("content", "title", "excerpt")):
            return False
        return all(tag_signature(str(a.get(k) or "")) == tag_signature(str(b.get(k) or "")) for k in ("content", "title", "excerpt"))
    return tag_signature(before.decode("utf-8", errors="replace")) == tag_signature(after.decode("utf-8", errors="replace"))


def auto_ok(cfg, ch, kinds):
    """sites/<id>.json の renovate_auto（"css"・"text" かその一覧）に収まる小さな直しか。既定は無効"""
    allow = cfg.get("renovate_auto") or []
    allow = {allow} if isinstance(allow, str) else set(allow)
    return bool(allow) and bool(kinds) and kinds <= (allow & {"css", "text"}) and len(ch) <= AUTO_MAX_FILES


# ---------------------------------------------------------------- 画面の写真

def _font(size):
    from PIL import ImageFont
    for p in ("C:/Windows/Fonts/YuGothB.ttc", "C:/Windows/Fonts/meiryob.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"):
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def screenshot(urls):
    """{url: PNG の bytes}。Playwright が無い・開けないページは入らない"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {}
    out = {}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        for u in urls:
            try:
                pg.goto(u, wait_until="networkidle", timeout=30000)
                out[u] = pg.screenshot(full_page=True)
            except Exception:
                pass
        b.close()
    return out


def compose(before_png, after_png, out: Path):
    """変更前と変更後を左右に並べた1枚（縦は2,400pxで切る）"""
    import io
    from PIL import Image, ImageDraw
    ims = [Image.open(io.BytesIO(x)).convert("RGB") if x else Image.new("RGB", (1280, 300), "#eeeeee")
           for x in (before_png, after_png)]
    ims = [im.crop((0, 0, im.width, min(im.height, 2400))) for im in ims]
    ims = [im.resize((640, max(1, round(im.height * 640 / im.width)))) for im in ims]
    h = max(im.height for im in ims)
    canvas = Image.new("RGB", (1300, h + 50), "white")
    d = ImageDraw.Draw(canvas)
    f = _font(22)
    for i, (im, label) in enumerate(zip(ims, ("変更前", "変更後"))):
        x = 10 + i * 650
        d.text((x, 12), label, fill="#1b4fa0", font=f)
        canvas.paste(im, (x, 50))
    canvas.save(out)
    return out


def _serve(root: Path):
    import functools
    import http.server
    import threading

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _export(cfg, dest: Path):
    """取った時点の中身を一時フォルダへ出す（変更前の写真を手元で撮るため）"""
    import io
    import zipfile
    w = workdir(cfg)
    r = subprocess.run(["git", f"--git-dir={w / '.git'}", "archive", "--format=zip", base_rev(cfg)], cwd=w, capture_output=True)
    if r.returncode == 0:
        zipfile.ZipFile(io.BytesIO(r.stdout)).extractall(dest)


def page_paths(cfg, ch, root):
    """写真と反映後の確認に使うページのパス（トップ＋変えたページ・最大5）"""
    w = workdir(cfg)
    paths = ["/"]
    for st, f in ch:
        if st == "D":
            continue
        if root and f.endswith(HTML_EXT) and (w / f).resolve().is_relative_to(root.resolve()):
            rel = (w / f).resolve().relative_to(root.resolve()).as_posix()
            p = "/" + (rel[:-len("index.html")] if rel.endswith("index.html") else rel)
        elif cfg["type"] == "wordpress" and f.startswith("pages/") and f.endswith(".json"):
            try:
                slug = json.loads((w / f).read_text(encoding="utf-8")).get("slug")
            except (OSError, ValueError):
                slug = None
            p = f"/{slug}/" if slug else None
        else:
            p = None
        if p and p not in paths:
            paths.append(p)
    return paths[:5]


def site_base(cfg):
    return (cfg.get("site_url") or f"https://{cfg['domain']}").rstrip("/")


def _slug(p):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", p.strip("/")) or "top"


def preview_local(cfg, ch):
    """静的な社: 取った時点と直した後の作業場所を手元で配信して撮る（反映の前に見られる）"""
    w = workdir(cfg)
    root = static_root(cfg, w)
    if root is None:
        return []
    out_dir = preview_dir(cfg)
    paths = page_paths(cfg, ch, root)
    made = []
    with tempfile.TemporaryDirectory() as td:
        _export(cfg, Path(td))
        broot = Path(td) / root.resolve().relative_to(w.resolve())
        s1, b_url = _serve(broot)
        s2, a_url = _serve(root)
        try:
            shots = screenshot([b_url + p for p in paths] + [a_url + p for p in paths])
        finally:
            s1.shutdown()
            s2.shutdown()
    for p in paths:
        if b_url + p in shots or a_url + p in shots:
            made.append(compose(shots.get(b_url + p), shots.get(a_url + p), out_dir / f"{_slug(p)}-compare.png"))
    return made


def preview_live_before(cfg, ch):
    """手元で配信できない社（WordPress・ビルドする Git の社）: 反映の前に本番を撮っておく"""
    out_dir = preview_dir(cfg)
    paths = page_paths(cfg, ch, None)
    shots = screenshot([site_base(cfg) + p for p in paths])
    for p in paths:
        if site_base(cfg) + p in shots:
            (out_dir / f"{_slug(p)}-before.png").write_bytes(shots[site_base(cfg) + p])
    return paths


def preview_live_after(cfg, paths):
    out_dir = preview_dir(cfg)
    shots = screenshot([site_base(cfg) + p for p in paths])
    made = []
    for p in paths:
        b = out_dir / f"{_slug(p)}-before.png"
        if site_base(cfg) + p in shots:
            made.append(compose(b.read_bytes() if b.is_file() else None, shots[site_base(cfg) + p],
                                out_dir / f"{_slug(p)}-compare.png"))
    return made


# ---------------------------------------------------------------- 反映後の確認

def fetch(url):
    """(状態コード, 本文)。届かなければ (0, "")"""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ss-renovate-check)", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def page_state(url):
    code, body = fetch(url)
    return {"code": code, "marks": sorted(k for k, rx in MARKERS.items() if rx.search(body))}


def verify(cfg, paths, before):
    """反映後に、ページが200で返り、反映前にあったナビ・フッター・問い合わせの導線が残っているか。問題の一覧"""
    wait = cfg.get("renovate_wait_sec")
    wait = (240 if is_git(cfg) else 5) if wait is None else int(wait)
    tries = int(cfg.get("renovate_verify_tries") or 3)
    problems = []
    for i in range(tries):
        time.sleep(wait if i == 0 else min(30, max(wait, 1)))
        problems = []
        for p in paths:
            now = page_state(site_base(cfg) + p)
            if now["code"] != 200:
                problems.append(f"{p} が {now['code'] or '応答なし'} で返ります")
                continue
            lost = [m for m in (before.get(p) or {}).get("marks", []) if m not in now["marks"]]
            if lost:
                problems.append(f"{p} から {'・'.join(lost)} が消えています")
        if not problems:
            return []
    return problems


# ---------------------------------------------------------------- 台帳

def redact(text):
    return SECRET.sub("（鍵らしき文字列を伏せました）", text or "")


def diff_summary(cfg, ch):
    out = wgit(workdir(cfg), "diff", "--cached", "--numstat", "--no-renames", base_rev(cfg), check=False)
    stat = {}
    for l in out.splitlines():
        a, d, f = (l.split("\t", 2) + ["", "", ""])[:3]
        stat[f] = (a, d)
    return [{"st": st, "file": f, "add": stat.get(f, ("", ""))[0], "del": stat.get(f, ("", ""))[1]} for st, f in ch]


def log(rec):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"at": datetime.now().isoformat(timespec="seconds"), **rec}
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def approver(how):
    if how == "auto":
        return "自動（renovate_auto）"
    who = os.environ.get("GITHUB_ACTOR") or os.environ.get("USERNAME") or os.environ.get("USER") or "不明"
    return f"{how}（{who}）"


# ---------------------------------------------------------------- 流れ

def run(cfg, ask, yes=False, preview=True):
    if cfg["type"] == "self-static":
        raise SystemExit("このリポジトリのサイトです。site/ と templates/ を直して build.py で公開してください")
    if cfg["type"] not in SC.GIT_TYPES + ("ftp", "wordpress"):
        raise SystemExit("この方式は先方のサーバーを取れないため、指示での改修はできません（ftp か Git の方式へ切り替えてください）")
    if pending(cfg):
        raise SystemExit("作業場所に、まだ反映していない変更があります。"
                         f"--apply で反映するか --discard で捨ててから、もう一度指示してください（{workdir(cfg)}）")
    print(pull(cfg))
    w = workdir(cfg)
    tower = tower_status()
    said = ask_claude(cfg, w, ask)
    outside = sorted(tower_status() - tower)
    if outside:
        discard(cfg)
        log({"site": cfg["id"], "type": cfg["type"], "ask": redact(ask), "decision": "stopped", "ng": ["作業場所の外を変えました"]})
        print("RENOVATE_OK=no")
        raise SystemExit("作業場所の外（管制塔）のファイルが変わりました。改修を捨てました:\n  " + "\n  ".join(outside[:10]))
    ch = pending(cfg)
    if not ch:
        print(f"変更はありません（{said[:200]}）")
        log({"site": cfg["id"], "type": cfg["type"], "ask": redact(ask), "decision": "nochange"})
        return 0
    state_path(cfg).write_text(json.dumps({"ask": ask, "at": datetime.now().isoformat(timespec="seconds"),
                                           "said": said}, ensure_ascii=False), encoding="utf-8")
    print(f"Claude: {said}")
    return review_and_apply(cfg, ch, ask, yes=yes, preview=preview, how="--yes")


def review_and_apply(cfg, ch, ask, yes=False, preview=True, how="--yes"):
    for st, f in ch:
        print(f"  {st} {f}")
    ng, notes, kinds = inspect_changes(cfg, ch, ask)
    for n in notes:
        print(f"  注: {n}")
    summary = diff_summary(cfg, ch)
    base = {"site": cfg["id"], "type": cfg["type"], "ask": redact(ask), "files": summary, "kinds": sorted(kinds)}
    if ng:
        print("検査で止めました（反映しません）:")
        for x in ng:
            print(f"  × {x}")
        print(f"作業場所はそのままです。見たら --discard で捨ててください（{workdir(cfg)}）")
        log({**base, "decision": "stopped", "ng": ng})
        return 1
    root = static_root(cfg, workdir(cfg))
    live_paths = None
    if preview:
        try:
            if root is not None:
                for p in preview_local(cfg, ch):
                    print(f"  写真: {p}")
            else:
                live_paths = preview_live_before(cfg, ch)
                print(f"  写真: 反映前の本番を撮りました（反映後に並べます）: {preview_dir(cfg)}")
        except Exception as e:      # 写真が撮れなくても検査と確認は進める
            print(f"  写真を撮れませんでした: {type(e).__name__}: {str(e)[:120]}")
    auto = auto_ok(cfg, ch, kinds)
    if not (yes or auto):
        print(f"検査は通りました。写真と差分を見て、よければ --apply で反映してください（種類: {'・'.join(sorted(kinds))}）")
        log({**base, "decision": "review"})
        return 0
    who = approver("auto" if auto and not yes else how)
    paths = page_paths(cfg, ch, root)
    before = {p: page_state(site_base(cfg) + p) for p in paths}
    msg = apply(cfg, ch)
    print(msg)
    if cfg["type"] == "wordpress":
        paths = paths + [p for p in page_paths(cfg, [("M", f) for f in
                                                     SC.mgit(SC.mirror(cfg), "diff", "--name-only", "remote~1", "remote").splitlines()], None)
                         if p not in paths]
    problems = verify(cfg, paths, before)
    if preview and root is None:
        try:
            for p in preview_live_after(cfg, live_paths or paths):
                print(f"  写真: {p}")
        except Exception as e:
            print(f"  写真を撮れませんでした: {type(e).__name__}: {str(e)[:120]}")
    if problems:
        print("反映後の確認で外れました。自動で戻します:")
        for x in problems:
            print(f"  × {x}")
        try:
            back = rollback(cfg)
            print(back)
            after_back = verify({**cfg, "renovate_verify_tries": 1}, ["/"], {})
        except SystemExit as e:
            back, after_back = f"戻せませんでした: {e}", ["戻せませんでした"]
        log({**base, "decision": "rolled_back", "approver": who, "problems": problems, "rollback": str(back)[:200],
             "after_rollback": after_back})
        state_path(cfg).unlink(missing_ok=True)
        print(f"要対応: {cfg['id']} のサイト改修を反映後に戻しました（{problems[0]}）")
        print("RENOVATE_OK=no")
        return 1
    log({**base, "decision": "applied", "approver": who, "checked": paths})
    state_path(cfg).unlink(missing_ok=True)
    print(f"反映しました（確認: {'・'.join(paths)}・{who}）")
    print("RENOVATE_OK=yes")
    return 0


def apply_pending(cfg, preview=True):
    ch = pending(cfg)
    if not ch:
        raise SystemExit("反映する変更がありません")
    st = json.loads(state_path(cfg).read_text(encoding="utf-8")) if state_path(cfg).is_file() else {}
    return review_and_apply(cfg, ch, st.get("ask", "（指示の記録なし・手で直した変更）"), yes=True, preview=preview, how="--apply")


def report(days=7, now=None):
    """直近の戻し・確かめられなかった回を知らせる（findings が読む。終了コードは常に0）"""
    now = now or datetime.now()
    bad = []
    if LOG.is_file():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if datetime.fromisoformat(r.get("at", "1970-01-01")) < now - timedelta(days=days):
                continue
            if r.get("decision") == "rolled_back":
                bad.append(f"要対応: {r['site']} のサイト改修（{r.get('ask', '')[:40]}）を反映後に戻しました: "
                           f"{(r.get('problems') or [''])[0]}" + ("・戻した後も確認が外れています" if r.get("after_rollback") else ""))
    for b in bad:
        print(b)
    print("RENOVATE_OK=" + ("no" if bad else "yes"))
    return 0


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site")
    ap.add_argument("--ask")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--discard", action="store_true")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.report:
        return report()
    if not a.site:
        ap.error("--site が要ります")
    cfg = S.load(a.site)
    if a.discard:
        discard(cfg)
        print("作業場所を取った時点に戻しました")
        return 0
    if a.apply:
        return apply_pending(cfg, preview=not a.no_preview)
    if not a.ask:
        ap.error("--ask \"<指示>\" か --apply / --discard を指定してください")
    return run(cfg, a.ask, yes=a.yes, preview=not a.no_preview)


if __name__ == "__main__":
    sys.exit(main())
