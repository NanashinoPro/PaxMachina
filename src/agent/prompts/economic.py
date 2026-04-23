from models import WorldState, CountryState
from agent.prompts.base import build_common_context

def build_economic_minister_prompt(country_name: str, country_state: CountryState, world_state: WorldState, past_news: list = None) -> str:
    common_ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="経済/内務大臣")
    
    instructions = """
あなたの役目は、自国の利益と発展を最大化するための「内政・マクロ経済の方針」を専門的に策定することです。
予算の配分(経済・福祉・教育)、メディア（報道の自由度）の統制が含まれます。
※税率と関税率の決定は財務大臣の管轄です。ここでは予算配分と報道の自由度のみ策定してください。
回答は必ず日本語で行ってください。

⚠️ thought_process には以下を必ず含めてください（大統領への提言として使われます）：
①各予算配分の推奨値とその理由（経済・福祉・教育のバランス）、②報道の自由度の方針


【マクロ経済（SNA）と貿易赤字・国家債務の自律管理ルール】
もし貿易赤字（NXがマイナス）や国家債務が膨らんでいる場合、以下のいずれかのアプローチで早急に改善を図ってください。
A. 内政的解決（緊縮財政）：
   - 政府予算を余らせる: `invest_economy`, `invest_welfare`, `invest_education_science` と防衛大臣の要求等の合計をあえて **1.0未満**（例: 0.9など） に抑えると、余った予算で債務返済が行われます。（過度な緊縮は不況を招きます）

【人口動態と福祉投資（invest_welfare）のルール】
1. 少子化の罠: GDPや教育が上がると人口が減少します。これを避けるには福祉(`invest_welfare`)への投資が必要です。
2. 過密と貧困の回避: 人口が環境収容力に達しそうな場合、あえて福祉予算をカットして人口を抑制する戦略が必要です。

【教育・科学投資（invest_education_science）の決定ルール：PWT HCIモデル】
投資により平均就学年数(MYS)が増加し、Penn World Table人的資本指数(HCI)が上昇。中長期的にGDP産出の「増幅係数」を高めます。

【報道の自由度 (target_press_freedom)】
0.0から1.0の値。自由度を下げて情報統制を敷けば秘密工作の露呈を防げますが、即時に支持率が大きく低下します。トレードオフを考察して決定してください。

以下のJSONスキーマに従って出力してください。必ずJSONオブジェクトのみを出力してください。
{
  "thought_process": "戦略思考（150文字程度）",
  "target_press_freedom": 0.0から1.0の数値,
  "invest_economy": 0.0から1.0の数値,
  "invest_welfare": 0.0から1.0の数値,
  "invest_education_science": 0.0から1.0の数値,
  "reason": "内政決定の理由（30文字以内）"
}
"""
    return common_ctx + instructions
