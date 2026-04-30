# --- 定数（プロトコルパラメータ）定義 ---

# ターン時間軸パラメータ
# 1ターン = 1年/TURNS_PER_YEAR（デフォルト: 4 = 四半期制）
# 税収・利払い・マクロモデルの年次→ターン変換に使用
TURNS_PER_YEAR = 4

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
INTEREST_REINVESTMENT_RATE = 0.70  # 利払いのうち国内民間投資に還流する割合（債権者=国内銀行・年金基金等の再投資）
TAX_APPROVAL_PENALTY_MULTIPLIER = 200.0 # 増税1%につき支持率が2%低下する係数
TAX_REDUCTION_APPROVAL_BONUS_MULTIPLIER = 100.0 # 減税1%につき支持率が1%上昇する係数
MAX_TAX_CHANGE_PER_TURN = 0.10 # 1ターンあたりの税率変動の上限（±10%）
DEBT_TO_GDP_PENALTY_THRESHOLD = 1.0  # 債務対GDP比が100%を超えるとペナルティ発生

# 国家債務の利払いモデル（全て年率で定義。ターン実行時に /TURNS_PER_YEAR で四半期化）
# [学術的根拠]
#   - 基本金利: 先進国の平均国債利回り ≈ 年率2-3% (2020s平均)
#   - 信用スプレッド感度: Harvard研究 (Reinhart et al.)
#     先進国: 債務GDP比 10%pt増 → +6bp/年 (新興国の約1/5)
#     新興国: 債務GDP比 10%pt増 → +45-120bp/年
#   - 閾値: 90%超で非線形的にスプレッドが拡大する閾値効果
#   - 日本の例外: GDP比260%超でも10年債利回り2.47%/年 (2026年4月)
#     → 自国通貨建て・国内保有95%・日銀YCC の特殊事情
DEBT_INTEREST_RATE_ANNUAL = 0.025    # 基本金利（年率2.5%）
DEBT_SPREAD_THRESHOLD = 0.90         # 信用スプレッド発生閾値（債務GDP比90%）
DEBT_SPREAD_SENSITIVITY = 0.006      # スプレッド感度（10%pt超過につき+60bp/年 = 先進国実証値の10倍。シミュレーション加速用）
DEBT_SPREAD_CAP_ANNUAL = 0.15        # 信用スプレッド上限（年率15%。ギリシャ危機級でキャップ）

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

# 軍事侵攻比率モデルの定数
# [学術的根拠] U.S. Army FM 3-0: 攻撃3:1ルール、Dupuy Institute: 歴史的戦力比分析
DEFAULT_AGGRESSOR_COMMITMENT = 0.50   # 攻撃側デフォルト投入率（侵攻軍の50%を前線に）
DEFAULT_DEFENDER_COMMITMENT = 0.80    # 防衛側デフォルト投入率（自衛のため高め）
MIN_COMMITMENT_RATIO = 0.10           # 最小投入率（10%未満の戦争はあり得ない）

# 動員速度制限（Rate Limiter）: 1ターンあたりの投入比率変動の上限
# [学術的根拠]
#   1. ロシア部分動員 (2022年9月): 30万人の動員を命令後、5週間で「完了」宣言されたが、
#      実際に前線配備されたのは82,000名（27%）のみ。ISW (Institute for the Study of War) は
#      「動員された兵力が実質的な戦闘力として機能するには数ヶ月を要する」と評価。
#      実効ベースで四半期あたり約+8%の戦力投入率増加に相当。
#      出典: ISW Assessment, 2022年9月-10月; Shoigu発表 2022/10/28
#   2. クラウゼヴィッツ『戦争論』(1832): 計画と実行の間には不可避な「摩擦 (Friction)」が
#      存在し、即時の戦力拡大は理論上不可能。兵站・訓練・装備配備がボトルネックとなる。
#   3. WW1 シュリーフェン計画 (1905): ドイツはロシアの総動員に6週間かかることを前提に
#      全戦略を構築。動員速度そのものが国家戦略の根本的制約であった。
#      出典: Schlieffen Plan academic analysis, EBSCO/historyskills.com
#   ※ ±10%/ターン(=四半期)はロシア2022年実績(+8%/Q)とほぼ一致し、「やや楽観的だが合理的」な値。
MAX_COMMITMENT_CHANGE_PER_TURN = 0.10 # 1ターンあたりの投入比率変動上限（±10%）

COMMITMENT_ECONOMIC_DRAIN = 0.01      # 投入比率1.0あたりの四半期GDP減衰率（戦時経済負担）

# --- 諜報システム定数 ---
INTEL_GROWTH_RATE = 0.02           # 諜報投資の成長率（軍事と同スケール）
INTEL_MAINTENANCE_ALPHA = 0.05     # 諜報網の自然減衰率

# --- 教育・科学システム定数（PWT HCI: Penn World Table 人的資本指数）---
# [学術的根拠] Penn World Table 11.0 (Feenstra, Inklaar & Timmer 2015)
# hc = e^φ(s), φ(s) = ミンサー方程式ベースの区分線形収益率関数
MINCER_RETURN_PRIMARY = 0.134      # 初等教育の収益率（就学0-4年目）[Psacharopoulos 1994]
MINCER_RETURN_SECONDARY = 0.101    # 中等教育の収益率（就学5-8年目）[Psacharopoulos 1994]
MINCER_RETURN_TERTIARY = 0.068     # 高等教育の収益率（就学9年目以降）[Psacharopoulos 1994]
MYS_GROWTH_RATE = 0.04             # 教育投資の平均就学年数(MYS)増加率 [Jackson et al. 2016, QJE]
MYS_DECAY_RATE = 0.001             # MYSの四半期あたり自然減衰率（年0.4%。退職・知識陳腐化）
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
FRAGMENTATION_TRADE_FACTOR_MULTIPLIER = 1.0  # 旧: 5.0 → 1.0 に引き下げ (Alesina-Spolaore: 貿易網1件あたりの分裂圧力を適正化)
FRAGMENTATION_INSTABILITY_THRESHOLD = 40.0   # 分裂判定の最低不安定性しきい値 (Goldstone et al. 2010: 複合危機時のみ分裂)
FRAGMENTATION_COOLDOWN_TURNS = 4             # 分裂/クーデター後のクールダウン期間（ターン数。Polity IV regime durability coding準拠）

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

# --- 影響力介入オークション定数 ---
# [学術的根拠] Morgenthau (1948): パワー・バキュームは周辺大国の介入を誘発する。
# Tullock (1980): コンテスト成功関数。歴史的実例: ウクライナ政変(2014)、エジプト政変(2013)
INFLUENCE_AUCTION_DEPENDENCY_GAIN = 0.20  # 勝者が獲得する依存度加算値（20%）
INFLUENCE_AUCTION_INDEPENDENCE_BONUS = 3.0  # 外部介入を退けた場合の支持率ボーナス

# --- 核兵器システム定数（v1-3追加）---
# [学術的根拠]
#   - Manhattan Project: GDP比0.4%×3年≈$360B現在価値 (DoE archives)
#   - 北朝鮮: GDP比15-24%を軍事費充当 (ICAN 2024)
#   - Wright's Law (1936): 累積生産量が倍増するごとに単位コストが一定比率で低下
#   - Glasstone & Dolan (1977): The Effects of Nuclear Weapons. US DoD/DoE.
#   - THAAD/Aegis迎撃実績: Missile Defense Advocacy Alliance

# 核開発パイプライン（段階別コスト）
NUCLEAR_DEV_STEP_COSTS = {
    1: {"gdp_ratio": 0.03, "turns": 8},   # Step1: ウラン濃縮/プルトニウム生産
    2: {"gdp_ratio": 0.02, "turns": 4},   # Step2: 核実験
    3: {"gdp_ratio": 0.015, "turns": 4},  # Step3: 実戦配備
}

# 核弾頭量産（Step4以降）
NUCLEAR_PRODUCTION_BASE_GDP_RATIO = 0.005  # 基本コスト = GDP × 0.5%
NUCLEAR_PRODUCTION_SCALE_FACTOR = 0.1      # Wright's Law係数: 1 + 0.1 × sqrt(既存弾頭数)

# 核ダメージモデル
NUCLEAR_TACTICAL_DAMAGE_RATIO = 0.25       # 戦術核: 前線軍事力×投入率の25%
NUCLEAR_TACTICAL_MAX_WARHEADS = 3          # 戦術核: 最大同時使用数
NUCLEAR_STRATEGIC_ECON_DAMAGE = 0.30       # 戦略核: 経済ダメージ基本率
NUCLEAR_STRATEGIC_POP_DAMAGE = 0.10        # 戦略核: 人口ダメージ基本率
NUCLEAR_STRATEGIC_MIL_DAMAGE = 0.15        # 戦略核: 軍事ダメージ基本率
NUCLEAR_STRATEGIC_DEFAULT_WARHEADS = 5     # 戦略核: デフォルト消費弾頭数
# ダメージ上限キャップ
NUCLEAR_MAX_ECON_DAMAGE_RATIO = 0.90       # 経済ダメージ上限90%
NUCLEAR_MAX_POP_DAMAGE_RATIO = 0.50        # 人口ダメージ上限50%
NUCLEAR_MAX_MIL_DAMAGE_RATIO = 0.80        # 軍事ダメージ上限80%

# ABM（ミサイル防衛）- 軍事力から自動算出
NUCLEAR_ABM_MILITARY_RATIO = 0.05          # 軍事力の5%がABM能力
WARHEAD_PENETRATION_FACTOR = 10.0          # 弾頭1発あたりの突破力係数
NUCLEAR_ABM_MAX_INTERCEPT = 0.80           # 迎撃率の上限80%
