"""
P-01: 大統領施政方針プロンプト（Proモデル）
Phase0の第1段: 大統領が今ターンの全体方針（PresidentPolicy）を策定する。
"""
from typing import List
from models import WorldState, CountryState, PresidentPolicy


def build_president_policy_prompt(
    country_name: str,
    country_state: CountryState,
    world_state: WorldState,
    past_news: List[str] = None,
) -> str:
    """
    P-01: 大統領施政方針プロンプト（Proモデル）
    今ターンの全体スタンスと各タスクへの指示を策定する。
    """
    from agent.prompts.base import build_common_context
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="大統領（施政方針策定）")

    wars_info = ""
    for w in world_state.active_wars:
        if w.aggressor == country_name or w.defender == country_name:
            opponent = w.defender if w.aggressor == country_name else w.aggressor
            role = "攻撃側" if w.aggressor == country_name else "防衛側"
            wars_info += f"  - {opponent}との戦争（{role}、経過{w.war_turns_elapsed}ターン）\n"
    if not wars_info:
        wars_info = "  なし\n"

    hidden = country_state.hidden_plans or "なし"

    return ctx + f"""
【現在の交戦状況】
{wars_info}
【前ターンの非公開メモ】
{hidden}

あなたは「{country_name}」の最高指導者です。
今ターンの全体的な施政方針を策定してください。

【出力する施政方針の用途】
この施政方針は、以下のタスクエージェント群に共有され、各エージェントが自律的に判断を行います:
- 内政担当: 税率・関税・経済/福祉/教育投資・報道統制・議会解散
- 外交担当: メッセージ・貿易・制裁・首脳会談・多国間協議・援助・パワーバキューム
- 軍事・諜報担当: 軍事投資・諜報投資・前線投入・諜報収集・破壊工作

【stance の選択肢（1つ選ぶ）】
- 拡張型: 領土・影響力の積極拡大
- 防御型: 現状維持・自国防衛最優先
- 外交優先型: 対話・協力関係による国際的地位向上
- 経済優先型: 国内経済成長と貿易拡大
- 強権維持型: 体制維持・国内統制強化（権威主義国向け）
- 危機対応型: 現在の緊急事態（戦争・経済危機等）への集中対処

【directives（3〜5項目）の書き方】
各タスクエージェントへの具体的な優先指示を書いてください。
例: 「軍事投資を抑制し、外交解決を最優先せよ」「イランとの貿易協定を推進せよ」

以下のJSONのみ出力してください:
{{
  "stance": "防御型",
  "directives": [
    "現在の経済基盤を最優先で強化せよ",
    "主要同盟国との関係を深化させよ",
    "軍事リスクを回避し外交解決を優先せよ"
  ],
  "hidden_plans": "（次ターンへの非公開戦略メモ。他国に知られたくない真の意図・計画）",
  "sns_posts": ["（国民向けSNS投稿1件目・100文字以内）"]
}}
"""
