#!/usr/bin/env bash
# 記事を書く AI（claude -p）を、範囲（自社の社・お客様の社ごと）を絞って1回ずつ動かす（救済・週次・自動修復の書き直し）。
# 範囲ごとに: 作業場所に置くお客様の社をその範囲だけにする → その範囲だけに効く管制塔の通行証を渡す → AI →
# 範囲の外の記事を触った分を戻す。最後に全部へ戻す。A社の回の AI がB社のまだ公開していない原稿・材料・狙う語を
# 読めないようにする（2026-10-11 運用者「ほかの社の原稿も見られないように」）。
# 鍵を持たない AI の手順から呼ぶ。範囲の一覧と通行証は、鍵のある「鍵を外す」手順が $RUNNER_TEMP に置く。
#
#   bash scripts/agent_passes.sh <指示書> <最大のターン数> [claude に渡す追加の引数…]
#   AGENT_WORK_KIND=rescue|weekly を付けると、その範囲の今日の仕事が0件の回は AI を起こさない（scripts/agent_work.py）
set -u
prompt_file="$1"
turns="$2"
shift 2
scopes=$(cat "$RUNNER_TEMP/agent_scopes" 2>/dev/null || echo own)
# 範囲を絞る前に、全社の記事→社の対応を控える（絞った後はほかの社の原稿が見えず、仕事を数え違える）
[ -n "${AGENT_WORK_KIND:-}" ] && python scripts/agent_work.py --snapshot
for sc in $scopes; do
  # 絞れなかった範囲は AI を起こさない（ほかの社の原稿・材料が見えたままになる）
  if ! python scripts/private_store.py --scope "$sc"; then
    echo "::error::範囲を絞れませんでした（この範囲の AI は動かしません）"
    continue
  fi
  # 仕事が0件の範囲は AI を起こさない（2026-10-12 運用者「仕事が無い社は飛ばす」）。数えられなければ飛ばさない
  if [ -n "${AGENT_WORK_KIND:-}" ]; then
    w=$(python scripts/agent_work.py --kind "$AGENT_WORK_KIND" --scope "$sc" | sed -n 's/^AGENT_WORK=//p')
    if [ "$w" = "0" ]; then
      echo "AGENT_PASS=skip（この範囲は今日の仕事が0件のため、AI を起こしません）"
      continue
    fi
  fi
  # 控えを作れなかった範囲は AI を起こさない（控えが欠けたまま戻すと、控えに無い原稿を消す）
  if ! python scripts/agent_guard.py --checkpoint; then
    echo "::error::範囲ごとの控えを作れませんでした（この範囲の AI は動かしません）"
    continue
  fi
  HUB_AGENT_TOKEN="$(cat "$RUNNER_TEMP/hub_tokens/$sc" 2>/dev/null || true)"
  export HUB_AGENT_TOKEN
  if [ "$sc" = "own" ]; then
    note="この回の対象は自社の社だけです（作業場所にお客様の社はありません）。"
  else
    note="この回の対象は、作業場所にあるお客様の社だけです。自社の社の TODO・記事はこの回では扱いません（別の回で行います）。"
  fi
  # 使える道具は許可の一覧（automation/agent_settings_article.json）だけ。Linux では Glob・Grep を名指ししないと探せない
  # お客様の範囲の回は AI の出力をログに出さない（その回で書いた記事の題・URL は伏せる語の一覧に無い。2026-10-12）
  out="/dev/stdout"
  [ "$sc" = "own" ] || out="$RUNNER_TEMP/claude_out_pass.txt"
  claude -p "$(cat "$prompt_file")

【この回の範囲】${note}" --permission-mode dontAsk --allowedTools "Glob,Grep" --settings automation/agent_settings_article.json \
    --max-turns "$turns" "$@" > "$out" 2>&1 || echo "::warning::AI の回が失敗しました（次の範囲へ続けます）"
  [ "$sc" = "own" ] || echo "AI の出力 $(wc -l < "$out") 行（お客様の範囲のため、ログには出しません）"
  python scripts/agent_guard.py --protect --site "$sc" --pass
done
python scripts/private_store.py --scope all
# この回で書いた記事の題・slug も伏せる語に足す（以後の工程のログで伏せる）
python scripts/ci_mask.py || true
