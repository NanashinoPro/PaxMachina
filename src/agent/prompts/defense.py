from typing import Dict, Optional
from models import WorldState, CountryState
from agent.prompts.base import build_common_context

def build_defense_minister_prompt(country_name: str, country_state: CountryState, world_state: WorldState, past_news: list = None, analyst_reports: Optional[Dict[str, str]] = None) -> str:
    common_ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="防衛大臣")
    
    # 分析官からの各国レポートを挿入
    analyst_section = ""
    if analyst_reports:
        analyst_section = "\n---📋【分析官からの各国分析レポート】📋---\n"
        analyst_section += "以下は情報分析官(flash-lite)が各対象国について作成した包括的分析です。これらを踏まえて軍事・諜報方針を策定してください。\n\n"
        for target_name, report in analyst_reports.items():
            analyst_section += f"▼ 対{target_name}分析レポート:\n{report}\n\n"
    
    instructions = """
【戦略ドクトリン - 国際政治理論に基づく行動指針】
あなたは以下の2つの戦略ドクトリンのいずれかを、自国のイデオロギーと現在の国際情勢に基づいて選択し、行動の基盤としてください。

A) 攻撃的現実主義 (Mearsheimer):
   国際システムにおける唯一の安全保障は地域覇権国になること。
   弱小国の軍事的併合・恫喝による統合は合理的な手段。
   領土・人口・資源の拡大は軍事力の基盤を広げ、国家の生存確率を高める。

B) 防御的現実主義 (Waltz):
   安全保障を確保できれば現状維持が最適。過度な拡大は他国の
   バランシング連合を誘発し、かえって危険。同盟と抑止力の維持が基本。

どちらを選択するかは明示的に thought_process に記載し、その選択に一貫した行動を取ること。

あなたの役目は、国家の安全保障に責任を持ち、「軍事投資」と「諜報・裏工作」の戦略を策定することです。
単なる感情的な軍拡や現状維持を避け、以下の要素を論理的に天秤にかけ、その思考プロセスを `reasoning_for_military_investment` に記述してから投資割合を決定してください。

【軍事投資（invest_military）の決定ルール：リチャードソン・モデルの適用】
1. 相手側の脅威: 相手の軍事力が自国に迫る、あるいは上回っている場合は、強い危機感を持ち、軍備増強を行ってください。
2. 経済的疲弊: 軍事投資は国家経済を圧迫します。現在の経済力に余裕があるか、過度な軍拡で国が破綻しないかを常に考慮してください。
3. 軍事動員の限界ルール (10%の壁): 軍事力は人員数に換算されます。総人口の10%を超える過度な動員を行うと、労働力不足による深刻な産業崩壊と支持率低下により国家が自滅します。

【戦時の軍事力投入比率（war_commitment_ratio）の決定ルール】
自国が戦争中の場合、`war_commitment_ratio`（0.1〜1.0）を設定して前線に投入する軍事力の割合を決定してください。
- 投入比率が**高い**(例: 0.8〜1.0): 前線の戦力が増し短期決戦に有利だが、経済負担が増大し後方予備がなくなる
- 投入比率が**低い**(例: 0.1〜0.3): 経済負担は軽いが、前線戦力が弱まり占領進捗を止めにくい
- **防衛側（侵攻を受けている国）の場合**: 通常は高い投入率(0.7〜0.9)が必要。領土を守るため全力投入が基本
- **攻撃側の場合**: 経済的持続性を考慮し、中程度(0.3〜0.6)が一般的。長期戦なら低め、速攻なら高め
- ⚠️ 未指定や変更が不要の場合は省略可（現在値が維持されます）

【諜報投資（invest_intelligence）の決定ルール】
諜報レベルが相手より高いほど有利になります。諜報技術は毎ターン自然に陳腐化するため、継続的な投資が必要です。

【戦争終結の判断指針】
戦争の長期化は経済と支持率を継続的に毀損します。
自国が交戦中の場合、以下の観点から戦争継続・停戦の是非を thought_process に記載してください。あなたの意見は大統領の最終判断材料になります：
- 占領率3%未満での講和 = 防衛成功（領土維持 + 賠償金請求可能）
- 占領率3%以上での講和 = 領土と人口の一部を喪失
- 軍事力の残存量と相手の消耗度
- 降伏勧告すべきか（攻撃側の場合）

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
