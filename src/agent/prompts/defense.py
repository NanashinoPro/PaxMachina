from typing import Dict, Optional
from models import WorldState, CountryState
from agent.prompts.base import build_common_context

def build_defense_minister_prompt(country_name: str, country_state: CountryState, world_state: WorldState, past_news: list = None, analyst_reports: Optional[Dict[str, str]] = None) -> str:
    common_ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="防衛大臣")

    is_at_war = any(
        w.aggressor == country_name or w.defender == country_name
        for w in world_state.active_wars
    )

    analyst_section = ""
    if analyst_reports:
        analyst_section = "\n---📋【分析官からの各国分析レポート】📋---\n"
        analyst_section += "以下を踏まえて軍事・諜報方針を策定してください。\n\n"
        for target_name, report in analyst_reports.items():
            analyst_section += f"▼ 対{target_name}分析レポート:\n{report}\n\n"

    instructions = """
あなたの役目は、「軍事投資の予算要求」「諜報・裏工作の最終決定」「☢️核開発投資の予算要求」を行うことです。
回答は必ず日本語で行ってください。

⚠️ thought_process には以下を必ず含めてください（大統領への提言として使われます）：
①軍事投資推奨値とその根拠、②諜報活動の方針と対象国、③戦時なら投入比率の推奨、④核戦略に関する提言

【軍事投資（request_invest_military）の決定ルール：リチャードソン・モデル】
1. 相手側の脅威: 相手の軍事力が自国に迫る、あるいは上回っている場合は、強い危機感を持ち増強を推奨。
2. 経済的疲弊: 軍事投資は経済を圧迫します。経済力に余裕があるかを常に考慮してください。
3. 軍事動員の限界ルール (10%の壁): 総人口の10%を超える過度な動員は国家自滅を招きます。

【諜報投資（request_invest_intelligence）の決定ルール】
諜報レベルが相手より高いほど有利。継続的な投資が必要です。

【☢️ 核開発投資（request_invest_nuclear）の決定ルール】
- 核開発は4段階（1:ウラン濃縮→2:核実験→3:実戦配備→4:核保有国）で進行。
- Step4到達後は核弾頭の量産に充当される。
- 核開発はGDPの大きな割合を消費するため、経済負担とのバランスを十分に考慮すること。
- 0.0の場合、核開発に予算を割かない（核開発しない）。

【☢️ 核使用の提言（nuclear_use_recommendation）】
- 大統領への助言として核使用を提言できます。最終決定は大統領が行います。
- 形式: "tactical:対象国名" or "strategic:対象国名" or null

【諜報・破壊工作（espionage_decisions）】
これらはあなたの最終決定です。大統領への確認は不要です。
"""

    if is_at_war:
        war_info = []
        for w in world_state.active_wars:
            if w.aggressor == country_name:
                war_info.append(f"{w.defender}（攻撃中・占領率{w.target_occupation_progress:.1f}%）")
            elif w.defender == country_name:
                war_info.append(f"{w.aggressor}（防衛中・被占領率{w.target_occupation_progress:.1f}%）")
        instructions += f"""
【⚔️ 現在交戦中: {', '.join(war_info)}】

【戦時の軍事力投入比率（war_commitment_ratios）の決定ルール（最終決定）】
あなたが `war_commitment_ratios` を設定すると、大統領の確認なしに前線投入比率が確定します。
- 高投入 (0.7〜0.9): 短期決戦有利。後方防衛の空洞化リスクあり。
- 低投入 (0.1〜0.3): 経済負担軽い。前線戦力弱い。
- ⚠️ 1ターンあたり±10%の変動制限あり。
- 変更不要な場合は war_commitment_ratios を空のオブジェクトにしてください。

【停戦・降伏に関する提言】
停戦・降伏の判断は大統領権限です。あなたは thought_process に以下を記載してください：
- 占領率と軍事力の消耗状況から見た停戦の是非（大統領への提言）
- 戦争継続のコストと見通し
"""

    instructions += """
以下のJSONスキーマに従って出力してください。必ずJSONオブジェクトのみを出力してください。
{
  "thought_process": "軍事・諜報方針の思考サマリー（150文字程度、大統領への提言を含む）",
  "reasoning_for_military_investment": "リチャードソン・モデルに基づく軍事投資の算出プロセス",
  "request_invest_military": 0.0から1.0の数値,
  "request_invest_intelligence": 0.0から1.0の数値,
  "request_invest_nuclear": 0.0から1.0の数値,
  "nuclear_use_recommendation": null,
  "war_commitment_ratios": {"交戦相手国名": 0.1から1.0の数値},
  "espionage_decisions": [
    {
      "target_country": "対象国名",
      "espionage_gather_intel": false,
      "espionage_intel_strategy": "手段（実行時のみ）",
      "reasoning_for_sabotage": "工作の考察",
      "espionage_sabotage": false,
      "espionage_sabotage_strategy": "手段（実行時のみ）",
      "reason": "諜報決定の理由（30文字以内）"
    }
  ]
}
※ war_commitment_ratios は交戦中でない場合は {} にしてください。
※ espionage_decisions は対象国がない場合は [] にしてください。
※ request_invest_nuclear は核開発を行わない場合は 0.0 にしてください。
※ nuclear_use_recommendation は核使用を提言しない場合は null にしてください。
"""
    return common_ctx + analyst_section + instructions
