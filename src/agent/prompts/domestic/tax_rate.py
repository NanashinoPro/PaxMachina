from models import WorldState, CountryState, PresidentPolicy
from agent.prompts.base import build_common_context
from agent.prompts.domestic import build_policy_section

def build_tax_rate_prompt(country_name, country_state: CountryState, world_state: WorldState, policy: PresidentPolicy, past_news=None) -> str:
    """I-01: 税率決定（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="財政担当官（税率）")
    return ctx + build_policy_section(policy) + f"""
【現在の財政状況】
- 税率: {country_state.tax_rate:.1%}
- 政府予算: {country_state.government_budget:.1f}
- 国家債務(GDP比): {country_state.national_debt/max(1,country_state.economy):.1%}
- 支持率: {country_state.approval_rating:.1f}%

【ルール】税率は0.10〜0.70。1ターンの変動上限±10%。増税で予算増・支持率低下。

施政方針の財政方針に従い、税率を1つ決定してください。JSONのみ出力:
{{"tax_rate": 0.30, "reason": "理由（30文字以内）"}}
"""
