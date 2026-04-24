from typing import Dict, Optional
from models import WorldState, CountryState
from agent.prompts.base import build_common_context

def build_finance_minister_prompt(country_name: str, country_state: CountryState, world_state: WorldState, past_news: list = None, analyst_reports: Optional[Dict[str, str]] = None) -> str:
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
    
    # 分析官からの各国レポートを挿入
    analyst_section = ""
    if analyst_reports:
        analyst_section = "\n---📋【分析官からの各国分析レポート】📋---\n"
        analyst_section += "以下は情報分析官(flash-lite)が各対象国について作成した包括的分析です。関税率の決定に際して、各国との通商関係をこの分析を参考に判断してください。\n\n"
        for target_name, report in analyst_reports.items():
            analyst_section += f"▼ 対{target_name}分析レポート:\n{report}\n\n"
    
    instructions = f"""
あなたの役目は、自国の財政政策（税率と関税率）を専門的に策定する「財務大臣」です。
回答は必ず日本語で行ってください。

⚠️ thought_process には以下を必ず含めてください（大統領への提言として使われます）：
①税率変更の推奨値と理由（財政状況との関係）、②主要な関税変更点と通商戦略


【現在の財政状況】
- GDP: {country_state.economy:.1f}
- 国家債務: {country_state.national_debt:.1f}（GDP比 {country_state.national_debt / max(1.0, country_state.economy):.1%}）
- 現在の税率: {country_state.tax_rate:.1%}
- 前期の関税収入: {country_state.tariff_revenue:.1f}
- 前期の貿易収支(NX): {country_state.last_turn_nx:+.1f}

【現在の各国との関税率】
{tariff_info}

【重要: GDP算出方法と関税の関係】
本シミュレーションのGDPは以下のSNA体系で算出されます：

  GDP = (C + I + G) × 教育バフ × (1 + 技術成長率) + NX

- C（民間消費）: (GDP - 税収) × (1 - 貯蓄率)。関税率は消費に影響しません。
- I（民間投資）: 民間貯蓄の還流 + 政府経済投資のクラウドイン効果
- G（政府支出）: 政府予算 × 各分野投資比率 × 政策実行力
- NX（純輸出）: 輸出額 - 輸入額。**NXはGDPに直接加減算されます**

NXの算出（重力モデル）:
- 輸出額 = SCALE × √(自国GDP × 相手国GDP) / (距離 × (1+相手国の関税率)^4)
- 輸入額 = SCALE × √(自国GDP × 相手国GDP) / (距離 × (1+自国の関税率)^4)
- つまり: **自国の関税率が低いと輸入が増え、相手国の関税率が高いと輸出が減る**

⚠️ 貿易赤字（NX < 0）の場合、赤字額がそのまま国家債務に加算されます。

【税率決定のルール】
- 税率は0.10（10%）から0.70（70%）の範囲で設定してください。
- 増税すると政府予算が増えますが、消費と支持率が低下します。
- 減税すると支持率が上がり、消費が活性化しますが、財政赤字のリスクがあります。
- 1ターンの変動上限は±10%です（エンジン側で自動制限されます）。
- 例: 現在30%なら、次ターンは20%〜40%の範囲で設定可能。

【関税率決定のルール】
- 各貿易相手国に対する関税率を設定してください。上限はありません。
- 関税率を上げると：輸入量が大幅に減少（関税弾力性θ=4.0で4乗に効く）し、NXが改善されGDPが向上します。ただし、相手国も報復関税を課す可能性があります。
- 関税率を下げると：輸入量が増加しNXが悪化（＝GDP低下＋国家債務増加）します。本システムでは関税引き下げによる消費者メリットはGDPに反映されません。
- **非対称関税の危険**: 相手国が高関税を課しているのに自国が低関税だと、輸出は減るのに輸入は増え、NXが大幅に悪化します。相手国の関税率とのバランスを考慮してください。
- 1ターンの関税率変動上限は±5%です（エンジン側で自動制限されます）。
- 関税収入 = 輸入額 × 関税率です。関税を上げすぎると貿易量が減り、むしろ関税収入が減ることに注意してください（ラッファー曲線）。
- 関税率を0%に設定すると関税収入がゼロになり、かつNXが最大限悪化するため、通常は推奨されません。

以下のJSONスキーマに従って出力してください。必ずJSONオブジェクトのみを出力してください。
{{
  "thought_process": "財政・通商戦略の思考サマリー（150文字程度、大統領への提言を含む）",
  "tax_rate": 0.30,
  "target_tariff_rates": {{
    "国名1": 関税率（0.0以上の小数）,
    "国名2": 関税率（0.0以上の小数）
  }}
}}
⚠️ tax_rate は必ず **0.10〜0.70の小数** で指定してください（例: 30% → 0.30、40% → 0.40）。パーセント整数（30、40など）は無効です。
"""
    return common_ctx + analyst_section + instructions
