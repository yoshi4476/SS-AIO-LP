# 用語とプラットフォーム別の重視シグナル（CLAUDE.md 0章から移設）

## 用語整理（AIO / LLMO / GEO / AEO）

| 用語 | 対象 | 本パイプラインでの扱い |
|:--|:--|:--|
| AIO（AI Overview Optimization） | Google検索のAI Overview・AIモードでの表示/引用獲得 | 主戦場。GSCの生成AIパフォーマンスレポートで計測 |
| LLMO（Large Language Model Optimization） | ChatGPT・Perplexity・Gemini・Claude・Copilot等での引用獲得 | AIOと同時に対策。GA4のAI参照元で計測 |
| GEO（Generative Engine Optimization） | 生成エンジン全般への最適化（AIO+LLMOの総称） | AIO/LLMOの上位概念として使用 |
| AEO（Answer Engine Optimization） | 回答エンジン（強調スニペット等含む）への最適化 | AIOの施策に包含 |

**基本方針**: AIOとSEOは対立しない。Google上位表示（SEO）がAI Overview引用の前提条件であり、「SEOで上位を取り、その構造でAIにも引用される」二段構えで設計する。

### プラットフォーム別の重視シグナル

| プラットフォーム | 最重視シグナル | 対応Phase |
|:--|:--|:--|
| Google AI Overview / AIモード | Google上位表示+構造化データ+E-E-A-T+抽出しやすい構造 | Phase 3〜6 |
| Gemini | Google上位+FAQPage/HowToスキーマ+E-E-A-T | Phase 5〜6 |
| ChatGPT（SearchGPT含む） | ドメイン権威・繰り返し引用・被リンク・メディア露出 | Phase 7（外部評価の蓄積） |
| Perplexity | 情報鮮度・信頼性・出典明記・速いインデックス | Phase 6〜7（即時インデックス+定期更新） |
| Claude | 正確性・著者信頼性 | Phase 5（E-E-A-T注入） |

---

