# -*- coding: utf-8 -*-
"""自動修復の案（AI が鍵の無いコンテナで作った差分）を、人の確認なしで本体へ取り込んでよいかを機械で決める。

本体へ入ったコードは、以後すべてのワークフローが鍵つきで動かす。AI は外の文章（CI のログ）を読むので、仕込まれた指示で
鍵を外へ送るコードを書く可能性がゼロではない。そこで、取り込んでよいのは「ふつうの直し」に見えるものだけにし、
外へ送る・コマンドを動かす・環境変数を読む・書き方を隠す書き方や、守る場所・門を弱める変更が1つでもあれば枝に置く
（2026-10-11 運用者「自動的に直して」。判定はここ1か所。selfheal の repair-branch が master のままのコードで呼ぶ）。

    python scripts/patch_policy.py <差分のファイル>
出す印: PATCH_POLICY=auto（取り込んでよい）/ review（枝に置く。理由を下に出す）
site/ の変更は判定にも取り込みにも入れない（ビルドが作り直す。取り込む側が --exclude で外す）
"""
import re
import sys
from pathlib import Path

MAX_FILES = 15
MAX_ADDED = 400

# 触れたら取り込まない場所（鍵の外し方・許可・ワークフロー・配って動く別の場所のコード・守秘の仕組み・依存）
FORBID = [r"^\.github/", r"^\.claude/", r"^\.env", r"^automation/agent_settings_", r"^automation/ai_container\.Dockerfile$",
          r"^automation/gas/", r"^automation/wordpress/", r"^functions/", r"^templates/", r"^private/",
          r"^requirements[^/]*\.txt$", r"^package(-lock)?\.json$",
          r"^scripts/(agent_guard|gcreds|private_store|client_private|ci_mask|log_leak_check|html_safety|patch_policy|"
          r"notify_slack|set_secrets|gas_deploy)\.py$",
          r"^tests/gates_history_h91_agent_jail\.py$", r"(^|/)(sitecustomize|usercustomize|conftest|setup)\.py$",
          r"\.pth$"]
# 中身を見て取り込んでよい種類（それ以外の種類のファイルは枝へ）
CODE = (".py",)
DATA = (".md", ".json", ".jsonl", ".txt", ".csv", ".yml.example")
# Python の足した行に1つでもあれば枝へ（外へ送る・コマンド・環境変数・鍵のファイル・書き方を隠す）
RISKY = [
    (r"\b(urllib|requests|http\.client|httplib2|socket|smtplib|ftplib|paramiko|aiohttp|httpx|websocket)\b", "外への通信"),
    (r"\bsubprocess\b|\bos\.(system|popen|exec\w*|spawn\w*|fork)\b|\bpty\b", "コマンドの実行"),
    (r"\bos\.environ\b|\bgetenv\b|\benviron\b", "環境変数の読み書き"),
    (r"\b(exec|eval|compile)\s*\(|__import__|\bimportlib\b|\bbuiltins\b|__builtins__|\bglobals\s*\(|\bgetattr\s*\(", "書き方を隠す"),
    (r"\b(base64|binascii|codecs|marshal|pickle|zlib|ctypes)\b|\\x[0-9a-fA-F]{2}|\bchr\s*\(", "中身を隠す"),
    (r"\.git/|credential|indexing-service-account|token|secret|password|private/|/proc/|\.ssh|\.env\b", "鍵・資格の場所"),
    (r"\bshutil\.rmtree\b|\bos\.(remove|unlink|rmdir)\b|\.unlink\s*\(", "ファイルの削除"),
]


def files(patch):
    """[(パス, 足した行, 消した行, 新しいファイルか, 消したファイルか, 中身が見えるか)]"""
    out, cur = [], None
    for ln in patch.splitlines():
        m = re.match(r"^diff --git a/(.+?) b/(.+)$", ln)
        if m:
            cur = {"path": m.group(2), "old": m.group(1), "add": [], "del": [], "new": False, "gone": False,
                   "binary": False, "mode": False}
            out.append(cur)
            continue
        if cur is None:
            continue
        if ln.startswith("new file mode"):
            cur["new"] = True
            cur["mode"] = not ln.endswith("100644")
        elif ln.startswith("deleted file mode"):
            cur["gone"] = True
        elif ln.startswith(("old mode", "new mode")):
            cur["mode"] = True
        elif ln.startswith(("GIT binary patch", "Binary files")):
            cur["binary"] = True
        elif ln.startswith("+") and not ln.startswith("+++"):
            cur["add"].append(ln[1:])
        elif ln.startswith("-") and not ln.startswith("---"):
            cur["del"].append(ln[1:])
    return out


def judge(patch):
    """(auto か, 理由の一覧)"""
    fs = [f for f in files(patch) if not f["path"].startswith("site/") and not f["old"].startswith("site/")]
    why = []
    if not fs:
        return False, ["site/ 以外の変更がありません（直した中身が無い）"]
    if len(fs) > MAX_FILES:
        why.append(f"変えたファイルが {len(fs)} 件（{MAX_FILES} 件まで）")
    added = sum(len(f["add"]) for f in fs)
    if added > MAX_ADDED:
        why.append(f"足した行が {added} 行（{MAX_ADDED} 行まで）")
    for f in fs:
        p = f["path"]
        for path in {p, f["old"]}:
            if any(re.search(rx, path) for rx in FORBID):
                why.append(f"{path}: 守る場所（鍵・許可・ワークフロー・配って動くコード・守秘の仕組み・依存）")
        if f["binary"] or f["mode"]:
            why.append(f"{p}: 中身の見えない変更（バイナリ・実行の権限）")
            continue
        if p.startswith("tests/"):
            if f["gone"]:
                why.append(f"{p}: 門のファイルを消している")
            lost = sum("check(" in x for x in f["del"]) - sum("check(" in x for x in f["add"])
            if lost > 0:
                why.append(f"{p}: 門の確かめを {lost} 個減らしている（門を弱めて通す直しは取り込まない）")
        if p.endswith(CODE):
            # コメントも含めて行全体を見る（「#」を文字列に入れてコメントに見せかけ、後ろに書く手を通さない）
            for x in f["add"]:
                for rx, label in RISKY:
                    if re.search(rx, x, re.I):
                        why.append(f"{p}: {label}（{x.strip()[:60]}）")
                        break
        elif not p.endswith(DATA):
            why.append(f"{p}: 中身を見て取り込める種類ではない（.py とデータだけ）")
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
