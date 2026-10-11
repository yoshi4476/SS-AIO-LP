# -*- coding: utf-8 -*-
"""自動修復の案（AI が鍵の無いコンテナで作った差分）を、人の確認なしで本体へ取り込んでよいかを機械で決める。

本体へ入ったコードは、以後すべてのワークフローが鍵つきで動かす。AI は外の文章（CI のログ）を読むので、仕込まれた指示で
鍵を外へ送るコードを書く可能性がゼロではない。そこで「取り込んでよい場所と書き方」を決めておき（許可の一覧）、
それ以外の場所・書き方が1つでもあれば枝に置く（2026-10-11 運用者「自動的に直して」。判定はここ1か所。selfheal の
repair-branch が master のままのコードで呼ぶ）。

取り込んでよい場所:
  - scripts/**/*.py … 新しい import の行を足さない・下の危ない書き方が無い
  - tests/*.py … 足すだけ（消す・書き換える行が無い。門を弱めない）・危ない書き方が無い
  - articles/**/*.md・data/**/*.json(l)・data/**/*.csv … 中身はデータ
それ以外（指示書・CLAUDE.md・sites/・templates/・ワークフロー・依存・守秘の仕組み）、名前の変更・写し・引用符つきの
ファイル名・中身の見えない変更・量の多い変更は枝へ。

    python scripts/patch_policy.py <差分のファイル>
出す印: PATCH_POLICY=auto（取り込んでよい）/ review（枝に置く。理由を下に出す）
site/ の変更は判定にも取り込みにも入れない（ビルドが作り直す。取り込む側が --exclude で外す）
"""
import re
import sys
from pathlib import Path

MAX_FILES = 15
MAX_ADDED = 400

# 許可の一覧に入っていても取り込まない場所（鍵の外し方・守秘の仕組み・判定そのもの・埋め込みの形・通知）
FORBID = [r"^scripts/(agent_guard|gcreds|private_store|client_private|ci_mask|log_leak_check|html_safety|patch_policy|embeds|"
          r"md2html|notify_slack|set_secrets|gas_deploy|hub_token|hub_client|agent_work)\.py$",
          r"^tests/gates_history_h91_agent_jail\.py$", r"(^|/)(sitecustomize|usercustomize|conftest|setup|__init__)\.py$"]
ALLOW = [(r"^scripts/[\w/-]+\.py$", "code"), (r"^tests/[\w-]+\.py$", "test"),
         (r"^articles/[\w/-]+\.md$", "data"), (r"^data/(?!.*\.\.)[\w/.-]+\.(json|jsonl|csv)$", "data")]
# Python の足した行に1つでもあれば枝へ（外へ送る・コマンド・環境変数・鍵のファイル・書き方を隠す）。
# ふつうの直しに出る書き方（re.compile・Path(__file__)・getattr(args, "x")・max_tokens・"　"）は通す
RISKY = [
    (r"\b(urllib|requests|http\.client|httplib2|socket|smtplib|ftplib|paramiko|aiohttp|httpx|websocket|ssl|telnetlib|"
     r"xmlrpc|asyncio|multiprocessing|threading|webbrowser)\b", "外への通信・裏の処理"),
    (r"\bsubprocess\b|\bos\.(system|popen|exec\w*|spawn\w*|fork|kill)\b|\bpty\b", "コマンドの実行"),
    (r"\bos\.environ\b|\bgetenv\b|\benviron\b", "環境変数の読み書き"),
    (r"(?<![.\w])(exec|eval|compile)\s*\(|__import__|\bimportlib\b|\bbuiltins\b|\bglobals\s*\(|\blocals\s*\(|"
     r"\bgetattr\s*\(\s*(os|sys|subprocess|builtins|__builtins__|importlib|socket|shutil|io|pathlib|urllib)\b|"
     r"\bgetattr\s*\([^,()]+,\s*[^\"'\s]|\bsetattr\s*\(|\bvars\s*\(|"
     r"\b__(builtins|globals|class|subclasses|bases|mro|dict|code|loader|spec|getattribute|reduce\w*)__\b", "書き方を隠す"),
    (r"\b(base64|binascii|codecs|marshal|pickle|zlib|ctypes|bz2|lzma)\b|(\\[xuU][0-9a-fA-F]{2}.*){3,}|\bchr\s*\(|"
     r"\bfromhex\b", "中身を隠す"),
    (r"\.git\b|\.github\b|credential|indexing-service-account|\btoken\b|\bsecret\b|password|private/|/proc/|\.ssh|"
     r"\.env\b|RUNNER_TEMP|GITHUB_", "鍵・資格・ワークフローの場所"),
    (r"\bshutil\.rmtree\b|\bos\.rmdir\b", "フォルダの削除"),
]
# 行頭のほか、; や : の後ろに置いた import も見る（x = 1; import socket・if x: import os）
IMPORT = re.compile(r"(^|[;:])\s*(import\s|from\s+\S+\s+import\s)")


HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def _odd(name):
    return {"path": name, "old": name, "add": [], "del": [], "new": False, "gone": False, "binary": False,
            "mode": False, "odd": True, "hunks": 0}


def files(patch):
    """差分をファイルごとに読む。git apply と同じく、塊（@@）の行数の分だけを中身として読む（中身が ++ や --- で
    始まる行を見出しと取り違えない）。git の見出し（diff --git）の無い差分・塊の後に続く別の見出し（--- / +++）は、
    git apply がそれを別のファイルとして当てるのに判定には載らないので、印を付けて枝へ回す。
    引用符つきの名前・名前の変更・写し・バイナリ・権限の変更も印を付ける"""
    out, cur, left = [], None, None
    for ln in patch.splitlines():
        if left:
            if ln.startswith("\\"):
                continue
            tag = ln[:1]
            if tag == "+":
                cur["add"].append(ln[1:])
                left[1] -= 1
            elif tag == "-":
                cur["del"].append(ln[1:])
                left[0] -= 1
            else:
                left[0] -= 1
                left[1] -= 1
            if left[0] <= 0 and left[1] <= 0:
                left = None
            continue
        if ln.startswith("diff --git "):
            m = re.match(r"^diff --git a/(\S+) b/(\S+)$", ln)
            cur = _odd(ln[:120])
            if m:
                cur.update(path=m.group(2), old=m.group(1), odd=False)
            out.append(cur)
            continue
        m = HUNK.match(ln)
        if m:
            if cur is None:
                cur = _odd("（git の見出しの無い差分）")
                out.append(cur)
            cur["hunks"] += 1
            left = [int(m.group(1) if m.group(1) is not None else 1), int(m.group(2) if m.group(2) is not None else 1)]
            continue
        if ln.startswith(("--- ", "+++ ")):
            # 見出しより前・塊の後に来た --- / +++ は、git apply が別のファイルとして当てる
            if cur is None or cur["hunks"]:
                cur = _odd("（git の見出しの無い差分）")
                out.append(cur)
            elif ln.startswith("+++ ") and ln[4:] not in (f"b/{cur['path']}", "/dev/null"):
                cur["odd"] = True
            elif ln.startswith("--- ") and ln[4:] not in (f"a/{cur['old']}", "/dev/null"):
                cur["odd"] = True
            continue
        if cur is None or cur["hunks"]:
            continue
        if ln.startswith("new file mode"):
            cur["new"] = True
            cur["mode"] = cur["mode"] or not ln.endswith("100644")
        elif ln.startswith("deleted file mode"):
            cur["gone"] = True
        elif ln.startswith(("old mode", "new mode")):
            cur["mode"] = True
        elif ln.startswith(("rename from", "rename to", "copy from", "copy to", "similarity index", "dissimilarity index")):
            cur["odd"] = True
        elif ln.startswith(("GIT binary patch", "Binary files")):
            cur["binary"] = True
    return out


def judge(patch):
    """(auto か, 理由の一覧)"""
    allf = files(patch)
    why = []
    fs = [f for f in allf if f["odd"] or not (f["path"].startswith("site/") and f["old"].startswith("site/"))]
    if not fs:
        return False, ["site/ 以外の変更がありません（直した中身が無い）"]
    if len(fs) > MAX_FILES:
        why.append(f"変えたファイルが {len(fs)} 件（{MAX_FILES} 件まで）")
    added = sum(len(f["add"]) for f in fs)
    if added > MAX_ADDED:
        why.append(f"足した行が {added} 行（{MAX_ADDED} 行まで）")
    for f in fs:
        p = f["path"]
        if f["odd"]:
            why.append(f"{p[:80]}: 名前の変更・写し・引用符つきの名前（中身を確かめきれない）")
            continue
        if f["binary"] or f["mode"]:
            why.append(f"{p}: 中身の見えない変更（バイナリ・実行の権限）")
            continue
        if any(re.search(rx, x) for x in {p, f["old"]} for rx in FORBID):
            why.append(f"{p}: 守る場所（鍵・守秘の仕組み・判定・埋め込み・通知）")
            continue
        kind = next((k for rx, k in ALLOW if re.search(rx, p)), None)
        if kind is None:
            why.append(f"{p}: 自動で取り込める場所ではない（scripts の .py・門の追加・記事・データだけ）")
            continue
        if kind == "data":
            continue
        if kind == "test" and (f["del"] or f["gone"]):
            why.append(f"{p}: 門を消す・書き換える変更（門を足すだけなら取り込む）")
        if f["gone"]:
            why.append(f"{p}: ファイルを消している")
        # コメントも含めて行全体を見る（「#」を文字列に入れてコメントに見せかけ、後ろに書く手を通さない）
        for x in f["add"]:
            if IMPORT.search(x):
                why.append(f"{p}: 新しい import（{x.strip()[:60]}）")
                continue
            for rx, label in RISKY:
                if re.search(rx, x, re.I):
                    why.append(f"{p}: {label}（{x.strip()[:60]}）")
                    break
    # 同じ理由を何度も並べない
    seen, uniq = set(), []
    for w in why:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return not uniq, uniq


def main():
    if len(sys.argv) < 2:
        print("使い方: python scripts/patch_policy.py <差分のファイル>")
        return 1
    patch = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    ok, why = judge(patch)
    print(f"PATCH_POLICY={'auto' if ok else 'review'}")
    for w in why[:20]:
        print("  " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
