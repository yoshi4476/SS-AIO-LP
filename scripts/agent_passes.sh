#!/usr/bin/env bash
# 記事を書く AI（claude -p）を、範囲（自社の社・お客様の社ごと）を絞って1回ずつ動かす（救済・週次・自動修復の書き直し）。
# 範囲ごとに: 作業場所に置くお客様の社をその範囲だけにする → その範囲だけに効く管制塔の通行証を渡す → AI →
# 範囲の外の記事を触った分を戻す。最後に全部へ戻す。A社の回の AI がB社のまだ公開していない原稿・材料・狙う語を
# 読めないようにする（2026-10-11 運用者「ほかの社の原稿も見られないように」）。
# 鍵を持たない AI の手順から呼ぶ。範囲の一覧と通行証は、鍵のある「鍵を外す」手順が $RUNNER_TEMP に置く。
#
#   bash scripts/agent_passes.sh <指示書> <最大のターン数> [claude に渡す追加の引数…]
set -u
prompt_file="$1"
turns="$2"
shift 2
scopes=$(cat "$RUNNER_TEMP/agent_scopes" 2>/dev/null || echo own)
for sc in $scopes; do
  python scripts/private_store.py --scope "$sc"
  python scripts/agent_guard.py --checkpoint
  HUB_AGENT_TOKEN="$(cat "$RUNNER_TEMP/hub_tokens/$sc" 2>/dev/null || true)"
  export HUB_AGENT_TOKEN
  if [ "$sc" = "own" ]; then
    note="この回の対象は自社の社だけです（作業場所にお客様の社はありません）。"
  else
    note="この回の対象は、作業場所にあるお客様の社だけです。自社の社の TODO・記事はこの回では扱いません（別の回で行います）。"
  fi
  # 使える道具は許可の一覧（automation/agent_settings_article.json）だけ。Linux では Glob・Grep を名指ししないと探せない
  claude -p "$(cat "$prompt_file")

【この回の範囲】${note}" --permission-mode dontAsk --allowedTools "Glob,Grep" --settings automation/agent_settings_article.json \
    --max-turns "$turns" "$@" || echo "::warning::AI の回が失敗しました（次の範囲へ続けます）"
  python scripts/agent_guard.py --protect --site "$sc" --pass
done
python scripts/private_store.py --scope all
