from typing import Dict
from models import WorldState, CountryState
from agent.prompts.base import build_common_context
from engine.constants import STRAIT_BLOCKADE_ELIGIBLE_COUNTRIES

def build_president_prompt(
    country_name: str,
    country_state: CountryState,
    world_state: WorldState,
    minister_summaries: Dict[str, str],
    past_news: list = None,
    budget_requests: Dict[str, float] = None,
    presidential_flags: Dict[str, str] = None,
) -> str:
    """
    大統領プロンプト（大臣最終決定制）
    - minister_summaries: {大臣名: thought_process}
    - budget_requests: {項目名: 要求値} 例: {request_invest_military: 0.20, ...}
    - presidential_flags: {フラグの説明: 推奨テキスト} 例: {"同盟国が攻撃されています": "join_ally_defense を検討"}
    """
    # 戦時判定（大統領プロンプト内で直接判断に使う）
    is_at_war = any(
        w.aggressor == country_name or w.defender == country_name
        for w in world_state.active_wars
    )
    ally_names = {
        r for r, rel in world_state.relations.get(country_name, {}).items()
        if str(rel).lower() == 'alliance'
    }
    ally_under_attack = any(
        (w.defender in ally_names or w.aggressor in ally_names)
        for w in world_state.active_wars
        if w.aggressor != country_name and w.defender != country_name
    )

    # common_ctxは世界情勢を含む（active_wars, relationsも表示済み）
    common_ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="最高指導者（大統領/首相）")

    # 大臣サマリー整形
    summaries_text = "\n".join(
        f"▼ {role}:\n{text}"
        for role, text in minister_summaries.items()
    )

    # 予算要求の整形
    if budget_requests:
        mil   = budget_requests.get("request_invest_military", 0.0)
        intel = budget_requests.get("request_invest_intelligence", 0.0)
        eco   = budget_requests.get("request_invest_economy", 0.0)
        wel   = budget_requests.get("request_invest_welfare", 0.0)
        edu   = budget_requests.get("request_invest_education_science", 0.0)
        total = mil + intel + eco + wel + edu
        surplus = 1.0 - total
        budget_section = f"""
【📊 予算要求の調停（大統領の最終決定が必要）】
防衛大臣:
  invest_military:      {mil:.2f}
  invest_intelligence:  {intel:.2f}
経済大臣:
  invest_economy:            {eco:.2f}
  invest_welfare:            {wel:.2f}
  invest_education_science:  {edu:.2f}
━━━━━━━━━━━━━━━━━━
要求合計: {total:.2f}  （余剰: {surplus:+.2f}）
※ 合計が1.0を超えている場合は各項目を調整してください。
※ 余剰がある場合は、追加配分するか緊縮財政として空けてください（空けると債務返済に充当）。
"""
    else:
        budget_section = "【⚠️ 予算要求情報が取得できませんでした。適切な値を独自判断してください。】\n"

    # 重大事案フラグ（大統領が判断すべき状況）
    flags_section = ""
    if is_at_war:
        war_info = []
        for w in world_state.active_wars:
            if w.aggressor == country_name:
                war_info.append(f"  ⚔️ 対{w.defender}（攻撃中・占領率{w.target_occupation_progress:.1f}%）")
            elif w.defender == country_name:
                war_info.append(f"  🛡️ 対{w.aggressor}（防衛中・被占領率{w.target_occupation_progress:.1f}%）")
        flags_section += f"\n【⚔️ 重大事案: 現在交戦中】\n" + "\n".join(war_info)
        flags_section += """
→ 以下を major_diplomatic_actions に含めることができます:
  - propose_ceasefire: true（停戦提案）
  - accept_ceasefire: true（停戦受諾）
  - demand_surrender: true（降伏勧告・攻撃側のみ）
  - accept_surrender: true（降伏受諾・防衛側のみ）
"""
    if ally_under_attack:
        flags_section += "\n【⚠️ 重大事案: 同盟国が攻撃を受けています】\n"
        for w in world_state.active_wars:
            if w.defender in ally_names:
                flags_section += f"  {w.defender}（防衛中）← {w.aggressor}（攻撃）\n"
            elif w.aggressor in ally_names:
                flags_section += f"  {w.aggressor}（攻撃中） → {w.defender}（防衛中）\n"
        flags_section += """→ 以下を major_diplomatic_actions に含めることができます:
  - join_ally_defense: true（共同防衛参加）+ defense_support_commitment（投入率0.01〜0.50）
  - target_country には攻撃国を指定してください
"""

    # v1-2: 海峡封鎖のエネルギー情報セクション
    energy_section = ""

    # 自国のエネルギー状況
    reserve = country_state.energy_reserve_turns
    target = country_state.energy_reserve_target_turns
    reserve_pct = (reserve / target * 100) if target > 0 else 100
    blockades = world_state.active_strait_blockades

    energy_status_str = f"備蓄{reserve:.2f}ターン/{target:.2f}ターン ({reserve_pct:.0f}%)"
    if reserve_pct <= 25:
        energy_status_str = f"🔴【危機】{energy_status_str} - インフラ崩壊・工場停止進行中"
    elif reserve_pct <= 50:
        energy_status_str = f"⚠️【警戒】{energy_status_str} - 節電要請・燃料高騰中"

    energy_section += f"\n【⚡ 自国エネルギー状況】 {energy_status_str}\n"

    # 現在の封鎖状況
    if blockades:
        energy_section += f"\n🚨 現在封鎖中の海峡: {', '.join(blockades)}"
        for strait in blockades:
            owner = world_state.strait_blockade_owners.get(strait, "不明")
            energy_section += f" (封鎖宣言国: {owner})"
        energy_section += "\n"
    else:
        energy_section += "現在海峡封鎖: なし\n"

    # 封鎖資格国の場合のみ、封鎖権限セクションを表示
    eligible_straits = [
        strait for strait, eligible in STRAIT_BLOCKADE_ELIGIBLE_COUNTRIES.items()
        if country_name in eligible
    ]
    if eligible_straits:
        energy_section += f"""\n【🚢 海峡封鎖権限: {country_name}は以下の海峡を封鎖・解除できます】
  封鎖可能: {', '.join(eligible_straits)}
  封鎖宣言時の影響:ホルムズ封鎖→ 日本(deficit 0.74)・フィリピン(deficit 0.90)に深刻なエネルギー危機
  JSON出力時: "declare_strait_blockade": "ホルムズ海峡"  または "resolve_strait_blockade": "ホルムズ海峡"を追加する
  ❗【重要】封鎖の解除は「宣言した国のみ」が行えます。自国が宣言していない海峡は resolve_strait_blockade で解除できません（null にしてください）。
  ❗【封鎖継続の戦略的価値】封鎖は停戦交渉・制裁解除・外交条件を引き出す強力なカードです。支持率が許す限り維持することで、相手国に大きな圧力をかけられます。一方、自国の支持率・経済への負の影響と国際的孤立コストを常に損益計算し、解除すべき閾値を慎重に判断してください。
"""

    instructions = f"""
あなたは最高指導者として、以下の2つの役割のみを担います：

1. **予算配分の最終決定（全大臣の要求を調停し、合計1.0以内に収める）**
2. **重大外交事案の最終決定（宣戦布告・同盟・停戦・降伏・共同防衛・海峡封鎖）**
{energy_section}
それ以外（外交メッセージ・援助・首脳会談・制裁・諜報・関税・税率）は大臣が決定済みです。

【🌐 各大臣からの提言サマリー】
{summaries_text}

{budget_section}
{flags_section}
【戦略ドクトリン（大統領の基本方針）】
A) 攻撃的現実主義 (Mearsheimer): 地域覇権が唯一の安全保障。積極的拡大戦略。
B) 防御的現実主義 (Waltz): 現状維持が最適。過度な拡大はバランシング連合を招く。
どちらを選択するかを thought_process に明記してください。

【重大外交事案の判断権限】
以下は大統領のみが決定できます：
- `declare_war`: 宣戦布告
- `propose_alliance`: 同盟提案
- `join_ally_defense`: 同盟国防衛参加
- `propose_annexation`: 平和的統合提案
- `accept_annexation`: 平和的統合受諾
- `propose_ceasefire`: 停戦提案
- `accept_ceasefire`: 停戦受諾
- `demand_surrender`: 降伏勧告（攻撃側のみ）
- `accept_surrender`: 降伏受諾（防衛側のみ）

以下のJSONスキーマに従って最終決定を出力してください。必ずJSONオブジェクトのみで出力すること。

```json
{{
  "thought_process": "大統領としての戦略判断（150文字程度・ドクトリン選択を含む）",
  "sns_posts": ["国民向けSNS（1件、100文字以内）"],
  "update_hidden_plans": "次期への秘匿計画メモ",
  "invest_military": 0.0から1.0の数値,
  "invest_intelligence": 0.0から1.0の数値,
  "invest_economy": 0.0から1.0の数値,
  "invest_welfare": 0.0から1.0の数値,
  "invest_education_science": 0.0から1.0の数値,
  "dissolve_parliament": false,
  "major_diplomatic_actions": [
    {{
      "target_country": "対象国名",
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
      "reason": "決定の理由（30文字以内）"
    }}
  ],
  "declare_strait_blockade": null,
  "resolve_strait_blockade": null
}}
```
※ major_diplomatic_actions は行動が何もない場合は空のリスト [] を出力してください。
※ invest_* の合計は必ず1.0以下にしてください。
※ declare_strait_blockade / resolve_strait_blockade: 海峡封鎖資格国のみ記入可能。資格がない場合は null にしてください。
※ resolve_strait_blockade: 自国が宣言していない封鎖は解除できません。封鎖宣言国でない場合は必ず null にしてください（宣言国が誰かは上記エネルギーセクションで確認できます）。
"""
    return common_ctx + instructions
