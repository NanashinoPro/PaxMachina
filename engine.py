import math
import random
from typing import Dict, List, Tuple
from models import WorldState, CountryState, AgentAction, RelationType, GovernmentType, WarState, TradeState, SanctionState, SummitProposal, AllianceProposal

# --- 定数（プロトコルパラメータ）定義 ---
DEMOCRACY_WARN_APPROVAL = 40.0
CRITICAL_APPROVAL = 15.0
WMA_HISTORY_WEIGHT = 0.8
WMA_BASE_WEIGHT = 0.2
WMA_BASE_VALUE = 50.0
MAX_LOG_HISTORY = 20

# 経済・軍事モデルの定数
BASE_ECONOMIC_GROWTH_RATE = 0.015
MILITARY_CROWDING_OUT_RATE = 0.002
BASE_MILITARY_GROWTH_RATE = 0.015
BASE_MILITARY_MAINTENANCE_ALPHA = 0.03
MAX_MILITARY_FATIGUE_ALPHA = 0.20

# マクロ経済モデル (SNA基準) の新しい定数
BASE_INVESTMENT_RATE = 0.14          # 基礎的な民間投資性向
GOVERNMENT_CROWD_IN_MULTIPLIER = 0.3 # 経済予算が民間投資を誘発する乗数
GOVERNMENT_CROWD_OUT_MULTIPLIER = 0.1# 軍事予算が民間投資を抑制する乗数
TAX_APPROVAL_PENALTY_MULTIPLIER = 200.0 # 増税1%につき支持率が2%低下する係数
DEBT_TO_GDP_PENALTY_THRESHOLD = 1.0  # 債務対GDP比が100%を超えるとペナルティ発生
DEBT_INTEREST_RATE = 0.02            # 国家債務の利払い金利（2%）

# 貿易・マクロ経済モデルの定数
MACRO_TAX_RATE = 0.30 # (旧定数。今後各国の可変 tax_rate で上書き)
DEMOCRACY_BASE_SAVING_RATE = 0.25
AUTHORITARIAN_BASE_SAVING_RATE = 0.30
TRADE_GRAVITY_FRICTION_ALLIANCE = 1.0
TRADE_GRAVITY_FRICTION_NEUTRAL = 2.0

# 戦争モデルの定数
DEFENDER_ADVANTAGE_MULTIPLIER = 1.2
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
        
        # 感情分析器（外部から注入。main.pyでAgentSystemのGeminiSentimentAnalyzerを渡す）
        self.analyzer = analyzer
        self.turn_domestic_factors: Dict[str, Dict[str, float]] = {}

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
        
        # 1. 内政の反映
        for country_name, action in actions.items():
            self._process_domestic(country_name, action)
            
        # 2. 外交・諜報アクションの反映
        for country_name, action in actions.items():
            self._process_diplomacy_and_espionage(country_name, action)
            
        # 3. 貿易と制裁の処理 (Gravity Model & Sanctions Damage applying)
        self._process_trade_and_sanctions()
            
        # 4. 戦争状態の処理
        self._process_wars()
        
        # 5. 内政イベント（選挙・反乱）の判定
        self._process_domestic_events()
        
        # 6. ランダムイベント（災害・技術革新）の判定
        self._process_random_events()
        
        # 7. 時間進行とターン終了処理は外部 (main.py) から advance_time() を呼び出すよう変更
        
        # イベントログをステートに記録
        self.state.news_events = self.events_this_turn.copy()
        
        return self.state

    def _process_domestic(self, country_name: str, action: AgentAction):
        country = self.state.countries[country_name]
        
        # 秘密計画の更新
        if hasattr(action, 'update_hidden_plans') and action.update_hidden_plans:
            country.hidden_plans = action.update_hidden_plans

        # --- 税率調整と政治的コスト（支持率ペナルティ） ---
        old_tax_rate = country.tax_rate
        new_tax_rate = action.domestic_policy.tax_rate
        
        # 税率の異常値を弾く (0.1 ~ 0.7 の範囲内にクランプ)
        new_tax_rate = max(0.10, min(0.70, new_tax_rate))
        country.tax_rate = new_tax_rate
        
        # 増税ペナルティ (税率が上がった場合のみ支持率低下)
        tax_diff = new_tax_rate - old_tax_rate
        if tax_diff > 0:
            penalty = tax_diff * TAX_APPROVAL_PENALTY_MULTIPLIER
            country.approval_rating = max(0.0, country.approval_rating - penalty)
            self.sys_logs_this_turn.append(f"[{country.name} 増税] 税率 {old_tax_rate:.1%}→{new_tax_rate:.1%} (支持率ペナルティ: -{penalty:.1f}%)")
        # ------------------------------------------------

        # --- 政策実行力の算出 ---
        # [学術的根拠] 民主主義国家では低支持率時に議会の攻防が激化し政策実現が困難になる。
        # 専制主義では強権的執行が可能ことから下限を保障（最低ε=0.5）。
        execution_power = 1.0
        if country.government_type == GovernmentType.DEMOCRACY:
            if country.approval_rating < DEMOCRACY_WARN_APPROVAL:
                execution_power = max(0.0, (country.approval_rating - CRITICAL_APPROVAL) / (DEMOCRACY_WARN_APPROVAL - CRITICAL_APPROVAL))
        elif country.government_type == GovernmentType.AUTHORITARIAN:
            if country.approval_rating < 25.0:
                execution_power = max(0.5, 0.5 + (country.approval_rating / 50.0))
        
        # --- マクロ経済モデリング (SNAベース: Y = C + I + G + NX) ---
        old_gdp = country.economy
        
        # 国家債務の利払い (利払い分だけ予算が減る、または債務が増える。ここでは簡単のため予算から天引き想定)
        interest_payment = country.national_debt * DEBT_INTEREST_RATE
        
        # 税収T = GDP * 税率 (※前ターンのGDPをベースにする)
        tax_revenue = old_gdp * country.tax_rate
        
        # 政府予算 (G全体のキャップ)
        # 利払いを差し引いた実質予算 (マイナスにはならない)
        country.government_budget = max(0.0, tax_revenue - interest_payment)
        budget = country.government_budget
        
        # 経済投資
        inv_econ = action.domestic_policy.invest_economy
        inv_mil = action.domestic_policy.invest_military
        inv_wel = action.domestic_policy.invest_welfare
        
        # 予算の総和を1.0に正規化（安全装置）
        total_inv = inv_econ + inv_mil + inv_wel
        if total_inv <= 0.0:
            inv_econ, inv_mil, inv_wel = 0.33, 0.33, 0.34 # 異常時のフォールバック
            total_inv = 1.0
        elif total_inv > 1.0:
            inv_econ /= total_inv
            inv_mil /= total_inv
            inv_wel /= total_inv
            total_inv = 1.0

        # 政府支出(G)のブレイクダウン
        g_econ = budget * inv_econ * execution_power
        g_mil = budget * inv_mil * execution_power
        g_wel = budget * inv_wel * execution_power
        G = g_econ + g_mil + g_wel

        # 基礎貯蓄率 (政治体制と福祉投資による低下)
        base_s_rate = AUTHORITARIAN_BASE_SAVING_RATE if country.government_type == GovernmentType.AUTHORITARIAN else DEMOCRACY_BASE_SAVING_RATE
        saving_rate = max(0.15, base_s_rate - (inv_wel * 0.15))

        # 1. 民間消費 (C)
        # ケインズ型消費関数: C = (Y - T) * (1 - s)
        # 増税すると即座に消費が減る
        C = max(0.0, (old_gdp - tax_revenue) * (1.0 - saving_rate))
        S_private = max(0.0, (old_gdp - tax_revenue) - C)

        # --- SNAマクロ経済モデル: 民間投資 (I) ---
        # [Harrod 1939; Domar 1946] 貯蓄=投資均衡仮定の下、民間貯蓄の一部が
        # 資本市場を通じて国内投資へ還流すると仮定。係数0.85は国内投資率を表し、
        # 残15%は海外流出・現預金積み上げ等として処理。
        # 政府の経済投資は民間投資を誘発（クラウドイン）し、軍事費が民間投資を押し出す（クラウドアウト）。
        I = max(0.0, S_private * 0.85 + (g_econ * GOVERNMENT_CROWD_IN_MULTIPLIER) - (g_mil * GOVERNMENT_CROWD_OUT_MULTIPLIER))
        
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
        breakthrough_multiplier = min(1.30, breakthrough_multiplier)
        
        I *= breakthrough_multiplier

        # 次ターンのGDP(Y)の暫定算出 = C + I + G + NX
        new_gdp_provisional = C + I + G + country.last_turn_nx
        
        # 災害ダメージは当期の経済から直接引く（巨大な資本破壊）
        if disaster_damage_sum > 0:
            damage_amount = old_gdp * (disaster_damage_sum / 100.0)
            new_gdp_provisional -= damage_amount
            approval_penalty = disaster_damage_sum * 0.5
            country.approval_rating = max(0.0, country.approval_rating - approval_penalty)
            self.sys_logs_this_turn.append(f"[{country.name} 災害被害] -{damage_amount:.1f} (支持率 -{approval_penalty:.1f}%)")

        # 債務対GDP比ペナルティ (インフレ・信認低下)
        debt_to_gdp = country.national_debt / max(1.0, old_gdp)
        if debt_to_gdp > DEBT_TO_GDP_PENALTY_THRESHOLD:
            # 100%超過分につき経済にデバフがかかる
            excess = debt_to_gdp - DEBT_TO_GDP_PENALTY_THRESHOLD
            penalty = 1.0 - min(0.05, excess * 0.02) # 最大5%のGDP押し下げ
            new_gdp_provisional *= penalty
            if self.state.turn % 5 == 0:
                 self.sys_logs_this_turn.append(f"[{country.name} 債務超過] 対GDP比{debt_to_gdp:.1%}により経済成長減退")
        
        # 経済力がゼロ以下になるのを防ぐ
        country.economy = max(1.0, new_gdp_provisional)
        
        # 成長率ボーナスの計算 (後で支持率に反映するため。軍事費分は除外して実質体感成長とするなどの計算もあるが、今回は総GDPで)
        gdp_growth_rate = (country.economy - old_gdp) / max(1.0, old_gdp) * 100.0
        
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
        
        # --- 福祉ボーナスによる支持率還元 ---
        # [学術的根拠] 福祈支出の支持率への効果が逓減することを対数関数（log1p）でモデル化。
        # 限界効用逓減の法則 (Gossen 1854) に基づき、一定水準以上の投資は
        # 効果が頭打ちになる。これにより「福祈へ全抜けすれば支持率が無限に上がる」メタ解法を防止。
        inv_wel = action.domestic_policy.invest_welfare
        old_approval = country.approval_rating
        welfare_trend = math.log1p(inv_wel * 5.0) * 1.5 - 1.0
        welfare_bonus = welfare_trend * execution_power
            
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
            f"経済力(GDP):{old_gdp:.1f} -> {country.economy:.1f} ({new_gdp_provisional - old_gdp:+.1f}), "
            f"軍事力:{old_military:.1f} -> {country.military:.1f} (+{military_growth:.1f}, 維持費: -{alpha*100:.1f}%), "
            f"支持率:{old_approval:.1f}% -> {country.approval_rating:.1f}%"
        )

    def _process_diplomacy_and_espionage(self, country_name: str, action: AgentAction):
        country = self.state.countries[country_name]
        
        for dip in action.diplomatic_policies:
            target_name = dip.target_country
            if target_name not in self.state.countries:
                continue
                
            # メッセージ送信（ログに残すだけ）
            if dip.message:
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
                self.state.pending_summits.append(SummitProposal(proposer=country_name, target=target_name, topic=dip.summit_topic))
                self.log_event(f"✉️ {country_name}が{target_name}に対して首脳会談を提案しました。議題: {dip.summit_topic}")

            # 首脳会談の受諾
            if dip.accept_summit:
                # 前ターンからの提案リストに探す
                matched = [s for s in self.state.pending_summits if s.proposer == target_name and s.target == country_name]
                if matched:
                    proposal = matched[0]
                    self.summits_to_run_this_turn.append(proposal)
                    self.log_event(f"✅ {country_name}が{target_name}からの首脳会談の提案（議題: {proposal.topic}）を受諾しました。会談が開催されます。")
                    self.state.pending_summits.remove(proposal)
                    
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
            
            # 二国間の収支差分。nx_theoreticalが大きい(黒字体質)の方が、二国間でも黒字になると仮定
            diff = nx_a - nx_b
            # 取引量の一部が赤字国から黒字国へ国富として移転
            # (diffが正ならAが黒字[輸出超過]、Bが赤字[輸入超過])
            deficit_transfer = (diff / max(1.0, ca.economy + cb.economy)) * base_volume * 1.5
            
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
            
            # 支持率に関するISモデルの二面性評価
            # 赤字国: 物価が下がり消費者余剰が発生("安くて便利")する一方、産業空洞化ペナルティが早く蓄積
            # 黒字国: 失業は減るが、物価上昇や過労によるペナルティ(マイルド)
            if deficit_transfer > 0:
                # Bが赤字
                cb_support = 1.0  # 安い輸入品の恩恵
                ca_support = 0.5  # 輸出産業の好調
                cb.trade_deficit_counter += 1
                ca.trade_deficit_counter = max(0, ca.trade_deficit_counter - 1)
                
                if cb.trade_deficit_counter > 3:
                    penalty = min(5.0, (cb.trade_deficit_counter - 3) * 1.5) # ペナルティ上限を5%に
                    cb_support -= penalty
                    self.sys_logs_this_turn.append(f"[Trade Penalty] {trade.country_b} は不均衡な貿易赤字による国内産業の空洞化・失業増(-{penalty:.1f})に苦しんでいます")
            else:
                # Aが赤字
                ca_support = 1.0
                cb_support = 0.5
                ca.trade_deficit_counter += 1
                cb.trade_deficit_counter = max(0, cb.trade_deficit_counter - 1)
                
                if ca.trade_deficit_counter > 3:
                    penalty = min(5.0, (ca.trade_deficit_counter - 3) * 1.5) # ペナルティ上限を5%に
                    ca_support -= penalty
                    self.sys_logs_this_turn.append(f"[Trade Penalty] {trade.country_a} は不均衡な貿易赤字による国内産業の空洞化・失業増(-{penalty:.1f})に苦しんでいます")
                
            if trade.country_a in self.turn_domestic_factors:
                self.turn_domestic_factors[trade.country_a]["trade_support_bonus"] += ca_support
            if trade.country_b in self.turn_domestic_factors:
                self.turn_domestic_factors[trade.country_b]["trade_support_bonus"] += cb_support
                
            self.sys_logs_this_turn.append(
                f"[Trade IS Balance] {trade.country_a} vs {trade.country_b} | "
                f"Volume:{base_volume:.1f}, IS Diff(A-B):{diff:+.0f} -> "
                f"{trade.country_a} ({ca_nx:+.1f} GDP_NX, Debt {ca.national_debt:.1f}, {ca_support:+.1f}% Support), "
                f"{trade.country_b} ({cb_nx:+.1f} GDP_NX, Debt {cb.national_debt:.1f}, {cb_support:+.1f}% Support)"
            )
            
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
        
        # 諜報力の定義（経済力と軍事力の合計値ベース）
        attacker_power = attacker.economy + attacker.military
        target_power = target.economy + target.military
        power_ratio = (attacker_power - target_power) / max(1.0, target_power)
        
        if action.espionage_sabotage:
            # 破壊工作の判定
            # 成功率 (基本15%、最大35%)
            sabotage_success_base = 0.15 + (power_ratio * 0.1)
            sabotage_success_chance = max(0.05, min(0.35, sabotage_success_base))
            is_success = random.random() < sabotage_success_chance
            
            # 発覚率 (基本25%、能力差で変動)
            sabotage_discovery_base = 0.25 - (power_ratio * 0.2)
            discovery_chance = max(0.10, min(0.50, sabotage_discovery_base))
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
            # 成功率 (基本30%、最大60%)
            intel_success_base = 0.30 + (power_ratio * 0.1)
            intel_success_chance = max(0.15, min(0.60, intel_success_base))
            is_success = random.random() < intel_success_chance

            # 発覚率 (基本10%、能力差で変動)
            intel_discovery_base = 0.10 - (power_ratio * 0.1)
            discovery_chance = max(0.05, min(0.30, intel_discovery_base))
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
        
        # 敗戦国を世界から削除
        del self.state.countries[loser_name]
        
        # 関連する戦争も終了させる
        self.state.active_wars = [w for w in self.state.active_wars if w.aggressor != loser_name and w.defender != loser_name]

    def _process_domestic_events(self):
        for name, country in self.state.countries.items():
            
            # 支持率低下による反乱リスク
            if country.approval_rating < 30.0:
                country.rebellion_risk += 5.0
                self.log_event(f"⚠️ {name}の国内で政府への抗議運動が激化しています。(支持率{country.approval_rating:.1f}%)")
            else:
                country.rebellion_risk = max(0.0, country.rebellion_risk - 2.0)
                
            # 체제別 イベント
            if country.government_type == GovernmentType.DEMOCRACY:
                # 支持率が0%に達した場合のみクーデター発生（ARCHITECTURE.md §2.6 準拠）
                if country.approval_rating <= 0.0:
                    self.log_event(f"⚠️ {name}で【政府機能麻痺】支持率が0%に達し、暴動により政権が崩壊しました！")
                    self._handle_rebellion(name, country)
                    if country.turns_until_election is not None:
                        country.turns_until_election = 16 # 米国の場合4年(16ターン)リセット
                    continue
                    
                if country.turns_until_election is not None:
                    country.turns_until_election -= 1
                    if country.turns_until_election <= 0:
                        self._handle_election(name, country)
                        country.turns_until_election = 16 # 米国の場合4年(16ターン)リセット
                        
            elif country.government_type == GovernmentType.AUTHORITARIAN:
                # 専制主義での反乱判定
                if country.rebellion_risk > random.uniform(20.0, 100.0):
                    self._handle_rebellion(name, country)
                    country.rebellion_risk = 0.0

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
                damage = random.uniform(min_dmg, max_dmg)
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
                    damage = random.uniform(min_dmg, max_dmg)
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

    def _handle_election(self, name: str, country: CountryState):
        self.log_event(f"🗳️ {name}で【大統領選挙】が実施されました。")
        
        # 落選確率は支持率の反比例 (例: 支持40%なら60%で落選)
        lose_chance = max(0.0, 100.0 - country.approval_rating) / 100.0
        
        if random.random() < lose_chance:
            self.log_event(f"🔄 【政権交代】{name}の現職が選挙で敗北しました！国家の政策方針が大きく見直されます。")
            country.approval_rating = 50.0 # 新政権へのご祝儀相場
            self.pending_elections.append(name)
        else:
            self.log_event(f"✅ {name}の現職が再選を果たしました。現状の政策が継続されます。")

    def _handle_rebellion(self, name: str, country: CountryState):
        self.log_event(f"🔥 【革命/クーデター発生】{name}で大規模な武装蜂起が発生し、政府が転覆しました！")
        
        # 確率で政治体制の選択
        if random.random() < 0.5:
            new_gov = GovernmentType.DEMOCRACY
            gov_str = "民主的な"
            country.turns_until_election = 16
        else:
            new_gov = GovernmentType.AUTHORITARIAN
            gov_str = "強権的な"
            country.turns_until_election = None
            
        old_gov = country.government_type
        country.government_type = new_gov
        
        self.log_event(f"🚩 【体制変化】クーデターの結果、{name}は{gov_str}新政権({new_gov.value})へと移行しました。")
        
        country.approval_rating = 40.0
        country.economy *= 0.9   # 内戦による経済ダメージ（10%減）
        country.military = country.economy * 0.1  # 軍事力をGDPの10%にリセット
        self.pending_rebellions.append(name)

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
            # 現状に飽きるため、毎ターン無条件で少しずつ支持率が下がる (-0.5%)
            # 支持率が高いほど減衰ペースを少し上げる工夫も可能
            fatigue_decay = -0.5 - ((old_approval - 50.0) * 0.01 if old_approval > 50.0 else 0)
            
            # Apply dynamic factors with carefully tuned weights
            growth_modifier = gdp_growth * 0.5
            if gdp_growth < -5.0:
                # 深刻な不況（5%以上のマイナス成長）には非線形なペナルティを課す（大恐慌レベルの支持率暴落）
                growth_modifier -= (abs(gdp_growth) - 5.0) ** 1.5
                
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


