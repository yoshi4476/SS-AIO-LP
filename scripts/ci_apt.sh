#!/usr/bin/env bash
# CI で apt のパッケージを入れる。
# Ubuntu の配布元が一時的に不調（取得の時間切れ・一覧の404）だと apt-get update が失敗を返し、
# 入れたいパッケージは取れる状態でも工程ごと止まっていた（2026-11-19 の準備の工程）。
# update の失敗では止めず「入れられたか」で決め、間を空けて3回までやり直す。
# その日の update は応答待ちで6分かかってから失敗した。1回ごとに時間の上限をかけ、やり直しで工程を長引かせない
set -u
[ $# -gt 0 ] || { echo "使い方: ci_apt.sh <パッケージ>..."; exit 2; }
if dpkg -s "$@" > /dev/null 2>&1; then
  echo "既に入っています: $*"
  exit 0
fi
wait_s=${CI_APT_WAIT:-20}
# 入れられなくても進む工程（自動修復・動画・月次）は1回だけ試す（3回だと配布元が落ちた日に最大25分待つ）
tries=${CI_APT_TRIES:-3}
opts=(-qq -o Acquire::Retries=3)
for i in $(seq 1 "$tries"); do
  # 前の回の install を時間切れで切ると dpkg が中断のまま残り、やり直しが全部失敗する
  [ "$i" = 1 ] || sudo dpkg --configure -a > /dev/null 2>&1 || true
  timeout 180 sudo apt-get update "${opts[@]}" || echo "apt-get update が失敗しました（${i}回目。入れられるかを試します）"
  if timeout 300 sudo apt-get install -y "${opts[@]}" "$@"; then
    exit 0
  fi
  [ "$i" = "$tries" ] || sleep $((wait_s * i))
done
echo "apt で $* を${tries}回とも入れられませんでした"
exit 1
