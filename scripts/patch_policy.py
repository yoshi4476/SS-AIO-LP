# -*- coding: utf-8 -*-
"""自動修復の案（AI が鍵の無いコンテナで作った差分）を、人の確認なしで本体へ取り込んでよいかを機械で決める。

本体へ入ったコードは、以後すべてのワークフローが鍵つきで動かす。AI は外の文章（CI のログ）を読むので、仕込まれた指示で
鍵を外へ送るコードを書く可能性がゼロではない。そこで「取り込んでよい場所と書き方」を決めておき（許可の一覧）、
それ以外の場所・書き方が1つでもあれば枝に置く（2026-10-11 運用者「自動的に直して」。判定はここ1か所。selfheal の
repair-branch が master のままのコードで呼ぶ）。

取り込んでよい場所:
  - scripts/**/*.py … 既にあるファイルの変更だけ・足す行は scripts 全体で40行まで・新しい import の行を足さない・
    下の危ない書き方が無い
  - tests/*.py … 足すだけ（消す・書き換える行が無い。門を弱めない）・危ない書き方が無い
それ以外（記事・データ・指示書・CLAUDE.md・sites/・templates/・ワークフロー・依存・守秘の仕組み）、名前の変更・写し・
引用符つきのファイル名・中身の見えない変更・量の多い変更は枝へ。
記事（articles/）とデータ（data/）は枝へ（2026-10-20 の点検）。記事は点数（score:）を書き換えれば門を通らずに公開でき、
data/ には書く AI が読む学び（lessons.jsonl）があり、仕込んだ指示が以後の記事に効いた。コードの修復に要らない

    python scripts/patch_policy.py <差分のファイル>
出す印: PATCH_POLICY=auto（取り込んでよい）/ review（枝に置く。理由を下に出す）
site/ の変更は判定にも取り込みにも入れない（ビルドが作り直す。取り込む側が --exclude で外す）
"""
import re
import sys
from pathlib import Path

MAX_FILES = 15
MAX_ADDED = 400
# scripts/ に足す行の上限（門の追加は数えない）。修復は小さな直しで足りる。大きな書き足しは人が読む（2026-10-20）
MAX_CODE_ADDED = 40

# 許可の一覧に入っていても取り込まない場所（鍵の外し方・守秘の仕組み・判定そのもの・埋め込みの形・通知）
FORBID = [r"^scripts/(agent_guard|gcreds|private_store|client_private|ci_mask|log_leak_check|html_safety|patch_policy|embeds|"
          r"md2html|notify_slack|set_secrets|gas_deploy|hub_token|hub_client|agent_work|egress_proxy)\.py$",
          r"^tests/gates_history_h91_agent_jail\.py$", r"(^|/)(sitecustomize|usercustomize|conftest|setup|__init__)\.py$"]
ALLOW = [(r"^scripts/[\w/-]+\.py$", "code"), (r"^tests/[\w-]+\.py$", "test")]
# 記事とデータは自動で取り込まない（上の説明。2026-10-20）
CONTENT = re.compile(r"^(articles|data)/")
# Python の足した行に1つでもあれば枝へ（外へ送る・コマンド・環境変数・鍵のファイル・書き方を隠す）。
# ふつうの直しに出る書き方（re.compile・Path(__file__)・getattr(args, "x")・max_tokens・"　"）は通す
RISKY = [
    (r"\b(urllib|requests|http\.client|httplib2|socket|smtplib|ftplib|paramiko|aiohttp|httpx|websocket|ssl|telnetlib|"
     r"xmlrpc|asyncio|multiprocessing|threading|webbrowser)\b", "外への通信・裏の処理"),
    (r"\bsubprocess\b|\bos\.(system|popen|exec\w*|spawn\w*|fork|kill)\b|\bpty\b", "コマンドの実行"),
    # 語の境目で切らない（os.environb・os.getenvb は \benviron\b に当たらなかった。2026-10-24 の点検）
    (r"environ|getenv", "環境変数の読み書き"),
    # 鍵の名前の形（SITE_PUSH_TOKEN・HUB_SECRET・ANTHROPIC_API_KEY・WP_CREDENTIALS_JSON）。大文字の定数だけを見る
    # （re.I の下でも大文字小文字を区別する。max_tokens のようなふつうの名前は通す）
    (r"(?-i:\b[A-Z][A-Z0-9]*_(?:[A-Z0-9]+_)*(?:TOKEN|TOKENS|SECRET|KEY|PASSWORD|CREDENTIALS?|AUTH)(?:_[A-Z0-9]+)*\b)",
     "鍵の名前"),
    # 外の宛先と、既にある「送る・環境変数を読む」手助けの関数（新しい import 無しで外へ送れた。2026-10-24 の点検）
    (r"\b[a-z]+://|\b\w*_(post|env|fetch|urlopen|request|upload|send)\s*\(|(?<![.\w])(post|fetch|urlopen|upload)\s*\(",
     "外の宛先・送る手助けの関数"),
    (r"(?<![.\w])(exec|eval|compile)\s*\(|__import__|\bimportlib\b|\bbuiltins\b|\bglobals\s*\(|\blocals\s*\(|"
     r"\bgetattr\s*\(\s*(os|sys|subprocess|builtins|__builtins__|importlib|socket|shutil|io|pathlib|urllib)\b|"
     r"\bgetattr\s*\([^,()]+,\s*[^\"'\s]|\bsetattr\s*\(|\bvars\s*\(|"
     r"\b__(builtins|globals|class|subclasses|bases|mro|dict|code|loader|spec|getattribute|reduce\w*)__\b", "書き方を隠す"),
    (r"\b(base64|binascii|codecs|marshal|pickle|zlib|ctypes|bz2|lzma)\b|(\\[xuU][0-9a-fA-F]{2}.*){3,}|\bchr\s*\(|"
     r"\bfromhex\b", "中身を隠す"),
    (r"\.git\b|\.github\b|credential|indexing-service-account|\btoken\b|\bsecret\b|password|private/|/proc/|\.ssh|"
     r"\.env\b|RUNNER_TEMP|GITHUB_", "鍵・資格・ワークフローの場所"),
    (r"\bshutil\.rmtree\b|\bos\.rmdir\b", "フォルダの削除"),
    # 文字列をつないで場所や名前を隠す（"/pr" + "oc/self/environ"・"indexing-service-" + "account.json" は上の
    # 「鍵・資格の場所」に当たらなかった。2026-10-20 の点検）
    (r"[\"']\s*\+\s*[rbfu]{0,2}[\"']", "文字列の連結（名前や場所を隠す）"),
    # ファイルへの書き込み・写し・移し（鍵を記事やデータへ写す・道具そのものを書き換える）。str の replace（引数2つ）は通し、
    # Path の replace（引数1つ＝ファイルの移し）だけを拾う
    (r"\.write_(text|bytes)\s*\(|\bopen\s*\((?:(?:[^()]|\([^()]*\))*,)?\s*(?:mode\s*=\s*)?[rbfu]{0,2}[\"'][rbt]*[wax+][rbtwax+]*[\"']|"
     r"\bshutil\.|\.rename\s*\(|\bos\.replace\s*\(|\.replace\s*\((?:[^,()]|\([^()]*\))*\)", "ファイルへの書き込み・写し"),
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
    code = sum(len(f["add"]) for f in fs if not f["odd"] and re.search(ALLOW[0][0], f["path"]))
    if code > MAX_CODE_ADDED:
        why.append(f"scripts/ に足した行が {code} 行（{MAX_CODE_ADDED} 行まで）")
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
        if CONTENT.search(p) or CONTENT.search(f["old"]):
            why.append(f"{p[:80]}: 記事・データの変更（点数や学びを書き換えると門を通らずに効く。人が確かめる）")
            continue
        kind = next((k for rx, k in ALLOW if re.search(rx, p)), None)
        if kind is None:
            why.append(f"{p}: 自動で取り込める場所ではない（scripts の既存の .py の変更・門の追加だけ）")
            continue
        if kind == "code" and f["new"]:
            why.append(f"{p}: scripts/ に新しいファイルを足している（既存のファイルの変更だけ取り込む）")
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
