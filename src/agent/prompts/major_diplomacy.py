"""
P-02: 重大外交決定プロンプト（flashモデル）
Phase0の第2段: 大統領施政方針（PresidentPolicy）を受け取り、
宣戦布告・同盟提案・停戦・併合・海峡封鎖などの重大外交アクションを決定する。
"""
from typing import List
from models import WorldState, CountryState, PresidentPolicy


def build_major_diplomacy_prompt(
    country_name: str,
    country_state: CountryState,
    world_state: WorldState,
    policy: PresidentPolicy,
    past_news: List[str] = None,
) -> str:
    """
    P-02: 重大外交決定プロンプト（flashモデル）
    大統領施政方針に従い、宣戦布告・同盟・停戦・海峡封鎖などを決定する。
    """
    from agent.prompts.base import build_common_context
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="大統領（重大外交決定）")

    stance = policy.stance
    directives_str = "\n".join(f"・{d}" for d in policy.directives)

    # 現在の戦争状況
    wars_info = ""
    for w in world_state.active_wars:
        if w.aggressor == country_name or w.defender == country_name:
            opponent = w.defender if w.aggressor == country_name else w.aggressor
            role = "攻撃側" if w.aggressor == country_name else "防衛側"
            wars_info += f"  - {opponent}（{role}、経過{w.war_turns_elapsed}ターン、占領進捗{w.target_occupation_progress:.0f}%）\n"
    if not wars_info:
        wars_info = "  なし\n"

    # 同盟状況
    alliance_info = ""
    for p, rel in world_state.relations.get(country_name, {}).items():
        if rel.value == "alliance":
            alliance_info += f"  - {p}\n"
    if not alliance_info:
        alliance_info = "  なし\n"

    # 海峡封鎖状況
    blockade_info = ""
    if world_state.active_strait_blockades:
        for s in world_state.active_strait_blockades:
            owner = world_state.strait_blockade_owners.get(s, "不明")
            blockade_info += f"  - {s}（封鎖国: {owner}）\n"
    else:
        blockade_info = "  なし\n"

    # 核兵器状況（v1-3追加）
    nuclear_info = ""
    if country_state.nuclear_warheads > 0:
        nuclear_info = f"""
【☢️ 核兵器状況】
自国核弾頭: {country_state.nuclear_warheads}発
"""
    elif country_state.nuclear_hosted_warheads > 0:
        nuclear_info = f"""
【☢️ 核配備状況】
{country_state.nuclear_host_provider}から{country_state.nuclear_hosted_warheads}発が配備中
"""

    # JSONスキーマの例示用ターゲット国名（自国以外の最初の国）
    example_target = next((n for n in world_state.countries if n != country_name), "相手国名")

    return ctx + f"""
【🏛️ 大統領施政方針 ({stance})】
{directives_str}

【現在の交戦状況】
{wars_info}
【同盟国】
{alliance_info}
【海峡封鎖状況】
{blockade_info}
{nuclear_info}
あなたは「{country_name}」の大統領として、**重大な外交決定のみ**を行ってください。
重大外交とは以下を指します:
- 宣戦布告（declare_war: true）
- 同盟提案（propose_alliance: true）
- 同盟国への防衛参加（join_ally_defense: true）
- 領土統合提案/受諾（propose_annexation / accept_annexation）
- 停戦提案/受諾（propose_ceasefire / accept_ceasefire）
- 降伏勧告/受諾（demand_surrender / accept_surrender）
- 海峡封鎖宣言（declare_strait_blockade: "海峡名"）
- 海峡封鎖解除（resolve_strait_blockade: "海峡名"）
- ☢️ 戦術核使用（launch_tactical_nuclear: "対象国名", tactical_nuclear_count: 数値）— 交戦中のみ。前線の敵軍事力に大ダメージ。弾頭数は1〜保有数の範囲で指定。
- ☢️ 戦略核使用（launch_strategic_nuclear: "対象国名", strategic_nuclear_count: 数値）— 交戦中のみ。敵の経済・人口・軍事に壊滅的ダメージ。弾頭数を指定。
- ☢️ 同盟国への核配備（deploy_nuclear_to_ally: "同盟国名", deploy_nuclear_count: 数値）
- ☢️ 自国領土の他国核撤去（remove_hosted_nuclear: true）

【☢️ 核兵器の威力目安】
■ 戦術核（前線軍事力への攻撃）:
  ダメージ = 敵軍事力 × 敵投入率 × 25% × log2(着弾弾頭数+1)
  - 1発着弾 → 敵前線軍事力の約25%を破壊
  - 3発着弾 → 約50%を破壊（2倍の威力）
  - 7発着弾 → 約75%を破壊（3倍の威力）
  ※ 敵のミサイル防衛（ABM）により一部が迎撃される可能性あり。
  ※ 軍事力が大きい敵ほどABM迎撃率が高い。

■ 戦略核（経済・人口・軍事への壊滅攻撃）:
  弾頭数が多いほど壊滅度が増加（対数スケーリング）。
  - 5発着弾 → 経済約-15%, 人口約-10%, 軍事約-20%
  - 15発着弾 → 経済約-30%, 人口約-20%, 軍事約-20%
  - 50発以上 → 国家機能の大部分を破壊
  ※ 戦略核もABMにより迎撃される可能性あり。

【ルール】
- 不要なアクションは出力しない（何もしない場合は major_diplomatic_actions: []）
- 核使用は交戦中の敵国にのみ可能。保有弾頭数が足りない場合は使用不可。
- 海峡封鎖は自国が資格を持つ場合のみ（イラン→ホルムズ海峡、アメリカ→ホルムズ海峡等）
- 施政方針に従い、合理的な判断のみ行う

以下のJSONのみ出力してください:
{{
  "major_diplomatic_actions": [
    {{
      "target_country": "{example_target}",
      "declare_war": false,
      "propose_alliance": false,
      "join_ally_defense": false,
      "defense_support_commitment": null,
      "propose_annexation": false,
      "accept_annexation": false,
      "propose_ceasefire": false,
      "accept_ceasefire": false,
      "demand_surrender": false,
      "accept_surrender": false,
      "reason": "理由"
    }}
  ],
  "declare_strait_blockade": null,
  "resolve_strait_blockade": null,
  "launch_tactical_nuclear": null,
  "tactical_nuclear_count": 1,
  "launch_strategic_nuclear": null,
  "strategic_nuclear_count": 5,
  "deploy_nuclear_to_ally": null,
  "deploy_nuclear_count": 0,
  "remove_hosted_nuclear": false
}}
"""
