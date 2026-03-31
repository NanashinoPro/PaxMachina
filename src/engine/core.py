import math
import random
from typing import Dict, List, Any
from models import WorldState, AgentAction, SummitProposal

from .constants import MAX_LOG_HISTORY
from .domestic import DomesticMixin
from .diplomacy import DiplomacyMixin
from .economy import EconomyMixin
from .military import MilitaryMixin
from .events import EventsMixin
from .public_opinion import PublicOpinionMixin
from .utils import UtilsMixin

class WorldEngine(
    DomesticMixin,
    DiplomacyMixin,
    EconomyMixin,
    MilitaryMixin,
    EventsMixin,
    PublicOpinionMixin,
    UtilsMixin
):
    """世界の毎ターンの出来事を処理し、状態を更新するエンジン"""
    
    def __init__(self, initial_state: WorldState, analyzer=None, db_manager=None):
        self.state = initial_state
        self.events_this_turn: List[str] = []
        self.sys_logs_this_turn: List[str] = []
        self.summits_to_run_this_turn: List[SummitProposal] = []
        self.pending_intel_requests: List[Dict[str, str]] = []
        self.pending_sabotage_requests: List[Dict[str, str]] = []
        # Added pending events that require LLM generation outside the engine
        self.pending_rebellions: List[str] = []
        self.pending_elections: List[str] = []
        
        # 感情分析器とデータベースマネージャー（外部から注入）
        self.analyzer = analyzer
        self.db_manager = db_manager
        self.turn_domestic_factors: Dict[str, Dict[str, float]] = {}
        self.turn_sns_logs: Dict[str, List[Dict[str, Any]]] = {} # Added for fragmentation logic
        self.turn_dutch_disease_penalty: Dict[str, float] = {} # オランダ病（援助過剰）による政策実行力デバフ

        # 1ターン目のみ、各国の初期教育レベルを保存（規格化用）
        for name, country in self.state.countries.items():
            if country.initial_human_capital_index <= 1.0 and country.human_capital_index > 1.0:
                country.initial_human_capital_index = country.human_capital_index
            # [追加] 政権の存続期間をインクリメント
            country.regime_duration += 1

    def log_event(self, message: str, is_private: bool = False, involved_countries: List[str] = None):
        """
        イベントログを追加し、データベースが有効ならQdrantにも記録する。
        """
        self.events_this_turn.append(message)
        
        if self.db_manager:
            if involved_countries is None:
                involved_countries = ["global"]
            # プレフィックス(絵文字等)を除去したクリーンなテキストを使っても良いが、ここではそのまま保存
            self.db_manager.add_event(
                turn=self.state.turn,
                event_type="news",
                content=message,
                is_private=is_private,
                involved_countries=involved_countries
            )

    def process_turn(self, actions: Dict[str, AgentAction]) -> WorldState:
        """
        全エージェントのアクションを受け取り、1ターン（3ヶ月）分の処理を行う
        処理順:
        1. 内政（経済、軍事、支持率の更新）
        2. 外交・諜報（同盟、宣戦布告、工作、貿易、制裁、会談提案・受諾）
        3. 貿易と制裁による経済パラメータの最終調整
        4. 戦争の自動処理（ダメージ計算、占領進捗、勝敗判定）
        5. 内政イベント判定（選挙、反乱）
        6. 時間の進行
        """
        self.events_this_turn = []
        self.sys_logs_this_turn = []
        self.summits_to_run_this_turn = []
        self.pending_intel_requests = []
        self.pending_sabotage_requests = []
        self.pending_rebellions = []
        self.pending_elections = []
        self.turn_domestic_factors = {}
        self.turn_sns_logs = {} # Reset SNS logs for the current turn
        self.turn_dutch_disease_penalty = {} # オランダ病（援助過剰）による政策実行力デバフ
        
        # 毎ターンの秘匿メッセージリセット
        for country in self.state.countries.values():
            country.private_messages = []
        
        # 0. 基礎予算の算出と属国化による外交権のオーバーライド
        from .constants import DEBT_INTEREST_RATE
        for country_name, country in self.state.countries.items():
            old_gdp = country.economy
            tax_revenue = old_gdp * country.tax_rate
            interest_payment = country.national_debt * DEBT_INTEREST_RATE
            
            # 予算が利払いを下回る場合はデフォルト（未払い分は借金に上乗せ）
            total_revenue = tax_revenue + country.tariff_revenue  # 税収 + 関税収入
            if total_revenue >= interest_payment:
                country.government_budget = total_revenue - interest_payment
            else:
                country.government_budget = 0.0
                default_amount = interest_payment - total_revenue
                country.national_debt += default_amount  # 払えなかった利息が元本組み込み（複利）
                self.sys_logs_this_turn.append(f"[{country_name} デフォルト] 利払い不能。未払利息 {default_amount:.1f} を債務に追加。")
            
            if country.tariff_revenue > 0:
                self.sys_logs_this_turn.append(f"[{country_name} 関税収入] {country.tariff_revenue:.1f} を歳入に計上 (税収:{tax_revenue:.1f} + 関税:{country.tariff_revenue:.1f} = {total_revenue:.1f})")
            
            # 属国化のデバフ（自然減衰）と外交オーバーライド
            if country.suzerain and country.suzerain not in self.state.countries:
                country.suzerain = None # 宗主国が滅亡した場合は独立
                
            decayed_deps = {}
            for k, v in country.dependency_ratio.items():
                if k in self.state.countries:
                    decayed_val = max(0.0, v - 0.05)
                    if decayed_val > 0:
                        decayed_deps[k] = decayed_val
            country.dependency_ratio = decayed_deps
            
            # 属国の独立判定（ヒステリシス方式: 依存度40%以下でランダムルーレット）
            if country.suzerain and country.suzerain in self.state.countries:
                suzerain_dep = country.dependency_ratio.get(country.suzerain, 0.0)
                if suzerain_dep <= 0.40:
                    independence_chance = (0.40 - suzerain_dep) / 0.40
                    roll = random.random()
                    if roll < independence_chance:
                        old_suzerain = country.suzerain
                        country.suzerain = None
                        self.log_event(
                            f"🗽 【独立回復】{country_name}は{old_suzerain}からの経済的従属を脱し、"
                            f"主権を回復しました！（依存度: {suzerain_dep*100:.1f}%, 独立確率: {independence_chance*100:.1f}%）",
                            involved_countries=[country_name, old_suzerain, "global"]
                        )
                        self.sys_logs_this_turn.append(
                            f"[{country_name} 独立回復] 依存度 {suzerain_dep*100:.1f}% (閾値40%), "
                            f"確率 {independence_chance*100:.1f}%, ロール {roll*100:.1f}%"
                        )
                    else:
                        self.sys_logs_this_turn.append(
                            f"[{country_name} 独立失敗] 依存度 {suzerain_dep*100:.1f}%, "
                            f"確率 {independence_chance*100:.1f}%, ロール {roll*100:.1f}%"
                        )
            

            # 属国の場合、独自の外交アクションを無効化（あるいは宗主国にひたすら協力する内容に書き換え可能だが、ここではシンプルに空にする）
            if country.suzerain and country_name in actions:
                actions[country_name].diplomatic_policies = []
                self.sys_logs_this_turn.append(f"[{country_name} 属国] 宗主国 {country.suzerain} の意向により、独自の外交権が凍結されました。")

        # 対外援助（オランダ病判定含む）の処理
        self._process_foreign_aid(actions)
        
        # 1. 内政の反映
        for country_name, action in actions.items():
            self._process_domestic(country_name, action)
        
        # 1.5. 軍事配備の更新（防衛大臣 → 大統領の最終決定を反映）
        self._process_military_deployments(actions)
        
        for country_name, action in actions.items():
            self._process_diplomacy_and_espionage(country_name, action)
        
        # 多国間会談: 受諾者が2名以上集まった提案を実行キューに移動
        for s in list(self.state.pending_summits):
            if s.participants and len(s.accepted_participants) >= 2:
                self.summits_to_run_this_turn.append(s)
                self.state.pending_summits.remove(s)
            
        # 3. 貿易と制裁の処理 (Gravity Model & Sanctions Damage applying)
        self._process_trade_and_sanctions()
        
        # 3.5. 緊張度効果の適用 (Mueller Rally + Schultz Audience Cost)
        try:
            from engine.tension import apply_tension_effects
            tension_events = apply_tension_effects(
                self.state, self.sys_logs_this_turn, self.events_this_turn
            )
            for event in tension_events:
                self.log_event(event, involved_countries=["global"])
        except Exception as e:
            self.sys_logs_this_turn.append(f"[緊張度処理エラー] {e}")
            
        # 4. 戦争状態の処理
        self._process_wars()
        
        # 5. ランダムイベント（災害・技術革新）の判定
        self._process_random_events()
        
        # 6. 時間進行とターン終了処理は外部 (main.py) から advance_time() を呼び出すよう変更
        
        # イベントログをステートに記録
        self.state.news_events.extend(self.events_this_turn.copy())
        
        return self.state

    def advance_time(self):
        self.state.turn += 1
        self.state.quarter += 1
        if self.state.quarter > 4:
            self.state.quarter = 1
            self.state.year += 1
            
        # メモリ対策：履歴トークン肥大化を防ぐためのトリミング処理
        self.state.news_events = self.state.news_events[-MAX_LOG_HISTORY:]
        self.state.disaster_history = [d for d in self.state.disaster_history if self.state.turn - d.turn <= MAX_LOG_HISTORY]
        
        if len(self.state.summit_logs) > MAX_LOG_HISTORY:
            self.state.summit_logs = self.state.summit_logs[-MAX_LOG_HISTORY:]
            
        for name, history in self.state.sns_logs.items():
            if len(history) > MAX_LOG_HISTORY:
                self.state.sns_logs[name] = history[-MAX_LOG_HISTORY:]
                
        # エージェントへのプロンプト注入用：主要ステータスの履歴を記録（直近4ターンまで）
        HISTORY_MAX_LEN = 4
        for c_name, country in self.state.countries.items():
            # 毎ターン、政権の存続期間をインクリメント
            country.regime_duration += 1
            
            # 【新機能】財政規律ペナルティ
            # 国債残高がGDPに対して大きすぎる場合、信認低下により経済成長にマイナスデバフをかける
            debt_ratio = country.national_debt / max(1.0, country.economy)
            if debt_ratio > 0.0:
                # 負債比率1.0で約-1.0%の成長阻害。借金依存度が高いほど悪化する非線形ペナルティ
                debt_penalty = min(5.0, (math.exp(debt_ratio * 1.5) - 1.0) * 0.5) 
                if debt_penalty > 0.1:
                    country.economy *= (1.0 - (debt_penalty / 100.0))
                    self.sys_logs_this_turn.append(f"[{c_name} 財政ペナルティ] 累積国債がGDP比{debt_ratio:.1%}に達したため、信用収縮により経済に-{debt_penalty:.2f}%のデバフが発生しました。")
            
            snapshot = {
                "turn": self.state.turn,
                "economy": round(country.economy, 1),
                "military": round(country.military, 1),
                "intelligence_level": round(country.intelligence_level, 1),
                "approval_rating": round(country.approval_rating, 1)
            }
            country.stat_history.append(snapshot)
            if len(country.stat_history) > HISTORY_MAX_LEN:
                country.stat_history = country.stat_history[-HISTORY_MAX_LEN:]
        
        # S-6: hidden_plans の文字列長制限（プロンプト膨張防止）
        # 長期シミュレーション時にLLMのコンテキストウィンドウ上限に達するのを防ぐため、
        # 最新1000文字のみ保持し古い情報を切り捨てる。
        MAX_HIDDEN_PLANS_LENGTH = 1000
        for country in self.state.countries.values():
            if len(country.hidden_plans) > MAX_HIDDEN_PLANS_LENGTH:
                country.hidden_plans = "..." + country.hidden_plans[-MAX_HIDDEN_PLANS_LENGTH:]
