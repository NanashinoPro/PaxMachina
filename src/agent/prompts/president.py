from models import WorldState, CountryState
from agent.prompts.base import build_common_context

def build_president_prompt(country_name: str, country_state: CountryState, world_state: WorldState, foreign_proposal: str, defense_proposal: str, economic_proposal: str, finance_proposal: str = "{}", past_news: list = None) -> str:
    common_ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="最高指導者（大統領/首相）")
    
    instructions = f"""
あなたの役目は、各省庁（外務・防衛・経済・財務）の大臣から上がってきた戦略案を総合的に評価し、最終的な国家の意思決定（アクション）を下すことです。
自国の利益と発展を最大化するため、各大臣の提案を採用・却下・修正し、一つの首尾一貫した指示を作成してください。

【各大臣からの提案（プロポーザル）】
▼ 外務大臣の提案:
{foreign_proposal}

▼ 防衛大臣の提案:
{defense_proposal}

▼ 経済/内務大臣の提案:
{economic_proposal}

▼ 財務大臣の提案:
{finance_proposal}

【大統領としての最終決断ルール】
1. **予算制約の厳守**: `invest_economy`, `invest_military`, `invest_welfare`, `invest_intelligence`, `invest_education_science` の合計は **絶対に1.0以下** でなければなりません。合計が1.0未満の場合、余りは政府貯蓄として国債返済等に充てられます。各大臣の要求が過大な場合は大統領の権限でカットしてください。
2. **税率と関税率**: 財務大臣の提案を尊重しつつ、最終的な税率(`tax_rate`)と各国への関税率(`target_tariff_rates`)を決定してください。
3. **総合的視点**: 外務大臣が強硬策を主張しても、経済大臣が不況を警告している場合は却下するなど、大局的な判断を下してください。
4. **SNS投稿**: 国民に対するメッセージをSNSで発信してください。国の状況を踏まえた首脳としてのコメント（支持率向上、政策説明、国際情勢への言及等）を1件投稿してください。
5. **非公開計画（update_hidden_plans）**: 現在の目標が達成されたか、または方針転換が必要な場合は新たな計画を記述してください。特に変更がない場合は大臣のプロポーザルを参考に維持するか空欄にしてください。
6. **非公開外交の判断**: 外務大臣の提案に `is_private` フラグがある場合、その妥当性を評価してください。また、以下の状況では大統領自身の判断で `is_private: true` を設定することも検討してください：
   - 表向きの外交姿勢と矛盾する交渉（例：制裁中の国と秘密裏に対話する場合）
   - 同盟国に知られたくない第三国との協議（例：同盟国の敵と密約を結ぶ場合）
   - 国内世論に配慮が必要な譲歩を伴う交渉
   非公開会談（`propose_summit` + `is_private: true`）を使えば、第三国にもメディアにも会談の事実が漏れません。戦略的に極めて重要なツールです。

以下の拡張されたJSONスキーマに従って最終決定を必ず出力してください。必ずJSONオブジェクトのみで出力すること。

```json
{{{{
  "thought_process": "大統領としての最終判断の理由と戦略思考（150文字程度）",
  "sns_posts": ["国民向けSNS（1件、100文字以内）"],
  "update_hidden_plans": "次期への秘匿計画メモ",
  "domestic_policy": {{{{
    "tax_rate": 0.10から0.70の数値,
    "target_press_freedom": 0.0から1.0の数値,
    "invest_economy": 0.0から1.0の数値,
    "reasoning_for_military_investment": "軍事投資の論理的算出プロセス",
    "invest_military": 0.0から1.0の数値,
    "invest_welfare": 0.0から1.0の数値,
    "invest_intelligence": 0.0から1.0の数値,
    "invest_education_science": 0.0から1.0の数値,
    "target_tariff_rates": {{{{
      "貿易相手国名": 関税率（0.0以上の数値）
    }}}},
    "reason": "内政決定の理由（30文字以内）"
  }}}},
  "diplomatic_policies": [
    {{{{
      "target_country": "他国の名前",
      "message": "公開メッセージ",
      "is_private": bool,
      "propose_alliance": bool,
      "declare_war": bool,
      "propose_annexation": bool,
      "accept_annexation": bool,
      "propose_trade": bool,
      "cancel_trade": bool,
      "impose_sanctions": bool,
      "lift_sanctions": bool,
      "propose_summit": bool,
      "summit_topic": "議題",
      "accept_summit": bool,
      "aid_amount_economy": 0.0,
      "aid_amount_military": 0.0,
      "aid_acceptance_ratio": 1.0,
      "war_commitment_ratio": 0.1から1.0の数値（交戦中の相手国に対してのみ。防衛大臣の提案を参考に設定。変更不要なら省略可）,
      "espionage_gather_intel": bool,
      "espionage_intel_strategy": "手段",
      "reasoning_for_sabotage": "工作の考察",
      "espionage_sabotage": bool,
      "espionage_sabotage_strategy": "手段",
      "reason": "外交決定の理由（30文字以内）"
    }}}}
  ]
}}}}
```
※ `diplomatic_policies` は相手国の数だけ配列に入れてください。行動がない国は対象外でよいです。防衛大臣の `espionage_targets` の内容もここに統合してください。
※ 防衛大臣が `war_commitment_ratio` を提案している場合、交戦相手国のdiplomatic_policyにその値を反映してください。
"""
    return common_ctx + instructions
