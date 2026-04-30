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
from .nuclear import NuclearMixin
from .utils import UtilsMixin

class WorldEngine(
    DomesticMixin,
    DiplomacyMixin,
    EconomyMixin,
    MilitaryMixin,
    EventsMixin,
    PublicOpinionMixin,
    NuclearMixin,
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

    def _cleanup_eliminated_country(self, eliminated_name: str):
        """消滅した国家に関連する全データを一括クリーンアップする（DRY共通関数）
        
        _handle_defeat（軍事的併合）と_handle_peaceful_annexation（平和的統合）の
        両方から呼び出される。消滅国への外交アクションが残留する「ゴーストバグ」を防止する。
        """
        # 1. 戦争データのクリーンアップ
        self.state.active_wars = [w for w in self.state.active_wars if w.aggressor != eliminated_name and w.defender != eliminated_name]
        
        # 2. 貿易協定の破棄
        self.state.active_trades = [t for t in self.state.active_trades if t.country_a != eliminated_name and t.country_b != eliminated_name]
        
        # 3. 経済制裁の解除
        self.state.active_sanctions = [s for s in self.state.active_sanctions if s.imposer != eliminated_name and s.target != eliminated_name]
        
        # 4. 保留中の提案（会談・同盟・統合）の削除
        self.state.pending_summits = [s for s in self.state.pending_summits if s.proposer != eliminated_name and s.target != eliminated_name]
        self.state.pending_alliances = [a for a in self.state.pending_alliances if a.proposer != eliminated_name and a.target != eliminated_name]
        self.state.pending_annexations = [a for a in self.state.pending_annexations if a.proposer != eliminated_name and a.target != eliminated_name]
        
        # 5. 保留中の援助申請の削除（従来欠落していた）
        self.state.pending_aid_proposals = [p for p in self.state.pending_aid_proposals if p.donor != eliminated_name and p.target != eliminated_name]
        
        # 5b. サブスク援助契約の削除
        self.state.recurring_aid_contracts = [c for c in self.state.recurring_aid_contracts if c.donor != eliminated_name and c.target != eliminated_name]
        
        # 6. 保留中の停戦提案の削除（従来欠落していた）
        self.state.pending_ceasefires = [c for c in self.state.pending_ceasefires if c.proposer != eliminated_name and c.target != eliminated_name]
        
        # 7. 保留中の降伏勧告の削除（従来欠落していた）
        self.state.pending_surrenders = [s for s in self.state.pending_surrenders if s.aggressor != eliminated_name and s.defender != eliminated_name]
        
        # 8. relations辞書から消滅国のエントリを完全削除（従来欠落していた）
        if eliminated_name in self.state.relations:
            del self.state.relations[eliminated_name]
        for country_name in list(self.state.relations.keys()):
            if eliminated_name in self.state.relations[country_name]:
                del self.state.relations[country_name][eliminated_name]
        
        # 9. 他国のdefender_supportersから消滅国を削除（従来欠落していた）
        for war in self.state.active_wars:
            if eliminated_name in war.defender_supporters:
                del war.defender_supporters[eliminated_name]
        
        # 10. 他国のdependency_ratioから消滅国を削除（従来欠落していた）
        for country in self.state.countries.values():
            if eliminated_name in country.dependency_ratio:
                del country.dependency_ratio[eliminated_name]
            # 宗主国が消滅した場合は独立回復
            if country.suzerain == eliminated_name:
                country.suzerain = None
        
        # 11. 多国間首脳会談のparticipantsリストから消滅国を除去
        for s in self.state.pending_summits:
            if eliminated_name in s.participants:
                s.participants = [p for p in s.participants if p != eliminated_name]
            if eliminated_name in s.accepted_participants:
                s.accepted_participants = [p for p in s.accepted_participants if p != eliminated_name]
        
        # 12. 消滅国リストに追加（AIプロンプトで外交対象外であることを明示するため）
        if eliminated_name not in self.state.defeated_countries:
            self.state.defeated_countries.append(eliminated_name)
        
        self.sys_logs_this_turn.append(f"[クリーンアップ完了] {eliminated_name}に関連する全データを削除しました。")

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
        from .constants import (
            TURNS_PER_YEAR, DEBT_INTEREST_RATE_ANNUAL,
            DEBT_SPREAD_THRESHOLD, DEBT_SPREAD_SENSITIVITY, DEBT_SPREAD_CAP_ANNUAL
        )
        for country_name, country in self.state.countries.items():
            old_gdp = country.economy
            # 税収: 年間GDPに税率を掛け、ターン数で割って四半期化
            tax_revenue = (old_gdp * country.tax_rate) / TURNS_PER_YEAR
            
            # 動的金利モデル（Harvard研究: 債務GDP比連動の信用スプレッド）
            # 全て年率で計算してから /TURNS_PER_YEAR でターン単位に変換
            debt_ratio = country.national_debt / max(1.0, old_gdp)
            if debt_ratio > DEBT_SPREAD_THRESHOLD:
                # 閾値超過分に感度を乗じてスプレッド算出（年率）
                credit_spread = (debt_ratio - DEBT_SPREAD_THRESHOLD) * DEBT_SPREAD_SENSITIVITY
                credit_spread = min(credit_spread, DEBT_SPREAD_CAP_ANNUAL)  # ギリシャ危機級でキャップ
                effective_rate_annual = DEBT_INTEREST_RATE_ANNUAL + credit_spread
            else:
                effective_rate_annual = DEBT_INTEREST_RATE_ANNUAL
            
            # 年率をターン単位に変換
            effective_rate_per_turn = effective_rate_annual / TURNS_PER_YEAR
            interest_payment = country.national_debt * effective_rate_per_turn
            
            # 予算が利払いを下回る場合はデフォルト（未払い分は借金に上乗せ）
            # 関税収入も四半期単位（economy.pyで計算済み）
            total_revenue = tax_revenue + country.tariff_revenue  # 税収 + 関税収入
            if total_revenue >= interest_payment:
                country.government_budget = total_revenue - interest_payment
            else:
                country.government_budget = 0.0
                default_amount = interest_payment - total_revenue
                country.national_debt += default_amount  # 払えなかった利息が元本組み込み（複利）
                self.sys_logs_this_turn.append(f"[{country_name} デフォルト] 利払い不能。未払利息 {default_amount:.1f} を債務に追加。")
            
            if effective_rate_annual > DEBT_INTEREST_RATE_ANNUAL + 0.001:
                self.sys_logs_this_turn.append(
                    f"[{country_name} 信用スプレッド] 債務GDP比{debt_ratio:.0%} → "
                    f"実効金利{effective_rate_annual:.2%}/年 ({effective_rate_per_turn:.3%}/Q) "
                    f"(基本{DEBT_INTEREST_RATE_ANNUAL:.2%} + スプレッド{effective_rate_annual - DEBT_INTEREST_RATE_ANNUAL:.2%})"
                )
            
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
        for country_name, action in actions.items():
            self._process_diplomacy_and_espionage(country_name, action)
        
        # パワー・バキューム・オークションの解決（Tullock CSF）
        # プレターンで分裂が発生した場合、各国のvacuum_bidを集計して吸収/独立を決定
        if self.state.pending_vacuum_auctions:
            self._resolve_vacuum_auctions(actions)
        
        # 影響力介入オークションの解決（軽量版パワー・バキューム）
        # プレターンでクーデター/革命が発生した場合、各国のvacuum_bidを集計して依存度変動を決定
        if self.state.pending_influence_auctions:
            self._resolve_influence_auctions(actions)
        
        # 多国間会談: 受諾者が2名以上集まった提案を実行キューに移動
        for s in list(self.state.pending_summits):
            if s.participants and len(s.accepted_participants) >= 2:
                self.summits_to_run_this_turn.append(s)
                self.state.pending_summits.remove(s)
            
        # 3. 貿易と制裁の処理 (Gravity Model & Sanctions Damage applying)
        self._process_trade_and_sanctions()
            
        # 4. 核兵器システムの処理（v1-3追加）
        self._process_nuclear_development(actions)   # 核開発・弾頭量産
        self._process_nuclear_strikes(actions)        # 核使用ダメージ適用
        self._process_nuclear_deployment(actions)     # 核配備（同盟国への核展開）
        self._process_nuclear_alliance_cleanup()      # 同盟破棄時の核自動撤去
        
        # 5. 戦争状態の処理
        self._process_wars()
        
        # 6. ランダムイベント（災害・技術革新）の判定
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
            
            # 【廃止】財政規律ペナルティ
            # domestic.py の利払いモデル（interest_leakage）で既に表現済み。
            # ここでさらにGDPを直接削ると二重計上となるため削除。
            # (v1-3.2: Álvarez-Pereira et al. 2022, Mankiw Ch.3 に準拠した整理)
            
            
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
