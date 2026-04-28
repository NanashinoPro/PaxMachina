"""
M-01: 軍事投資（金額ベース）+ 核開発投資
M-02: 諜報投資（金額ベース）
M-03: 前線投入比率
"""
from typing import Dict
from models import WorldState, CountryState, PresidentPolicy
from agent.prompts.base import build_common_context
from agent.prompts.domestic import build_policy_section


def build_military_invest_prompt(
    country_name: str, country_state: CountryState, world_state: WorldState,
    policy: PresidentPolicy, analyst_reports: Dict[str, str] = None, past_news=None
) -> str:
    """M-01: 軍事投資額の決定 + 核開発投資（flash）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="軍事担当官（軍事投資・核戦略）")
    ar = ""
    if analyst_reports:
        ar = "\n---【分析官レポート（軍事バランス参照）】---\n"
        for t, r in analyst_reports.items():
            ar += f"▼ 対{t}:\n{r}\n\n"

    # 核情報
    step_names = {0: "未着手", 1: "ウラン濃縮中", 2: "核実験段階", 3: "実戦配備中", 4: "核保有国"}
    nuke_step = step_names.get(country_state.nuclear_dev_step, "不明")
    nuke_section = f"\n【☢️ 核開発状況】\n核弾頭: {country_state.nuclear_warheads}発 / 開発段階: {nuke_step}\n"
    if country_state.nuclear_dev_step in (1, 2, 3):
        progress = (country_state.nuclear_dev_invested / max(1.0, country_state.nuclear_dev_target)) * 100
        nuke_section += f"開発進捗: {country_state.nuclear_dev_invested:.1f}/{country_state.nuclear_dev_target:.1f} ({progress:.0f}%)\n"

    budget = country_state.government_budget
    debt_ratio = country_state.national_debt / max(1.0, country_state.economy) * 100

    return ctx + build_policy_section(policy) + ar + nuke_section + f"""
現在の軍事力={country_state.military:.1f} / 経済力={country_state.economy:.1f}

【💰 今期の政府歳入: {budget:.1f} B$】
国家債務: {country_state.national_debt:.1f} B$ (対GDP比: {debt_ratio:.0f}%)
歳入を超える額を要求することも可能ですが、超過分は赤字国債として発行され、利払い負担が増大します。

【リチャードソン・モデルに基づく算出プロセス】
1. 相手側の脅威: 自国より強い敵がいるか？
2. 経済的疲弊: 軍事投資は経済を圧迫するか？
3. 動員限界(10%の壁): 軍事力が人口×10%を超えていないか？

【☢️ 核開発投資（request_nuclear）の決定ルール】
- 核開発は4段階（1:ウラン濃縮→2:核実験→3:実戦配備→4:核保有国）で進行。
- 0.0の場合、核開発に予算を割かない。Step4到達後は弾頭量産に充当。
- 大きな経済負担を伴うため、戦略的必要性を十分に検討すること。

【☢️ 核使用の提言（nuclear_use_recommendation）】
- 大統領への助言として核使用を提言可能。最終決定権は大統領にある。
- 交戦中の敵国だけでなく、先制核攻撃（自動宣戦布告を伴う）の提言も可能。
- 形式: "tactical:対象国名" or "strategic:対象国名" or null

施政方針（{policy.stance}）に従い、reasoning_for_military_investmentで算出プロセスを説明した上で投資額を決定してください。

JSONのみ出力（コードブロック不要、金額はB$単位で指定）:
{{"request_military": ???, "request_nuclear": ???, "nuclear_use_recommendation": null, "reasoning_for_military_investment": "算出プロセスの説明"}}
"""


def build_intel_invest_prompt(
    country_name: str, country_state: CountryState, world_state: WorldState,
    policy: PresidentPolicy, past_news=None
) -> str:
    """M-02: 諜報投資額の決定（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="諜報担当官（諜報投資）")
    others_intel = {n: s.intelligence_level for n, s in world_state.countries.items() if n != country_name}
    intel_str = ", ".join(f"{n}:{v:.1f}" for n, v in others_intel.items())
    budget = country_state.government_budget
    return ctx + build_policy_section(policy) + f"""
自国諜報レベル={country_state.intelligence_level:.1f} / 他国: {intel_str}

【💰 今期の政府歳入: {budget:.1f} B$】
【ルール】諜報レベルが高いほど諜報成功率が向上。金額（B$単位）で投資額を指定してください。

JSONのみ出力（コードブロック不要、金額はB$単位で指定）:
{{"request_intelligence": ???, "reason": "理由（30文字以内）"}}
"""


def build_war_commitment_prompt(
    country_name: str, country_state: CountryState, world_state: WorldState,
    policy: PresidentPolicy, past_news=None
) -> str:
    """M-03: 前線投入比率の設定（flash）- 交戦中のみ呼び出す"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="作戦担当官（前線投入）")
    war_info = ""
    for w in world_state.active_wars:
        if w.aggressor == country_name:
            war_info += f"  ⚔️ 対{w.defender}: 攻撃側 / 占領率{w.target_occupation_progress:.1f}% / 現投入率{w.aggressor_commitment_ratio:.0%}\n"
        elif w.defender == country_name:
            war_info += f"  🛡️ 対{w.aggressor}: 防衛側 / 被占領率{w.target_occupation_progress:.1f}% / 現投入率{w.defender_commitment_ratio:.0%}\n"
    return ctx + build_policy_section(policy) + f"""
現在の軍事力={country_state.military:.1f}

【交戦状況】
{war_info}

【ルール】
- 投入比率(0.0〜1.0)で前線の兵力投入を設定
- 防御側は高い投入率を維持するのが自然。攻撃側は兵站を考慮。
- 投入比率は±{0.10:.0%}/ターンまでの変動制限あり（動員速度制限）

JSONのみ出力:
{{"commitment_ratio": ???, "reason": "理由（30文字以内）"}}
"""


def build_espionage_gather_prompt(
    country_name: str, country_state: CountryState, world_state: WorldState,
    target_name: str, policy: PresidentPolicy,
    analyst_report: str = "", past_news=None
) -> str:
    """M-04: 諜報収集の実施（flash-lite）- 対象国1つごとに呼び出す"""
    target_state = world_state.countries.get(target_name)
    rel = world_state.relations.get(country_name, {}).get(target_name, "neutral")
    return build_policy_section(policy) + f"""
あなたは「{country_name}」の諜報担当官です。対象国「{target_name}」への諜報収集を実施するか判断してください。

自国諜報レベル={country_state.intelligence_level:.1f} / 対象国諜報レベル={getattr(target_state,'intelligence_level',0):.1f}
二国間関係={rel} / 分析官レポート: {analyst_report[:200] if analyst_report else 'なし'}

【ルール】espionage_gather_intel=trueで情報収集を実施。失敗リスクあり（相手の諜報力が高いほど失敗しやすい）。

JSONのみ出力:
{{"espionage_gather_intel": false, "espionage_intel_strategy": null, "reason": "理由（30文字以内）"}}
"""


def build_espionage_sabotage_prompt(
    country_name: str, country_state: CountryState, world_state: WorldState,
    target_name: str, policy: PresidentPolicy,
    analyst_report: str = "", past_news=None
) -> str:
    """M-05: 破壊工作の実施（flash）- 対象国1つごとに呼び出す"""
    target_state = world_state.countries.get(target_name)
    rel = world_state.relations.get(country_name, {}).get(target_name, "neutral")
    return build_policy_section(policy) + f"""
あなたは「{country_name}」の工作担当官です。対象国「{target_name}」への破壊工作を実施するか判断してください。

自国諜報レベル={country_state.intelligence_level:.1f} / 対象国諜報レベル={getattr(target_state,'intelligence_level',0):.1f}
対象国軍事力={getattr(target_state,'military',0):.1f} / 二国間関係={rel}
分析官レポート: {analyst_report[:200] if analyst_report else 'なし'}

【ルール】espionage_sabotage=trueでインフラ・世論への破壊工作を実施。
実行コスト・リスク・外交的リスクを考察してください（reasoning_for_sabotage）。

JSONのみ出力:
{{"espionage_sabotage": false, "espionage_sabotage_strategy": null, "reasoning_for_sabotage": "考察（工作する・しない理由）"}}
"""
