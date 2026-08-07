# -*- coding: utf-8 -*-
"""次に書くKWで一次情報を集める（ワークフローから1行で呼ぶため）

使い方: python scripts/research_next.py <site_id>

台帳から次のKWを引き、research.py に渡すだけ。
ワークフローにPythonを直書きするとYAMLのインデントが崩れるため、ここに置く。
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) < 2:
        raise SystemExit("使い方: python scripts/research_next.py <site_id>")
    site_id = sys.argv[1]

    kw = ""
    try:
        import hub_client
        kw = ((hub_client.next_kw(site_id) or {}).get("keyword") or "").strip()
    except Exception as e:
        print(f"（台帳から次のKWを取得できませんでした: {e}）")

    if not kw:
        # 台帳が使えないときはローカルのKW計画から拾う（収集を止めない）
        try:
            import site_brief
            import sites as sites_mod
            cands = site_brief.local_next_kw(sites_mod.load(site_id), limit=1)
            kw = cands[0]["keyword"] if cands else ""
        except Exception:
            pass

    if not kw:
        print("次のKWが分からないため、一次情報の収集をスキップします")
        return

    print(f"収集対象: {kw}")
    subprocess.run([sys.executable, "scripts/research.py", kw, "--site", site_id], cwd=ROOT)


if __name__ == "__main__":
    main()
