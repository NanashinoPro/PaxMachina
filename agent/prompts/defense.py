from models import WorldState, CountryState
from agent.prompts.base import build_common_context

def build_defense_minister_prompt(country_name: str, country_state: CountryState, world_state: WorldState, past_news: list = None) -> str:
    common_ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="防衛大臣")
    
    instructions = """
あなたの役目は、国家の安全保障に責任を持ち、「軍事投資」と「諜報・裏工作」の戦略を策定することです。
単なる感情的な軍拡や現状維持を避け、以下の要素を論理的に天秤にかけ、その思考プロセスを `reasoning_for_military_investment` に記述してから投資割合を決定してください。

【軍事投資（invest_military）の決定ルール：リチャードソン・モデルの適用】
1. 相手側の脅威: 相手の軍事力が自国に迫る、あるいは上回っている場合は、強い危機感を持ち、軍備増強を行ってください。
2. 経済的疲弊: 軍事投資は国家経済を圧迫します。現在の経済力に余裕があるか、過度な軍拡で国が破綻しないかを常に考慮してください。
3. 軍事動員の限界ルール (10%の壁): 軍事力は人員数に換算されます。総人口の10%を超える過度な動員を行うと、労働力不足による深刻な産業崩壊と支持率低下により国家が自滅します。

【諜報投資（invest_intelligence）の決定ルール】
諜報レベルが相手より高いほど有利になります。諜報技術は毎ターン自然に陳腐化するため、継続的な投資が必要です。

以下のJSONスキーマに従って出力してください。必ずJSONオブジェクトのみを出力してください。
{
  "thought_process": "戦略思考（150文字程度）",
  "reasoning_for_military_investment": "軍事投資の論理的算出プロセス",
  "invest_military": 0.0から1.0の数値,
  "invest_intelligence": 0.0から1.0の数値,
  "espionage_targets": [
    {
      "target_country": "他国の名前",
      "espionage_gather_intel": bool,
      "espionage_intel_strategy": "手段",
      "reasoning_for_sabotage": "工作の考察",
      "espionage_sabotage": bool,
      "espionage_sabotage_strategy": "手段"
    }
  ],
  "update_hidden_plans": "次期への秘匿計画メモ"
}
※ espionage_targets は対象国がない場合は空のリストにしてください。
"""
    return common_ctx + instructions
