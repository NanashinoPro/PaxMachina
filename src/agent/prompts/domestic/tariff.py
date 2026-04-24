from models import WorldState, CountryState, PresidentPolicy
from agent.prompts.base import build_common_context
from agent.prompts.domestic import build_policy_section

def build_tariff_prompt(country_name, country_state: CountryState, world_state: WorldState, policy: PresidentPolicy, past_news=None) -> str:
    """I-02: 関税率決定（flash）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="通商担当官（関税率）")
    tariff_info = ""
    for t in world_state.active_trades:
        if t.country_a == country_name:
            tariff_info += f"  - 対{t.country_b}: 自国={t.tariff_a_to_b:.1%}, 相手={t.tariff_b_to_a:.1%}\n"
        elif t.country_b == country_name:
            tariff_info += f"  - 対{t.country_a}: 自国={t.tariff_b_to_a:.1%}, 相手={t.tariff_a_to_b:.1%}\n"
    if not tariff_info:
        tariff_info = "  （貿易協定なし）\n"

    countries = [n for n in world_state.countries if n != country_name]
    example = {c: 0.10 for c in countries[:2]}
    return ctx + build_policy_section(policy) + f"""
【現在の関税率】
{tariff_info}
【ルール】各貿易相手国への関税率を設定。1ターン±5%制限。NX(純輸出)に直接影響。
自国関税↑→輸入減→NX改善。相手国関税↑→輸出減→NX悪化。

施政方針の通商方針に従い、各国への関税率を決定してください。JSONのみ出力:
{{"target_tariff_rates": {example}, "reason": "理由（30文字以内）"}}
※ 対象は貿易協定締結国のみ。未締結国は省略可。
"""
