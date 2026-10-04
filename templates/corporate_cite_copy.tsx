"use client";
// 自動配置: 管制塔の scripts/research_publish.py が src/components/CiteCopy.tsx に置く（直接編集しない）。
// 調査ページの「そのまま貼れる出典」をコピーするボタン。JS が無くても文は表示されたままなので、選んでコピーできる。
import { useState } from "react";

export default function CiteCopy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 2000);
    } catch {
      setDone(false);
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      className="rounded-full border border-pulse px-4 py-2 text-sm font-bold text-pulse"
    >
      {done ? "コピーしました" : "コピー"}
    </button>
  );
}
