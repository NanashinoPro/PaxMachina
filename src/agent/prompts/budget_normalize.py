"""
B-01: 予算正規化エージェント（flash-lite）
各タスクエージェントが独立して提案した投資比率を、
合計1.0以内に収まるよう再調整する。
"""
from models import PresidentPolicy


def build_budget_normalize_prompt(
    country_name: str,
    policy: PresidentPolicy,
    invest_military: float,
    invest_intelligence: float,
    invest_economy: float,
    invest_welfare: float,
    invest_education_science: float,
) -> str:
    """
    B-01: 予算正規化プロンプト（flash-lite）
    各タスクエージェントの提案値を受け取り、合計1.0以内に正規化した確定値を出力する。
    合計が1.0以下の場合もそのまま出力して構わない（余剰=債務返済）。
    """
    total = invest_military + invest_intelligence + invest_economy + invest_welfare + invest_education_science
    stance = policy.stance
    directives_str = "\n".join(f"・{d}" for d in policy.directives)

    return f"""あなたは「{country_name}」の予算正規化担当官です。
各省庁の投資要求を集計し、財政規律に従って最終的な予算配分を確定してください。

【🏛️ 大統領施政方針（{stance}）】
{directives_str}

【各タスクエージェントの要求値（未正規化）】
  軍事投資        invest_military:          {invest_military:.3f}
  諜報投資        invest_intelligence:      {invest_intelligence:.3f}
  経済投資        invest_economy:           {invest_economy:.3f}
  福祉投資        invest_welfare:           {invest_welfare:.3f}
  教育・科学投資  invest_education_science: {invest_education_science:.3f}
  ────────────────────────────────────
  合計                                      {total:.3f}

【ルール】
- 合計が1.0を超える場合は**必ず1.0以内**に収まるよう全項目を按分してください。
- 合計が1.0以下の場合は**変更不要**。余剰は自動的に債務返済に充当されます。
- 施政方針の優先順位（重視項目は削りすぎない）を考慮してください。
- 各値は 0.0 以上・0.0 〜 1.0 の範囲で出力してください。

以下のJSONのみ出力してください（余分なテキスト不要）:
{{
  "invest_military": {invest_military:.3f},
  "invest_intelligence": {invest_intelligence:.3f},
  "invest_economy": {invest_economy:.3f},
  "invest_welfare": {invest_welfare:.3f},
  "invest_education_science": {invest_education_science:.3f}
}}
"""
