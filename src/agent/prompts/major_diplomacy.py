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

    other_countries = [n for n in world_state.countries if n != country_name]
    example_target = other_countries[0] if other_countries else "対象国"

    return ctx + f"""
【🏛️ 大統領施政方針 ({stance})】
{directives_str}

【現在の交戦状況】
{wars_info}
【同盟国】
{alliance_info}
【海峡封鎖状況】
{blockade_info}

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

【ルール】
- 不要なアクションは出力しない（何もしない場合は major_diplomatic_actions: []）
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
  "resolve_strait_blockade": null
}}
"""
