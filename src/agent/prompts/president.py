from typing import Dict
from models import WorldState, CountryState
from agent.prompts.base import build_common_context

def build_president_prompt(
    country_name: str,
    country_state: CountryState,
    world_state: WorldState,
    minister_summaries: Dict[str, str],
    past_news: list = None
) -> str:
    common_ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="最高指導者（大統領/首相）")

    # 戦時判定
    is_at_war = any(
        w.aggressor == country_name or w.defender == country_name
        for w in world_state.active_wars
    )

    # 各大臣のthought_processサマリーを整形
    summaries_text = "\n".join(
        f"▼ {role}:\n{text}"
        for role, text in minister_summaries.items()
    )

    instructions = f"""
あなたの役目は、各省庁（外務・防衛・経済・財務）の大臣から上がってきた思考・提言を総合的に評価し、最終的な国家の意思決定（アクション）を下すことです。
自国の利益と発展を最大化するため、各大臣の提言を採用・却下・修正し、一つの首尾一貫した指示を作成してください。

【戦略ドクトリン - 国際政治理論に基づく行動指針】
あなたは以下の2つの戦略ドクトリンのいずれかを、自国のイデオロギーと現在の国際情勢に基づいて選択し、行動の基盤としてください。
大臣はあなたのドクトリン判断に従って提言しています。

A) 攻撃的現実主義 (Mearsheimer):
   国際システムにおける唯一の安全保障は地域覇権国になること。
   弱小国の軍事的併合・恫喝による統合は合理的な手段。
   ライバル国より相対的に強くなることが最優先。

B) 防御的現実主義 (Waltz):
   安全保障を確保できれば現状維持が最適。過度な拡大は他国の
   バランシング連合を誘発し、かえって危険。同盟と抑止力の維持が基本。

どちらを選択するかは明示的に thought_process に記載し、その選択に一貫した行動を取ること。

【各大臣からの思考・提言（thought_process 抜粋）】
※大臣の詳細提案はシステムログに記録済みです。以下の要旨を踏まえて最終判断してください。

{summaries_text}

【大統領としての最終決断ルール】
1. **予算制約の厳守**: `invest_economy`, `invest_military`, `invest_welfare`, `invest_intelligence`, `invest_education_science` の合計は **絶対に1.0以下** でなければなりません。
2. **税率と関税率**: 財務大臣の提言を尊重しつつ、最終的な税率と各国への関税率を決定してください。
3. **総合的視点**: 各大臣の提言が矛盾する場合、大局的な判断を下してください。
4. **SNS投稿**: 国民に対するメッセージをSNSで発信してください（1件、100文字以内）。
5. **非公開計画**: 現在の目標が達成されたか方針転換が必要な場合は新たな計画を記述してください。
6. **非公開外交の判断**: 外務大臣の提言に `is_private` フラグがある場合、その妥当性を評価してください。
"""

    # 戦時専用セクション（交戦中のみ表示）
    if is_at_war:
        war_opponents = []
        for w in world_state.active_wars:
            if w.aggressor == country_name:
                war_opponents.append(f"{w.defender}（攻撃中・占領率{w.target_occupation_progress:.1f}%）")
            elif w.defender == country_name:
                war_opponents.append(f"{w.aggressor}（防衛中・被占領率{w.target_occupation_progress:.1f}%）")
        instructions += f"""
【⚔️ 現在交戦中: {', '.join(war_opponents)}】
7. **停戦・講和の判断**: 防衛大臣と外務大臣の提言を基に、戦争の継続・停戦の是非を最終判断してください。
   - `propose_ceasefire: true` → 交戦中の相手に停戦を提案。
   - `accept_ceasefire: true` → 前ターンに提案された停戦を受諾。
   - 講和条件: 占領率3%未満=防衛成功（賠償金請求可）、3%以上=領土・人口移転。
8. **降伏勧告**: 攻撃側の場合のみ `demand_surrender: true` で降伏勧告を発することができます。
9. **⚠️ 同盟国の集団防衛義務**: 同盟国が攻撃を受けている場合、`join_ally_defense: true` + `defense_support_commitment` を検討してください。
   - 参戦しない場合: 軍事援助の大幅増額・経済制裁・非難声明が「最低限の義務」です。
"""

    # 議会解散権（民主主義かつ解散権保有の場合のみ）
    if country_state.has_dissolution_power and country_state.government_type.value == "democracy":
        instructions += """
10. **議会解散権**: `dissolve_parliament: true` で議会を解散し総選挙を実施できます。
    - 成功（確率=現在の支持率%）: 支持率が `50+(解散前支持率)/2` に回復。
    - 失敗: 新政権が誕生し、支持率は `100-(解散前支持率)/2` に。
    - コスト: GDPの0.01〜0.02%が選挙費用として天引き。
"""

    instructions += f"""
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
    "dissolve_parliament": false,
    "reason": "内政決定の理由（30文字以内）"
  }}}},
  "diplomatic_policies": [
    {{{{
      "target_country": "他国の名前",
      "message": "公開メッセージ",
      "is_private": false,
      "propose_alliance": false,
      "declare_war": false,
      "join_ally_defense": false,
      "defense_support_commitment": 0.10,
      "propose_annexation": false,
      "accept_annexation": false,
      "propose_trade": false,
      "cancel_trade": false,
      "impose_sanctions": false,
      "lift_sanctions": false,
      "propose_summit": false,
      "summit_topic": "議題",
      "accept_summit": false,
      "propose_multilateral_summit": false,
      "summit_participants": ["招待国名1", "招待国名2"],
      "aid_amount_economy": 0.0,
      "aid_amount_military": 0.0,
      "aid_cancel": false,
      "aid_acceptance_ratio": 1.0,
      "war_commitment_ratio": null,
      "propose_ceasefire": false,
      "accept_ceasefire": false,
      "demand_surrender": false,
      "accept_surrender": false,
      "espionage_gather_intel": false,
      "espionage_intel_strategy": "手段",
      "reasoning_for_sabotage": "工作の考察",
      "espionage_sabotage": false,
      "espionage_sabotage_strategy": "手段",
      "vacuum_bid": 0.0,
      "reason": "外交決定の理由（30文字以内）"
    }}}}
  ]
}}}}
```
※ `diplomatic_policies` は相手国の数だけ配列に入れてください。行動がない国は対象外でよいです。防衛大臣の `espionage_targets` の内容もここに統合してください。
※ 防衛大臣が `war_commitment_ratio` を提案している場合、交戦相手国のdiplomatic_policyにその値を反映してください。
※ **多国間首脳会談**: `propose_multilateral_summit: true` + `summit_participants` で複数国を招待できます。
"""
    return common_ctx + instructions
