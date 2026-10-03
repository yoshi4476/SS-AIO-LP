# -*- coding: utf-8 -*-
"""Git を使わない配信先（レンタルサーバー・ZIP納品）へ、管制塔から記事を届ける。

publish.py の external-html と同じ書き出し（write_external_html）を、手元の作業場所で行い、
書き出したファイルだけを相手のサーバーへ上げる（ftp）か、まとめて渡す（zip）。
sitemap.xml・llms.txt・article-manifest.json は公開中のものを HTTPS で読んで足すので、
相手のサーバーに既にある記事の分を消さない。

  ftp  … FTPS（既定）/ FTP / SFTP。接続情報はシートに書かず、
         FTP_CREDENTIALS_JSON（CI の Secret）か ftp-credentials.json（手元・コミットしない）に置く:
         {"<site id>": {"protocol": "ftps", "host": "...", "port": 21, "user": "...",
                        "password": "...", "root": "/public_html"}}
  zip  … deliveries/<id>/<日付>-<slug>.zip を作る（コミットしない）。相手が自分で上げる
"""
import ftplib
import json
import os
import re
import shutil
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".publish-work"
TYPES = ("ftp", "zip")
# 公開しないファイル（原稿は相手の重複判定用。サーバーに置くと誰でも読める）
PRIVATE = (".md",)


def index_path(cfg):
    """配信した記事の一覧（関連記事のリンクに使う）。相手のサーバーを一覧できない方式があるため手元で持つ"""
    return ROOT / "data" / "clients" / cfg["id"] / "delivered.json"


def load_index(cfg):
    p = index_path(cfg)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except ValueError:
        return {}


def stage(cfg):
    """作業場所を用意する。雛形は先方の見た目に合わせたもの（data/clients/<id>/template.html）が優先"""
    d = WORK / f"{cfg['id']}-files"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    own = ROOT / "data" / "clients" / cfg["id"] / "template.html"
    tpl = (own if own.is_file() else ROOT / "templates" / "external_article.html").read_text(encoding="utf-8")
    origin = f"https://{cfg['domain']}"
    tpl = (tpl.replace("{{SITE_NAME}}", cfg.get("name", cfg["domain"]))
              .replace("{{ORIGIN}}", origin)
              .replace("{{PREFIX}}", (cfg.get("url_prefix") or "/blog").rstrip("/")))
    (d / "_template.html").write_text(tpl, encoding="utf-8")
    # 関連記事は write_external_html が blog/ の中から選ぶ。配信済みの記事を見出しだけの控えで並べる
    for slug, r in load_index(cfg).items():
        f = d / "blog" / slug / "index.html"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f'<h1>{r["title"]}</h1>"datePublished": "{r.get("date", "")}"', encoding="utf-8")
    # 公開中の索引を読んで足す（無いものは作らない＝ _update_external_index と同じ扱い）
    for name in ("sitemap.xml", "llms.txt", "article-manifest.json"):
        try:
            req = urllib.request.Request(f"{origin}/{name}", headers={"User-Agent": "Mozilla/5.0 SS-AIO-Pipeline"})
            with urllib.request.urlopen(req, timeout=20) as r:
                (d / name).write_bytes(r.read())
        except Exception:
            pass
    return d


def stage_cfg(cfg):
    """write_external_html に渡す設定。書き出し先は作業場所の中で決まった形にする"""
    return dict(cfg, template="_template.html", content_dir="_src",
                images_dir=cfg.get("images_dir") or "images")


def files_of(written, base: Path, prefix="/blog"):
    """(ファイル, 相手のサーバーでの置き場) の組。記事は書き出し上 blog/ に置かれるので、接頭辞の場所へ移す"""
    pre = prefix.strip("/")
    out = []
    for w in written:
        w = Path(w)
        for f in ([w] if w.is_file() else sorted(p for p in w.rglob("*") if p.is_file())):
            rel = f.relative_to(base).as_posix()
            if rel.endswith(PRIVATE) or rel.startswith("_"):
                continue
            if pre != "blog" and rel.startswith("blog/"):
                if f.suffix == ".html":
                    f.write_text(f.read_text(encoding="utf-8").replace('href="/blog/', f'href="/{pre}/'), encoding="utf-8")
                rel = (f"{pre}/" if pre else "") + rel[5:]
            out.append((f, rel))
    return out


def credentials(cfg):
    raw = os.environ.get("FTP_CREDENTIALS_JSON")
    if not raw:
        p = ROOT / "ftp-credentials.json"
        raw = p.read_text(encoding="utf-8-sig") if p.is_file() else "{}"
    c = json.loads(raw).get(cfg["id"])
    if not c or not c.get("host"):
        raise SystemExit(f"{cfg['id']}: FTP の接続情報がありません（FTP_CREDENTIALS_JSON か ftp-credentials.json）")
    return c


class Remote:
    """相手のサーバー（FTPS / FTP / SFTP）。置く・読む・消すだけを持つ"""

    def __init__(self, c):
        self.proto = (c.get("protocol") or "ftps").lower()
        self.root = (c.get("root") or "").rstrip("/")
        if self.proto == "sftp":
            try:
                import paramiko
            except ImportError:
                raise SystemExit("SFTP には paramiko が要ります（pip install paramiko）")
            self.t = paramiko.Transport((c["host"], int(c.get("port") or 22)))
            self.t.connect(username=c["user"], password=c.get("password"))
            self.s = paramiko.SFTPClient.from_transport(self.t)
        else:
            self.f = ftplib.FTP_TLS() if self.proto == "ftps" else ftplib.FTP()
            self.f.connect(c["host"], int(c.get("port") or 21), timeout=60)
            self.f.login(c["user"], c.get("password", ""))
            if self.proto == "ftps":
                self.f.prot_p()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        if self.proto == "sftp":
            self.s.close()
            self.t.close()
        else:
            try:
                self.f.quit()
            except Exception:
                self.f.close()

    def _mkdirs(self, path):
        cur = ""
        for part in path.split("/")[:-1]:
            if not part:
                continue
            cur = f"{cur}/{part}"
            try:
                self.s.mkdir(cur) if self.proto == "sftp" else self.f.mkd(cur)
            except (OSError, ftplib.error_perm):
                pass

    def put(self, local, rel):
        path = f"{self.root}/{rel}"
        self._mkdirs(path)
        if self.proto == "sftp":
            self.s.put(str(local), path)
        else:
            with open(local, "rb") as fh:
                self.f.storbinary(f"STOR {path}", fh)

    def get(self, rel):
        """無ければ None（.htaccess の無いサーバーもある）"""
        import io
        buf = io.BytesIO()
        try:
            if self.proto == "sftp":
                self.s.getfo(f"{self.root}/{rel}", buf)
            else:
                self.f.retrbinary(f"RETR {self.root}/{rel}", buf.write)
        except (OSError, ftplib.error_perm):
            return None
        return buf.getvalue()

    def rmtree(self, rel):
        """フォルダごと消す。消したファイル数を返す（無ければ0）"""
        path = f"{self.root}/{rel}".rstrip("/")
        n = 0
        if self.proto == "sftp":
            import stat
            try:
                entries = self.s.listdir_attr(path)
            except OSError:
                return 0
            for e in entries:
                sub = f"{rel.rstrip('/')}/{e.filename}"
                if stat.S_ISDIR(e.st_mode):
                    n += self.rmtree(sub)
                else:
                    self.s.remove(f"{path}/{e.filename}")
                    n += 1
            self.s.rmdir(path)
            return n
        try:
            names = self.f.nlst(path)
        except ftplib.error_perm:
            return 0
        for full in names:
            name = full.rsplit("/", 1)[-1]
            if name in (".", ".."):
                continue
            sub = f"{rel.rstrip('/')}/{name}"
            try:
                self.f.delete(f"{path}/{name}")
                n += 1
            except ftplib.error_perm:
                n += self.rmtree(sub)
        try:
            self.f.rmd(path)
        except ftplib.error_perm:
            pass
        return n


def _ftp_upload(c, items):
    with Remote(c) as r:
        for f, rel in items:
            r.put(f, rel)


def retract(cfg, rows, push: bool):
    """統合で消した記事を相手のサーバーから外し、301 で送る（retract.py の FTP・ZIP 版）。

    sitemap・llms.txt・manifest は retract.apply で直し（Git の社と同じ処理）、転送は
    Apache の .htaccess に Redirect 301 を1行ずつ足す（レンタルサーバーの大半は Apache。
    既存の .htaccess は読んでから足すので、先方の設定は消さない）。
    ZIP の社は、直したファイルと「消すもの・転送」の手順書を ZIP にして渡す。戻り値は処理できたか"""
    import retract as RT
    base = stage(cfg)
    pre = (cfg.get("url_prefix") or "/blog").strip("/")
    touched, gone, lines = set(), [], []
    for row in rows:
        touched |= {t for t in RT.apply(row, cfg, base) if t in ("sitemap.xml", "llms.txt", "article-manifest.json")}
        gone += [f"{pre}/{row['slug']}" if pre else row["slug"], f"images/{row['slug']}", f"images/blog/{row['slug']}"]
        lines.append(f"Redirect 301 {row['from']} https://{cfg['domain']}{row['to']}")
    if not push:
        for l in lines:
            print(f"  {l}")
        return False
    # 関連記事に消した記事を出さない
    idx = load_index(cfg)
    if any(idx.pop(row["slug"], None) for row in rows):
        index_path(cfg).write_text(json.dumps(idx, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    if cfg["type"] == "ftp":
        with Remote(credentials(cfg)) as r:
            for rel in sorted(touched):
                r.put(base / rel, rel)
            for rel in gone:
                n = r.rmtree(rel)
                if n:
                    print(f"  消しました: {rel}（{n}ファイル）")
            cur = (r.get(".htaccess") or b"").decode("utf-8", "replace")
            add = [l for l in lines if l not in cur]
            if add:
                ht = base / ".htaccess"
                body = "\n".join(["# 統合した記事の転送（管制塔）"] + add) + "\n"
                ht.write_text((cur.rstrip("\n") + "\n" if cur else "") + body, encoding="utf-8", newline="\n")
                r.put(ht, ".htaccess")
        return True
    out = ROOT / "deliveries" / cfg["id"] / f"{date.today().isoformat()}-取り下げ.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(touched):
            z.write(base / rel, rel)
        steps = (["1. 同梱のファイルでサーバーの同じ名前のファイルを上書きしてください",
                  "2. 次のフォルダを削除してください"] + [f"   /{g}/" for g in gone]
                 + ["3. .htaccess の末尾に次の行を足してください（古い記事を新しい記事へ転送します）"]
                 + [f"   {l}" for l in lines])
        z.writestr("手順.txt", "\n".join(steps) + "\n")
    print(f"  取り下げの ZIP: {out.relative_to(ROOT)}")
    return True


def deliver_batch(cfg, written, base: Path, push: bool, label: str):
    """複数の記事をまとめて届ける（描き直し用）。同じファイルは1回だけ上げる"""
    items = list(dict((rel, (f, rel)) for f, rel in files_of(written, base, cfg.get("url_prefix") or "/blog")).values())
    print(f"  上げるファイル: {len(items)}")
    if not push:
        return None
    if cfg["type"] == "ftp":
        _ftp_upload(credentials(cfg), items)
        return f"{cfg['domain']} へ {len(items)} ファイル"
    out = ROOT / "deliveries" / cfg["id"] / f"{date.today().isoformat()}-{label}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f, rel in items:
            z.write(f, rel)
    print(f"  ZIP: {out.relative_to(ROOT)}")
    return str(out)


def deliver(cfg, meta, written, base: Path, push: bool):
    """書き出したファイルを届け、配信済みの一覧に足す。push しないときは何を上げるかだけ出す"""
    items = files_of(written, base, cfg.get("url_prefix") or "/blog")
    for _, rel in items:
        print(f"  書き込み: {rel}")
    if not push:
        print("\n※ --push を付けると相手のサーバーへ上げます" if cfg["type"] == "ftp"
              else "\n※ --push を付けると ZIP を作ります")
        return None
    if cfg["type"] == "ftp":
        _ftp_upload(credentials(cfg), items)
        where = f"{cfg['domain']} へ {len(items)} ファイル"
    else:
        out = ROOT / "deliveries" / cfg["id"] / f"{date.today().isoformat()}-{meta['slug']}.zip"
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f, rel in items:
                z.write(f, rel)
        where = str(out.relative_to(ROOT))
    idx = load_index(cfg)
    idx[meta["slug"]] = {"title": re.sub(r"\s+", " ", meta["title"]), "date": str(meta["date"])}
    p = index_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(idx, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"配信しました: {where}")
    return where
