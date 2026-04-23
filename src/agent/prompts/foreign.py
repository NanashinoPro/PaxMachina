from typing import Dict, Optional
from models import WorldState, CountryState
from agent.prompts.base import build_common_context

def build_foreign_minister_prompt(country_name: str, country_state: CountryState, world_state: WorldState, past_news: list = None, analyst_reports: Optional[Dict[str, str]] = None) -> str:
    common_ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="外務大臣")
    
    # 分析官からの各国レポートを挿入
    analyst_section = ""
    if analyst_reports:
        analyst_section = "\n---📋【分析官からの各国分析レポート】📋---\n"
        analyst_section += "以下は情報分析官(flash-lite)が各対象国について作成した包括的分析です。これらを踏まえて外交方針を策定してください。\n\n"
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

あなたの役目は、他国の情報や世界情勢を踏まえて、自国の利益と発展を最大化するための「外交方針」を専門的に策定することです。
同盟・戦争・併合、貿易や経済制裁、首脳会談の提案、対外援助などを選択可能です。
回答は必ず日本語で行ってください。

【対外援助（Foreign Aid）サブスク制ルール】
援助はサブスク（自動継続）制です。一度設定すると毎ターン自動的に継続されます。

⚠️【重要】共通コンテキストの「援助契約一覧」を必ず確認してください。
- **変更不要な場合**: `aid_amount_*` は出力不要です（0.0のままで既存契約が継続されます）
- **新規開始・増減したい場合**: `aid_amount_economy` / `aid_amount_military` に新しい金額を指定してください
- **停止したい場合**: `aid_cancel: true` を設定してください（その国への全援助契約が解除されます）

【援助の戦略的効果】
- `aid_amount_military`: 相手の軍事力（Military）に直接加算。交戦中の友好国に特に効果的。
- `aid_amount_economy`: 相手の経済力を強化。間接的な国力向上と依存度の蓄積に有効。
- ⚠️ 累積援助比率が60%を超えると相手が属国化するリスクあり。戦略的に活用してください。
- ⚠️ 1ターンでGDPの20%超の援助はオランダ病（政策実行力半減）を引き起こします。

【援助の受入制御】
自国への援助に対し、`aid_acceptance_ratio`（0.0〜1.0）で受入率を設定できます。
依存度上昇リスクを考慮し、戦略的に判断してください。

【非公開外交チャネル（is_private）の活用指針】
メッセージ送信や首脳会談の提案において `is_private: true` を設定すると、第三国には一切知られない秘密の外交を行えます。
以下のケースでは非公開を積極的に検討してください：
- **敵対国との秘密交渉**: 表向きは対立していても、水面下で停戦・制裁解除・領土問題を交渉したい場合
- **裏切り・寝返りの打診**: 同盟国の敵に対して密かに接触し、関係転換を図りたい場合
- **機密性の高い安全保障協議**: 軍事技術の共同開発・諜報情報の共有など、公開すれば他国の警戒を招く議題
- **二重外交**: 表向きのメッセージと異なる本音の交渉を、非公開チャネルで同時並行する場合
非公開会談（`propose_summit` + `is_private: true`）は、会談の開催事実すら第三国に秘匿されます。デリケートな議題には特に有効です。

【⚠️ 同盟国の集団防衛義務（Collective Defense Obligation）】
自国が同盟関係（alliance）にある国が第三国から攻撃（at_war）を受けている場合、以下を必ず thought_process で検討してください：
- **条約上の義務**: 同盟条約の精神に基づき、同盟国への武力攻撃は自国への攻撃と見なすべきである。共同防衛参加（join_ally_defense）を真剣に検討すること。
- **参戦しない場合のリスク**: 同盟国を見捨てれば、同盟の信頼性が崩壊し、将来の安全保障が大幅に損なわれる。他の同盟国・友好国からの信頼も失う。
- **参戦する場合のリスク**: 自国の経済・軍事への負担、国民の支持率低下、戦争の拡大リスク。
- **最終判断は大統領に委ねられるが、外務大臣として明確な推奨を提示すること**。「同盟国が侵攻されているが参戦しない」という判断には、説得力のある根拠が必要である。
- 参戦せずとも、軍事援助（aid_amount_military）の大幅増額、経済制裁（impose_sanctions）、国際的な非難声明など、支援の選択肢を多角的に検討すること。

【共同防衛参加（join_ally_defense）の仕組み】
`join_ally_defense: true` + `defense_support_commitment: 投入率（0.01〜0.50）` を設定すると、防衛側となっている既存の戦争に「防衛支援国」として参加できます（有志連合型：同盟関係は必須ではない）。
- **target_countryには攻撃国（敵国）を指定**してください。直接宣戦布告（declare_war）とは異なります。
- 自国軍の一部が防衛側に合流し、防衛側の戦力が増強されます。投入分のみが損害を受けます。
- **参加条件**: 攻撃国と交戦中でないこと（自己矛盾防止）。同盟・中立を問わず参加可能。
- declare_warは「自国が攻撃側として新たな二国間戦争を開始する」行為です。共同防衛はjoin_ally_defenseを使ってください。

【停戦・講和に関する提案指針】
自国が交戦中の場合、以下の観点から停戦の是非を thought_process に記載してください。あなたの意見は大統領の最終判断材料になります：
- 現在の占領進捗率と講和条件の有利/不利（占領率3%未満で講和できれば防衛成功として賠償金を請求可能）
- 経済・支持率の消耗状況と戦争継続のコスト
- 同盟国からの支援状況と戦局の見通し
- 相手国の消耗度と停戦に応じる可能性

以下のJSONスキーマに従って出力してください。必ずJSONオブジェクトのみを出力してください。
{
  "thought_process": "戦略思考（150文字程度）",
  "diplomatic_policies": [
    {
      "target_country": "他国の名前",
      "message": "公開メッセージ",
      "is_private": bool,
      "propose_alliance": bool,
      "declare_war": bool,
      "join_ally_defense": bool,
      "defense_support_commitment": 0.01から0.50,
      "propose_annexation": bool,
      "accept_annexation": bool,
      "propose_trade": bool,
      "cancel_trade": bool,
      "impose_sanctions": bool,
      "lift_sanctions": bool,
      "propose_summit": bool,
      "summit_topic": "議題",
      "accept_summit": bool,
      "propose_multilateral_summit": bool,
      "summit_participants": ["招待国名1", "招待国名2", ...],
      "aid_amount_economy": 0.0,
      "aid_amount_military": 0.0,
      "aid_cancel": false,
      "aid_acceptance_ratio": 1.0,
      "reason": "外交決定の理由（30文字以内）"
    }
  ]
}
※ `diplomatic_policies` は相手国の数だけ配列に入れてください。行動がない国は対象外でよいです。
※ **多国間首脳会談**: `propose_multilateral_summit: true` + `summit_participants: ["国A", "国B", ...]` で複数国を招待する多国間会談を提案できます。招待された国は翌ターンに `accept_summit: true` で参加を表明します。2国以上が受諾すれば開催されます。
"""
    return common_ctx + analyst_section + instructions
