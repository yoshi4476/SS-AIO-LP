# 問い合わせを管制塔へ集約する（GAS設定手順）

3サイトの問い合わせが、それぞれ別のスプレッドシートに分散している。
`forward-to-hub.gs` を各サイトの Apps Script に追加すると、管制塔スプレッドシート1冊にも
コピーが集まる。作業は**コーポレートと補助金サイトの2か所**（AI集客ラボは管制塔と同じ処理系のため不要）。

## なぜ「送信先の変更」ではなく「転送」なのか

コーポレートには送信者への自動返信、補助金には重複検出・リードスコアリング・Slack通知・
種別ごとの自動返信3文面がある。送信先を管制塔に付け替えるとこれらが全て止まる。
既存の処理はそのまま残し、**コピーだけを送る**。管制塔が落ちても各サイトの受付は止まらない。

## 貼り付けるコード

`automation/gas/forward-to-hub.ready.gs` を使う。
管制塔のURLと合言葉を**埋め込み済み**なので、そのまま貼れば動く。

> このファイルは合言葉を含むため Git 管理から外してある。共有やコミットはしないこと。
> 紛失した場合は `automation/gas/forward-to-hub.gs` の `XXXX` 部分を `.env` の
> `HUB_URL` / `HUB_SECRET` で置き換えれば同じものが作れる。

---

## 手順1: コーポレートサイト

1. コーポレートの問い合わせ用スプレッドシートを開く
2. メニュー **拡張機能 → Apps Script**
3. 左「ファイル」の **＋ → スクリプト**、名前を `forward-to-hub` にする
4. `forward-to-hub.ready.gs` の中身を**全て**貼り付けて保存
5. 既存の `contact-endpoint.gs`（または コード.gs）を開き、`doPost` の中の
   **シート保存が終わった直後**に次の1行を足す

```javascript
    if (SHEET_ID) {
      appendRow([
        new Date(), site.label, payload.type, name,
        payload.company, email, payload.tel, payload.service, message,
      ]);
    }

    forwardToHub_(payload, 'corporate');   // ← この1行を追加

    return json({ ok: true });
```

6. 保存 → **デプロイ → デプロイを管理 → 鉛筆アイコン → バージョン「新バージョン」→ デプロイ**

## 手順2: AI導入補助金サイト

1. 補助金サイトの問い合わせ用スプレッドシートを開く
2. 同じく **拡張機能 → Apps Script** → **＋ → スクリプト** → `forward-to-hub`
3. `forward-to-hub.ready.gs` の中身を貼り付けて保存
4. `form-endpoint.gs`（または コード.gs）の `doPost` の中、
   **`saveToSheet_(lead)` を含む try/finally ブロックが終わった直後**に足す

```javascript
  } finally {
    try { lock.releaseLock(); } catch (e2) {}
  }

  forwardToHub_(lead, 'subsidy');   // ← この1行を追加

  // ---- 通知の二重化 ----
```

5. 保存 → **デプロイ → デプロイを管理 → 鉛筆 → 新バージョン → デプロイ**

---

## 動作確認

各プロジェクトの Apps Script エディタで、関数一覧から `testForwardToHub` を選んで**実行**。
初回は権限の承認を求められるので許可する。

管制塔スプレッドシートの「問い合わせ」シートに1行増えていれば成功。
増えない場合は Apps Script の**実行数**（左メニュー）でエラー内容を確認する。

## つまずきやすい点

| 症状 | 原因 |
|:--|:--|
| 転送されない | デプロイし直していない。コードを保存しただけでは反映されない |
| 通知メールが2通届く | `silent: true` が外れている。ready版はそのままで正しい |
| `forwardToHub_ is not defined` | ファイルを追加したプロジェクトと、doPost があるプロジェクトが別 |
| 権限エラー | `testForwardToHub` を一度手動実行して承認する |

## 済んだ後

3サイトの問い合わせが管制塔スプレッドシートに集まる。
各サイトのシートにも従来どおり残るので、これまでの運用は変えなくてよい。
