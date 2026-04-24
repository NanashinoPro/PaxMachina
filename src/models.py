from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

# ---------------------------------------------------------
# 国家・体制等の基本定義
# ---------------------------------------------------------

class GovernmentType(str, Enum):
    DEMOCRACY = "democracy"       # 民主主義（選挙あり）
    AUTHORITARIAN = "authoritarian" # 専制主義（反乱リスクあり）

class RelationType(str, Enum):
    ALLIANCE = "alliance"         # 同盟
    NEUTRAL = "neutral"           # 中立
    AT_WAR = "at_war"             # 戦争状態（交戦中）

class CountryState(BaseModel):
    """各国の状況を表すモデル"""
    name: str = Field(..., description="国名")
    government_type: GovernmentType = Field(..., description="政治体制")
    ideology: str = Field(..., description="国家の理念や現在の戦略目標（ペルソナ）")
    
    # リソースパラメータ
    economy: float = Field(..., description="経済力（GDP等、一国の総生産量）")
    government_budget: float = Field(0.0, description="政府の裁量で使える次ターン向け予算（税収等）")
    national_debt: float = Field(0.0, description="国家累積債務（財政赤字・貿易赤字等の累積）")
    tax_rate: float = Field(0.30, ge=0.0, le=1.0, description="現在の租税負担率（0.0-1.0）")
    press_freedom: float = Field(..., ge=0.0, le=1.0, description="現在の報道の自由度（0.0-1.0。低いほど情報統制されるが国民不満が高まる）")
    military: float = Field(..., description="軍事力")
    intelligence_level: float = Field(0.0, description="諜報レベル（蓄積される諜報・技術力。invest_intelligence投資により成長し、諜報活動の成功率に直結する）")
    area: float = Field(0.0, description="領土の面積（平方キロメートル）")
    approval_rating: float = Field(..., ge=0, le=100, description="国民の支持率（安定度: 0-100）")
    human_capital_index: float = Field(default=1.0, description="人的資本指数(PWT HCI)。Penn World Table準拠、e^φ(s)で算出")
    initial_human_capital_index: float = Field(default=1.0, description="初期人的資本指数（1ターン目に保存）")
    mean_years_schooling: float = Field(default=0.0, description="平均就学年数(MYS)。Barro & Lee (2013)準拠")
    regime_duration: int = Field(default=0, description="現政権の存続期間（ターン数）")
    population: float = Field(..., description="総人口（百万人単位）")
    initial_population: float = Field(..., description="初期の総人口（各種規格化やリセット用）")
    working_age_ratio: float = Field(0.60, description="生産年齢人口比率（労働力計算用。初期値60%）")
    
    # 地理・貿易パラメータ
    capital_lat: float = Field(0.0, description="首都の緯度")
    capital_lon: float = Field(0.0, description="首都の経度")
    tariff_revenue: float = Field(0.0, description="前ターンの関税収入")
    
    
    # 内政情報
    has_dissolution_power: bool = Field(False, description="【民主主義のみ】議会解散権の有無。議院内閣制の国はTrue、厳格な三権分立（大統領制）の国はFalse")
    turns_until_election: Optional[int] = Field(None, description="【民主主義のみ】次回の選挙までのターン数")
    rebellion_risk: float = Field(0.0, description="【専制主義等】現在の反乱発生率")
    trade_deficit_counter: int = Field(0, description="貿易赤字が継続しているターン数（産業空洞化ペナルティ用）")
    last_turn_nx: float = Field(0.0, description="前ターンの総純輸出（NX）。負なら貿易赤字")
    
    # 秘匿情報（他国からは原則見えない真の値）
    # ※AIのプロンプト上では状況に応じて公開・非公開を制御します
    hidden_plans: str = Field("", description="AI自身が記録する秘密の目標や計画")

    # 情報偽装（対外発表値）
    # AIが意図的に真値と異なる数値を発表できる。Noneなら偽装なし（真値をそのまま公開）
    reported_economy: Optional[float] = Field(None, description="対外公式発表の経済力（偽装値）。Noneなら偽装なし")
    reported_military: Optional[float] = Field(None, description="対外公式発表の軍事力（偽装値）。Noneなら偽装なし")
    reported_approval_rating: Optional[float] = Field(None, description="対外公式発表の支持率（偽装値）。Noneなら偽装なし")
    reported_intelligence_level: Optional[float] = Field(None, description="対外公式発表の諜報力（偽装値）。Noneなら偽装なし。実力を隠すことで奇襲効果を狙える")
    reported_gdp_per_capita: Optional[float] = Field(None, description="対外公式発表の1人当たりGDP（偽装値）。Noneなら偽装なし")

    leaked_intel: List[str] = Field(default_factory=list, description="過去に他国に漏洩した自国の機密情報の履歴（自国は気づいていない体で管理）")
    stat_history: List[Dict[str, float]] = Field(default_factory=list, description="過去のステータス履歴（直近4ターン分程度保持）")
    private_messages: List[str] = Field(default_factory=list, description="当ターンに他国から受け取った非公開メッセージや提案のリスト")
    
    # 対外援助・属国化関連
    dependency_ratio: Dict[str, float] = Field(default_factory=dict, description="他国に対する経済的依存度（0.0-1.0）。60%を超えると属国化する")
    suzerain: Optional[str] = Field(None, description="属国化した場合の宗主国の国名（独自外交権を喪失する）")

    # ==========================================================
    # エネルギーシステム（v1-2追加）
    # ==========================================================
    energy_self_sufficiency: float = Field(
        0.13, ge=0.0, le=1.0,
        description="エネルギー自給率(0-1)。国内生産で賄える割合。産油国は0.9以上、輸入大国は0.1前後。"
    )
    energy_import_sources: Dict[str, float] = Field(
        default_factory=dict,
        description=(
            "エネルギー輸入元と割合の辞書。"
            "キーが国名(シミュ内)→ 戦争中/制裁で自動遮断。"
            "キーが '__中東'/'__その他' 等 (__始まり)→ 海峡封鎖で遮断。"
            "全値合計 = 1.0 - energy_self_sufficiency になるよう設定。"
            "起動時に data/energy_import_sources.json から読み込まれる。"
        )
    )
    energy_reserve_turns: float = Field(
        1.0, ge=0.0,
        description=(
            "エネルギー備蓄残量（ターン単位）。"
            "封鎖時は毎ターン net_deficit 分消費。"
            "供給正常時は次ターン頭に energy_reserve_target_turns へ即時リセット。"
        )
    )
    energy_reserve_target_turns: float = Field(
        1.0, ge=0.0,
        description="各国の目標備蓄量（ターン単位）。供給再開後のリセット先。initial_stats.csvで設定。"
    )
    energy_export_blocked: bool = Field(
        False,
        description=(
            "この国のエネルギー輸出が封鎖中かどうか。"
            "海峡封鎖発動時に産油国（イラン・サウジ）をTrue、解除時にFalseへ変更される。"
        )
    )

# ---------------------------------------------------------
# アクション定義（AIが出力するJSON構造）
# ---------------------------------------------------------

class DomesticAction(BaseModel):
    """内政アクション（予充分配: 合計100%になること）"""
    tax_rate: float = Field(0.30, description="当期の目標税率（0.10〜0.70等。上げることで予算は増えるが消費と支持率が即時に低下する。下げることで支持率上昇と経済成長ボーナスが得られる）")
    report_economy: Optional[float] = Field(None, description="【情報偽装】対外公式発表する経済力。Noneなら真値をそのまま発表。意図的に乖離させることで他国の判断を誤誘導できるが、メディアに暴かれるリスクがある")
    report_military: Optional[float] = Field(None, description="【情報偽装】対外公式発表する軍事力。Noneなら真値をそのまま発表")
    report_approval_rating: Optional[float] = Field(None, description="【情報偽装】対外公式発表する支持率(%)。Noneなら真値をそのまま発表。上げすぎると不審がられる")
    report_intelligence_level: Optional[float] = Field(None, description="【情報偽装】対外公式発表する諜報力。Noneなら真値をそのまま発表。過小申告で油断を誘える")
    report_gdp_per_capita: Optional[float] = Field(None, description="【情報偽装】対外公式発表する1人当たりGDP。Noneなら真値をそのまま発表")
    deception_reason: str = Field("", description="情報偽装を行う場合の戦略的理由（偽装しない場合は空文字列でよい）")
    target_press_freedom: float = Field(..., description="当期目標とする報道の自由度（0.0〜1.0。下げるほど秘密裏の工作が暴露されにくくなるが、強権的な統制により即座に支持率が大きく低下するペナルティがある）")

    invest_economy: float = Field(..., description="経済成長への投資割合（0.0-1.0）")
    reasoning_for_military_investment: str = Field(..., description="リチャードソン・モデル（相手の脅威、自国の経済的負担、潜在的敵意）に基づく軍事投資割合の論理的算出プロセス")
    invest_military: float = Field(..., description="軍備増強への投資割合（0.0-1.0）")
    invest_welfare: float = Field(..., description="治安・福祉維持（支持率維持）への投資割合（0.0-1.0）")
    invest_intelligence: float = Field(0.0, description="諜報・技術開発への投資割合（0.0-1.0。諜報レベルを蓄積し、諜報活動の成功率を向上させる）")
    invest_education_science: float = Field(0.0, description="教育・科学技術への投資割合（0.0-1.0）。人的資本を蓄積し、長期的な経済成長バフを生み出す")
    target_tariff_rates: Dict[str, float] = Field(default_factory=dict, description="各国に対する目標関税率。キーは国名、値は関税率（0.0〜、上限なし）。財務大臣が決定。")
    dissolve_parliament: bool = Field(False, description="【民主主義国家のみ】議会解散権を行使するか。解散前支持率の確率で成功し支持率が回復するが、失敗すれば新政権が誕生する。選挙費用としてGDPの0.01〜0.02%が予算から天引きされる")
    reason: str = Field(..., max_length=50, description="この内政決定の簡潔な理由（30文字以内厳守）")

class DiplomaticAction(BaseModel):
    """特定のターゲット国へ向けた外交・軍事・諜報アクション"""
    target_country: str = Field(..., description="対象となる国名")
    message: Optional[str] = Field(None, description="メッセージ内容（あれば）")
    is_private: bool = Field(False, description="対象国とのやり取り（メッセージや会談提案）を第三国に非公開にするかどうか")
    propose_alliance: bool = Field(False, description="同盟を提案するかどうか")
    declare_war: bool = Field(False, description="宣戦布告するかどうか")
    join_ally_defense: bool = Field(False, description="同盟国が防衛側となっている既存の戦争に、防衛支援国として参加するか。target_countryには攻撃国（敵国）を指定する")
    defense_support_commitment: Optional[float] = Field(None, ge=0.01, le=0.5, description="共同防衛に投入する自国軍事力の比率（0.01〜0.50）。同盟国防衛参加時に設定")
    propose_annexation: bool = Field(False, description="対象国に対して、自国への平和的な統合（吸収合併）を提案するか")
    accept_annexation: bool = Field(False, description="前のターンに対象国から提案された平和的統合を受諾するか（受諾した場合、自国は対象国に吸収され消滅します）")
    
    # 諜報工作
    espionage_gather_intel: bool = Field(False, description="対象国の弱点や機密情報を収集するための諜報活動を行うか (任意)")
    espionage_intel_strategy: Optional[str] = Field(None, description="諜報活動の具体的な手法（サイバー攻撃、ヒューミントなど。実行時のみ記載）")
    reasoning_for_sabotage: Optional[str] = Field(None, description="破壊工作を実行する、または控えることの戦略的メリットとデメリットの考察")
    espionage_sabotage: bool = Field(False, description="対象国のインフラや世論を破壊・操作する工作活動を行うか (任意)")
    espionage_sabotage_strategy: Optional[str] = Field(None, description="破壊工作の具体的な手法（偽情報拡散、インフラ破壊など。実行時のみ記載）")
    
    # 貿易・制裁
    propose_trade: bool = Field(False, description="貿易協定（関税引き下げ等）を新規提案するか")
    cancel_trade: bool = Field(False, description="現在の貿易協定を破棄するか")
    impose_sanctions: bool = Field(False, description="経済制裁（関税引き上げ、禁輸等）を発動するか")
    lift_sanctions: bool = Field(False, description="経済制裁を解除するか")
    
    # 首脳会談
    propose_summit: bool = Field(False, description="対象国との2国間首脳会談を提案するか")
    accept_summit: bool = Field(False, description="前のターンに相手から提案された首脳会談（2国間・多国間いずれも）を受諾するか")
    summit_topic: Optional[str] = Field(None, description="首脳会談で議論したい議題（提案または受諾時のみ記載）")
    
    # 多国間首脳会談
    propose_multilateral_summit: bool = Field(False, description="複数国が参加する多国間首脳会談を提案するか。ホスト国としてsummit_participantsに招待国リストを指定する")
    summit_participants: List[str] = Field(default_factory=list, description="多国間首脳会談に招待する国名のリスト（propose_multilateral_summit時のみ。上限なし、全参加国可能）")
    
    # 軍事侵攻比率の変更
    war_commitment_ratio: Optional[float] = Field(None, ge=0.1, le=1.0, description="交戦中の場合、この戦争に投入する軍事力の比率を変更する（0.1〜1.0。未指定なら現状維持）")
    
    # 停戦・講和・降伏勧告
    propose_ceasefire: bool = Field(False, description="交戦中の相手国に停戦を提案するか（双方合意で講和会談に移行）")
    accept_ceasefire: bool = Field(False, description="前ターンに相手国から提案された停戦を受諾するか（受諾すると講和会談フェーズに移行）")
    demand_surrender: bool = Field(False, description="交戦中の相手国に降伏勧告を発するか（攻撃側のみ使用可能）")
    accept_surrender: bool = Field(False, description="前ターンに攻撃側から発された降伏勧告を受諾するか（受諾すると占領率が即100%となり国家消滅）")
    
    # 対外援助 (Foreign Aid) ─ サブスク制
    # aid_amount > 0 を指定すると recurring_aid_contracts に登録/更新（毎ターン自動継続）
    # 変更不要な場合は 0.0 のまま → 既存契約を維持（何もしない）
    # 停止したい場合は aid_cancel=True → 当該契約を解除
    aid_amount_economy: float = Field(0.0, ge=0.0, description="【サブスク登録/変更】対象国への経済援助の新規設定額（0.0=変更なし。変更時のみ指定すること）")
    aid_amount_military: float = Field(0.0, ge=0.0, description="【サブスク登録/変更】対象国への軍事援助の新規設定額（0.0=変更なし。変更時のみ指定すること）")
    aid_cancel: bool = Field(False, description="【サブスク解除】Trueで対象国への援助契約を全解除する")
    # 対外援助の受入制御（援助をサブスクしている送り手へのターン毎の受入率）
    aid_acceptance_ratio: float = Field(1.0, ge=0.0, le=1.0, description="対象国からの援助契約受入率（0.0〜1.0。毎ターン適用。デフォルト1.0=全額受入）")
    
    # パワー・バキューム・オークション (Tullock CSF)
    vacuum_bid: float = Field(0.0, ge=0.0, description="パワー・バキューム・オークションへのベット額（0.0〜自国軍事力）。分裂した新国家に対して軍事介入し吸収を試みる場合に設定。0=介入しない")
    
    reason: str = Field(..., max_length=50, description="この外交決定の簡潔な理由（30文字以内厳守）")

class AgentAction(BaseModel):
    """各ターンごとにAIエージェントが出力する行動全体の構造"""
    thought_process: str = Field(..., description="自国の状況と他国の動向を踏まえた戦略的思考（非公開）")
    sns_posts: List[str] = Field(default_factory=list, description="自国の国民に向けて発信する首脳としてのSNS投稿（1件最大140文字）。状況に応じて0件でも、最大1件でも可。国民へのアピールが含まれる")
    update_hidden_plans: str = Field("", description="次ターンの自分に引き継ぐべき非公開の計画や長期戦略のメモ（変更がなければ前回のままにするか、空欄にするのではなく記載してください）")
    domestic_policy: DomesticAction = Field(..., description="内政の予算分配")
    diplomatic_policies: List[DiplomaticAction] = Field(..., description="他国に対する個別の外交アクションのリスト")

# ---------------------------------------------------------
# 大臣最終決定制 モデル（v1.18〜）
# 各大臣が担当ドメインを最終決定し、大統領は予算調停と重大事案のみ担当
# ---------------------------------------------------------

class MinisterDecisionForeign(BaseModel):
    """外務大臣の最終決定（援助・首脳会談・制裁・メッセージ）"""
    thought_process: str = Field(..., description="外交方針の思考サマリー（大統領への提言として使用）")
    diplomatic_policies: List[DiplomaticAction] = Field(
        default_factory=list,
        description="外交行動リスト。ただし declare_war/propose_alliance/join_ally_defense/propose_annexation/accept_annexation/propose_ceasefire/accept_ceasefire/demand_surrender/accept_surrender は含めない（大統領権限）"
    )

class MinisterDecisionDefense(BaseModel):
    """防衛大臣の最終決定（諜報・軍事投入比率）+ 予算要求"""
    thought_process: str = Field(..., description="軍事・諜報方針の思考サマリー（大統領への提言として使用）")
    reasoning_for_military_investment: str = Field(..., description="リチャードソン・モデルに基づく軍事投資の算出プロセス")
    request_invest_military: float = Field(..., ge=0.0, le=1.0, description="軍事投資の予算要求（大統領が調停）")
    request_invest_intelligence: float = Field(0.0, ge=0.0, le=1.0, description="諜報投資の予算要求（大統領が調停）")
    war_commitment_ratios: Dict[str, float] = Field(
        default_factory=dict,
        description="交戦中の各相手国への軍事力投入比率（最終決定）。{相手国名: 0.1〜1.0}"
    )
    espionage_decisions: List[DiplomaticAction] = Field(
        default_factory=list,
        description="諜報・破壊工作の最終決定リスト（espionage_gather_intel/espionage_sabotage フィールドのみ使用）"
    )

class MinisterDecisionEconomic(BaseModel):
    """経済大臣の最終決定（報道の自由度・情報偽装）+ 予算要求"""
    thought_process: str = Field(..., description="内政経済方針の思考サマリー（大統領への提言として使用）")
    target_press_freedom: float = Field(..., ge=0.0, le=1.0, description="報道の自由度（最終決定）")
    request_invest_economy: float = Field(..., ge=0.0, le=1.0, description="経済投資の予算要求（大統領が調停）")
    request_invest_welfare: float = Field(..., ge=0.0, le=1.0, description="福祉投資の予算要求（大統領が調停）")
    request_invest_education_science: float = Field(0.0, ge=0.0, le=1.0, description="教育・科学技術投資の予算要求（大統領が調停）")

class MinisterDecisionFinance(BaseModel):
    """財務大臣の最終決定（税率・関税率）"""
    thought_process: str = Field(..., description="財政方針の思考サマリー（大統領への提言として使用）")
    tax_rate: float = Field(..., ge=0.1, le=0.7, description="税率（最終決定）")
    target_tariff_rates: Dict[str, float] = Field(default_factory=dict, description="各国への関税率（最終決定）")

class PresidentDecision(BaseModel):
    """大統領の最終決定（予算調停 + 重大外交事案）"""
    thought_process: str = Field(..., description="大統領としての戦略的判断サマリー")
    sns_posts: List[str] = Field(default_factory=list, description="国民向けSNS投稿（1件・100文字以内）")
    update_hidden_plans: str = Field("", description="次ターンへの非公開計画メモ")
    # 予算配分（大臣要求を調停した確定値）
    invest_military: float = Field(..., ge=0.0, le=1.0)
    invest_intelligence: float = Field(0.0, ge=0.0, le=1.0)
    invest_economy: float = Field(..., ge=0.0, le=1.0)
    invest_welfare: float = Field(..., ge=0.0, le=1.0)
    invest_education_science: float = Field(0.0, ge=0.0, le=1.0)
    dissolve_parliament: bool = Field(False)
    # 重大外交事案（declare_war / alliance / ceasefire / annexation 等）
    major_diplomatic_actions: List[DiplomaticAction] = Field(
        default_factory=list,
        description="大統領権限の外交決定リスト（declare_war, propose_alliance, join_ally_defense, propose_annexation, accept_annexation, propose_ceasefire, accept_ceasefire, demand_surrender, accept_surrender のみ）"
    )
    # ==================================================
    # 海峡封鎖権限（v1-2追加。大統領のみが宣言・解除できる）
    # ==================================================
    declare_strait_blockade: Optional[str] = Field(
        None,
        description=(
            "宣言する海峡封鎖の名称。例: 'ホルムズ海峡'。"
            "【実行可能な国のみ】イラン（ホルムズ海峡に面しており軍事封鎖が現実的）、"
            "アメリカ（第5艦隊による海軍封鎖）、サウジアラビア（自国輸出停止による実質封鎖）。"
            "Noneなら封鎖宣言なし。"
        )
    )
    resolve_strait_blockade: Optional[str] = Field(
        None,
        description=(
            "解除する海峡封鎖の名称。例: 'ホルムズ海峡'。"
            "封鎖を宣言した国のみが解除できる。"
            "Noneなら解除アクションなし。"
        )
    )

# ---------------------------------------------------------
# タスクエージェント制（v2.0）: 大統領施政方針モデル
# ---------------------------------------------------------

class PresidentPolicy(BaseModel):
    """
    P-01: 大統領施政方針（Phase0でProモデルが生成）
    各タスクエージェント（flash/flash-lite）がこれを参照して意思決定を行う。
    """
    stance: str = Field(
        ...,
        description="全体的な外交・内政スタンス（例: '拡張型', '防御型', '外交優先型', '経済優先型'）"
    )
    directives: List[str] = Field(
        default_factory=list,
        description="各タスクエージェントへの具体的な優先指示リスト（3〜5項目）"
    )
    hidden_plans: str = Field(
        "",
        description="非公開の戦略メモ（他国には見せない内部方針）。hidden_plansフィールドの更新に使用。"
    )
    sns_posts: List[str] = Field(
        default_factory=list,
        description="大統領/首相名義のSNS投稿（0〜2件・各100文字以内）"
    )

# ---------------------------------------------------------
# 世界（World）の状態定義
# ---------------------------------------------------------

class WarState(BaseModel):
    """戦争状態を記録するモデル"""
    aggressor: str = Field(..., description="攻撃側（宣戦布告した国）")
    defender: str = Field(..., description="防衛側（攻撃された国）")
    target_occupation_progress: float = Field(0.0, ge=0.0, le=100.0, description="攻撃側による防衛側領土の占領進捗率（0-100）。100で降伏。")
    aggressor_commitment_ratio: float = Field(0.50, ge=0.0, le=1.0, description="攻撃側の軍事力投入比率（0.0-1.0）。自国軍のうちどれだけを前線に投入するか")
    defender_commitment_ratio: float = Field(0.80, ge=0.0, le=1.0, description="防衛側の軍事力投入比率（0.0-1.0）。自衛のため通常は高め")
    war_turns_elapsed: int = Field(0, ge=0, description="戦争経過ターン数。Rally効果と戦争疲弊の計算に使用")
    defender_supporters: Dict[str, float] = Field(default_factory=dict, description="防衛支援国とその投入比率 {国名: 投入率}。同盟国が防衛に参加した場合に追加される")
    aggressor_cumulative_military_loss: float = Field(0.0, description="攻撃側の累積軍事損害額（講和時の賠償金計算用）")
    defender_cumulative_military_loss: float = Field(0.0, description="防衛側の累積軍事損害額（講和時の賠償金計算用）")
    aggressor_cumulative_civilian_gdp_loss: float = Field(0.0, description="攻撃側の累積民間人GDP損害額（人口損失×一人当たりGDP）")
    defender_cumulative_civilian_gdp_loss: float = Field(0.0, description="防衛側の累積民間人GDP損害額（人口損失×一人当たりGDP）")

class TradeState(BaseModel):
    """貿易協定を結んでいるペア"""
    country_a: str
    country_b: str
    tariff_a_to_b: float = Field(0.05, description="国Aが国Bからの輸入品に課す関税率")
    tariff_b_to_a: float = Field(0.05, description="国Bが国Aからの輸入品に課す関税率")

class SanctionState(BaseModel):
    """経済制裁状態"""
    imposer: str = Field(..., description="制裁を発動している国")
    target: str = Field(..., description="制裁対象の国")

class AllianceProposal(BaseModel):
    """同盟提案の保留中のリクエスト（相互合意メカニズム）"""
    proposer: str = Field(..., description="同盟を提案した国")
    target: str = Field(..., description="提案された国")

class SummitProposal(BaseModel):
    """首脳会談の保留中の提案（2国間・多国間兼用）"""
    proposer: str
    target: str = Field("", description="2国間会談の場合の対象国。多国間会談の場合は空文字")
    topic: str
    is_private: bool = Field(False, description="当該会談を非公開で行うか（他国には会談したことすら秘匿される）")
    participants: List[str] = Field(default_factory=list, description="多国間会談の参加国リスト（ホスト国を含む全参加国）。空の場合は2国間会談")
    accepted_participants: List[str] = Field(default_factory=list, description="受諾済みの参加国リスト")

class AnnexationProposal(BaseModel):
    """平和的統合の保留中の提案"""
    proposer: str = Field(..., description="統合（吸収）を提案した国")
    target: str = Field(..., description="提案された（吸収される）国")

class CeasefireProposal(BaseModel):
    """停戦提案の保留中リクエスト（翌ターンに相手が受諾すれば講和会談へ移行）"""
    proposer: str = Field(..., description="停戦を提案した国")
    target: str = Field(..., description="提案された国")

class SurrenderDemand(BaseModel):
    """降伏勧告の保留中リクエスト（攻撃側のみ発行可能）"""
    aggressor: str = Field(..., description="降伏を勧告した攻撃側の国")
    defender: str = Field(..., description="勧告された防衛側の国")

class PendingAidProposal(BaseModel):
    """保留中の対外援助の申請（後方互換用・現在はRecurringAidに置換済み）"""
    donor: str = Field(..., description="援助元の国名")
    target: str = Field(..., description="援助先の国名")
    amount_economy: float = Field(0.0, ge=0.0, description="経済援助申請額")
    amount_military: float = Field(0.0, ge=0.0, description="軍事援助申請額")

class RecurringAid(BaseModel):
    """毎ターン自動継続される援助契約（サブスク型）"""
    donor: str = Field(..., description="援助元の国名")
    target: str = Field(..., description="援助先の国名")
    amount_economy: float = Field(0.0, ge=0.0, description="経済援助額/ターン")
    amount_military: float = Field(0.0, ge=0.0, description="軍事援助額/ターン")

class BreakthroughState(BaseModel):
    """技術革新（GPTs）の進行状態"""
    origin_country: str = Field(..., description="技術革新が発生した国")
    name: str = Field(..., description="技術革新の名称")
    turns_active: int = Field(0, description="発生してからのターン数")
    spread_globally: bool = Field(False, description="世界中に波及したかどうか")

class DisasterEvent(BaseModel):
    """発生した災害の記録"""
    turn: int
    country: Optional[str] = Field(None, description="国規模の場合の対象国。世界規模はNone")
    name: str = Field(..., description="災害の種類（例: 超巨大火山噴火 (VEI 7), 超大型台風）")
    damage_percent: float = Field(..., description="経済への実質ダメージ（%）")

class WorldState(BaseModel):
    """世界全体の現在の状況"""
    turn: int = Field(1, description="現在のターン数")
    year: int = Field(2025, description="現在の西暦")
    quarter: int = Field(1, description="現在の四半期（1〜4）")
    
    countries: Dict[str, CountryState] = Field(..., description="各国のステータスマップ。キーは国名")
    relations: Dict[str, Dict[str, RelationType]] = Field(
        default_factory=dict, 
        description="国と国の関係値。relations['国A']['国B'] = RelationType"
    )
    active_wars: List[WarState] = Field(default_factory=list, description="現在進行中の戦争リスト")
    active_trades: List[TradeState] = Field(default_factory=list, description="有効な貿易協定リスト")
    active_sanctions: List[SanctionState] = Field(default_factory=list, description="発動中の経済制裁リスト")
    pending_summits: List[SummitProposal] = Field(default_factory=list, description="前ターンに提案された首脳会談のリスト")
    pending_alliances: List[AllianceProposal] = Field(default_factory=list, description="前ターンに提案された同盟のリスト（相互合意メカニズム）")
    pending_annexations: List[AnnexationProposal] = Field(default_factory=list, description="前ターンに提案された平和的統合のリスト")
    pending_ceasefires: List[CeasefireProposal] = Field(default_factory=list, description="前ターンに提案された停戦のリスト")
    pending_surrenders: List[SurrenderDemand] = Field(default_factory=list, description="前ターンに発された降伏勧告のリスト")
    pending_aid_proposals: List[PendingAidProposal] = Field(default_factory=list, description="（後方互換）旧pending援助リスト")
    recurring_aid_contracts: List["RecurringAid"] = Field(default_factory=list, description="毎ターン自動継続される援助契約リスト（サブスク）")
    active_breakthroughs: List[BreakthroughState] = Field(default_factory=list, description="現在進行中の技術革新")
    disaster_history: List[DisasterEvent] = Field(default_factory=list, description="過去に発生した重大災害の履歴")
    pending_vacuum_auctions: List[dict] = Field(default_factory=list, description="分裂により誕生した新国家に対するパワー・バキューム・オークションの保留中リスト")
    pending_influence_auctions: List[dict] = Field(default_factory=list, description="クーデター/革命により政変が発生した国に対する影響力介入オークションの保留中リスト")
    defeated_countries: List[str] = Field(default_factory=list, description="併合・降伏等により消滅した国家名のリスト（AIプロンプトで外交対象外であることを明示するために使用）")
    
    # ログ・UI用データ
    news_events: List[str] = Field(default_factory=list, description="前ターンに世界で起きた公開イベント（ニュース）")
    sns_logs: Dict[str, List[dict]] = Field(default_factory=dict, description="各国のSNS投稿とその感情スコア、検閲結果、および投稿者（Leader/Citizen/Espionage）の履歴")
    summit_logs: List[dict] = Field(default_factory=list, description="過去の首脳会談の議事録リスト。{'turn': int, 'participants': [str, str], 'log': str, 'summary': str, 'is_private': bool} 形式など")

    # ==================================================
    # エネルギーシステム（v1-2追加）
    # ==================================================
    active_strait_blockades: List[str] = Field(
        default_factory=list,
        description=(
            "現在封鎖中の海峡名リスト。例: ['ホルムズ海峡']。"
            "封鎖宣言国とその海峡名を記録する辞書形式も将来的に検討。"
        )
    )
    strait_blockade_owners: Dict[str, str] = Field(
        default_factory=dict,
        description="封鎖中の海峡と宣言した国のマッピング。{'ホルムズ海峡': 'イラン'} のような形式。解除権限の確認に使用。"
    )
