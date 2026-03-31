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

# ---------------------------------------------------------
# 軍事配備関連の定義
# ---------------------------------------------------------

class DeploymentType(str, Enum):
    """配備ユニットの種別"""
    ARMY = "army"    # 陸軍
    NAVY = "navy"    # 海軍
    AIR = "air"      # 空軍

class ArmyPosture(str, Enum):
    """陸軍の態勢"""
    OFFENSIVE = "offensive"         # 攻勢: 攻撃+20%, 防御-10%
    DEFENSIVE = "defensive"         # 守勢: 防御+30%, 攻撃-20%
    INTIMIDATION = "intimidation"   # 威嚇: 戦闘効果なし、緊張度上昇

class NavalMission(str, Enum):
    """海軍のミッション種別"""
    PATROL = "patrol"                       # 通商護衛（平時/戦時）
    SHOW_OF_FORCE = "show_of_force"         # 砲艦外交・武力示威（平時/戦時）
    BLOCKADE = "blockade"                   # 海上封鎖（戦時のみ）
    NAVAL_ENGAGEMENT = "naval_engagement"   # 艦隊決戦（戦時のみ）
    AMPHIBIOUS_SUPPORT = "amphibious_support" # 上陸支援（戦時のみ）
    SHORE_BOMBARDMENT = "shore_bombardment" # 艦砲射撃（戦時のみ）

class AirMission(str, Enum):
    """空軍のミッション種別"""
    AIR_SUPERIORITY = "air_superiority"       # 制空権確保（平時/戦時）
    GROUND_SUPPORT = "ground_support"         # 地上部隊支援（戦時のみ）
    STRATEGIC_BOMBING = "strategic_bombing"   # 戦略爆撃（戦時のみ）
    RECON_FLIGHT = "recon_flight"             # 偵察飛行（平時/戦時）

class FortificationLevel(str, Enum):
    """要塞化レベル"""
    NONE = "none"      # なし
    LIGHT = "light"    # 軽度要塞 (+25%防御)
    HEAVY = "heavy"    # 重度要塞 (+50%防御)

class MilitaryDeploymentOrder(BaseModel):
    """防衛大臣が出力する個別の配備命令"""
    type: DeploymentType = Field(..., description="配備ユニット種別（army/navy/air）")
    target_country: str = Field(..., description="配備先の対象国名")
    # 陸軍用フィールド
    divisions: int = Field(0, ge=0, description="配備する陸軍師団数")
    posture: Optional[ArmyPosture] = Field(None, description="陸軍の態勢（offensive/defensive/intimidation）")
    fortify: FortificationLevel = Field(FortificationLevel.NONE, description="要塞化レベル")
    # 海軍用フィールド
    fleets: int = Field(0, ge=0, description="派遣する海軍艦隊数")
    naval_mission: Optional[NavalMission] = Field(None, description="海軍ミッション種別")
    # 空軍用フィールド
    squadrons: int = Field(0, ge=0, description="投入する空軍飛行隊数")
    air_mission: Optional[AirMission] = Field(None, description="空軍ミッション種別")

class ForceAllocation(BaseModel):
    """兵科比率（陸海空の配分）。合計は1.0以下"""
    army_ratio: float = Field(0.70, ge=0.0, le=1.0, description="陸軍の割合")
    navy_ratio: float = Field(0.15, ge=0.0, le=1.0, description="海軍の割合")
    air_ratio: float = Field(0.15, ge=0.0, le=1.0, description="空軍の割合")

class MilitaryDeploymentState(BaseModel):
    """国家の現在の軍事配備状態（防衛大臣が毎ターン更新）"""
    force_allocation: ForceAllocation = Field(default_factory=ForceAllocation)
    deployments: List[MilitaryDeploymentOrder] = Field(default_factory=list, description="各方面への配備命令リスト")

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
    leaked_intel: List[str] = Field(default_factory=list, description="過去に他国に漏洩した自国の機密情報の履歴（自国は気づいていない体で管理）")
    stat_history: List[Dict[str, float]] = Field(default_factory=list, description="過去のステータス履歴（直近4ターン分程度保持）")
    private_messages: List[str] = Field(default_factory=list, description="当ターンに他国から受け取った非公開メッセージや提案のリスト")
    
    # 対外援助・属国化関連
    dependency_ratio: Dict[str, float] = Field(default_factory=dict, description="他国に対する経済的依存度（0.0-1.0）。60%を超えると属国化する")
    suzerain: Optional[str] = Field(None, description="属国化した場合の宗主国の国名（独自外交権を喪失する）")
    
    # 地図可視化・軍事配備関連
    iso_code: str = Field("", description="ISO 3166-1 Alpha-3 国コード（地図レンダリング用）")
    has_coastline: bool = Field(True, description="海岸線の有無（海軍ユニット表示制御用）")
    military_deployment: MilitaryDeploymentState = Field(
        default_factory=MilitaryDeploymentState,
        description="現在の軍事配備状態（防衛大臣が毎ターン更新）"
    )

# ---------------------------------------------------------
# アクション定義（AIが出力するJSON構造）
# ---------------------------------------------------------

class DomesticAction(BaseModel):
    """内政アクション（予充分配: 合計100%になること）"""
    tax_rate: float = Field(0.30, description="当期の目標税率（0.10〜0.70等。上げることで予算は増えるが消費と支持率が即時に低下する。下げることで支持率上昇と経済成長ボーナスが得られる）")
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
    
    # 対外援助 (Foreign Aid)
    aid_amount_economy: float = Field(0.0, ge=0.0, description="対象国に対する民生・インフラへの経済支援額（自国の政府予算から拠出。翌ターンに相手国が受入判断する）")
    aid_amount_military: float = Field(0.0, ge=0.0, description="対象国に対する兵器・軍事物資の軍事支援額（自国の政府予算から拠出。翌ターンに相手国が受入判断する）")
    # 対外援助の受入制御（前ターンに相手国から申請された援助に対して受入率を設定）
    aid_acceptance_ratio: float = Field(1.0, ge=0.0, le=1.0, description="対象国からの援助申請に対する受入率（0.0〜1.0の連続値。実際の申請額を確認した上で戦略的に判断する。例: 0.0=全拒否、0.3=3割のみ受入、1.0=全額受入。デフォルト1.0=全額受入）")
    
    reason: str = Field(..., max_length=50, description="この外交決定の簡潔な理由（30文字以内厳守）")

class AgentAction(BaseModel):
    """各ターンごとにAIエージェントが出力する行動全体の構造"""
    thought_process: str = Field(..., description="自国の状況と他国の動向を踏まえた戦略的思考（非公開）")
    sns_posts: List[str] = Field(default_factory=list, description="自国の国民に向けて発信する首脳としてのSNS投稿（1件最大140文字）。状況に応じて0件でも、最大1件でも可。国民へのアピールが含まれる")
    update_hidden_plans: str = Field("", description="次ターンの自分に引き継ぐべき非公開の計画や長期戦略のメモ（変更がなければ前回のままにするか、空欄にするのではなく記載してください）")
    domestic_policy: DomesticAction = Field(..., description="内政の予算分配")
    diplomatic_policies: List[DiplomaticAction] = Field(..., description="他国に対する個別の外交アクションのリスト")
    
    # 軍事配備関連（防衛大臣が決定、大統領が承認）
    force_allocation: Optional[ForceAllocation] = Field(None, description="陸海空の兵科比率（合計1.0）。省略時は前ターンの設定を維持")
    deployments: List[MilitaryDeploymentOrder] = Field(default_factory=list, description="各方面への軍事配備命令リスト")

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

class PendingAidProposal(BaseModel):
    """保留中の対外援助の申請（翌ターンに受取国が受入判断する）"""
    donor: str = Field(..., description="援助元の国名")
    target: str = Field(..., description="援助先の国名")
    amount_economy: float = Field(0.0, ge=0.0, description="経済援助申請額")
    amount_military: float = Field(0.0, ge=0.0, description="軍事援助申請額")

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
    pending_aid_proposals: List[PendingAidProposal] = Field(default_factory=list, description="前ターンに申請された対外援助のリスト（翌ターンに受取国が受入判断する）")
    active_breakthroughs: List[BreakthroughState] = Field(default_factory=list, description="現在進行中の技術革新")
    disaster_history: List[DisasterEvent] = Field(default_factory=list, description="過去に発生した重大災害の履歴")
    
    # ログ・UI用データ
    news_events: List[str] = Field(default_factory=list, description="前ターンに世界で起きた公開イベント（ニュース）")
    sns_logs: Dict[str, List[dict]] = Field(default_factory=dict, description="各国のSNS投稿とその感情スコア、検閲結果、および投稿者（Leader/Citizen/Espionage）の履歴")
    summit_logs: List[dict] = Field(default_factory=list, description="過去の首脳会談の議事録リスト。{'turn': int, 'participants': [str, str], 'log': str, 'summary': str, 'is_private': bool} 形式など")
