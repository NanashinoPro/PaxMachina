from models import WorldState, CountryState, PresidentPolicy
from agent.prompts.base import build_common_context
from agent.prompts.domestic import build_policy_section

def build_economy_invest_prompt(country_name, country_state: CountryState, world_state: WorldState, policy: PresidentPolicy, past_news=None) -> str:
    """I-03: 経済投資額の決定（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="経済担当官（経済投資）")
    budget = country_state.government_budget
    debt_ratio = country_state.national_debt / max(1.0, country_state.economy) * 100
    return ctx + build_policy_section(policy) + f"""
GDP={country_state.economy:.1f} / 1人当GDP={country_state.economy/max(0.1,country_state.population):.2f}
貿易収支NX={country_state.last_turn_nx:+.1f} / 国家債務GDP比={debt_ratio:.0f}%

【💰 今期の政府歳入: {budget:.1f} B$】
国家債務: {country_state.national_debt:.1f} B$
歳入を超える額を要求することも可能ですが、超過分は赤字国債として発行され、利払い負担が増大します。
債務が多い場合は要求額を抑えることを検討してください。

【ルール】request_economy(B$単位): GDP成長への直接投資額。政府支出として経済に投入される。

施政方針に従い{country_name}の経済投資額を判断してください。
JSONのみ出力（コードブロック不要、金額はB$単位で指定）:
{{"request_economy": ???, "reason": "理由（30文字以内）"}}
"""

def build_welfare_invest_prompt(country_name, country_state: CountryState, world_state: WorldState, policy: PresidentPolicy, past_news=None) -> str:
    """I-04: 福祉投資額の決定（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="福祉担当官（福祉投資）")
    density = country_state.population / max(10.0, country_state.area * 150.0)
    budget = country_state.government_budget
    return ctx + build_policy_section(policy) + f"""
支持率={country_state.approval_rating:.1f}% / 人口密度={density*100:.1f}%（環境収容力比）

【💰 今期の政府歳入: {budget:.1f} B$】
【ルール】request_welfare(B$単位): 支持率維持・人口動態管理のための福祉支出額。少子化対策として有効。
過密（80%超）なら福祉カットで人口抑制も選択肢。

施政方針に従い{country_name}の福祉投資額を判断してください。
JSONのみ出力（コードブロック不要、金額はB$単位で指定）:
{{"request_welfare": ???, "reason": "理由（30文字以内）"}}
"""

def build_education_invest_prompt(country_name, country_state: CountryState, world_state: WorldState, policy: PresidentPolicy, past_news=None) -> str:
    """I-05: 教育・科学投資額の決定（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="教育担当官（教育投資）")
    budget = country_state.government_budget
    return ctx + build_policy_section(policy) + f"""
人的資本指数HCI={country_state.human_capital_index:.3f} / 平均就学年数={country_state.mean_years_schooling:.1f}年

【💰 今期の政府歳入: {budget:.1f} B$】
【ルール】request_education(B$単位): HCIを蓄積し中長期的なGDP成長バフを生むための教育・科学支出額。

施政方針に従い{country_name}の教育・科学投資額を判断してください。
JSONのみ出力（コードブロック不要、金額はB$単位で指定）:
{{"request_education": ???, "reason": "理由（30文字以内）"}}
"""
