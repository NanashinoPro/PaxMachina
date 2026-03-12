import uuid
import math
import random
import logging
import json
from enum import Enum
from scipy.stats import skewnorm
from typing import Dict, List, Any

# Local imports
from models import WorldState, CountryState, GovernmentType, RelationType, AgentAction, WarState, TradeState, SanctionState, SummitProposal, AllianceProposal, AnnexationProposal

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
TRADE_GRAVITY_FRICTION_ALLIANCE = 1.0
TRADE_GRAVITY_FRICTION_NEUTRAL = 2.0

# 戦争モデルの定数
DEFENDER_ADVANTAGE_MULTIPLIER = 1.2

# --- 諜報システム定数 ---
INTEL_GROWTH_RATE = 0.02           # 諜報投資の成長率（軍事と同スケール）
INTEL_MAINTENANCE_ALPHA = 0.05     # 諜報網の自然減衰率

# --- 教育・科学システム定数（内生的成長理論）---
EDUCATION_GROWTH_RATE = 0.05       # 教育投資の成長率（人的資本の蓄積速度。絶対額スケール調整済み）
EDUCATION_MAINTENANCE_ALPHA = 0.015 # 人的資本の自然減衰率（1%/四半期。知識の陳腐化等）
EDUCATION_GDP_ALPHA = 0.1         # 人的資本の産出弾力性（alpha）。0.1なら知識が1%増えるとGDP効率が0.1%向上する。

# --- 政治・実行力モデル定数 ---
DEMOCRACY_MIN_EXECUTION_POWER = 0.4 # 民主主義における政策実行力の最低保証値（官僚機構による基本執行分）

# ------------------------------------

class WorldEngine:
    """世界の毎ターンの出来事を処理し、状態を更新するエンジン"""
    
    def __init__(self, initial_state: WorldState, analyzer=None):
        self.state = initial_state
        self.events_this_turn: List[str] = []
        self.sys_logs_this_turn: List[str] = []
        self.summits_to_run_this_turn: List[SummitProposal] = []
        self.pending_intel_requests: List[Dict[str, str]] = []
        self.pending_sabotage_requests: List[Dict[str, str]] = []
        # Added pending events that require LLM generation outside the engine
        self.pending_rebellions: List[str] = []
        self.pending_elections: List[str] = []
        
        # 感情分析器（外部から注入）
        self.analyzer = analyzer
        self.turn_domestic_factors: Dict[str, Dict[str, float]] = {}
        self.turn_sns_logs: Dict[str, List[Dict[str, Any]]] = {} # Added for fragmentation logic
        self.turn_dutch_disease_penalty: Dict[str, float] = {} # オランダ病（援助過剰）による政策実行力デバフ

        # 1ターン目のみ、各国の初期教育レベルを保存（規格化用）
        for name, country in self.state.countries.items():
            if country.initial_education_level <= 1.0 and country.education_level > 1.0:
                country.initial_education_level = country.education_level
            # [追加] 政権の存続期間をインクリメント
            country.regime_duration += 1

    def log_event(self, message: str):
        self.events_this_turn.append(message)

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
        for country_name, country in self.state.countries.items():
            old_gdp = country.economy
            interest_payment = country.national_debt * DEBT_INTEREST_RATE
            tax_revenue = old_gdp * country.tax_rate
            country.government_budget = max(0.0, tax_revenue - interest_payment)
            
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
            
        # 3. 貿易と制裁の処理 (Gravity Model & Sanctions Damage applying)
        self._process_trade_and_sanctions()
            
        # 4. 戦争状態の処理
        self._process_wars()
        
        # 5. ランダムイベント（災害・技術革新）の判定
        self._process_random_events()
        
        # 6. 時間進行とターン終了処理は外部 (main.py) から advance_time() を呼び出すよう変更
        
        # イベントログをステートに記録
        self.state.news_events.extend(self.events_this_turn.copy())
        
        return self.state

    def process_pre_turn(self):
        """
        AIエージェントの意思決定前に、システムが自動で発生させるイベント（政権交代など）を処理する
        """
        self.events_this_turn = []
        self.sys_logs_this_turn = []
        self.pending_rebellions = []
        self.pending_elections = []
        
        # 反乱と選挙の進行（Alesina-Spolaore分裂判定もここに含まれる）
        # 分裂で新しい国が self.state.countries に追加されるため、list() でコピーして回す
        for name, country in list(self.state.countries.items()):
            # 支持率低下による反乱リスク
            if country.approval_rating < 30.0:
                country.rebellion_risk += 5.0
                self.log_event(f"⚠️ {name}の国内で政府への抗議運動が激化しています。(支持率{country.approval_rating:.1f}%)")
            else:
                country.rebellion_risk = max(0.0, country.rebellion_risk - 2.0)
                
            # 체제別 イベント
            if country.government_type == GovernmentType.DEMOCRACY:
                # 民主主義の動的クーデター確率 (Alesina-Spolaore統合)
                if country.approval_rating <= 30.0:
                    # 30%で0、0%で100%になるクーデター確率
                    coup_prob = max(0.0, (30.0 - country.approval_rating) / 30.0 * 100.0)
                    if random.uniform(0.0, 100.0) < coup_prob:
                        self.log_event(f"⚠️ {name}で【政府機能麻痺】激しい暴動により民主政権が崩壊しました！(支持率{country.approval_rating:.1f}%)")
                        self._handle_rebellion(name, country)
                        if name in self.state.countries and self.state.countries[name].turns_until_election is not None:
                            self.state.countries[name].turns_until_election = 16 # 米国の場合4年(16ターン)リセット
                        continue
                    
                if country.turns_until_election is not None:
                    country.turns_until_election -= 1
                    if country.turns_until_election <= 0:
                        self._handle_election(name, country)
                        if name in self.state.countries:
                            self.state.countries[name].turns_until_election = 16 # 米国の場合4年(16ターン)リセット
                        
            elif country.government_type == GovernmentType.AUTHORITARIAN:
                # 専制主義での反乱判定
                if country.rebellion_risk > random.uniform(20.0, 100.0):
                    self._handle_rebellion(name, country)
                    if name in self.state.countries:
                        self.state.countries[name].rebellion_risk = 0.0
                    
        # プレターンイベントでリストを上書き（前ターンのログをここでクリア）
        self.state.news_events = self.events_this_turn.copy()

    def _process_foreign_aid(self, actions: Dict[str, AgentAction]):
        """
        対外援助の無償提供と、オランダ病（吸収能力限界）、および属国化の進行を処理する
        """
        received_aid_econ = {name: 0.0 for name in self.state.countries}
        received_aid_mil = {name: 0.0 for name in self.state.countries}
        
        # 1. 援助の流出処理（自国の予算 G から天引き）
        for donor_name, action in actions.items():
            if donor_name not in self.state.countries:
                continue
            donor = self.state.countries[donor_name]
            
            for dip in action.diplomatic_policies:
                target_name = dip.target_country
                if target_name not in self.state.countries or target_name == donor_name:
                    continue
                
                req_econ = getattr(dip, 'aid_amount_economy', 0.0)
                req_mil = getattr(dip, 'aid_amount_military', 0.0)
                
                if req_econ <= 0 and req_mil <= 0:
                    continue
                
                total_req = req_econ + req_mil
                if total_req > donor.government_budget:
                    # 予算上限のクランプ
                    ratio = donor.government_budget / total_req
                    req_econ *= ratio
                    req_mil *= ratio
                    total_req = donor.government_budget
                
                if total_req <= 0:
                    continue
                    
                # 予算から天引き
                donor.government_budget -= total_req
                received_aid_econ[target_name] += req_econ
                received_aid_mil[target_name] += req_mil
                
                # 依存度の加算
                target = self.state.countries[target_name]
                dependency_addition = total_req / max(1.0, target.economy)
                target.dependency_ratio[donor_name] = target.dependency_ratio.get(donor_name, 0.0) + dependency_addition
                
                # ログ・ニュース
                self.sys_logs_this_turn.append(f"[{donor_name} -> {target_name} 援助] 経済: {req_econ:.1f}, 軍事: {req_mil:.1f} (依存度 +{dependency_addition*100:.1f}%)")
                self.log_event(f"💰 【対外援助】{donor_name}が{target_name}に対して莫大な援助（経済:{req_econ:.1f}, 軍事:{req_mil:.1f}）を実施しました。")

        # 2. 援助の流入処理とオランダ病判定
        for target_name, target in self.state.countries.items():
            total_econ = received_aid_econ[target_name]
            total_mil = received_aid_mil[target_name]
            total_received = total_econ + total_mil
            
            if total_received <= 0:
                continue
                
            # 吸収能力の限界（オランダ病判定）: 1ターンにGDPの20%以上を受け取ると発症
            limit = target.economy * 0.20
            
            if total_received > limit:
                # 限界超過！ 政策実行力が大暴落（最大で0.5倍になる）
                excess_ratio = (total_received - limit) / target.economy
                debuff = max(0.5, 1.0 - (excess_ratio * 2.0))
                self.turn_dutch_disease_penalty[target_name] = debuff
                
                # 資金の消滅（モラルハザード: 超過分の50%が虚無に消える）
                lost_amount = (total_received - limit) * 0.50
                survival_ratio = (total_received - lost_amount) / total_received
                
                total_econ *= survival_ratio
                total_mil *= survival_ratio
                
                self.sys_logs_this_turn.append(f"🚨 [{target_name} オランダ病発症] 莫大な援助により汚職とインフレが蔓延。政策実行力 x{debuff:.2f}。支援金 {lost_amount:.1f} が消散。")
                self.log_event(f"⚠️ 【援助の呪い】{target_name}に自国の経済規模を上回る巨額の対外援助が流入した結果、急激なインフレと官僚の腐敗（オランダ病）が発生し、国家機能が麻痺しています！")
                
                # 支持率も暴落（強制徴用や物価高騰への反発）
                target.approval_rating = max(0.0, target.approval_rating - 15.0)
                
            # 無事に残った資金を国家のパラメータに反映
            target.economy += total_econ # 経済援助はGDPを直接ブースト
            target.military += total_mil # 軍事力ストックに追加
            
            # 属国化の閾値判定
            for donor_name, dep_ratio in target.dependency_ratio.items():
                if dep_ratio > 0.60 and target.suzerain != donor_name:
                    target.suzerain = donor_name
                    self.log_event(f"👑 【属国化】{target_name}は{donor_name}からの巨額の経済・軍事支援により主権を喪失し、完全に{donor_name}の属国（傀儡国家）となりました。")
                    self.sys_logs_this_turn.append(f"[{target_name} 属国化] {donor_name}への依存度が {dep_ratio*100:.1f}% に達し、主権喪失。")

    def _process_domestic(self, country_name: str, action: AgentAction):
        country = self.state.countries[country_name]
        
        # 秘密計画の更新
        if hasattr(action, 'update_hidden_plans') and action.update_hidden_plans:
            country.hidden_plans = action.update_hidden_plans

        # --- 税率調整と政治的コスト（支持率ペナルティ） ---
        old_tax_rate = country.tax_rate
        new_tax_rate = action.domestic_policy.tax_rate
        
        # 税率の異常値を弾く (0.1 ~ 0.7 の範囲内にクランプ)
        # 首脳AIが 15.0(%) のように整数で返してきた場合の補正ロジック
        if new_tax_rate >= 1.0:
            new_tax_rate /= 100.0
            
        new_tax_rate = max(0.10, min(0.70, new_tax_rate))
    
        # 1ターンあたりの税率変動を±10%に制限（急激な増減税による社会崩壊の防止）
        clamped_tax_rate = max(old_tax_rate - MAX_TAX_CHANGE_PER_TURN, min(old_tax_rate + MAX_TAX_CHANGE_PER_TURN, new_tax_rate))
        if abs(clamped_tax_rate - new_tax_rate) > 0.001:
            self.sys_logs_this_turn.append(f"[{country_name} 税率制限] AI要求 {new_tax_rate:.1%} を {clamped_tax_rate:.1%} にクランプ (上限±{MAX_TAX_CHANGE_PER_TURN:.0%}/ターン)")
            new_tax_rate = clamped_tax_rate
        country.tax_rate = new_tax_rate
        
        tax_diff = new_tax_rate - old_tax_rate
        if tax_diff > 0:
            penalty = tax_diff * TAX_APPROVAL_PENALTY_MULTIPLIER
            country.approval_rating = max(0.0, country.approval_rating - penalty)
            self.sys_logs_this_turn.append(f"[{country.name} 増税] 税率 {old_tax_rate:.1%}→{new_tax_rate:.1%} (支持率ペナルティ: -{penalty:.1f}%)")
        elif tax_diff < 0:
            bonus = abs(tax_diff) * TAX_REDUCTION_APPROVAL_BONUS_MULTIPLIER
            country.approval_rating = min(100.0, country.approval_rating + bonus)
            self.sys_logs_this_turn.append(f"[{country.name} 減税] 税率 {old_tax_rate:.1%}→{new_tax_rate:.1%} (支持率ボーナス: +{bonus:.1f}%)")
        # ------------------------------------------------

        # --- 政策実行力の算出 ---
        # [学術的根拠] 民主主義国家では低支持率時に議会の攻防が激化し政策実現が困難になる。
        # 専制主義では強権的執行が可能ことから下限を保障（最低ε=0.5）。
        execution_power = 1.0
        if country.government_type == GovernmentType.DEMOCRACY:
            if country.approval_rating < DEMOCRACY_WARN_APPROVAL:
                execution_power = max(DEMOCRACY_MIN_EXECUTION_POWER, (country.approval_rating - CRITICAL_APPROVAL) / (DEMOCRACY_WARN_APPROVAL - CRITICAL_APPROVAL))
        elif country.government_type == GovernmentType.AUTHORITARIAN:
            if country.approval_rating < 25.0:
                execution_power = max(0.5, 0.5 + (country.approval_rating / 50.0))
                
        # オランダ病ペナルティの適用
        if country_name in self.turn_dutch_disease_penalty:
            penalty_ratio = self.turn_dutch_disease_penalty[country_name]
            execution_power = max(0.1, execution_power * penalty_ratio)
        
        # --- マクロ経済モデリング (SNAベース: Y = C + I + G + NX) ---
        old_gdp = country.economy
        
        # 国家債務の利払い (利払い分だけ予算が減る、または債務が増える。ここでは簡単のため予算から天引き想定)
        interest_payment = country.national_debt * DEBT_INTEREST_RATE
        
        # 税収T = GDP * 税率 (※前ターンのGDPをベースにする)
        # 報道の自由度の更新とペナルティ計算
        # 自由度を急激に制限（下げる）すると、国民の不満によって支持率が大きく下落する
        target_freedom = getattr(action.domestic_policy, 'target_press_freedom', country.press_freedom)
        freedom_diff = target_freedom - country.press_freedom
        
        if freedom_diff < -0.05:
            # 自由度を下げた場合: 0.1の制限につき、支持率-5%程度のペナルティ
            freedom_penalty = abs(freedom_diff) * 50.0
            country.approval_rating = max(0.0, country.approval_rating - freedom_penalty)
            self.sys_logs_this_turn.append(f"[{country.name} 報道統制] 自由度低下({freedom_diff:+.2f})により支持率急落 -{freedom_penalty:.1f}%")
        elif freedom_diff > 0.05:
            # 自由度を上げた場合: 0.1の緩和につき、支持率+2%程度のボーナス（統制解除による限定的な支持回復）
            freedom_bonus = freedom_diff * 20.0
            country.approval_rating = min(100.0, country.approval_rating + freedom_bonus)
            self.sys_logs_this_turn.append(f"[{country.name} 情報公開] 自由度上昇({freedom_diff:+.2f})により支持率回復 +{freedom_bonus:.1f}%")
        
        # 自由度の数値を更新
        country.press_freedom = target_freedom

        # 政府予算 (すでに対外援助等で引かれている額)
        budget = country.government_budget
        
        # 経済投資
        inv_econ = action.domestic_policy.invest_economy
        inv_mil = action.domestic_policy.invest_military
        inv_wel = action.domestic_policy.invest_welfare
        inv_intel = getattr(action.domestic_policy, 'invest_intelligence', 0.0)
        inv_edu = getattr(action.domestic_policy, 'invest_education_science', 0.0)
        
        # 予算の総和を1.0に正規化（安全装置）
        total_inv = inv_econ + inv_mil + inv_wel + inv_intel + inv_edu
        if total_inv <= 0.0:
            inv_econ, inv_mil, inv_wel, inv_intel, inv_edu = 0.25, 0.25, 0.25, 0.125, 0.125 # 異常時のフォールバック
            total_inv = 1.0
        elif total_inv > 1.0:
            inv_econ /= total_inv
            inv_mil /= total_inv
            inv_wel /= total_inv
            inv_intel /= total_inv
            inv_edu /= total_inv
            total_inv = 1.0

        # 政府支出(G)のブレイクダウン
        g_econ = budget * inv_econ * execution_power
        g_mil = budget * inv_mil * execution_power
        g_wel = budget * inv_wel * execution_power
        g_intel = budget * inv_intel * execution_power
        g_edu = budget * inv_edu * execution_power
        G = g_econ + g_mil + g_wel + g_intel + g_edu

        # 政府の未執行予算（余剰金）を算出
        S_gov = max(0.0, budget - G)
        
        # 国家債務の自動返済
        if S_gov > 0.0:
            repayment = min(country.national_debt, S_gov)
            country.national_debt -= repayment
            if repayment > 0.1:
                self.sys_logs_this_turn.append(f"[{country.name} 債務返済] 未執行予算にて {repayment:.1f} を返済 (政府貯蓄: {S_gov:.1f})")

        # 基礎貯蓄率 (政治体制と福祉投資による低下)
        base_s_rate = AUTHORITARIAN_BASE_SAVING_RATE if country.government_type == GovernmentType.AUTHORITARIAN else DEMOCRACY_BASE_SAVING_RATE
        saving_rate = max(0.15, base_s_rate - (inv_wel * 0.15))

        tax_revenue = old_gdp * country.tax_rate

        # 1. 民間消費 (C)
        # ケインズ型消費関数: C = (Y - T) * (1 - s)
        # 増税すると即座に消費が減る。減税すると消費が大きく活性化するボーナスを追加。
        C = max(0.0, (old_gdp - tax_revenue) * (1.0 - saving_rate))
        if tax_diff < 0:
            consumption_bonus_multiplier = 1.0 + (abs(tax_diff) * 2.0)
            C *= consumption_bonus_multiplier
            
        S_private = max(0.0, (old_gdp - tax_revenue) - C)

        # --- SNAマクロ経済モデル: 民間投資 (I) ---
        # [Harrod 1939; Domar 1946] 貯蓄=投資均衡仮定の下、民間貯蓄の一部が
        # 資本市場を通じて国内投資へ還流すると仮定。係数0.85は国内投資率を表し、
        # 残15%は海外流出・現預金積み上げ等として処理。
        # 政府の経済投資は民間投資を誘発（クラウドイン）し、軍事費が民間投資を押し出す（クラウドアウト）。
        # 民間貯蓄に加え、政府の未執行予算(S_gov)が金融市場を通じて民間投資に還流する
        I = max(0.0, S_private * 0.85 + (S_gov * DEBT_REPAYMENT_CROWD_IN_MULTIPLIER) + (g_econ * GOVERNMENT_CROWD_IN_MULTIPLIER) - (g_mil * GOVERNMENT_CROWD_OUT_MULTIPLIER))
        
        # -- 災害・技術革新のフロー影響を適用 --
        disaster_damage_sum = sum(d.damage_percent for d in self.state.disaster_history if d.turn == self.state.turn and (d.country == country_name or d.country is None))
        
        breakthrough_multiplier = 1.0
        for bt in self.state.active_breakthroughs:
            # 古すぎる技術革新は陳腐化し、追加のボーナスを生まない
            if bt.turns_active > 20:
                continue
            if bt.origin_country == country_name and not bt.spread_globally:
                breakthrough_multiplier += random.uniform(0.05, 0.15) # 投資に対するバフを現実的な範囲に
            elif bt.spread_globally:
                breakthrough_multiplier += random.uniform(0.01, 0.05)
                
        # 強制的にキャップをかける（バブル抑制）
        breakthrough_multiplier = min(1.10, breakthrough_multiplier)
        
        I *= breakthrough_multiplier

        # 次ターンのGDP(Y)の暫定算出 = C + I + G + NX
        # 教育・科学投資による人的資本バフの適用 (弾力性モデル: Y = (C + I + G) * (H / H0)^alpha + NX)
        # H0(initial_education_level)は開始時の絶対額。比率をとることで単位依存を解消
        h_ratio = country.education_level / max(1.0, country.initial_education_level)
        new_gdp_provisional = (C + I + G) * (h_ratio ** EDUCATION_GDP_ALPHA) + country.last_turn_nx
        
        # 災害ダメージは当期の経済から直接引く（巨大な資本破壊）
        if disaster_damage_sum > 0:
            damage_amount = old_gdp * (disaster_damage_sum / 100.0)
            new_gdp_provisional -= damage_amount
            approval_penalty = disaster_damage_sum * 0.5
            country.approval_rating = max(0.0, country.approval_rating - approval_penalty)
            self.sys_logs_this_turn.append(f"[{country.name} 災害被害] -{damage_amount:.1f} (支持率 -{approval_penalty:.1f}%)")

        # 債務対GDP比の計算（記録用。直接GDPを削るペナルティは二重計上防止のため廃止。利払いで表現済み）
        debt_to_gdp = country.national_debt / max(1.0, old_gdp)
        if debt_to_gdp > DEBT_TO_GDP_PENALTY_THRESHOLD and self.state.turn % 5 == 0:
            self.sys_logs_this_turn.append(f"[{country.name} 債務警告] 対GDP比{debt_to_gdp:.1%}。利払い負担が増大しています")
        
        # ===== 人口動態モデル (ロジスティック方程式と環境収容力) =====
        old_pop = country.population
        gdp_per_capita = old_gdp / max(0.1, old_pop)
        
        # 環境収容力(K): 面積(平方km) × 1平方kmあたりの最大人口定数(例: 150人など)
        # ※現実の1平方kmあたり限界密度は国によるが、ゲームバランスとして例えば面積1000万km2の国で15億人を上限とする
        CARRYING_CAPACITY_COEFFICIENT = 150.0 
        carrying_capacity = max(10.0, country.area * CARRYING_CAPACITY_COEFFICIENT)
        
        # 出生率: 基礎2%。1人当たりGDPと教育水準が高いほど低下 (少子化の罠)
        base_birth_rate = 0.02
        import math
        birth_rate_reduction = min(0.015, (math.log10(max(1.0, gdp_per_capita)) * 0.002) + (country.education_level / 1000.0 * 0.005))
        welfare_birth_bonus = inv_wel * 0.01 * execution_power
        birth_rate = max(0.001, base_birth_rate - birth_rate_reduction + welfare_birth_bonus)
        
        # 死亡率: 通常0.5%。絶対的貧困(GDP per capita < 0.8)や災害で増加
        base_death_rate = 0.005
        poverty_death_increase = max(0.0, 0.01 - (gdp_per_capita / 50.0))
        disaster_death_increase = disaster_damage_sum / 5000.0
        death_rate = base_death_rate + poverty_death_increase + disaster_death_increase
        
        # ロジスティック方程式に基づく人口増加率の計算 (環境収容力に近づくほど増加率が0になる)
        # N(t+1) = N(t) + r * N(t) * (1 - N(t) / K)
        intrinsic_growth_rate = birth_rate - death_rate
        pop_growth_rate = intrinsic_growth_rate * (1.0 - (old_pop / carrying_capacity))
        country.population = max(0.1, old_pop * (1.0 + pop_growth_rate))
        
        # --- 人口過密(Overpopulation)ペナルティ ---
        density_ratio = country.population / carrying_capacity
        if density_ratio > 0.90:
            # 収容力の90%を超えた場合、住宅・インフラの逼迫による強力な支持率ペナルティ
            density_penalty = (density_ratio - 0.90) * 100.0 # 最大10%程度の低下
            country.approval_rating = max(0.0, country.approval_rating - density_penalty)
            self.sys_logs_this_turn.append(f"[{country.name} 人口過密] 密集率{density_ratio:.1%}。インフラ逼迫により支持率 -{density_penalty:.1f}%")
        
        # --- 1人当たりGDP急低下/絶対的貧困による社会不安ペナルティ ---
        # 1. 絶対的貧困ライン (世界銀行基準の過度な貧困: 年間約800ドル相当をシミュレーション上の0.8とする)
        if gdp_per_capita < 0.8:
            extreme_poverty_penalty = 5.0 # 毎ターン強烈に下がる
            country.approval_rating = max(0.0, country.approval_rating - extreme_poverty_penalty)
            self.sys_logs_this_turn.append(f"[{country.name} 絶対的貧困] GDP/C {gdp_per_capita:.2f}未満による暴動・社会不安 (支持率 -{extreme_poverty_penalty:.1f}%)")
        
        # 経済力がゼロ以下になるのを防ぐ
        country.economy = max(1.0, new_gdp_provisional)

        
        # ===== リチャードソン・モデル (Richardson 1960) =====
        # [学術的根拠] 軍拡競争の数理モデル。軍事負担率がGDP比で高くなるほど、
        # 維持費（疲弊係数α）が二次関数的に跳ね上がる。これにより、経済的に
        # 持続不可能な軍拡がシステム的に自壊するメカニズムを提供し、現実の「帝国の過度な拡大」
        # (Paul Kennedy 1987) を模倣する。計算にはSNA更新前の前期GDPを使用。
        military_burden = country.military / max(1.0, old_gdp)
        dynamic_alpha = BASE_MILITARY_MAINTENANCE_ALPHA + (military_burden * 2.0) ** 2
        alpha = min(MAX_MILITARY_FATIGUE_ALPHA, dynamic_alpha)
        
        # 軍事投資による増加分（政策実行力ε適用済みの政府軍事支出に成長率を乗算）
        military_growth = g_mil * BASE_MILITARY_GROWTH_RATE
        old_military = country.military
        country.military = (country.military * (1.0 - alpha)) + military_growth
        
        # ===== 学術的に適正化された軍事動員限界ルール (10%の壁) =====
        # Personnel = M / (GDP per capita * 定数)
        MOBILIZATION_CONSTANT = 3.4
        current_gdp_per_capita = country.economy / max(0.1, country.population)
        estimated_personnel = country.military / max(0.1, current_gdp_per_capita * MOBILIZATION_CONSTANT)
        mobilization_rate = estimated_personnel / max(0.1, country.population)
        
        mobilization_penalty_text = ""
        if mobilization_rate > 0.10: # 10%超過で過剰動員ペナルティ
            excess_mobilization = mobilization_rate - 0.10
            # 産業空洞化によるGDP蒸発と、支持率の大幅低下
            mobilization_penalty = min(0.5, excess_mobilization * 2.0)
            country.economy = max(1.0, country.economy * (1.0 - mobilization_penalty))
            rebel_penalty = min(50.0, excess_mobilization * 200.0)
            country.approval_rating = max(0.0, country.approval_rating - rebel_penalty)
            mobilization_penalty_text = f" | [過剰動員ペナルティ] 動員限界突破({mobilization_rate:.1%}) GDP-{mobilization_penalty*100:.1f}%, 支持率急落"
            self.sys_logs_this_turn.append(f"[{country.name} 極限動員] 動員率{mobilization_rate:.1%}。労働力不足で経済力-{mobilization_penalty*100:.1f}%, 支持-{rebel_penalty:.1f}%")

        # 成長率ボーナスの計算 (総GDPではなく1人当たりGDPの成長率を使用し、人口増による豊かさの希釈と過剰動員ペナルティを反映)
        new_gdp_per_capita = country.economy / max(0.1, country.population)
        gdp_growth_rate = (new_gdp_per_capita - gdp_per_capita) / max(1.0, gdp_per_capita) * 100.0

        # 2. 相対的な貧困ショック (1人当たりGDPが前期比で-5.0%以上急落した場合)
        if gdp_growth_rate < -5.0:
            relative_poverty_penalty = min(10.0, abs(gdp_growth_rate) * 0.5)
            country.approval_rating = max(0.0, country.approval_rating - relative_poverty_penalty)
            self.sys_logs_this_turn.append(f"[{country.name} 生活水準急落] GDP/C成長率 {gdp_growth_rate:.1f}%。市民の経済的不安増大 (支持率 -{relative_poverty_penalty:.1f}%)")

        
        # --- 福祉ボーナスによる支持率還元 ---
        # [学術的根拠] 福祈支出の支持率への効果が逓減することを対数関数（log1p）でモデル化。
        # 限界効用逓減の法則 (Gossen 1854) に基づき、一定水準以上の投資は
        # 効果が頭打ちになる。これにより「福祈へ全抜けすれば支持率が無限に上がる」メタ解法を防止。
        inv_wel = action.domestic_policy.invest_welfare
        old_approval = country.approval_rating
        welfare_trend = math.log1p(inv_wel * 5.0) * 1.5 - 1.0
        welfare_bonus = welfare_trend * execution_power

        # --- 諜報レベルの蓄積・減衰（リチャードソンモデルと同様のパターン）---
        old_intel = country.intelligence_level
        intel_growth = g_intel * INTEL_GROWTH_RATE
        country.intelligence_level = (country.intelligence_level * (1.0 - INTEL_MAINTENANCE_ALPHA)) + intel_growth

        # --- 教育・科学技術の蓄積・減衰（ルーカス・モデル）---
        old_edu = country.education_level
        edu_growth = g_edu * EDUCATION_GROWTH_RATE
        country.education_level = (country.education_level * (1.0 - EDUCATION_MAINTENANCE_ALPHA)) + edu_growth
            
        self.turn_domestic_factors[country_name] = {
            "gdp_growth_rate": gdp_growth_rate,
            "welfare_bonus": welfare_bonus,
            "inv_wel": inv_wel,
            "trade_support_bonus": 0.0,
            "inv_econ": inv_econ,
            "inv_mil": inv_mil,
            "total_inv": total_inv
        }
            
        self.sys_logs_this_turn.append(
            f"内政更新完了: {country.name} | "
            f"税率:{new_tax_rate:.1%} (税収:{tax_revenue:.1f}) | 予算(G):{budget:.1f} | "
            f"1人当GDP:{gdp_per_capita:.1f} -> {new_gdp_per_capita:.1f} ({gdp_growth_rate:+.1f}%) | "
            f"人口:{old_pop:.1f} -> {country.population:.1f} ({pop_growth_rate*100:+.2f}%) | "
            f"動員率:{mobilization_rate:.1%}{mobilization_penalty_text}\n"
            f"  > 軍事力:{old_military:.1f} -> {country.military:.1f} (+{military_growth:.1f}, 維持費: -{alpha*100:.1f}%), "
            f"諜報:{old_intel:.1f} -> {country.intelligence_level:.1f}, "
            f"教育:{old_edu:.2f} -> {country.education_level:.2f}, "
            f"支持率:{old_approval:.1f}% -> {country.approval_rating:.1f}%"
        )

    def _process_diplomacy_and_espionage(self, country_name: str, action: AgentAction):
        country = self.state.countries[country_name]
        
        for dip in action.diplomatic_policies:
            target_name = dip.target_country
            if target_name not in self.state.countries:
                continue
                
            # メッセージ送信
            if dip.message:
                if getattr(dip, 'is_private', False):
                    self.sys_logs_this_turn.append(f"[非公開メッセージ] {country_name} -> {target_name}: {dip.message}")
                    if target_name in self.state.countries:
                        self.state.countries[target_name].private_messages.append(f"【{country_name}からの極秘通信】\n{dip.message}")
                else:
                    self.log_event(f"[{country_name} -> {target_name}] メッセージ送信: {dip.message}")
                
            # 同盟提案の処理 (相互合意メカニズム: 相手も同ターンまたは前ターンにpropose_allianceしていれば成立)
            if dip.propose_alliance:
                rel = self._get_relation(country_name, target_name)
                if rel == RelationType.AT_WAR:
                    self.log_event(f"⚠️ {country_name}から{target_name}への同盟提案は戦争状態のため無効です。")
                elif rel == RelationType.ALLIANCE:
                    pass  # 既に同盟済み
                else:
                    # 前ターンに相手から提案が来ているか確認
                    matched = [a for a in self.state.pending_alliances if a.proposer == target_name and a.target == country_name]
                    if matched:
                        # 双方合意成立！
                        self._update_relation(country_name, target_name, RelationType.ALLIANCE)
                        self.log_event(f"🤝 {country_name}と{target_name}が相互合意の上、軍事同盟を締結しました。")
                        self.state.pending_alliances.remove(matched[0])
                    else:
                        # 提案をキューに積む（翌ターン以降に相手が受諾すれば成立）
                        existing = [a for a in self.state.pending_alliances if a.proposer == country_name and a.target == target_name]
                        if not existing:
                            self.state.pending_alliances.append(AllianceProposal(proposer=country_name, target=target_name))
                            self.log_event(f"✉️ {country_name}が{target_name}に対して軍事同盟を提案しました。（相手の合意を待機中）")
                
            # 宣戦布告
            if dip.declare_war:
                rel = self._get_relation(country_name, target_name)
                if rel != RelationType.AT_WAR:
                    self._update_relation(country_name, target_name, RelationType.AT_WAR)
                    # 新しい戦争を作成
                    new_war = WarState(aggressor=country_name, defender=target_name)
                    self.state.active_wars.append(new_war)
                    self.log_event(f"⚔️ 【開戦】{country_name}が{target_name}に対して宣戦布告しました！")
                    
            # 諜報工作
            if dip.espionage_gather_intel or dip.espionage_sabotage:
                self._process_espionage(country_name, target_name, dip)

            # 貿易・制裁
            if getattr(dip, 'propose_trade', False):
                self.log_event(f"🤝 {country_name}から{target_name}へ貿易・経済協力の提案がなされました。")
                rel = self._get_relation(country_name, target_name)
                if rel != RelationType.AT_WAR:
                    existing = [t for t in self.state.active_trades if (t.country_a == country_name and t.country_b == target_name) or (t.country_a == target_name and t.country_b == country_name)]
                    if not existing:
                        self.state.active_trades.append(TradeState(country_a=country_name, country_b=target_name))
                        self.log_event(f"🚢 {country_name}と{target_name}の間で貿易協定が開始されました。")
            
            if getattr(dip, 'cancel_trade', False):
                self.log_event(f"⚠️ {country_name}が{target_name}との貿易協定を破棄しました。")
                self.state.active_trades = [t for t in self.state.active_trades if not ((t.country_a == country_name and t.country_b == target_name) or (t.country_a == target_name and t.country_b == country_name))]
            
            if getattr(dip, 'impose_sanctions', False):
                self.log_event(f"⛔ {country_name}が{target_name}に対して本格的な経済制裁を発動しました。")
                existing = [s for s in self.state.active_sanctions if s.imposer == country_name and s.target == target_name]
                if not existing:
                    self.state.active_sanctions.append(SanctionState(imposer=country_name, target=target_name))
            
            if getattr(dip, 'lift_sanctions', False):
                self.log_event(f"✅ {country_name}が{target_name}への経済制裁を解除しました。")
                self.state.active_sanctions = [s for s in self.state.active_sanctions if not (s.imposer == country_name and s.target == target_name)]

            # 首脳会談の提案
            if dip.propose_summit:
                is_private_summit = getattr(dip, 'is_private', False)
                self.state.pending_summits.append(SummitProposal(proposer=country_name, target=target_name, topic=dip.summit_topic, is_private=is_private_summit))
                if is_private_summit:
                    self.sys_logs_this_turn.append(f"[非公開会談提案] {country_name} -> {target_name}: {dip.summit_topic}")
                    if target_name in self.state.countries:
                        self.state.countries[target_name].private_messages.append(f"【{country_name}からの極秘の会談提案】\n議題: {dip.summit_topic}")
                else:
                    self.log_event(f"✉️ {country_name}が{target_name}に対して首脳会談を提案しました。議題: {dip.summit_topic}")

            # 首脳会談の受諾
            if dip.accept_summit:
                # 前ターンからの提案リストに探す
                matched = [s for s in self.state.pending_summits if s.proposer == target_name and s.target == country_name]
                if matched:
                    proposal = matched[0]
                    self.summits_to_run_this_turn.append(proposal)
                    if proposal.is_private:
                        self.sys_logs_this_turn.append(f"[非公開会談受諾] {country_name}が{target_name}からの提案を受諾。")
                    else:
                        self.log_event(f"✅ {country_name}が{target_name}からの首脳会談の提案（議題: {proposal.topic}）を受諾しました。会談が開催されます。")
                    self.state.pending_summits.remove(proposal)
                    
            # 平和的統合（吸収合併）の提案
            if getattr(dip, 'propose_annexation', False):
                existing = [a for a in self.state.pending_annexations if a.proposer == country_name and a.target == target_name]
                if not existing:
                    self.state.pending_annexations.append(AnnexationProposal(proposer=country_name, target=target_name))
                    if getattr(dip, 'is_private', False):
                         self.sys_logs_this_turn.append(f"[非公開統合提案] {country_name} -> {target_name}")
                         if target_name in self.state.countries:
                             self.state.countries[target_name].private_messages.append(f"【{country_name}からの極秘の国家統合提案】\n我が国への合流を提案する。")
                    else:
                         self.log_event(f"📜 {country_name}が{target_name}に対して平和的で対等な「国家統合」を提案しました。（{target_name}の合意を待機中）")

            # 平和的統合の受諾
            if getattr(dip, 'accept_annexation', False):
                matched = [a for a in self.state.pending_annexations if a.proposer == target_name and a.target == country_name]
                if matched:
                    proposal = matched[0]
                    self.state.pending_annexations.remove(proposal)
                    # 統合受諾ロジック: 専制は即決、民主は支持率による確率
                    if country.government_type == GovernmentType.DEMOCRACY:
                        roll = random.uniform(0.0, 100.0)
                        if roll > country.approval_rating:
                            self.log_event(f"❌ {country_name}の指導部が{target_name}との国家統合を試みましたが、国民投票および議会で反対多数により否決され、統合は白紙となりました。")
                            self.sys_logs_this_turn.append(f"[{country_name} 統合否決] 乱数 {roll:.1f} > 支持率 {country.approval_rating:.1f}")
                            continue # 次のdiplomatic policyへ
                        else:
                            self.sys_logs_this_turn.append(f"[{country_name} 統合承認] 乱数 {roll:.1f} <= 支持率 {country.approval_rating:.1f}")

                    self._handle_peaceful_annexation(target_name, country_name)
                    # 統合された国はすでにself.state.countriesから削除されているため、これ以上ループを進めない
                    break

    def _process_trade_and_sanctions(self):
        # 期限切れ提案のクリア（1ターンのみ有効）
        self.state.pending_summits = [s for s in self.state.pending_summits if s not in self.summits_to_run_this_turn]
        
        # 同盟提案の期限切れクリア（同ターン内で双方合意が成立しなかった提案を除去）
        # ※同ターン内で双方がpropose_allianceした場合は _process_diplomacy_and_espionage 内で既に処理済み
        # 残った提案は次ターンまで保持し、次ターンの _process_diplomacy_and_espionage で再度チェックされる
        # 2ターン以上放置された提案はここでクリアする（pending_alliances は翌ターンの処理前にリセット）
        
        # 当期のNXをリセット
        for c_name, country in self.state.countries.items():
            country.last_turn_nx = 0.0

        # Trade (IS Balance / Trade Deficit Model)
        # まず全国家のISバランス(貯蓄・投資バランス)を算出
        macro_balances = {}
        
        for c_name, country in self.state.countries.items():
            dom = self.turn_domestic_factors.get(c_name, {})
            inv_welfare = dom.get("inv_wel", 0.0)
            inv_economy = dom.get("inv_econ", 0.0)
            # engine.py内での統一を図るため、ここでは新モデルに合わせて再度S, I, G, Tを推定
            
            # 1. 貯蓄率 (S) ※_process_domestic と同一の式を使用（ARCHITECTURE.md §2.2 準拠）
            base_s_rate = AUTHORITARIAN_BASE_SAVING_RATE if country.government_type == GovernmentType.AUTHORITARIAN else DEMOCRACY_BASE_SAVING_RATE
            s_rate = max(0.15, base_s_rate - (inv_welfare * 0.15))
            
            # 簡略化のため、ISバランスの評価式に用いる名目上の算出
            # (S - I) + (T - G) = NX
            T = country.economy * country.tax_rate
            # G は前ターンの投資合計割合を予算に掛けたものと推定する
            G = country.government_budget * dom.get("total_inv", 1.0)
            
            C = (country.economy - T) * (1.0 - s_rate)
            S_private = max(0.0, (country.economy - T) - C) # 民間貯蓄
            
            # I は民間貯蓄の85% + インフラ投資により誘発されると仮定
            I = max(0.0, S_private * 0.85 + (G * inv_economy * GOVERNMENT_CROWD_IN_MULTIPLIER))
            
            # IS方程式に基づく経常収支(NX)理論値
            nx_theoretical = (S_private - I) + (T - G)
            macro_balances[c_name] = nx_theoretical

        for trade in self.state.active_trades:
            if trade.country_a not in self.state.countries or trade.country_b not in self.state.countries:
                continue
            ca = self.state.countries[trade.country_a]
            cb = self.state.countries[trade.country_b]
            rel = self._get_relation(trade.country_a, trade.country_b)
            friction = TRADE_GRAVITY_FRICTION_ALLIANCE if rel == RelationType.ALLIANCE else TRADE_GRAVITY_FRICTION_NEUTRAL
            
            # 重力モデルに基づくベース取引量: 経済規模の平方根に比例、摩擦に反比例
            base_volume = math.sqrt(ca.economy * cb.economy) / friction
            
            # 制裁によるGravity Modelハイブリッド介入
            sanctions_exist = any(s for s in self.state.active_sanctions if 
                                 (s.imposer == trade.country_a and s.target == trade.country_b) or
                                 (s.imposer == trade.country_b and s.target == trade.country_a))
            if sanctions_exist:
                base_volume *= 0.05 # 制裁中は貿易額が95%減少
            
            nx_a = macro_balances[trade.country_a]
            nx_b = macro_balances[trade.country_b]
            
            # 【SNA基準への改修】絶対額の差分ではなく、GDPに対する収支比率の差分を用いる（スケール・バイアスの解消）
            nx_ratio_a = nx_a / max(1.0, ca.economy)
            nx_ratio_b = nx_b / max(1.0, cb.economy)
            diff_ratio = nx_ratio_a - nx_ratio_b
            
            # 【学術的適正化】係数を15.0から0.5へ大幅に下方修正。
            # 貯蓄・投資バランスの差が二国間不均衡に与える影響度（弾力性）を現実的な範囲に収める。
            raw_transfer = diff_ratio * base_volume * 0.5
            
            # 物理的限界のガードレール: 赤字転移額は二国間の貿易総量(base_volume)を超えない
            transfer_capped_by_volume = max(-base_volume, min(base_volume, raw_transfer))
            
            # マクロ経済的ガードレール (サドン・ストップ防止): 1ターンの流出は相手国/自国のGDPの3%を上限とする
            # (IMF等の5%ルールに基づき、四半期ベースで3%＝年率約12%を「歴史的最大級のショック」として設定)
            limit_a = ca.economy * 0.03
            limit_b = cb.economy * 0.03
            deficit_transfer = max(-limit_a, min(limit_b, transfer_capped_by_volume))
            
            mutual_bonus = base_volume * 0.005 # 貿易による共通の経済効率化ボーナス
            
            # 【SNA基準への改修】GDP(economy)からの直接減算を廃止。
            # 純輸出(NX)を記録し、赤字分は国家債務に追加
            ca_nx = mutual_bonus + deficit_transfer
            cb_nx = mutual_bonus - deficit_transfer
            
            ca.last_turn_nx += ca_nx
            cb.last_turn_nx += cb_nx
            
            # 赤字国は資金不足を海外からの借入（対外債務）で補う
            if ca_nx < 0:
                ca.national_debt += abs(ca_nx)
            if cb_nx < 0:
                cb.national_debt += abs(cb_nx)
            
            # 支持率の基礎ボーナス（貿易による相互利益）
            ca_support = 0.5
            cb_support = 0.5
            if deficit_transfer > 0:
                # Bが赤字（安い輸入品の恩恵）
                cb_support = 1.0
            else:
                # Aが赤字
                ca_support = 1.0
                
            if trade.country_a in self.turn_domestic_factors:
                self.turn_domestic_factors[trade.country_a]["trade_support_bonus"] += ca_support
            if trade.country_b in self.turn_domestic_factors:
                self.turn_domestic_factors[trade.country_b]["trade_support_bonus"] += cb_support
                
            self.sys_logs_this_turn.append(
                f"[Trade IS Balance] {trade.country_a} vs {trade.country_b} | "
                f"Volume:{base_volume:.1f}, NX_Ratio Diff(A-B):{diff_ratio:+.2%} -> "
                f"{trade.country_a} ({ca_nx:+.1f} GDP_NX, Debt {ca.national_debt:.1f}, {ca_support:+.1f}% Support), "
                f"{trade.country_b} ({cb_nx:+.1f} GDP_NX, Debt {cb.national_debt:.1f}, {cb_support:+.1f}% Support)"
            )
            
        # 各国の総貿易収支(NX)による支持率ペナルティ評価
        for c_name, country in self.state.countries.items():
            if country.last_turn_nx < 0:
                # 国全体で赤字
                country.trade_deficit_counter += 1
                if country.trade_deficit_counter > 3:
                    # ペナルティ上限を3%に緩和
                    penalty = min(3.0, (country.trade_deficit_counter - 3) * 1.0)
                    if c_name in self.turn_domestic_factors:
                        self.turn_domestic_factors[c_name]["trade_support_bonus"] -= penalty
                    self.sys_logs_this_turn.append(f"[Trade Penalty] {c_name} は全体的な貿易赤字による国内産業空洞化で支持率低下(-{penalty:.1f}%)")
            else:
                # 単年度黒字ならカウンターを減少（またはリセット）
                country.trade_deficit_counter = max(0, country.trade_deficit_counter - 1)
            
        # Sanctions (Damage Model)
        for sanction in self.state.active_sanctions:
            if sanction.imposer not in self.state.countries or sanction.target not in self.state.countries:
                continue
            imposer = self.state.countries[sanction.imposer]
            target = self.state.countries[sanction.target]
            
            # 制裁ダメージ: max 10%デバフ。2.0 * (imposer / target)
            ratio = imposer.economy / max(1.0, target.economy)
            damage_percent = min(10.0, 2.0 * ratio)
            
            target.economy *= (1.0 - damage_percent / 100.0)
            imposer.economy *= 0.99 # 発動国も1%の経済遅滞ダメージを受ける
            
            # 制裁による支持率ペナルティ（ARCHITECTURE.md §2.3 準拠）
            target_approval_penalty = min(5.0, 1.0 * ratio)  # 対象国: GDP比率に応じて最大5%低下
            imposer_approval_penalty = 0.5  # 発動国: 常に0.5%低下
            target.approval_rating = max(0.0, target.approval_rating - target_approval_penalty)
            imposer.approval_rating = max(0.0, imposer.approval_rating - imposer_approval_penalty)
            self.sys_logs_this_turn.append(
                f"[制裁ダメージ] {sanction.imposer} -> {sanction.target} | "
                f"経済デバフ: -{damage_percent:.1f}% (発動国: -1.0%) | "
                f"支持率ペナルティ: 対象国 -{target_approval_penalty:.1f}%, 発動国 -{imposer_approval_penalty:.1f}%"
            )

    def _process_espionage(self, attacker_name: str, target_name: str, action):
        attacker = self.state.countries[attacker_name]
        target = self.state.countries[target_name]
        
        # 諜報力の定義（intelligence_levelベース）
        attacker_intel = attacker.intelligence_level
        target_intel = target.intelligence_level
        intel_ratio = (attacker_intel - target_intel) / max(1.0, target_intel)
        
        if action.espionage_sabotage:
            # 破壊工作の判定
            # 成功率 (基本15%、キャップなし)
            sabotage_success_base = 0.15 + (intel_ratio * 0.15)
            sabotage_success_chance = max(0.05, sabotage_success_base)
            is_success = random.random() < sabotage_success_chance
            
            # 発覚率 (基本25%、能力差で変動、下限のみ)
            sabotage_discovery_base = 0.25 - (intel_ratio * 0.20)
            discovery_chance = max(0.05, sabotage_discovery_base)
            is_discovered = random.random() < discovery_chance
            
            strategy = action.espionage_sabotage_strategy.lower()
            
            if is_success:
                dmg_approval = random.uniform(5.0, 15.0)
                dmg_econ_multiplier = 0.95
                
                if any(k in strategy for k in ["sns", "情報", "フェイク", "デマ", "世論", "プロパガンダ", "インフル", "選挙", "メディア", "認知戦"]):
                    dmg_approval = random.uniform(10.0, 20.0)
                    dmg_econ_multiplier = 0.98
                    self.log_event(f"📱 {target_name}のネット空間や社会で大規模な混乱や不審な世論操作の痕跡が確認され、政権支持率が急落しています。")
                elif any(k in strategy for k in ["インフラ", "爆破", "物理", "暗殺", "テロ", "マルウェア", "ハッキング", "システム", "電力", "サイバー", "通信", "ネットワーク"]):
                    dmg_econ_multiplier = 0.90
                    dmg_approval = random.uniform(2.0, 6.0)
                    self.log_event(f"💻 {target_name}の社会インフラ・主要システムに原因不明の重大な障害が発生しました。")
                else:
                    self.log_event(f"💣 {target_name}で社会不安を高める不審な事件が連続して発生しています。")
                    
                target.approval_rating = max(0.0, target.approval_rating - dmg_approval)
                target.economy *= dmg_econ_multiplier
                attacker.hidden_plans += f" [工作成果: {target_name}に対して「{action.espionage_sabotage_strategy}」を実行し、社会不安を煽ることに成功した。継続して弱体化を狙う]"
                
                # 破壊工作成功時、SNS投稿（偽情報・体制批判）を作成するためのリクエストをキューに追加
                self.pending_sabotage_requests.append({
                    "attacker": attacker_name,
                    "target": target_name,
                    "target_hidden_plans": target.hidden_plans,
                    "strategy": action.espionage_sabotage_strategy
                })

            # 発覚処理
            if is_discovered:
                if is_success:
                    self.log_event(f"🚨 【重大事態】{target_name}を襲った一連の事件について、当局の捜査により{attacker_name}の工作機関による関与であったことが特定され、白日の下に晒されました！")
                else:
                    self.log_event(f"🚨 【工作未遂・発覚】{target_name}の防諜機関が、{attacker_name}による工作計画「{action.espionage_sabotage_strategy}」を未然に阻止し、大々的に摘発しました！")
            else:
                if not is_success:
                     # 失敗かつ未発覚：相手のニュースにも自国のニュースにも出ない扱いとし、エージェントの思考ループを防ぐためプロンプトにはフィードバックしない
                     pass
                     # attacker.hidden_plans += f" [工作失敗（未発覚）: {target_name}への「{action.espionage_sabotage_strategy}」は決定打に欠け、目立った成果を上げられなかった。幸い相手には気づかれていない。]"

        if action.espionage_gather_intel:
            # 情報収集の判定
            # 成功率 (基本30%、キャップなし)
            intel_success_base = 0.30 + (intel_ratio * 0.15)
            intel_success_chance = max(0.15, intel_success_base)
            is_success = random.random() < intel_success_chance

            # 発覚率 (基本10%、下限のみ)
            intel_discovery_base = 0.10 - (intel_ratio * 0.10)
            discovery_chance = max(0.05, intel_discovery_base)
            is_discovered = random.random() < discovery_chance
            
            if is_success:
                # 秘密裏の成功・発覚に関わらず、レポートは生成するためRequestに積む
                self.pending_intel_requests.append({
                    "attacker": attacker_name,
                    "target": target_name,
                    "target_hidden_plans": target.hidden_plans,
                    "strategy": action.espionage_intel_strategy or "相手の秘密計画や弱点を探れ"
                })
            else:
                # 失敗かつ未発覚：エージェントの思考ループを防ぐためプロンプトにはフィードバックしない
                pass
                # attacker.hidden_plans += f" [情報収集失敗（未発覚）: {target_name}に対する情報収集作戦は難航しており、有用な情報は得られなかった。]"

            # 発覚処理
            if is_discovered:
                if is_success:
                    self.log_event(f"🚨 【情報漏洩発覚】{target_name}の政府システムや要人周辺から、{attacker_name}へと何らかの機密情報が流出していた痕跡が発見されました。")
                else:
                    self.log_event(f"🚨 【スパイ摘発】{attacker_name}の諜報員が{target_name}にて機密情報を探っていたところを現地当局に発見され、強制排除されました。情報の流出は阻止されました。")


    def _process_wars(self):
        surviving_wars = []
        
        for war in self.state.active_wars:
            aggressor = self.state.countries.get(war.aggressor)
            defender = self.state.countries.get(war.defender)
            
            if not aggressor or not defender:
                continue # 国が既に滅亡している等
                
            # ダメージ計算
            # 防衛側ボーナス
            def_power = defender.military * DEFENDER_ADVANTAGE_MULTIPLIER
            agg_power = aggressor.military
            
            # お互いへの軍事ダメージ（相手戦力の10%程度）
            agg_damage = def_power * random.uniform(0.05, 0.15)
            def_damage = agg_power * random.uniform(0.05, 0.15)
            
            aggressor.military = max(0.0, aggressor.military - agg_damage)
            defender.military = max(0.0, defender.military - def_damage)
            
            # 経済デバフ（戦争状態による疲弊）
            aggressor.economy *= 0.98
            defender.economy *= 0.98
            # 支持率デバフ（長引く戦争の不満）
            aggressor.approval_rating -= 1.0
            defender.approval_rating -= 1.5 # 防戦の被害実感
            
            # 占領進捗率の更新 (戦力差による)
            # 攻撃側が圧倒していれば進捗が進む。防衛側が押し返せば進捗が下がる（マイナスにはならないよう処理）
            power_diff = agg_power - def_power
            progress_change = power_diff / max(1, def_power) * 5.0 # 例: 戦力が2倍なら毎ターン+5%以上
            
            war.target_occupation_progress = max(0.0, min(100.0, war.target_occupation_progress + progress_change))
            
            self.log_event(
                f"🔥 【戦況報告】{war.aggressor} vs {war.defender} | "
                f"占領進捗: {war.target_occupation_progress:.1f}% "
                f"(両軍に損害発生: A軍残{aggressor.military:.0f} / D軍残{defender.military:.0f})"
            )
            
            # 敗北判定
            war_ended = False
            if war.target_occupation_progress >= 100.0 or defender.military < 1.0:
                self._handle_defeat(defender.name, aggressor.name)
                war_ended = True
            elif aggressor.military < 1.0:
                self._handle_defeat(aggressor.name, defender.name)
                war_ended = True
                
            if not war_ended:
                surviving_wars.append(war)
                
        self.state.active_wars = surviving_wars

    def _handle_defeat(self, loser_name: str, winner_name: str):
        loser = self.state.countries[loser_name]
        winner = self.state.countries[winner_name]
        
        self.log_event(f"💀 【国家崩壊】{loser_name}の政府は崩壊し、{winner_name}に対して無条件降伏しました！")
        
        # 併合ボーナス (経済力の吸収)
        winner.economy += loser.economy * 0.5
        winner.military += loser.military * 0.2
        winner.population += loser.population
        winner.initial_population += loser.initial_population
        self.log_event(f"📈 {winner_name}は{loser_name}の領土と人口({loser.population:.1f}M)を併合しました。")
        
        # 敗戦国を世界から削除
        del self.state.countries[loser_name]
        
        # 関連するデータのクリーンアップ
        
        # 1. 関連する戦争も終了させる
        self.state.active_wars = [w for w in self.state.active_wars if w.aggressor != loser_name and w.defender != loser_name]
        
        # 2. 貿易協定の破棄
        self.state.active_trades = [t for t in self.state.active_trades if t.country_a != loser_name and t.country_b != loser_name]
        
        # 3. 経済制裁の解除
        self.state.active_sanctions = [s for s in self.state.active_sanctions if s.imposer != loser_name and s.target != loser_name]
        
        # 4. 保留中の提案（会談・同盟・統合）の削除
        self.state.pending_summits = [s for s in self.state.pending_summits if s.proposer != loser_name and s.target != loser_name]
        self.state.pending_alliances = [a for a in self.state.pending_alliances if a.proposer != loser_name and a.target != loser_name]
        self.state.pending_annexations = [a for a in self.state.pending_annexations if a.proposer != loser_name and a.target != loser_name]
        
        # 5. 技術革新の原産国が敗北した場合（必要に応じて）
        for bt in self.state.active_breakthroughs:
            if bt.origin_country == loser_name:
                # 原産国が滅んでも技術自体は普及し続ける可能性があるが、ここでは伝播を維持し、原産国の表示のみ考慮
                pass

    def _handle_peaceful_annexation(self, absorber_name: str, absorbed_name: str):
        absorber = self.state.countries[absorber_name]
        absorbed = self.state.countries[absorbed_name]
        
        self.log_event(f"🕊️ 【国家統合】歴史的合意に基づき、{absorbed_name}は国家を解散し、{absorber_name}と平和的に統合しました！")
        
        # 併合ボーナス (リソースの完全引継ぎ)
        absorber.economy += absorbed.economy
        absorber.military += absorbed.military
        absorber.population += absorbed.population
        absorber.initial_population += absorbed.initial_population
        # 行政の効率化・技術の統合：諜報や教育は（平均ではなく）高い方をベースにボーナスを加える等も考えられるが、ここでは現状を維持しつつ少し微増させる
        absorber.intelligence_level = max(absorber.intelligence_level, absorbed.intelligence_level) + 1.0
        
        # 国債の引継ぎ
        absorber.national_debt += absorbed.national_debt
        
        self.log_event(f"📈 {absorber_name}は{absorbed_name}の全領土、インフラ、そして市民を迎え入れ、新たな大国家として生まれ変わりました。")
        
        # 吸収された国を世界から削除
        del self.state.countries[absorbed_name]
        
        # 関連するデータのクリーンアップ
        self.state.active_wars = [w for w in self.state.active_wars if w.aggressor != absorbed_name and w.defender != absorbed_name]
        self.state.active_trades = [t for t in self.state.active_trades if t.country_a != absorbed_name and t.country_b != absorbed_name]
        self.state.active_sanctions = [s for s in self.state.active_sanctions if s.imposer != absorbed_name and s.target != absorbed_name]
        self.state.pending_summits = [s for s in self.state.pending_summits if s.proposer != absorbed_name and s.target != absorbed_name]
        self.state.pending_alliances = [a for a in self.state.pending_alliances if a.proposer != absorbed_name and a.target != absorbed_name]
        self.state.pending_annexations = [a for a in self.state.pending_annexations if a.proposer != absorbed_name and a.target != absorbed_name]


    from models import DisasterEvent
    def _process_random_events(self):
        """災害イベントおよび技術革新の発生を処理する"""
        from models import DisasterEvent, BreakthroughState
        
        # 技術革新の進行更新
        for bt in self.state.active_breakthroughs:
            if not bt.spread_globally:
                bt.turns_active += 1
                if bt.turns_active >= 4:
                    bt.spread_globally = True
                    self.log_event(f"💡 【技術波及】{bt.origin_country}発の技術革新「{bt.name}」が世界中に普及し、世界経済の底上げに寄与し始めました。")
        
        # ------------- 災害 -------------
        # 1. 世界規模災害
        global_disasters = [
            ("パンデミック", 0.015, 3.0, 5.0),
            ("巨大太陽フレア", 0.008, 1.0, 10.0),
            ("超巨大火山噴火 (VEI 7)", 0.001, 5.0, 15.0),
            ("巨大隕石落下", 0.00001, 10.0, 50.0),      # 0.001%
            ("破局噴火 (VEI 8)", 0.0000005, 10.0, 30.0) # 0.00005%
        ]
        
        for name, prob, min_dmg, max_dmg in global_disasters:
            if random.random() < prob:
                # 歪正規分布を用いてダメージを決定。a=4は正の歪み（低い値が多く、稀に高い値）
                a = 4
                damage = skewnorm.rvs(a, loc=min_dmg, scale=max_dmg)
                damage = max(min_dmg, damage)
                new_event = DisasterEvent(turn=self.state.turn, name=name, damage_percent=damage)
                self.state.disaster_history.append(new_event)
                self.log_event(f"🚨 【世界規模の厄災発生】{name}が発生！世界全体で推定 -{damage:.1f}% の経済ダメージによる大混乱が起きています。")
                break # 一度に複数起きる確率は無視する（処理軽減）
                
        # 2. 国規模災害
        national_disasters = [
            ("巨大地震", 0.030, 1.0, 5.0),
            ("超大型台風/ハリケーン", 0.080, 0.5, 2.0),
            ("大干ばつ", 0.050, 0.5, 1.5),
            ("火山噴火 (VEI 4)", 0.154, 0.5, 1.0),
            ("火山噴火 (VEI 5)", 0.015, 1.0, 3.0),
            ("大噴火 (VEI 6)", 0.0025, 10.0, 20.0)
        ]
        
        EARTH_LAND_AREA = 148940000.0
        
        for country_name in list(self.state.countries.keys()):
            country = self.state.countries[country_name]
            for name, prob, min_dmg, max_dmg in national_disasters:
                actual_prob = prob
                if "火山噴火" in name or "大噴火" in name:
                    area_ratio = country.area / EARTH_LAND_AREA
                    actual_prob = prob * area_ratio
                    
                if random.random() < actual_prob:
                    # 歪正規分布を用いてダメージを決定。a=4は正の歪み（低い値が多く、稀に高い値）
                    a = 4
                    damage = skewnorm.rvs(a, loc=min_dmg, scale=max_dmg)
                    damage = max(min_dmg, damage)
                    new_event = DisasterEvent(turn=self.state.turn, country=country_name, name=name, damage_percent=damage)
                    self.state.disaster_history.append(new_event)
                    self.log_event(f"🌪️ 【国家災害発生】{country_name}で{name}が直撃し、-{damage:.1f}% に相当する経済ダメージを受けました！")
                    break # 同一国内で複数同時被災は無視
                    
        # ------------- 技術革新 -------------
        # 技術革新は各国 2.0%の確率で発生。ただし進行中は同国で連続発生しづらくする
        for country_name in list(self.state.countries.keys()):
            if any(bt.origin_country == country_name and not bt.spread_globally for bt in self.state.active_breakthroughs):
                continue # すでに独占的な技術革新中
                
            if random.random() < 0.020:
                # 発生フラグを立て、技術名は main.py 側の agent ループか専用エージェントで生成するため予約する
                # ここでは仮の名前を入れ、あとで_update_breakthrough_names()等でAgentから更新する前提（あるいはAgentをこのクラスに繋ぐ）
                # 今回は main.py の process_turn 実行後に AgentSystem を叩くためのメタデータを self に持たせるのがスマート
                # または仮の技術名で BreakthroughState を作成し、後続処理で上書きする。
                new_bt = BreakthroughState(
                    origin_country=country_name, 
                    name=f"（AI生成待ちの技術革新 - T{self.state.turn}）", 
                    turns_active=0, 
                    spread_globally=False
                )
                self.state.active_breakthroughs.append(new_bt)
                # ログはAgentが名前を生成した際に main.py 等で出力させる仕組みにするため、ここでは簡素にする。
                self.sys_logs_this_turn.append(f"[{country_name}] 技術革新フラグが立ちました")

    def _handle_election(self, country_name: str, country: CountryState):
        """
        民主主義国家の大統領選挙の論理を処理する
        """
        import random
        roll = random.uniform(0.0, 100.0)
        self.log_event(f"🗳️ {country_name}で国家元首の総選挙が実施されました。(現在の与党支持率: {country.approval_rating:.1f}%)")
        
        if roll <= country.approval_rating:
            # 再選
            self.log_event(f"✅ 【選挙結果】{country_name}の現政権が過半数の信任を得て再選を果たしました！")
            self.sys_logs_this_turn.append(f"[{country_name} 選挙] 乱数 {roll:.1f} <= 支持率 {country.approval_rating:.1f} により再選")
        else:
            # 敗北（政権交代）
            self.log_event(f"🔄 【政権交代】{country_name}の選挙で現政権が敗北し、新たな指導者が選出されました。")
            self.sys_logs_this_turn.append(f"[{country_name} 選挙] 乱数 {roll:.1f} > 支持率 {country.approval_rating:.1f} により落選")
            
            # 敗北時の新政権の支持率は期待値として 100.0 - Approval にリセット（Option C準拠）
            new_approval = max(0.0, min(100.0, 100.0 - country.approval_rating))
            country.approval_rating = new_approval
            self.sys_logs_this_turn.append(f"[{country_name} 新政権] 新たなハネムーン期間として支持率が {new_approval:.1f}% にリセットされました。")
            country.regime_duration = 0  # 選挙での政権交代によりリセット

    def _handle_rebellion(self, country_name: str, country: CountryState):
        """国家崩壊（クーデター・革命）の処理。Alesina-Spolaoreモデルに基づく分裂判定を含む"""
        
        # --- 1. 分裂(Fragmentation)の判定 ---
        
        # 基礎不安定性 (どれだけマイナスまで支持率が振り切れていたか等の不満度。0-100程度)
        base_instability = max(0.0, 30.0 - country.approval_rating) + min(100.0, country.rebellion_risk)
        
        # 面積（国土規模）による多様性/異質性コスト（Alesina-Spolaore: サイズによる分裂圧力）
        # ※ここでは面積の絶対値をベースに係数をかける（最大+30%程度）
        size_factor = min(30.0, country.area * 0.05)
        
        # 自由貿易の恩恵（Alesina-Spolaore: 貿易網が発達しているほど小国が生き返りやすいため分裂圧力増）
        # 対象国が結んでいる貿易協定の数をカウント
        trade_count = sum(1 for t in self.state.active_trades if t.country_a == country_name or t.country_b == country_name)
        trade_factor = trade_count * 5.0 # 1つにつき+5%
        
        # 分裂確率 P_frag
        p_frag = min(100.0, (base_instability * 0.2) + size_factor + trade_factor)
        
        # 民主主義の場合は武力弾圧を行わないため相対的に分裂のハードルが低い(平和的独立)
        if country.government_type == GovernmentType.DEMOCRACY:
            p_frag += 10.0
        else: # 専制主義は流血を辞さず抑え込むため分裂発生率はやや低い
            p_frag -= 10.0
            
        p_frag = max(0.0, min(100.0, p_frag))
        
        is_fragmentation = random.uniform(0.0, 100.0) < p_frag
        
        if is_fragmentation:
            self._execute_fragmentation(country_name, country, base_instability)
            return

        # --- 2. 通常のクーデター（政権交代のみ） ---
        self.log_event(f"🔄 【政権交代】{country_name}にてクーデターが成功し、新政府が樹立されました！")
        
        # 【Option C】クーデター後の経済の立て直し（基本GDPのリセット＝悪循環の底打ち）
        # 旧政権の負債や非効率さをリセットし、新たなベースラインを設定する。
        # クーデターまでの経済ダメージは維持するが、そこからの再出発を保障する。
        # （ここではGDP自体を底上げするのではなく、経済成長ペナルティをリセットする意味合いで、
        #   政府予算の強制補充や税率の一時的適正化を行う）
        country.economy = max(10.0, country.economy * 0.9) # 内戦による経済ダメージ（10%減）
        country.military = max(0.5, country.economy * 0.1)  # 軍事力をGDPの10%にリセット
        country.government_budget = country.economy * 0.1 # 緊急予算の確保
        country.tax_rate = 0.3 # 標準税率へ一旦リセット
        
        # 政府支持率の反転 (100% - 旧支持率) 
        # 低い支持率で倒れた政府の交代劇であるほど、初期の熱狂（ハネムーン期間）が高くなる
        country.approval_rating = max(50.0, 100.0 - country.approval_rating)
        country.rebellion_risk = 0.0
        country.regime_duration = 0 # クーデター成立によりリセット
        
        # 専制・独裁は民主化するかどうかの分岐
        if country.government_type == GovernmentType.AUTHORITARIAN:
            if random.random() < 0.3: # 30%で民主化
                country.government_type = GovernmentType.DEMOCRACY
                country.turns_until_election = 16
                self.log_event(f"🕊️ {country_name}は民主化宣言を行いました！新政権は初の自由選挙に向けた準備を進めています。")
            else:
                self.log_event(f"🛡️ {country_name}では新たな軍事政権が実権を握り、引き続き強権的な統治が続きます。")
        else:
            # 民主主義が崩壊した場合、軍事政権化する可能性
            if random.random() < 0.4:
                country.government_type = GovernmentType.AUTHORITARIAN
                country.turns_until_election = None
                self.log_event(f"⚔️ {country_name}の混乱に乗じて軍部が蜂起！民主政権は崩壊し、専制主義国家への道を歩み始めました。")
            else:
                self.log_event(f"🗳️ {country_name}で臨時政府が樹立され、早期の総選挙が約束されました。")
                country.turns_until_election = 4
        
        # イデオロギーの刷新（非同期処理のため、メインループの「AIプロンプト」フェーズでAgentが思考する。
        # ここではフラグだけを立て、ログは出さない。プロンプトへの渡し方はagent.py側の責任とする）
        country.ideology = f"[新政権樹立フェーズ] 旧政権({country.ideology})を打倒した新政府の指針を策定中"
        
        # 秘密計画の破棄とターゲットのリセット
        country.hidden_plans = "政権交代により過去の計画はすべて白紙撤回された。新たな国家戦略を立案せよ。"

        # 案C: クーデター時の「死のループ」を防ぐため、旧政権の負の遺産・基準となるペナルティをリセット
        country.national_debt = 0.0
        country.trade_deficit_counter = 0
        country.last_turn_nx = 0.0
        country.rebellion_risk = 0.0
        country.intelligence_level = 0.0  # 諜報組織も崩壊・リセット
        
        self.pending_rebellions.append(country_name)

    def _execute_fragmentation(self, old_name: str, old_country: CountryState, base_instability: float):
        """国家分裂の実行ロジック。最大100%の転覆(乗っ取り)を含む"""
        
        # 1. 離脱(奪取)されるリソース割合の決定
        # 不満度(base_instability: 0~200程度) が高いほど、丸ごとひっくり返る可能性大
        # 通常は20-40%、最悪のクーデターなら70-100%
        mean_split_ratio = min(95.0, 20.0 + (base_instability * 0.4))
        split_ratio = max(10.0, min(100.0, random.gauss(mean_split_ratio, 10.0))) / 100.0
        
        is_overthrow = split_ratio > 0.85 # 85%以上持っていかれたら事実上の国家転覆（旧体制が辺境に追いやられる）
        
        if is_overthrow:
            self.log_event(f"🧨 【国家転覆】度重なる失政と圧政への怒りが爆発！{old_name}におけるクーデターは全土規模の革命へと発展し、国家がひっくり返りました！(国土奪取率: {split_ratio:.1%})")
        else:
            self.log_event(f"💥 【国家分裂】{old_name}にて分離独立運動が激化！政府のコントロールを外れ、一部地域が独立を宣言しました！(離脱率: {split_ratio:.1%})")
            
        # 2. Agentによる新国家名とイデオロギーの生成
        from agent import AgentSystem # ここで動的インポート
        dummy_agent = AgentSystem(None) # 生成用のダミーインスタンス
        
        # ログから市民の不満を探す
        sns_logs = self.turn_sns_logs.get(old_name, [])
        new_name, new_ideology = dummy_agent.generate_fragmentation_profile(old_name, sns_logs)
        
        # （重要）名前の重複チェック
        if new_name == old_name or new_name in self.state.countries:
            new_name = f"新{old_name}共和国"
            
        # 3. リソースの分割
        new_economy = max(1.0, old_country.economy * split_ratio)
        new_military = max(0.5, old_country.military * split_ratio)
        new_area = max(1.0, old_country.area * split_ratio)
        new_debt = old_country.national_debt * split_ratio
        new_population = max(0.1, old_country.population * split_ratio)
        
        # 人的インフラ（教育）の引き継ぎ（無減衰で100%引き継ぎ）
        new_education = old_country.education_level
        new_initial_education = old_country.initial_education_level
        # 組織インフラ（諜報）の分割
        new_intelligence = max(0.0, old_country.intelligence_level * split_ratio)
        
        old_country.economy = max(1.0, old_country.economy - new_economy)
        old_country.military = max(0.5, old_country.military - new_military)
        old_country.area = max(1.0, old_country.area - new_area)
        old_country.national_debt = max(0.0, old_country.national_debt - new_debt)
        old_country.population = max(0.1, old_country.population - new_population)
        old_country.intelligence_level = max(0.0, old_country.intelligence_level - new_intelligence)
        
        if is_overthrow:
             # 事実上の乗っ取りなので新国家が旧体制の借金を帳消し（デフォルト）にすることが多い
             new_debt *= 0.2
             
        # 政体の反転/決定
        new_gov_type = GovernmentType.DEMOCRACY if old_country.government_type == GovernmentType.AUTHORITARIAN else GovernmentType.AUTHORITARIAN
        if random.random() < 0.2: # 20%で偶然同じ政体になる（内ゲバ）
            new_gov_type = old_country.government_type

        # 4. 新国家オブジェクトの生成
        new_country = CountryState(
            name=new_name,
            economy=new_economy,
            military=new_military,
            approval_rating=80.0, # 独立初期の熱狂
            government_type=new_gov_type,
            ideology=new_ideology,
            press_freedom=0.8 if new_gov_type == GovernmentType.DEMOCRACY else 0.2,
            target_country=old_name, # 当面は旧国を強く意識
            area=new_area,
            population=new_population,
            initial_population=new_population,
            education_level=new_education,
            initial_education_level=max(1.0, new_initial_education), # 0割りを防ぐ
            intelligence_level=new_intelligence
        )
        new_country.national_debt = new_debt
        if new_gov_type == GovernmentType.DEMOCRACY:
            new_country.turns_until_election = 16
            
        # 世界に追加
        self.state.countries[new_name] = new_country
        
        # 5. 外交関係（平和的独立か、内戦か）
        if old_country.government_type == GovernmentType.DEMOCRACY:
            # Velvet Divorce（平和的独立）
            self.log_event(f"🤝 民主的な手続き（住民投票等）により、{new_name}の独立が平和裏に承認されました。旧体制との間に武力衝突はありません。")
            old_country.approval_rating = max(30.0, old_country.approval_rating) # やや落ち着く
        else:
            # Secessionist War（内戦突入）
            self.log_event(f"⚔️ 【独立戦争勃発】{old_name}の独裁体制は独立を許さず、直ちに{new_name}に対する武力鎮圧を開始！凄惨な内戦に突入しました！")
            war = WarState(
                id=str(uuid.uuid4()),
                aggressor=old_name,
                defender=new_name,
                turn_started=self.state.turn,
                target_occupation_progress=0.0
            )
            self.state.active_wars.append(war)
            
        # もし100%乗っ取られて旧政権のリソースが微小（1.0未満）になった場合、事実上の滅亡処理
        if old_country.economy <= 1.5 or old_country.military <= 1.0:
             self._handle_defeat(old_name, new_name)
             self.log_event(f"☠️ 【旧体制消滅】リソースのほぼ全てを掌握した{new_name}により、旧体制({old_name})は完全に歴史から抹消されました。")

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

    # ヘルパー関数
    def _get_relation(self, c1: str, c2: str) -> RelationType:
        if c1 not in self.state.relations:
            self.state.relations[c1] = {}
        if c2 not in self.state.relations[c1]:
            self.state.relations[c1][c2] = RelationType.NEUTRAL
        return self.state.relations[c1][c2]

    def _update_relation(self, c1: str, c2: str, rel: RelationType):
        if c1 not in self.state.relations:
            self.state.relations[c1] = {}
        if c2 not in self.state.relations:
            self.state.relations[c2] = {}
        self.state.relations[c1][c2] = rel
        self.state.relations[c2][c1] = rel

    def evaluate_public_opinion(self, timelines: Dict[str, List[Dict[str, str]]], media_modifiers: Dict[str, float]):
        """
        全国のSNSタイムライン（投稿リスト）およびメディア影響を受け取り、
        加重移動平均（WMA）モデルを用いて最終的な支持率を計算・適用する。
        timelines: { "国名": [ {"author": "Citizen/Leader/Espionage", "text": "投稿内容"} ] }
        """
        for country_name, posts in timelines.items():
            country = self.state.countries[country_name]
            sns_history = []
            total_sns_modifier = 0.0
            censored_count = 0
            
            for post_item in posts:
                author = post_item["author"]
                text = post_item["text"]
                
                scores = self.analyzer.analyze(text)
                avg_score = sum(scores) / len(scores) if scores else 0.0
                
                # スコアを-2.0〜+2.0程度にスケール。マイルドにするため0.8倍
                post_modifier = avg_score * 1.6 
                
                is_censored = False
                if country.government_type == GovernmentType.AUTHORITARIAN:
                    # 首脳の投稿は検閲しない
                    if author != "Leader":
                        # 専制主義はネガティブな発言を検閲
                        if post_modifier < -0.3:
                            is_censored = True
                            post_modifier = 0.0 # 支持率低下を免れる
                            # 国民の投稿が検閲された場合のみフラストレーションが蓄積
                            if author == "Citizen":
                                censored_count += 1
                
                # 各投稿の感情スコアをシステムログに出力
                censor_tag = " [検閲]" if is_censored else ""
                self.sys_logs_this_turn.append(f"[{country_name} SNS] {author}: score={avg_score:+.2f} modifier={post_modifier:+.2f}{censor_tag} | {text[:50]}")
                
                # Leader投稿は支持率に影響させない（自己操作防止）
                if not is_censored and author != "Leader":
                    total_sns_modifier += post_modifier
                    
                sns_history.append({
                    "author": author,
                    "post": text,
                    "score": avg_score,
                    "censored": is_censored
                })
                
            # 支持率への影響をマイルドに制限（最大+-3.0%）
            total_sns_modifier = max(-3.0, min(3.0, total_sns_modifier))
                
            # ログ保存
            if country_name not in self.state.sns_logs:
                self.state.sns_logs[country_name] = []
            self.state.sns_logs[country_name].append({
                "turn": self.state.turn,
                "posts": sns_history,
                "total_modifier": total_sns_modifier,
                "censored_count": censored_count
            })
            
            # --- WMA (Weighted Moving Average) による支持率計算 ---
            dom = self.turn_domestic_factors.get(country_name, {})
            gdp_growth = dom.get("gdp_growth_rate", 0.0)
            welfare_bonus = dom.get("welfare_bonus", 0.0)
            trade_bonus = dom.get("trade_support_bonus", 0.0)
            media_mod = media_modifiers.get(country_name, 0.0)
            
            # WMA Calculation: 
            # Current = Base 50% * 0.2 + Previous * 0.8 + Dynamic Bonuses
            old_approval = country.approval_rating
            base_trend = (old_approval * WMA_HISTORY_WEIGHT) + (WMA_BASE_VALUE * WMA_BASE_WEIGHT)
            
            # 政治疲労 ( पॉलिटिकलフｧティーグ ) による支持率の自然減衰
            # 長期政権化するほど、国民の「飽き」や「蓄積した不満」により減衰圧力が強くなる
            # duration 20ターンで約 -1.5、40ターンで約 -3.5 の強力なペナルティとなる
            duration_factor = (country.regime_duration / 10.0) ** 1.2
            
            # 従来： -0.5 - ((old_approval - 50.0) * 0.01 if old_approval > 50.0 else 0)
            # 変更： 基本的に-0.5をベースとし、長期政権ほど追加デバフ。支持率が高いほどさらに減衰ペースが上がる。
            approval_factor = ((old_approval - 50.0) * 0.03 if old_approval > 50.0 else 0)
            fatigue_decay = -0.5 - duration_factor - approval_factor
            
            # Apply dynamic factors with carefully tuned weights
            growth_modifier = gdp_growth * 0.5
            if gdp_growth < -5.0:
                # 深刻な不況（5%以上のマイナス成長）には非線形なペナルティを課すが、
                # クーデター等の直後に発生する無限死亡ループを防ぐため、1ターンのペナルティ上限を設ける
                penalty = (abs(gdp_growth) - 5.0) ** 1.5
                growth_modifier -= min(30.0, penalty)
                
            new_approval = (
                base_trend 
                + fatigue_decay              # Natural political fatigue decay
                + growth_modifier            # Dynamic GDP growth/collapse modifier
                + (media_mod * 1.0)          # max +-5.0
                + (total_sns_modifier * 0.5) # max +-1.5
                + welfare_bonus              # based on log curve approx -2.0 to +2.5
                + trade_bonus                # from trade benefits or deficit penalties
            )
            
            country.approval_rating = max(0.0, min(100.0, new_approval))
            
            # 検閲による反乱リスクの増加
            if censored_count > 0:
                country.rebellion_risk += censored_count * 1.5
                self.sys_logs_this_turn.append(f"[{country.name} SNS] 一般国民の投稿が{censored_count}件検閲され、反乱リスクが上昇")

            self.sys_logs_this_turn.append(
                f"[{country.name} 支持率更新] {old_approval:.1f}% -> {country.approval_rating:.1f}% "
                f"(内訳: 政治疲労{fatigue_decay:.1f}, GDP成長{growth_modifier:+.1f}, 福祉{welfare_bonus:+.1f}, 貿易恩恵{trade_bonus:+.1f}, メディア{media_mod:+.1f}, SNS世論{total_sns_modifier*0.5:+.1f})"
            )


