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
    military: float = Field(..., description="軍事力")
    area: float = Field(0.0, description="領土の面積（平方キロメートル）")
    approval_rating: float = Field(..., ge=0, le=100, description="国民の支持率（安定度: 0-100）")
    
    # 内政情報
    turns_until_election: Optional[int] = Field(None, description="【民主主義のみ】次回の選挙までのターン数")
    rebellion_risk: float = Field(0.0, description="【専制主義等】現在の反乱発生率")
    trade_deficit_counter: int = Field(0, description="貿易赤字が継続しているターン数（産業空洞化ペナルティ用）")
    last_turn_nx: float = Field(0.0, description="前ターンの総純輸出（NX）。負なら貿易赤字")
    
    # 秘匿情報（他国からは原則見えない真の値）
    # ※AIのプロンプト上では状況に応じて公開・非公開を制御します
    hidden_plans: str = Field("", description="AI自身が記録する秘密の目標や計画")
    leaked_intel: List[str] = Field(default_factory=list, description="過去に他国に漏洩した自国の機密情報の履歴（自国は気づいていない体で管理）")

# ---------------------------------------------------------
# アクション定義（AIが出力するJSON構造）
# ---------------------------------------------------------

class DomesticAction(BaseModel):
    """内政アクション（予充分配: 合計100%になること）"""
    tax_rate: float = Field(0.30, description="当期の目標税率（0.10〜0.70等。上げることで予算は増えるが消費と支持率が即時に低下する）")
    invest_economy: float = Field(..., description="経済成長への投資割合（0.0-1.0）")
    reasoning_for_military_investment: str = Field(..., description="リチャードソン・モデル（相手の脅威、自国の経済的負担、潜在的敵意）に基づく軍事投資割合の論理的算出プロセス")
    invest_military: float = Field(..., description="軍備増強への投資割合（0.0-1.0）")
    invest_welfare: float = Field(..., description="治安・福祉維持（支持率維持）への投資割合（0.0-1.0）")

class DiplomaticAction(BaseModel):
    """特定のターゲット国へ向けた外交・軍事・諜報アクション"""
    target_country: str = Field(..., description="対象となる国名")
    message: Optional[str] = Field(None, description="メッセージ内容（あれば）")
    propose_alliance: bool = Field(False, description="同盟を提案するかどうか")
    declare_war: bool = Field(False, description="宣戦布告するかどうか")
    
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
    propose_summit: bool = Field(False, description="対象国との首脳会談を提案するか")
    accept_summit: bool = Field(False, description="前のターンに相手から提案された首脳会談を受諾するか")
    summit_topic: Optional[str] = Field(None, description="首脳会談で議論したい議題（提案または受諾時のみ記載）")

class AgentAction(BaseModel):
    """各ターンごとにAIエージェントが出力する行動全体の構造"""
    thought_process: str = Field(..., description="自国の状況と他国の動向を踏まえた戦略的思考（非公開）")
    sns_posts: List[str] = Field(default_factory=list, description="自国の国民に向けて発信する首脳としてのSNS投稿（1件最大140文字）。状況に応じて0件でも、最大1件でも可。国民へのアピールが含まれる")
    update_hidden_plans: str = Field("", description="次ターンの自分に引き継ぐべき非公開の計画や長期戦略のメモ（変更がなければ前回のままにするか、空欄にするのではなく記載してください）")
    domestic_policy: DomesticAction = Field(..., description="内政の予算分配")
    diplomatic_policies: List[DiplomaticAction] = Field(..., description="他国に対する個別の外交アクションのリスト")

# ---------------------------------------------------------
# 世界（World）の状態定義
# ---------------------------------------------------------

class WarState(BaseModel):
    """戦争状態を記録するモデル"""
    aggressor: str = Field(..., description="攻撃側（宣戦布告した国）")
    defender: str = Field(..., description="防衛側（攻撃された国）")
    target_occupation_progress: float = Field(0.0, ge=0.0, le=100.0, description="攻撃側による防衛側領土の占領進捗率（0-100）。100で降伏。")

class TradeState(BaseModel):
    """貿易協定を結んでいるペア"""
    country_a: str
    country_b: str

class SanctionState(BaseModel):
    """経済制裁状態"""
    imposer: str = Field(..., description="制裁を発動している国")
    target: str = Field(..., description="制裁対象の国")

class AllianceProposal(BaseModel):
    """同盟提案の保留中のリクエスト（相互合意メカニズム）"""
    proposer: str = Field(..., description="同盟を提案した国")
    target: str = Field(..., description="提案された国")

class SummitProposal(BaseModel):
    """首脳会談の保留中の提案"""
    proposer: str
    target: str
    topic: str

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
    active_breakthroughs: List[BreakthroughState] = Field(default_factory=list, description="現在進行中の技術革新")
    disaster_history: List[DisasterEvent] = Field(default_factory=list, description="過去に発生した重大災害の履歴")
    
    # ログ・UI用データ
    news_events: List[str] = Field(default_factory=list, description="前ターンに世界で起きた公開イベント（ニュース）")
    sns_logs: Dict[str, List[dict]] = Field(default_factory=dict, description="各国のSNS投稿とその感情スコア、検閲結果、および投稿者（Leader/Citizen/Espionage）の履歴")
    summit_logs: List[dict] = Field(default_factory=list, description="過去の首脳会談の議事録リスト。{'turn': int, 'participants': [str, str], 'log': str} 形式など")
