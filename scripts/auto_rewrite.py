# -*- coding: utf-8 -*-
"""「人が判断すること」として残っていた直しを、機械に任せる。

auto_improve は、タイトルの書き換えと検索意図の見直しを人へ回していた。
理由は「正規表現で当てると主張のずれた記事が量産される」から。これは正しい。
ただし記事本体はすでに無人の claude が書いている。同じ仕組みに検算を付ければ、
ここも任せられる。判断は claude がし、**通してよいかは機械が決める**。

流れ:
  1. auto_improve が挙げた対象を1本取る
  2. claude -p に、その1本だけを直させる（何を守るかを渡す）
  3. 検算する。1つでも崩れたら git checkout で元に戻す
  4. 台帳に残す

検算（1つでも外れたら書き込まない）:
  - 触ったファイルがその1本だけか
  - 狙う語（keyword）が変わっていないか
  - タイトルが15〜45字で、狙う語を含むか
  - 本文の数字が増えていないか（**数字を作らせない**。減るのは可）
  - 外部の出典リンクが消えていないか
  - score_check の警告が増えていないか
  - kw_guard が通るか（既存記事との食い合いを作らない）
  - build.py が通るか

  python scripts/auto_rewrite.py              # 何を直すか見る
  python scripts/auto_rewrite.py --write      # 実際に直す（既定3本）
  python scripts/auto_rewrite.py --write --limit 1
"""
import argparse
import collections
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"
TITLE_MIN, TITLE_MAX = 15, 45


def sh(args, timeout=1800):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="ignore", timeout=timeout)


def aio_items():
    """1ページ目にいるのに AI Overview に答えを取られている疑いの記事（最優先）。

    ai_citation_check が月ごとに data/ai_citations/YYYY-MM.json に残す。
    順位はあるのにクリックが期待の半分未満＝AIが答えを出し、自社は引用されていない。
    直す手は「そこにしか無い情報」を先頭に置くこと（第8.2章の最高優先度）
    """
    files = sorted((ROOT / "data" / "ai_citations").glob("*.json"))
    if not files:
        return []
    try:
        d = json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return []
    out, seen = [], set()
    for sid, s in (d.get("sites") or {}).items():
        for it in s.get("items") or []:
            slug = (it.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
            if not slug or slug in seen or not (ROOT / "articles" / f"{slug}.md").is_file():
                continue
            seen.add(slug)
            out.append({"kind": "aio", "slug": slug, "site": sid,
                        "why": (f"{it.get('pos', 0):.1f}位・表示{it.get('imp', 0)}・CTR{it.get('ctr', 0)}%"
                                f"（目安{it.get('expected_ctr', 0)}%）｜「{it.get('kw', '')}」でAI Overviewに答えを取られている疑い")})
    return out


def targets():
    """直すべき記事を、効く順に受け取る。

    最優先は「1ページ目にいるのに AI Overview に取られている」記事（aio_items）。
    次に rank_up の「4〜10位でクリックが取れていない」。無ければ auto_improve の一覧。
    """
    head = aio_items()
    try:
        import rank_rescue as RR
        # 11〜30位で止まり、需要のある語に答えていない記事。表示が多い順に来る
        seen0 = {x["slug"] for x in head}
        head = head + [x for x in RR.items() if x["slug"] not in seen0]
    except Exception as e:
        print(f"  （rank_rescue から取れません: {str(e)[:50]}）")
    try:
        import rank_up
        items = rank_up.human_items()
        if items or head:
            seen = {x["slug"] for x in head}
            return head + [x for x in items if x["slug"] not in seen]
    except Exception as e:
        print(f"  （rank_up から取れないため auto_improve を使います: {str(e)[:40]}）")
    import auto_improve as ai
    try:
        return ai.human_items()
    except AttributeError:
        # auto_improve が一覧を返さない版のときは、出力から拾う
        r = sh([sys.executable, "scripts/auto_improve.py"])
        out = []
        for m in re.finditer(r"\[(title|review)\]\s+(\S+)\s+(.*)", r.stdout or ""):
            out.append({"kind": m.group(1), "slug": m.group(2), "why": m.group(3).strip()})
        return out


PROMPT = """articles/{slug}.md を直してください。この1ファイル以外は触らないでください。

直す理由: {why}

{what}

必ず守ること:
- 事実を変えない。数字・社名・出典・年月日は1文字も変えない。**新しい数字を書かない**
- 外部の出典リンク（href="http…"）を消さない
- ですます調。1文は50字を目安、100字を超えない
- フロントマターの keyword は変えない
- 記事の主張をずらさない。読者が求めている答えを先に書く

直したら、変更点を1行で説明して終了してください。"""

WHAT = {
    "title": ("フロントマターの title・description と、H1相当の書き出しを\n"
              "見直してください。検索結果に出るのはタイトルと説明文の両方で、\n"
              "説明文だけを直しても、タイトルだけを直しても効きません。\n"
              "この記事は表示されているのにクリックされていません。検索結果に並ぶ他の\n"
              "ページと同じことを言っているためです。**検索結果に出せないもの**\n"
              "（違反になる例・失敗した事例・自社で実際に測った数字）をタイトルの前半に置いて\n"
              "ください。15〜45字。狙う語（keyword）は必ず残すこと。\n"
              "description は60〜160字。狙う語を含め、タイトルで言っていないことを書く\n"
              "（同じ文言を繰り返すと、検索結果で見える情報量が半分になる）。\n"
              "本文にない内容をタイトルや説明文に書かないこと（書くなら本文にも追記する）。"),
    "aio": ("この記事は検索1ページ目にいるのに、AI Overview（AIによる概要）が答えを出してしまい、\n"
            "クリックされていません。AIが引用するのは「そこにしか無い情報」です。\n"
            "1. 冒頭200字を、下に示す自社の一次情報（実数）を含む断言型の回答に書き直す\n"
            "2. 狙う語に対する答えを、40〜60字の1文＋比較表（または手順表）で本文の最初のH2直下に置く\n"
            "3. 「失敗例・注意点」の見出しに、一次情報から言える具体例を1つ足す\n"
            "4. FAQ の最初の1問を、狙う語そのものの質問にし、回答に一次情報の数字を1つ入れる\n"
            "使ってよい自社の一次情報（**この数字以外の新しい数字は書かない**）:\n{facts}"),
    "stuck": ("この記事は検索1ページ目の手前（11〜30位）で止まっています。\n"
              "**実際に検索されている語に、記事が答えていない**のが原因です。\n"
              "下に、その語と順位・表示回数を挙げます。\n"
              "1. その語が扱う内容が、この記事の主題に**本当に含まれるか**を最初に判断する\n"
              "   含まれないなら、何も変えずに終了する（無理に足すと主題がぼやけて、\n"
              "   いま取れている順位まで落ちる）\n"
              "2. 含まれるなら、その語に答える**H2またはH3の節を1つ足す**。\n"
              "   見出しにその語を自然な日本語で入れ、直下に40〜60字の1文結論を置く\n"
              "3. 語を本文にちりばめる直し方はしないこと。読者が読んで意味のある\n"
              "   節になっていなければ順位は動かない\n"
              "4. 既存の見出し・本文は消さない。足すだけにする\n"
              "5. 同義語・言い換え（例: 整骨院と接骨院）なら別々の節を作らず、\n"
              "   1つの節でまとめて扱い、両方の呼び方を本文に書く\n"),
    "review": ("直前の自動修正で表示回数が落ちています。検索意図とずれた可能性があります。\n"
               "冒頭200字と各H2直下の1文結論を読み、狙う語で検索した人が求めている答えに\n"
               "なっているか確かめてください。ずれていれば直してください。\n"
               "ずれていなければ何も変えずに終了してください（無理に直さない）。"),
}


def claude_bin():
    """claude の実行ファイルを解決する。

    Windows では `claude` は claude.cmd として入るため、名前だけを
    subprocess に渡すと WinError 2 になる（CreateProcess は PATHEXT を
    探さない）。Linux の CI では通るので、手元だけで落ちて気づきにくい。
    """
    import shutil
    return shutil.which("claude") or shutil.which("claude.cmd") or "claude"


def warns(slug):
    r = sh([sys.executable, "scripts/score_check.py", slug], timeout=300)
    return [l for l in (r.stdout or "").splitlines() if l.startswith("WARN")]


def meta(slug):
    t = (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")
    fm = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
    fm = fm.group(1) if fm else ""
    g = lambda k: (re.search(rf"^{k}:\s*(.+)$", fm, re.M) or [0, ""])[1].strip().strip('"')
    return g("title"), g("keyword"), t


def numbers(s):
    return collections.Counter(re.findall(r"[0-9０-９][0-9０-９,，.．%％]*", s))


def sources(s):
    return set(re.findall(r'href="(https?://[^"]+)"', s))


def snapshot():
    """articles/ の指紋。「触ったのはこの1本だけか」を、git ではなく直前の状態と比べる。

    週次では link_boost・rank_up・split_paragraphs が先に記事を直し、その分は
    まだコミットされていない。git status と比べると、その未コミットの記事が
    「別の記事まで変わっている」と見なされ、正しい書き換えまで毎回戻していた"""
    import hashlib
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in (ROOT / "articles").glob("*.md")}


def changed_since(snap):
    now = snapshot()
    return sorted(n for n in set(snap) | set(now) if snap.get(n) != now.get(n))


def check(slug, before, before_warns, snap=None, allowed="", terms=()):
    """直した結果を検算する。通らない理由を返す（空なら合格）"""
    if snap is not None:
        other = [c for c in changed_since(snap) if c != f"{slug}.md"]
    else:
        changed = [l[3:].strip() for l in
                   (sh(["git", "status", "--porcelain", "--", "articles"]).stdout or "").splitlines()]
        other = [c for c in changed if c != f"articles/{slug}.md"]
    if other:
        return f"別の記事まで変わっています: {', '.join(other[:3])}"

    title, kw, after = meta(slug)
    _, kw0, _ = before
    if kw != kw0:
        return f"狙う語が変わりました（{kw0} → {kw}）"
    if not (TITLE_MIN <= len(title) <= TITLE_MAX):
        return f"タイトルが{len(title)}字（{TITLE_MIN}〜{TITLE_MAX}字）"
    parts = [w for w in re.split(r"[\s　]+", kw) if len(w) >= 2]
    if parts and not any(w.lower() in title.lower() for w in parts):
        return f"タイトルに狙う語が入っていません（{kw}）"

    b = before[2]
    new_nums = numbers(after) - numbers(b) - numbers(allowed or "")
    if new_nums:
        return f"本文に無かった数字が増えました: {dict(list(new_nums.items())[:4])}"
    lost = sources(b) - sources(after)
    if lost:
        return f"出典リンクが消えました: {list(lost)[:2]}"

    now = warns(slug)
    if len(now) > len(before_warns):
        return f"警告が増えました（{len(before_warns)} → {len(now)}）"

    # --exclude-slug を必ず渡す。渡さないと、その記事自身が食い合い相手として
    # 数えられ、順位を持つ記事のリライトは100%差し戻される。
    # 実際 kw_guard は「狙う語が既存記事と完全一致: meo-algorithm-kouryaku」と
    # 自分自身を挙げて終了コード2を返していた（2026-09-22 に発見）
    r = sh([sys.executable, "scripts/kw_guard.py", kw, "--site",
            site_of(slug), "--title", title, "--exclude-slug", slug], timeout=600)
    if r.returncode:
        return f"既存記事と食い合います（kw_guard 終了コード{r.returncode}）"

    if terms:
        # 「足した」と言いながら見出しが変わっていないものを通さない。
        # 本文にちりばめるだけの直し方では順位は動かない
        heads = " ".join(re.findall(r"^#{2,4}\\s*(.+)$", after, re.M)).lower()
        if not any(x.lower() in heads for x in terms):
            return "狙った語が見出しに入っていません（" + "/".join(terms[:3]) + "）"
        if len(after) < len(b) * 0.98:
            return f"本文が減りました（{len(b)}→{len(after)}字）。足す直しのはずです"

    r = sh([sys.executable, "scripts/build.py"], timeout=1800)
    if r.returncode or "BLOCKED" in (r.stdout or ""):
        return "ビルドが通りません"
    return ""


def site_of(slug):
    import sites as S
    t = (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")
    cat = (re.search(r"^category:\s*(.+)$", t, re.M) or [0, ""])[1].strip()
    return S.find_category_owner(cat) or "ai-lab"


def hub_rewrite_log(item, why):
    """管制塔の「リライトログ」に残す。手元の台帳（auto_fix.jsonl）だけだと、
    シートを見る人には直した記録が1件も見えなかった（4行しか無かった）"""
    try:
        import hub_client
        if not hub_client.enabled():
            return
        m = re.search(r"(\d+(?:\.\d+)?)位", item.get("why", ""))
        hub_client.rewrite_log(item.get("site", ""), item["slug"],
                               reason=f"{item['kind']}: {item.get('why', '')[:60]}",
                               summary=why[:80], pos_before=(m.group(1) if m else ""))
        # rank_up --effect が前後を比べる台帳にも残す。ここに無いと後順位が永遠に空欄のまま
        if m:
            import rank_up
            log = rank_up.load_log()
            log[item["slug"]] = {"at": time.strftime("%Y-%m-%d"), "pos": float(m.group(1)),
                                 "site": item.get("site", ""), "by": "auto_rewrite"}
            rank_up.save_log(log)
    except Exception as e:
        print(f"     （管制塔への記録をスキップ: {str(e)[:60]}）")


def note(slug, kind, ok, why):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"),
                            "by": "auto_rewrite", "slug": slug, "kind": kind,
                            "ok": ok, "note": why}, ensure_ascii=False) + "\n")


def run_one(item, write):
    slug, kind = item["slug"], item["kind"]
    p = ROOT / "articles" / f"{slug}.md"
    if not p.is_file():
        return False, "記事がありません"
    if write:
        import shutil
        if not (shutil.which("claude") or shutil.which("claude.cmd")):
            return False, "claude が見つかりません（npm install -g @anthropic-ai/claude-code）"
    if not write:
        return True, "（確認のみ）"

    before, before_warns, snap = meta(slug), warns(slug), snapshot()
    allowed = ""
    what = WHAT[kind]
    if kind == "aio":
        import facts as F
        _, fs = F.load_for(item.get("site") or site_of(slug))
        allowed = "\n".join(f"- {f.get('claim', '')}" for f in fs if f.get("claim"))
        what = what.format(facts=allowed or "（登録された一次情報がありません。数字は足さないでください）")
    prompt = PROMPT.format(slug=slug, why=item["why"], what=what)
    # 権限を全部飛ばすのではなく、使える道具を読み書きだけに絞る。
    # この工程がやるのは1ファイルの書き換えだけで、コマンド実行も外部通信も要らない
    exe = claude_bin()
    r = sh([exe, "-p", prompt, "--max-turns", "40",
            "--allowedTools", "Read,Edit"], timeout=1800)
    if r.returncode and not p.read_text(encoding="utf-8-sig") != before[2]:
        return False, f"claude が動きませんでした（{(r.stderr or '')[:60]}）"

    if p.read_text(encoding="utf-8-sig") == before[2]:
        return True, "変更なし（直す必要なしと判断）"

    ng = check(slug, before, before_warns, snap, allowed,
               item.get("terms") or ())
    if ng:
        sh(["git", "checkout", "--", f"articles/{slug}.md"])
        sh([sys.executable, "scripts/build.py"], timeout=1800)
        return False, ng
    return True, f"直しました（{before[0][:24]}… → {meta(slug)[0][:24]}…）"


def selftest():
    """検算が本当に効くかを、本番の記事で確かめる。

    claude を呼ばずに、こちらで「やってはいけない書き換え」を当てて、
    検算が止めるかを見る。止まらなければ、その穴から壊れた記事が通る。
    最後は必ず git checkout で元に戻す。
    """
    import auto_improve  # 対象の取り方まで含めて試す
    items = targets()
    if not items:
        print("  対象がないため、記事を1本選んで試します")
        items = [{"kind": "title", "slug": sorted(
            p.stem for p in (ROOT / "articles").glob("*.md"))[0], "why": "自己診断"}]
    slug = items[0]["slug"]
    p = ROOT / "articles" / f"{slug}.md"
    orig = p.read_text(encoding="utf-8-sig")
    before, before_warns, snap = meta(slug), warns(slug), snapshot()
    title, kw, body = before

    # やってはいけない書き換えを、1つずつ当てる
    cases = [
        ("無かった数字を書く", body.replace("。", "。前年比12.7%増です。", 1)),
        ("出典リンクを消す",
         re.sub(r'<a href="https?://[^"]+"[^>]*>(.*?)</a>', r"\1", body, count=1)),
        ("狙う語を変える", body.replace(f"keyword: {kw}", "keyword: 別の語", 1)),
        ("タイトルを短くしすぎる",
         body.replace(f"title: {title}", "title: 短い", 1)),
    ]
    # stuck 種別の検算は terms を渡したときだけ効く。別に試す
    stuck_cases = [
        ("語を本文にちりばめるだけ（見出しに入れない）",
         body + chr(10) + "この記事は接骨院にも当てはまります。" + chr(10), ("接骨院",)),
        ("見出しに入れたが本文を削る",
         body[:len(body) // 2] + chr(10) + "## 接骨院の場合" + chr(10), ("接骨院",)),
    ]
    ok = 0
    try:
        for name, broken, terms in stuck_cases:
            p.write_text(broken, encoding="utf-8", newline="")
            ng = check(slug, before, before_warns, snap, "", terms)
            print(f"  {'OK' if ng else 'NG'}  {name}: "
                  + (f"止めた（{ng[:44]}）" if ng else "素通りしました"))
            ok += bool(ng)
            p.write_text(orig, encoding="utf-8", newline="")
        for name, broken in cases:
            if broken == body:
                print(f"  --  {name}: この記事では試せません")
                continue
            p.write_text(broken, encoding="utf-8", newline="")
            ng = check(slug, before, before_warns, snap)
            print(f"  {'OK' if ng else 'NG'}  {name}: "
                  + (f"止めた（{ng[:44]}）" if ng else "素通りしました"))
            ok += bool(ng)
            p.write_text(orig, encoding="utf-8", newline="")
    finally:
        p.write_text(orig, encoding="utf-8", newline="")
        sh([sys.executable, "scripts/build.py"], timeout=1800)
    total = len(cases) + len(stuck_cases)
    print(f"\n  {ok}/{total} を止めました（記事は元に戻しました）")
    return 0 if ok == total else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=3, help="1回に直す本数")
    # 1本あたり最大30分かかる。本数だけ増やすとCIの時間上限で途中終了し、
    # 直した分がcommitされずに捨てられる。残り時間を見て、次を始めない
    ap.add_argument("--budget-min", type=int, default=0,
                    help="この分数を超えたら、次の記事に着手しない（0=無制限）")
    ap.add_argument("--selftest", action="store_true",
                    help="検算が効くかを本番の記事で確かめる（claudeは呼ばない）")
    a = ap.parse_args()

    if a.selftest:
        print("■ 検算の自己診断（やってはいけない書き換えを当てて、止まるか見る）\n")
        return selftest()

    items = targets()
    print(f"■ 人の判断に回っていた直し: {len(items)}件"
          + (f"（1回に{a.limit}本まで）\n" if a.write else "\n"))
    if not items:
        print("  対象がありません")
        return 0
    if not a.write:
        for x in items[:12]:
            print(f"  [{x['kind']}] {x['slug'][:36]:<36} {x['why'][:40]}")
        print("\n  --write を付けると claude が直し、機械が検算します"
              "（通らなければ元に戻します）")
        return 0

    ok = ng = 0
    started = time.time()
    for x in items[:a.limit]:
        used = (time.time() - started) / 60
        if a.budget_min and used >= a.budget_min:
            print(f"\n  {used:.0f}分使ったので、ここで止めます"
                  f"（残りは次回。上限{a.budget_min}分）")
            break
        good, why = run_one(x, True)
        print(f"  {'○' if good else '×'} [{x['kind']}] {x['slug'][:34]:<34} {why[:56]}")
        note(x["slug"], x["kind"], good, why)
        if good and why.startswith("直しました"):
            hub_rewrite_log(x, why)
        ok, ng = ok + good, ng + (not good)
    print(f"\n  直した {ok}件 / 戻した {ng}件 / {(time.time() - started) / 60:.0f}分")
    print("  台帳: automation/logs/auto_fix.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
