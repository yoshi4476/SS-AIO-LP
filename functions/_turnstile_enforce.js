// ロボットよけで断るか（AI集客ラボの受付 /api/lead・/api/subscribe）。scripts/turnstile_status.py --decide --apply が、
// 本物の相談がすべてロボットよけを通っていることを記録で確かめてから true にする（手で書き換えない）
export const DECIDED = { lead: false, subscribe: false };
