# -*- coding: utf-8 -*-
"""配信先に元からある記事と重複した自作の記事を、機械で取り下げて既存の記事へ301で送る。

日次の監査（daily_audit の「既存記事と重複」）が毎日 TODO に出すが、公開済みの記事は救済の AI に消させない
（AI は外の文章を読むので、仕込まれた指示で関係ない記事を消しうる）。取り下げは AI ではなく、実績で決めてここが行う
（2026-10-11 運用者「自動的に直して」）。

決め方（cannibal_check.external_dup_check と同じ材料）:
  - 題名が似ていて、Search Console で同じ検索語に両方が出ている（verdict=conflict）組だけ。似ているだけの組は触らない
  - 既存の記事が先にあるので自作側を外す。ただし自作側の表示が既存側の3倍以上なら、自作側のほうが強いので残す（知らせるだけ）
  - 1回に3本まで（検出器が誤ったときに一度に多くを消さない）

取り下げ方は統合（auto_merge）と同じ: 原稿を articles/_merged/ へ移し、内部リンクを既存の記事へ付け替え、
data/retractions.jsonl に積む（配信先から外して301を書くのは retract.py --pending --push）。管制塔の語は「対象外」にする。

    python scripts/dup_retract.py            # 何をするかを見る
    python scripts/dup_retract.py --write    # 取り下げる
出す印: DUP_RETRACT_OK=yes（取り下げる組が無い・取り下げた）/ no（取り下げられなかった）/ unknown（判定の材料が取れない）
"""
import argparse
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LIMIT = 3
STRONGER = 3


def plan(hits):
    """[(hit, 'retract' | 'keep', 理由)]"""
    out = []
    for h in hits:
        if h.get("verdict") != "conflict":
            continue
        a, b = h.get("imp") or (0, 0)
        if b and a >= STRONGER * b:
            out.append((h, "keep", f"自作側の表示が既存側の{STRONGER}倍以上（自作{a}回 / 既存{b}回）のため残します"))
        else:
            out.append((h, "retract", f"同じ語に両方が出ています（表示 自作{a}回 / 既存{b}回）。既存が先にあるため自作側を外します"))
    return out


def retract(h, root=ROOT, today=None):
    """1組を取り下げる。(from_url, to_url) を返す"""
    import auto_merge as AM
    today = today or date.today().isoformat()
    site, slug = h["site"], h["mine"]["slug"]
    src = root / "articles" / f"{slug}.md"
    from_url = AM.url_of(site, slug)
    to_url = urlparse(h["theirs"]["url"]).path or "/"
    merged = root / "articles" / "_merged"
    merged.mkdir(parents=True, exist_ok=True)
    t = src.read_text(encoding="utf-8-sig")
    t = t.replace("---\n", f"---\nretracted_for: {h['theirs']['url']}\nmerged_at: {today}\n", 1)
    (merged / f"{slug}.md").write_text(t, encoding="utf-8", newline="")
    src.unlink()
    AM.relink(site, from_url, to_url, "")
    AM._append(AM.RETRACT, {"site": site, "slug": slug, "from": from_url, "to": to_url, "at": today,
                            "survivor": h["theirs"].get("slug", ""), "reason": "既存記事と重複: 自作側を取り下げ"})
    return from_url, to_url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=LIMIT)
    a = ap.parse_args()
    import cannibal_check
    import private_store as PS
    try:
        hits = cannibal_check.external_dup_check()
    except Exception as e:
        print(f"DUP_RETRACT_OK=unknown（重複の判定ができませんでした: {type(e).__name__}）")
        return 0
    todo = plan(hits)
    print(f"\n■ 既存記事と重複した自作の記事: 取り下げ {sum(1 for _, d, _ in todo if d == 'retract')}組・"
          f"残す {sum(1 for _, d, _ in todo if d == 'keep')}組")
    done, failed = 0, 0
    for h, decision, why in todo:
        name = PS.shown(h["mine"]["slug"])
        if decision == "keep":
            print(f"  ― {name}: {why}")
            continue
        if not a.write or done >= a.limit:
            print(f"  ・{name}: {why}" + ("" if a.write else "（--write で取り下げ）"))
            continue
        try:
            retract(h)
            done += 1
            print(f"  ○ {name}: 取り下げました（{why}）")
        except Exception as e:
            failed += 1
            print(f"  × {name}: 取り下げられませんでした（{type(e).__name__}）")
            continue
        kw = h["mine"].get("kw") or ""
        if kw:
            try:
                import hub_client
                if hub_client.enabled():
                    hub_client.retire_kw(h["site"], [kw], "既存記事と重複したため取り下げ", force=True)
            except Exception as e:
                print(f"     （管制塔の語を対象外にできませんでした: {type(e).__name__}）")
    if failed:
        print(f"DUP_RETRACT_OK=no（{failed}本を取り下げられませんでした）")
        print(f"要対応: 既存記事と重複した自作の記事 {failed}本を取り下げられませんでした（dup_retract のログを確認）")
    else:
        print("DUP_RETRACT_OK=yes" + (f"（{done}本を取り下げ）" if done else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
