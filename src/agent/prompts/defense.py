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
    
    # 海岸線情報
    coastline_note = ""
    if not country_state.has_coastline:
        coastline_note = "\n⚠️ あなたの国には海岸線がないため、海軍を保有・配備することはできません。force_allocationのnavy_ratioは0.0にしてください。\n"
    
    # 現在の配備状況
    current_deployment_info = ""
    if country_state.military_deployment.deployments:
        current_deployment_info = "\n---🗺️【現在の軍事配備状況】🗺️---\n"
        current_deployment_info += f"兵科比率: 陸軍{country_state.military_deployment.force_allocation.army_ratio:.0%} / 海軍{country_state.military_deployment.force_allocation.navy_ratio:.0%} / 空軍{country_state.military_deployment.force_allocation.air_ratio:.0%}\n"
        for d in country_state.military_deployment.deployments:
            d_type = d.type.value
            if d_type == "army":
                posture_str = d.posture.value if d.posture else "defensive"
                fort_str = f", 要塞:{d.fortify.value}" if d.fortify.value != "none" else ""
                current_deployment_info += f"  陸軍 {d.divisions}師団 → {d.target_country}方面 ({posture_str}{fort_str})\n"
            elif d_type == "navy":
                mission_str = d.naval_mission.value if d.naval_mission else "patrol"
                current_deployment_info += f"  海軍 {d.fleets}艦隊 → {d.target_country}方面 ({mission_str})\n"
            elif d_type == "air":
                mission_str = d.air_mission.value if d.air_mission else "air_superiority"
                current_deployment_info += f"  空軍 {d.squadrons}飛行隊 → {d.target_country}方面 ({mission_str})\n"
        current_deployment_info += "\n"
    
    instructions = f"""
あなたの役目は、国家の安全保障に責任を持ち、「軍事投資」「諜報・裏工作」「**軍事配備**」の戦略を策定することです。
単なる感情的な軍拡や現状維持を避け、以下の要素を論理的に天秤にかけ、その思考プロセスを `reasoning_for_military_investment` に記述してから投資割合を決定してください。
{coastline_note}
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

【⭐ 軍事配備命令（deployments）— 完全自由配備システム ⭐】
あなたは毎ターン、自国の全軍をどの国の方面にどのように配備するかを自由に決定します。
これはAge of Empires のように、ユニットをどの方面に派遣するかの指示です。

▼ `force_allocation` — 兵科比率（陸海空の配分）
  army_ratio/navy_ratio/air_ratio で自国の軍事力をどの兵科に配分するか決めます（合計1.0）。

▼ `deployments` — 各方面への配備命令  
  target_country（対象国名）を指定し、兵力の種類(type)と数、任務を命令します。
  **配備先未指定の兵力は首都防衛に自動配属されます。**

  🟩 陸軍 (type: "army"):
    - target_country: どの国の方面に配備するか
    - divisions: 師団数
    - posture: "offensive"(攻+20%/守-10%) / "defensive"(守+30%/攻-20%) / "intimidation"(戦闘効果なし、緊張度↑)
    - fortify: "none" / "light"(防御+25%) / "heavy"(防御+50%, コスト高)
    
  🔵 海軍 (type: "navy"):
    - target_country: どの国の近海に展開するか
    - fleets: 艦隊数
    - naval_mission:
      ・"patrol" — 通商護衛（平時/戦時OK）
      ・"show_of_force" — 砲艦外交・武力示威（平時/戦時OK、緊張度大幅↑）
      ・"blockade" — 海上封鎖（⚠️戦時のみ、敵NX削減）
      ・"naval_engagement" — 艦隊決戦（⚠️戦時のみ、制海権確保）
      ・"amphibious_support" — 上陸支援（⚠️戦時のみ、陸軍攻撃力+20%）
      ・"shore_bombardment" — 艦砲射撃（⚠️戦時のみ、敵経済にダメージ）
  
  ✈️ 空軍 (type: "air"):
    - target_country: 任務の対象国
    - squadrons: 飛行隊数
    - air_mission:
      ・"air_superiority" — 制空権確保（平時/戦時OK）
      ・"ground_support" — 地上支援（⚠️戦時のみ、陸軍攻撃力+15%）  
      ・"strategic_bombing" — 戦略爆撃（⚠️戦時のみ、敵経済ダメージ）
      ・"recon_flight" — 偵察飛行（平時/戦時OK、敵配備情報取得+緊張度微↑）

【⚠️ 威嚇配備・砲艦外交の戦略的活用】
戦争せずとも、"intimidation"態勢の陸軍やshow_of_force海軍を特定国に向けて配備することで：
- 相手国の国民に恐怖を与え支持率を低下させられる（高緊張時）
- ただし、威嚇を維持し続けると自国にもオーディエンスコスト（「口だけか」と疑われ支持率低下）が発生する
- 緊張度50+で偶発的軍事衝突が5%の確率で自動発生するリスクもある

以下のJSONスキーマに従って出力してください。必ずJSONオブジェクトのみを出力してください。
{{
  "thought_process": "戦略思考（150文字程度）",
  "reasoning_for_military_investment": "軍事投資の論理的算出プロセス",
  "invest_military": 0.0から1.0の数値,
  "invest_intelligence": 0.0から1.0の数値,
  "force_allocation": {{
    "army_ratio": 0.0-1.0,
    "navy_ratio": 0.0-1.0,
    "air_ratio": 0.0-1.0
  }},
  "deployments": [
    {{
      "type": "army",
      "target_country": "対象国名",
      "divisions": 整数,
      "posture": "offensive"/"defensive"/"intimidation",
      "fortify": "none"/"light"/"heavy"
    }},
    {{
      "type": "navy",
      "target_country": "対象国名",
      "fleets": 整数,
      "naval_mission": "patrol"/"show_of_force"/"blockade"/"naval_engagement"/"amphibious_support"/"shore_bombardment"
    }},
    {{
      "type": "air",
      "target_country": "対象国名",
      "squadrons": 整数,
      "air_mission": "air_superiority"/"ground_support"/"strategic_bombing"/"recon_flight"
    }}
  ],
  "war_commitment_ratio": 0.1から1.0の数値（戦争中の場合のみ。変更不要なら省略可）,
  "espionage_targets": [
    {{
      "target_country": "他国の名前",
      "espionage_gather_intel": bool,
      "espionage_intel_strategy": "手段",
      "reasoning_for_sabotage": "工作の考察",
      "espionage_sabotage": bool,
      "espionage_sabotage_strategy": "手段"
    }}
  ],
  "update_hidden_plans": "次期への秘匿計画メモ"
}}
※ deployments は複数の配備命令を自由に指定可能です。配備先がなければ空のリストでOKです。
※ espionage_targets は対象国がない場合は空のリストにしてください。
※ ⚠️戦時のみとマークされたミッションを平時に指定した場合、エンジンにより無視されます。
"""
    return common_ctx + analyst_section + current_deployment_info + instructions
