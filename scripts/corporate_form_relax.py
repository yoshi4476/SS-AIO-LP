# -*- coding: utf-8 -*-
"""コーポレートの問い合わせフォームで「会社名」を必須から外す。

実測（28日）: フォームを開いた7人のうち送信は1人。必須は 名前・会社名・メール・
相談内容（選択）・同意 の5つで、会社名は個人事業主や検討初期の人には書きにくい。
届いた後に聞けば済む項目なので必須から外す。効果は funnel（開いた→送信）で翌月に見る。

  python corp_form.py          # 同期 → 直す → 差分を見る（押さない）
  python corp_form.py --push   # 配信先（SS-CorporateHP）へ commit + push
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\user\Desktop\システム開発\SSオウンドメディア（AIO）")
sys.path.insert(0, str(ROOT / "scripts"))

OLD = '''          <LabelText text="会社名・店舗名" required />
          <input required name="company" autoComplete="organization" placeholder="株式会社◯◯" className={inputCls} disabled={busy} />'''
NEW = '''          <LabelText text="会社名・店舗名（任意）" />
          <input name="company" autoComplete="organization" placeholder="株式会社◯◯（個人の方は空欄で構いません）" className={inputCls} disabled={busy} />'''


def main():
    import publish
    import sites as S
    cfg = S.load("corporate")
    token = publish._push_token()
    dest = publish.ensure_clone(cfg, token)
    p = dest / "src" / "components" / "ContactForm.tsx"
    t = p.read_text(encoding="utf-8")
    if NEW in t:
        print("すでに任意になっています")
    else:
        assert OLD in t, "差し込み位置が見つかりません（フォームが変わっています）"
        p.write_text(t.replace(OLD, NEW, 1), encoding="utf-8", newline="\n")
        print("会社名を任意にしました")
    print(subprocess.run(["git", "diff", "--stat"], cwd=dest, capture_output=True, text=True,
                         encoding="utf-8").stdout.strip())
    if "--push" not in sys.argv:
        print("押していません（--push で配信）")
        return
    subprocess.run(["git", "add", "src/components/ContactForm.tsx"], cwd=dest, check=True)
    subprocess.run(["git", "-c", "user.name=AIO Pipeline Bot", "-c", "user.email=noreply@7senses.co.jp",
                    "commit", "-q", "-m", "問い合わせフォームの会社名を任意にする（開いた7人中1人しか送っていなかった）"],
                   cwd=dest, check=True)
    env = publish.git_auth(token)
    r = subprocess.run(["git", "push", f"https://x-access-token@github.com/{cfg['repo']}.git",
                        f"HEAD:{cfg['branch']}"], cwd=dest, env=env, capture_output=True, text=True)
    print("push:", "OK" if r.returncode == 0 else "NG")
    if r.returncode != 0:
        print(r.stderr[-300:].replace(token or "@@", "***"))


if __name__ == "__main__":
    main()
