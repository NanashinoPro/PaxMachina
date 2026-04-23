from typing import Dict, Optional
from models import WorldState, CountryState
from agent.prompts.base import build_common_context

def build_defense_minister_prompt(country_name: str, country_state: CountryState, world_state: WorldState, past_news: list = None, analyst_reports: Optional[Dict[str, str]] = None) -> str:
    common_ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="防衛大臣")

    # 戦時判定
    is_at_war = any(
        w.aggressor == country_name or w.defender == country_name
        for w in world_state.active_wars
    )

    # 分析官からの各国レポートを挿入
    analyst_section = ""
    if analyst_reports:
        analyst_section = "\n---📋【分析官からの各国分析レポート】📋---\n"
        analyst_section += "以下は情報分析官(flash-lite)が各対象国について作成した包括的分析です。これらを踏まえて軍事・諜報方針を策定してください。\n\n"
        for target_name, report in analyst_reports.items():
            analyst_section += f"▼ 対{target_name}分析レポート:\n{report}\n\n"

    instructions = """
あなたの役目は、国家の安全保障に責任を持ち、「軍事投資」と「諜報・裏工作」の戦略を策定することです。
単なる感情的な軍拡や現状維持を避け、以下の要素を論理的に天秤にかけ、その思考プロセスを `reasoning_for_military_investment` に記述してから投資割合を決定してください。
回答は必ず日本語で行ってください。

⚠️ thought_process には以下を必ず含めてください（大統領への提言として使われます）：
①軍事投資推奨値とその根拠（リチャードソン・モデルに基づく）、②諜報活動の方針と対象国、③戦時なら投入比率・停戦見解

【軍事投資（invest_military）の決定ルール：リチャードソン・モデルの適用】
1. 相手側の脅威: 相手の軍事力が自国に迫る、あるいは上回っている場合は、強い危機感を持ち、軍備増強を行ってください。
2. 経済的疲弊: 軍事投資は国家経済を圧迫します。現在の経済力に余裕があるか、過度な軍拡で国が破綻しないかを常に考慮してください。
3. 軍事動員の限界ルール (10%の壁): 軍事力は人員数に換算されます。総人口の10%を超える過度な動員を行うと、労働力不足による深刻な産業崩壊と支持率低下により国家が自滅します。

【諜報投資（invest_intelligence）の決定ルール】
諜報レベルが相手より高いほど有利になります。諜報技術は毎ターン自然に陳腐化するため、継続的な投資が必要です。
"""

    # 戦時専用セクション
    if is_at_war:
        war_info = []
        for w in world_state.active_wars:
            if w.aggressor == country_name:
                war_info.append(f"{w.defender}（攻撃中・占領率{w.target_occupation_progress:.1f}%）")
            elif w.defender == country_name:
                war_info.append(f"{w.aggressor}（防衛中・被占領率{w.target_occupation_progress:.1f}%）")
        instructions += f"""
【⚔️ 現在交戦中: {', '.join(war_info)}】

【戦時の軍事力投入比率（war_commitment_ratio）の決定ルール】
自国が戦争中の場合、`war_commitment_ratio`（0.1〜1.0）を設定して前線に投入する軍事力の割合を決定してください。
- 投入比率が**高い**(例: 0.8〜1.0): 前線の戦力が増し短期決戦に有利だが、経済負担が増大し後方予備がなくなる
- 投入比率が**低い**(例: 0.1〜0.3): 経済負担は軽いが、前線戦力が弱まり占領進捗を止めにくい
- **防衛側の場合**: 通常は高い投入率(0.7〜0.9)が必要。領土を守るため全力投入が基本
- **攻撃側の場合**: 経済的持続性を考慮し、中程度(0.3〜0.6)が一般的。長期戦なら低め、速攻なら高め
- ⚠️ **後方防衛リスク（極めて重要）**: 投入した軍事力は前線に固定され、残りの未投入分でしか他国からの奇襲・宣戦布告に対抗できない。高い投入率は「第三国に背後を突かれたら壊滅する」リスクと引き換えである。
- ⚠️ **動員速度制限**: 1ターンあたりの変動幅は**±10%**に制限されます（例: 現在0.20→次ターン最大0.30）。
- ⚠️ 未指定や変更が不要の場合は省略可（現在値が維持されます）

【戦争終結の判断指針】
戦争の長期化は経済と支持率を継続的に毀損します。
自国が交戦中の場合、以下の観点から戦争継続・停戦の是非を thought_process に記載してください。あなたの意見は大統領の最終判断材料になります：
- 占領率3%未満での講和 = 防衛成功（領土維持 + 賠償金請求可能）
- 占領率3%以上での講和 = 領土と人口の一部を喪失
- 軍事力の残存量と相手の消耗度
- 降伏勧告すべきか（攻撃側の場合）
"""

    instructions += """
以下のJSONスキーマに従って出力してください。必ずJSONオブジェクトのみを出力してください。
{
  "thought_process": "戦略思考（150文字程度）",
  "reasoning_for_military_investment": "軍事投資の論理的算出プロセス",
  "invest_military": 0.0から1.0の数値,
  "invest_intelligence": 0.0から1.0の数値,
  "war_commitment_ratio": 0.1から1.0の数値（戦争中の場合のみ。変更不要なら省略可）,
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
    return common_ctx + analyst_section + instructions
