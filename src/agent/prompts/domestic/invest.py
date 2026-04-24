from models import WorldState, CountryState, PresidentPolicy
from agent.prompts.base import build_common_context
from agent.prompts.domestic import build_policy_section

def build_economy_invest_prompt(country_name, country_state: CountryState, world_state: WorldState, policy: PresidentPolicy, past_news=None) -> str:
    """I-03: 経済投資配分（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="経済担当官（経済投資）")
    return ctx + build_policy_section(policy) + f"""
GDP={country_state.economy:.1f} / 1人当GDP={country_state.economy/max(0.1,country_state.population):.2f}
貿易収支NX={country_state.last_turn_nx:+.1f} / 国家債務GDP比={country_state.national_debt/max(1,country_state.economy):.1%}

【ルール】invest_economy(0.0〜1.0): GDP成長への直接投資比率。予算×invest_economyが政府支出として経済に投入される。
債務が多い場合は合計を1.0未満に抑えて余剰を債務返済に充てることを検討。

施政方針に従い経済投資配分を決定してください。JSONのみ出力:
{{"invest_economy": 0.35, "reason": "理由（30文字以内）"}}
"""

def build_welfare_invest_prompt(country_name, country_state: CountryState, world_state: WorldState, policy: PresidentPolicy, past_news=None) -> str:
    """I-04: 福祉投資配分（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="福祉担当官（福祉投資）")
    density = country_state.population / max(10.0, country_state.area * 150.0)
    return ctx + build_policy_section(policy) + f"""
支持率={country_state.approval_rating:.1f}% / 人口密度={density*100:.1f}%（環境収容力比）
【ルール】invest_welfare: 支持率維持・人口動態管理。少子化対策として有効。
過密（80%超）なら福祉カットで人口抑制も選択肢。

JSONのみ出力:
{{"invest_welfare": 0.25, "reason": "理由（30文字以内）"}}
"""

def build_education_invest_prompt(country_name, country_state: CountryState, world_state: WorldState, policy: PresidentPolicy, past_news=None) -> str:
    """I-05: 教育・科学投資配分（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="教育担当官（教育投資）")
    return ctx + build_policy_section(policy) + f"""
人的資本指数HCI={country_state.human_capital_index:.3f} / 平均就学年数={country_state.mean_years_schooling:.1f}年
【ルール】invest_education_science: HCIを蓄積し中長期的なGDP成長バフを生む。

JSONのみ出力:
{{"invest_education_science": 0.05, "reason": "理由（30文字以内）"}}
"""
