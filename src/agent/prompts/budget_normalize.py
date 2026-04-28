"""
B-01: 予算配分エージェント（flash-lite）
各タスクエージェントが独立して要求した金額（B$）を、
政府歳入を参照しながら最終配分する。
歳入を超える場合は赤字国債を発行する判断も可能。
"""
from models import PresidentPolicy


def build_budget_normalize_prompt(
    country_name: str,
    policy: PresidentPolicy,
    request_military: float,
    request_intelligence: float,
    request_economy: float,
    request_welfare: float,
    request_education: float,
    request_nuclear: float,
    government_budget: float,
    national_debt: float,
    economy: float,
) -> str:
    """
    B-01: 予算配分プロンプト（flash-lite）
    各タスクエージェントの要求金額を受け取り、最終配分を金額で出力する。
    """
    total_request = request_military + request_intelligence + request_economy + request_welfare + request_education + request_nuclear
    deficit = max(0, total_request - government_budget)
    debt_ratio = national_debt / max(1.0, economy) * 100
    stance = policy.stance
    directives_str = "\n".join(f"・{d}" for d in policy.directives)

    return f"""あなたは「{country_name}」の予算配分担当官です。
各省庁の予算要求（金額：B$単位）を精査し、最終的な予算配分を確定してください。

【🏛️ 大統領施政方針（{stance}）】
{directives_str}

【💰 財政状況】
  政府歳入（税収+関税-利払い）: {government_budget:.1f} B$
  国家債務残高:                  {national_debt:.1f} B$ (対GDP比: {debt_ratio:.0f}%)

【各省庁の予算要求（B$単位）】
  軍事費要求     request_military:     {request_military:.1f}
  諜報費要求     request_intelligence: {request_intelligence:.1f}
  経済投資要求   request_economy:      {request_economy:.1f}
  福祉費要求     request_welfare:      {request_welfare:.1f}
  教育費要求     request_education:    {request_education:.1f}
  核開発要求     request_nuclear:      {request_nuclear:.1f}
  ────────────────────────────────────
  要求合計                            {total_request:.1f}
  差額                                {deficit:+.1f}（{'赤字' if deficit > 0 else '黒字'}）

【ルール】
- 配分は金額（B$単位）で出力してください。各値は 0.0 以上。
- 配分合計が歳入を超えた場合、超過分は**赤字国債**として自動発行されます。
- 赤字国債が増えると将来の利払い負担が増大し、歳入が圧迫されます。
- 配分合計が歳入以下の場合、余剰分は自動的に債務返済に充当されます。
- 施政方針の優先順位（重視項目は削りすぎない）を考慮してください。
- 配分合計は歳入の2倍を上限とします（安全装置）。

以下のJSONのみ出力してください（余分なテキスト不要）:
{{
  "budget_military": 0.0,
  "budget_intelligence": 0.0,
  "budget_economy": 0.0,
  "budget_welfare": 0.0,
  "budget_education": 0.0,
  "budget_nuclear": 0.0,
  "reasoning": "配分理由"
}}
"""
