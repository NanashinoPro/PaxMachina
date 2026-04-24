from models import WorldState, CountryState, PresidentPolicy
from agent.prompts.base import build_common_context
from agent.prompts.domestic import build_policy_section

def build_press_freedom_prompt(country_name, country_state: CountryState, world_state: WorldState, policy: PresidentPolicy, past_news=None) -> str:
    """I-06: 報道の自由度設定（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="内務担当官（報道統制）")
    cur = country_state.press_freedom
    return ctx + build_policy_section(policy) + f"""
現在の報道の自由度={cur:.3f} / 支持率={country_state.approval_rating:.1f}%
【ルール】0.0〜1.0。下げると情報統制が強まり秘密工作露呈リスク低下。ただし即時支持率低下。

施政方針に従い{country_name}の報道の自由度を判断してください。
JSONのみ出力（コードブロック不要、数値は自分で判断すること）:
{{"target_press_freedom": ???, "reason": "理由（30文字以内）"}}
"""

def build_deception_prompt(country_name, country_state: CountryState, world_state: WorldState, policy: PresidentPolicy, past_news=None) -> str:
    """I-07: 情報偽装（flash）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="情報担当官（対外公表）")
    return ctx + build_policy_section(policy) + f"""
現在の真値: 経済={country_state.economy:.1f} / 軍事={country_state.military:.1f} / 支持率={country_state.approval_rating:.1f}% / 諜報={country_state.intelligence_level:.1f}
現在の偽装: 経済={country_state.reported_economy} / 軍事={country_state.reported_military} / 支持率={country_state.reported_approval_rating} / 諜報={country_state.reported_intelligence_level}

【ルール】Noneなら真値をそのまま公開。意図的に乖離させることで他国の判断を誤誘導できるが、
メディアに暴かれるリスクあり。偽装しない場合は全フィールドをnullに。

JSONのみ出力（偽装しない場合は全null）:
{{"report_economy": null, "report_military": null, "report_approval_rating": null, "report_intelligence_level": null, "report_gdp_per_capita": null, "deception_reason": ""}}
"""

def build_parliament_prompt(country_name, country_state: CountryState, world_state: WorldState, policy: PresidentPolicy, past_news=None) -> str:
    """I-08: 議会解散判断（flash-lite）・民主主義のみ"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="政治担当官（議会）")
    turns_left = country_state.turns_until_election
    return ctx + build_policy_section(policy) + f"""
次回選挙まで={turns_left}ターン / 支持率={country_state.approval_rating:.1f}% / 解散権={country_state.has_dissolution_power}
【ルール】dissolve_parliament=trueで議会解散。成功率=支持率%。失敗すると政権交代。費用=GDP×0.01〜0.02%。

JSONのみ出力:
{{"dissolve_parliament": false, "reason": "理由（30文字以内）"}}
"""
