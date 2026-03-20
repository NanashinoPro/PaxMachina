from models import WorldState, CountryState
from agent.prompts.base import build_common_context

def build_finance_minister_prompt(country_name: str, country_state: CountryState, world_state: WorldState, past_news: list = None) -> str:
    common_ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="財務大臣")
    
    # 現在の関税率情報を構築
    tariff_info = ""
    for trade in world_state.active_trades:
        if trade.country_a == country_name:
            tariff_info += f"  - 対{trade.country_b}: 自国の関税率={trade.tariff_a_to_b:.1%}, 相手国の関税率={trade.tariff_b_to_a:.1%}\n"
        elif trade.country_b == country_name:
            tariff_info += f"  - 対{trade.country_a}: 自国の関税率={trade.tariff_b_to_a:.1%}, 相手国の関税率={trade.tariff_a_to_b:.1%}\n"
    
    if not tariff_info:
        tariff_info = "  （現在、貿易協定を結んでいる国はありません）\n"
    
    instructions = f"""
あなたの役目は、自国の財政政策（税率と関税率）を専門的に策定する「財務大臣」です。
回答は必ず日本語で行ってください。

【現在の財政状況】
- GDP: {country_state.economy:.1f}
- 国家債務: {country_state.national_debt:.1f}（GDP比 {country_state.national_debt / max(1.0, country_state.economy):.1%}）
- 現在の税率: {country_state.tax_rate:.1%}
- 前期の関税収入: {country_state.tariff_revenue:.1f}
- 前期の貿易収支(NX): {country_state.last_turn_nx:+.1f}

【現在の各国との関税率】
{tariff_info}

【税率決定のルール】
- 税率は0.10（10%）から0.70（70%）の範囲で設定してください。
- 増税すると政府予算が増えますが、消費と支持率が低下します。
- 減税すると支持率が上がり、消費が活性化しますが、財政赤字のリスクがあります。
- 1ターンの変動上限は±10%です（エンジン側で自動制限されます）。
- 例: 現在30%なら、次ターンは20%〜40%の範囲で設定可能。

【関税率決定のルール】
- 各貿易相手国に対する関税率を設定してください。上限はありません。
- 関税率を上げると：輸入品が高くなり、相手国からの貿易量が大幅に減少（関税弾力性θ=4.0で4乗に効く）。ただし、相手国も報復関税を課す可能性があります。
- 関税率を下げると：安い輸入品が流入し消費者は利益を得ますが、国内産業が圧迫される可能性があります。
- 1ターンの関税率変動上限は±5%です（エンジン側で自動制限されます）。
- 関税収入 = 輸入額 × 関税率です。関税を上げすぎると貿易量が減り、むしろ関税収入が減ることに注意してください（ラッファー曲線）。

以下のJSONスキーマに従って出力してください。必ずJSONオブジェクトのみを出力してください。
{{
  "thought_process": "財政・通商戦略の思考（150文字程度）",
  "tax_rate": 0.10から0.70の数値,
  "target_tariff_rates": {{
    "国名1": 関税率（0.0以上の数値）,
    "国名2": 関税率（0.0以上の数値）
  }},
  "reason": "財政決定の理由（30文字以内）"
}}
"""
    return common_ctx + instructions
