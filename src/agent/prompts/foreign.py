from typing import Dict, Optional
from models import WorldState, CountryState
from agent.prompts.base import build_common_context

# 大統領権限の外交フラグ（外務大臣は出力禁止）
PRESIDENTIAL_FLAGS = {
    "declare_war", "propose_alliance", "join_ally_defense",
    "propose_annexation", "accept_annexation",
    "propose_ceasefire", "accept_ceasefire",
    "demand_surrender", "accept_surrender",
}

def build_foreign_minister_prompt(country_name: str, country_state: CountryState, world_state: WorldState, past_news: list = None, analyst_reports: Optional[Dict[str, str]] = None) -> str:
    common_ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="外務大臣")

    # 同盟国が攻撃されているか
    ally_names = {
        r for r, rel in world_state.relations.get(country_name, {}).items()
        if str(rel).lower() == 'alliance'
    }

    # 分析官レポート
    analyst_section = ""
    if analyst_reports:
        analyst_section = "\n---📋【分析官からの各国分析レポート】📋---\n"
        analyst_section += "以下を踏まえて外交方針を策定してください。\n\n"
        for target_name, report in analyst_reports.items():
            analyst_section += f"▼ 対{target_name}分析レポート:\n{report}\n\n"

    instructions = """
あなたの役目は、外交・貿易・援助・首脳会談の戦略を最終決定することです。
回答は必ず日本語で行ってください。

⚠️ thought_process には以下を必ず含めてください（大統領への提言として使われます）：
①現在の国際情勢と自国の外交的立ち位置、②主要外交アクション（対象国と理由）、③懸念事項または大統領への推奨

【重要：権限の境界線】
以下は大統領の専権事項です。あなたは出力しないでください：
- 宣戦布告（declare_war）
- 同盟提案（propose_alliance）
- 共同防衛参加（join_ally_defense）
- 平和的統合提案/受諾（propose_annexation / accept_annexation）
- 停戦提案/受諾（propose_ceasefire / accept_ceasefire）
- 降伏勧告/受諾（demand_surrender / accept_surrender）
これらが必要と考える場合、thought_process に「大統領への提言」として記載してください。

【対外援助（Foreign Aid）サブスク制ルール】
援助はサブスク（自動継続）制です。一度設定すると毎ターン自動的に継続されます。
⚠️ 共通コンテキストの「援助契約一覧」を必ず確認してください。
- **変更不要な場合**: `aid_amount_*` は出力不要です（0.0のままで既存契約が継続されます）
- **新規開始・増減**: `aid_amount_economy` / `aid_amount_military` に新しい金額を指定
- **停止**: `aid_cancel: true` を設定（その国への全援助契約が解除されます）

【援助の戦略的効果】
- `aid_amount_military`: 相手の軍事力に直接加算。交戦中の友好国に特に効果的。
- `aid_amount_economy`: 相手の経済力を強化。依存度の蓄積に有効。
- ⚠️ 累積援助比率が60%を超えると相手が属国化するリスクあり。
- ⚠️ 1ターンでGDPの20%超の援助はオランダ病を引き起こします。

【援助の受入制御（aid_acceptance_ratio）】
他国から受け取っている援助の受入率を毎ターン調整できます（0.0〜1.0）。
自国の `dependency_ratio` を確認し、属国化リスク（60%超）が高まっている場合は受入率を引き下げてください。
政治的シグナルや自立戦略として全拒否（0.0）も選択できます。

【非公開外交チャネル（is_private）】
`is_private: true` で第三国に秘密の外交を行えます。
"""

    if ally_names:
        at_war_allies = [
            f"{w.defender}（vs {w.aggressor}）" if w.defender in ally_names
            else f"{w.aggressor}（vs {w.defender}）"
            for w in world_state.active_wars
            if (w.defender in ally_names or w.aggressor in ally_names)
            and w.aggressor != country_name and w.defender != country_name
        ]
        if at_war_allies:
            instructions += f"""
【⚠️ 同盟国が交戦中: {', '.join(at_war_allies)}】
thought_process に以下を必ず記載してください（大統領への提言として使用）：
- 軍事援助（aid_amount_military）の大幅増額を検討すべきか
- 経済制裁（impose_sanctions）で攻撃国に圧力をかけるべきか
- 共同防衛参加の推奨（大統領判断への提言）
"""

    instructions += """
以下のJSONスキーマに従って出力してください。必ずJSONオブジェクトのみを出力してください。
{
  "thought_process": "外交方針の思考サマリー（150文字程度、大統領への提言を含む）",
  "diplomatic_policies": [
    {
      "target_country": "他国の名前",
      "message": "公開メッセージ",
      "is_private": false,
      "propose_trade": false,
      "cancel_trade": false,
      "impose_sanctions": false,
      "lift_sanctions": false,
      "propose_summit": false,
      "summit_topic": "議題",
      "accept_summit": false,
      "propose_multilateral_summit": false,
      "summit_participants": ["招待国名1"],
      "aid_amount_economy": 0.0,
      "aid_amount_military": 0.0,
      "aid_cancel": false,
      "aid_acceptance_ratio": 1.0,
      "reason": "外交決定の理由（30文字以内）"
    }
  ]
}
※ `diplomatic_policies` は相手国の数だけ配列に入れてください。行動がない国は対象外でよいです。
※ 宣戦布告・同盟・停戦・降伏等は大統領権限のため出力しないでください。
"""
    return common_ctx + analyst_section + instructions
