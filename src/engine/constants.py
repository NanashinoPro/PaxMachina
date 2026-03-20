# --- 定数（プロトコルパラメータ）定義 ---
DEMOCRACY_WARN_APPROVAL = 40.0
CRITICAL_APPROVAL = 15.0
WMA_HISTORY_WEIGHT = 0.8
WMA_BASE_WEIGHT = 0.2
WMA_BASE_VALUE = 50.0
MAX_LOG_HISTORY = 20

# 経済・軍事モデルの定数
BASE_ECONOMIC_GROWTH_RATE = 0.006
MILITARY_CROWDING_OUT_RATE = 0.002
BASE_MILITARY_GROWTH_RATE = 0.015
BASE_MILITARY_MAINTENANCE_ALPHA = 0.03
MAX_MILITARY_FATIGUE_ALPHA = 0.20

# マクロ経済モデル (SNA基準) の新しい定数
BASE_INVESTMENT_RATE = 0.14          # 基礎的な民間投資性向
GOVERNMENT_CROWD_IN_MULTIPLIER = 0.05 # 経済予算が民間投資を誘発する乗数
GOVERNMENT_CROWD_OUT_MULTIPLIER = 0.15# 軍事予算が民間投資を抑制する乗数
DEBT_REPAYMENT_CROWD_IN_MULTIPLIER = 0.8 # 政府の余剰金・債務返済が民間投資市場に還流する乗数
TAX_APPROVAL_PENALTY_MULTIPLIER = 200.0 # 増税1%につき支持率が2%低下する係数
TAX_REDUCTION_APPROVAL_BONUS_MULTIPLIER = 100.0 # 減税1%につき支持率が1%上昇する係数
MAX_TAX_CHANGE_PER_TURN = 0.10 # 1ターンあたりの税率変動の上限（±10%）
DEBT_TO_GDP_PENALTY_THRESHOLD = 1.0  # 債務対GDP比が100%を超えるとペナルティ発生
DEBT_INTEREST_RATE = 0.01            # 国家債務の利払い金利（2%）

# 貿易・マクロ経済モデルの定数
MACRO_TAX_RATE = 0.30 # (旧定数。今後各国の可変 tax_rate で上書き)
DEMOCRACY_BASE_SAVING_RATE = 0.25
AUTHORITARIAN_BASE_SAVING_RATE = 0.30

# 拡張重力モデル定数（Anderson & van Wincoop 2003）
GRAVITY_TARIFF_ELASTICITY = 4.0           # 関税弾力性θ（Simonovska & Waugh 2011）
GRAVITY_ALLIANCE_DISTANCE_FACTOR = 0.5    # 同盟時の実効距離係数（距離を半分にする）
GRAVITY_SANCTION_DISTANCE_FACTOR = 10.0   # 制裁時の実効距離係数（距離を10倍にする）
GRAVITY_TRADE_SCALE = 50.0                # 貿易量スケール係数（現実の貿易/GDP比≈3-5%に合わせて逆算）
DEFAULT_TARIFF_RATE = 0.05                # デフォルト関税率（5%、貿易協定なしの場合）

# 戦争モデルの定数
DEFENDER_ADVANTAGE_MULTIPLIER = 1.2

# --- 諜報システム定数 ---
INTEL_GROWTH_RATE = 0.02           # 諜報投資の成長率（軍事と同スケール）
INTEL_MAINTENANCE_ALPHA = 0.05     # 諜報網の自然減衰率

# --- 教育・科学システム定数（内生的成長理論）---
EDUCATION_GROWTH_RATE = 0.05       # 教育投資の成長率（人的資本の蓄積速度。絶対額スケール調整済み）
EDUCATION_MAINTENANCE_ALPHA = 0.015 # 人的資本の自然減衰率（1%/四半期。知識の陳腐化等）
ENDOGENOUS_GROWTH_ALPHA = 0.05     # 内生的成長ボーナス係数。教育・科学投資が直接GDP成長率（イノベーション）に与える影響

# --- 政治・実行力モデル定数 ---
DEMOCRACY_MIN_EXECUTION_POWER = 0.4 # 民主主義における政策実行力の最低保証値（官僚機構による基本執行分）

# --- 災害・イベント定数 ---
EARTH_LAND_AREA = 148940000.0

GLOBAL_DISASTERS = [
    ("パンデミック", 0.015, 3.0, 5.0),
    ("巨大太陽フレア", 0.008, 1.0, 10.0),
    ("超巨大火山噴火 (VEI 7)", 0.001, 5.0, 15.0),
    ("巨大隕石落下", 0.00001, 10.0, 50.0),      # 0.001%
    ("破局噴火 (VEI 8)", 0.0000005, 10.0, 30.0) # 0.00005%
]

NATIONAL_DISASTERS = [
    ("巨大地震", 0.030, 1.0, 5.0),
    ("超大型台風/ハリケーン", 0.080, 0.5, 2.0),
    ("大干ばつ", 0.050, 0.5, 1.5),
    ("火山噴火 (VEI 4)", 0.154, 0.5, 1.0),
    ("火山噴火 (VEI 5)", 0.015, 1.0, 3.0),
    ("大噴火 (VEI 6)", 0.0025, 10.0, 20.0)
]

# --- 反乱・分裂モデル定数 ---
FRAGMENTATION_BASE_INSTABILITY_MULTIPLIER = 0.2
FRAGMENTATION_SIZE_FACTOR_MULTIPLIER = 0.05
FRAGMENTATION_TRADE_FACTOR_MULTIPLIER = 5.0

# クーデター後の緊急予算リセット比率（対GDP比）
# [学術的根拠] AfDB研究によりクーデター後の税収低下は段階的であり、
# 即座にGDP比10%まで激減するエビデンスは存在しない。
# 正常時の税率(30%)に対し、行政機構の混乱による一時的な低下を0.20〜0.30の範囲でランダムに表現する。
COUP_BUDGET_RATIO_MIN = 0.20
COUP_BUDGET_RATIO_MAX = 0.30

# --- 分裂後経済安定化モデル定数 ---
# [学術的根拠] Álvarez-Pereira et al. (2022, PLOS ONE)
# 分裂後のGDP/C低下は累計-20%～-24%で収束する。ソ連崩壊時でも年-10%程度が上限。
GDP_GROWTH_FLOOR_EARLY = -10.0   # 分裂直後(2ターン以内)のGDP/C成長率下限（四半期あたり）
GDP_GROWTH_FLOOR_NORMAL = -5.0   # 通常時のGDP/C成長率下限（四半期あたり）
