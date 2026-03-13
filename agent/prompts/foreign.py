from models import WorldState, CountryState
from agent.prompts.base import build_common_context

def build_foreign_minister_prompt(country_name: str, country_state: CountryState, world_state: WorldState, past_news: list = None) -> str:
    common_ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="外務大臣")
    
    instructions = """
あなたの役目は、他国の情報や世界情勢を踏まえて、自国の利益と発展を最大化するための「外交方針」を専門的に策定することです。
同盟・戦争・併合、貿易や経済制裁、首脳会談の提案、対外援助などを選択可能です。
回答は必ず日本語で行ってください。

【対外援助（Foreign Aid）と属国化・代理戦争ルール】
外交アクションで `aid_amount_economy` または `aid_amount_military` を指定すると、自国の予算（G）を削って相手国に無償の資金提供を行えます。
1. 属国化（Vassalage）の戦略: 巨額の支援を継続的に行い、相手のGDPに対する「累積援助比率（依存度）」が60(%)を超えさせると、相手の主権を強制的に剥奪し、完全な「属国（傀儡）」にすることができます。
2. 代理戦争の戦略: 直接戦いたくない仮想敵国がある場合、その周辺国に軍事支援を流し込んで戦わせることが可能です。
3. ⚠️【重要】オランダ病（吸収限界）の警告: 相手国が1ターンの間に「自国の実質GDPの20%」を超える援助を与えられると、汚職とインフレ（オランダ病）により政策実行力が大暴落（最大半減）します。相手が吸収できる適量を見極めながら継続的に資金漬けにしてください。

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
      "reason": "外交決定の理由（30文字以内）"
    }
  ]
}
※ diplomatic_policies は相手国の数だけ配列に入れてください。行動がない国は対象外でよいです。
"""
    return common_ctx + instructions
