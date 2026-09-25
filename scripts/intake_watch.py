# -*- coding: utf-8 -*-
"""記入済みのヒアリングシートを置くだけで、クライアントの運用を立ち上げる。

これまでは `client_intake.py <ファイル> --apply` を手で打つ必要があり、
ファイル名を指定し損ねたり、不備の確認を飛ばしたりしていた。

    intake/ に記入済みの .xlsx を置く → あとは自動

    python scripts/intake_watch.py            # 何が起きるかを見るだけ
    python scripts/intake_watch.py --apply    # 登録まで行う

置いたシートは、結果によって行き先が変わる。

    intake/done/  登録できたもの（会社IDを付けて保存）
    intake/todo/  不備があったもの。同じ名前の .不備.txt に直す箇所を書く

**不備のあるシートは登録しない。** 主力商材や一次情報が空のまま通すと、
どのサイトでも書ける記事が量産され、AI検索に引用されない。ここで止める。

日次のパイプラインからも呼ばれるので、シートを push すれば自動で拾われる。
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

IN = ROOT / "intake"
DONE = IN / "done"
TODO = IN / "todo"
MAX_SITES = 20   # 日次の枠は40（1社2本×20社）。pipeline-multi.yml の cron の本数÷2 と揃える


def sheets():
    """置かれた記入済みシート。Excelの一時ファイルと、処理済みは除く"""
    if not IN.is_dir():
        return []
    # 未記入の雛形は、置き場に残しておくもの。毎回「不備」として報告されると、
    # 本当に直すべきシートが埋もれる
    blank = {"データ記入シート.xlsx", "実績記入シート.xlsx", "ヒアリングシート.xlsx", "メニュー記入シート.xlsx"}
    return sorted(p for p in IN.glob("*.xlsx")
                  if not p.name.startswith(("~$", ".")) and p.name not in blank)


def site_count():
    return len([p for p in (ROOT / "sites").glob("*.json") if p.stem != "sample"])


def move(src, dst_dir, note=""):
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    n = 1
    while dst.exists():                      # 同名を上書きしない
        dst = dst_dir / f"{src.stem}({n}){src.suffix}"
        n += 1
    shutil.move(str(src), str(dst))
    if note:
        dst.with_suffix(".不備.txt").write_text(note, encoding="utf-8", newline="")
    return dst


def _tabs(src):
    """シートのタブ名。読めないものは空にして、従来どおり名前で振り分ける"""
    # read_only は必ず閉じる。開いたままだと、このあとの move で
    # 「別のプロセスが使用中です」になり、公開の途中で止まる
    try:
        from openpyxl import load_workbook
        wb = load_workbook(src, read_only=True)
        try:
            return set(wb.sheetnames)
        finally:
            wb.close()
    except Exception:
        return set()


def kind(src):
    """シートの種類。名前ではなくタブの構成で決める。
    ファイル名で振り分けていたため、一次データのシートがクライアント用の検査にかけられ
    毎回「不備23件」で弾かれたり、名前に「実績」「データ」を含むヒアリングシートが
    上限の判定をすり抜けたりしていた"""
    tabs = _tabs(src)
    # 実績・お客様の声の記入シートは会社の立ち上げではなく、一次情報と掲載の登録
    if tabs & {"経理BPOの効果", "継続率", "お客様の声"}:
        return "jisseki"
    # 多言語メニューのシート（訪日客向け）
    if "メニュー" in tabs:
        return "menu"
    if tabs >= {"概要", "データ"}:
        return "data"
    return "client"


def one(src, write, k=None):
    """シート1枚を見る。(登録できたか, 説明) を返す"""
    k = k or kind(src)
    if k == "jisseki":
        import jisseki_intake as J
        return J.one(src, write)
    if k == "menu":
        import menu_page as MP
        return MP.one(src, write)
    if k == "data":
        import data_intake as D
        return D.one(src, write)
    import client_intake as C
    try:
        got = C.read_sheet(src)
        cfg = C.to_config(got)
        ng, warn = C.review(got, cfg)
    except Exception as e:
        return False, "読めません（%s）" % str(e)[:80]

    name = cfg.get("name") or cfg.get("id") or src.stem
    if ng:
        note = ("このシートは登録していません。次を直して intake/ に戻してください。\n\n"
                + "\n".join("  - " + x for x in ng)
                + ("\n\n（警告）\n" + "\n".join("  - " + x for x in warn) if warn else "")
                + "\n")
        if write:
            move(src, TODO, note)
        return False, "%s: 不備%d件（intake/todo/ へ移しました）" % (name, len(ng))

    if not write:
        return True, "%s: 登録できます（--apply で実行）" % name

    ind = next((k for k, (lab, _) in C.INDUSTRY.items() if lab in src.name), "")
    C.apply(got, cfg, ind)
    move(src, DONE)
    return True, "%s（%s）を登録しました" % (name, cfg.get("id", "?"))


def main():
    ap = argparse.ArgumentParser(
        description="intake/ に置かれたヒアリングシートを読み込んで立ち上げる")
    ap.add_argument("--apply", action="store_true", help="登録まで行う")
    a = ap.parse_args()

    IN.mkdir(exist_ok=True)
    found = sheets()
    print("■ ヒアリングシートの取り込み（%s）" % IN.relative_to(ROOT).as_posix())
    if not found:
        print("   置かれているシートはありません")
        print("   記入用シートを作る: python scripts/client_intake.py --sheet")
        print("INTAKE=none")
        return 0

    before = site_count()
    ok = ng = 0
    for p in found:
        k = kind(p)
        # 上限を超えて受け入れると、記事の枠が足りず全社の本数が減る。
        # 受け入れる前に止めて、別リポジトリへ分ける判断をしてもらう。
        # 数えるのはクライアントのシートだけ、しかも実際のサイト数で。
        # 「登録できた件数」で数えていたため、一次データや実績のシートが通るたびに
        # クライアントのシートが保留にされていた
        if a.apply and k == "client" and site_count() >= MAX_SITES:
            print("   %-28s 保留（%d社が上限です）" % (p.name[:28], MAX_SITES))
            ng += 1
            continue
        good, why = one(p, a.apply, k)
        print("   %s %s" % ("○" if good else "×", why))
        ok, ng = ok + good, ng + (not good)

    after = site_count()
    print("\n   登録 %d件 / 見送り %d件（サイト数 %d → %d）" % (ok, ng, before, after))
    if after > MAX_SITES:
        print("INTAKE=over")
        print("   ::error::サイトが%d件になりました。この仕組みは%d社までです。"
              "%d社目からは別リポジトリに分けてください" % (after, MAX_SITES, MAX_SITES + 1))
    elif ng:
        print("INTAKE=ng")
        print("   不備のあるシートは intake/todo/ にあります。"
              "同じ名前の .不備.txt に直す箇所を書きました")
    else:
        print("INTAKE=ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
