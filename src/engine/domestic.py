import math
import random
from typing import Dict
from models import AgentAction, GovernmentType

from .constants import (
    DEMOCRACY_WARN_APPROVAL, CRITICAL_APPROVAL,
    DEMOCRACY_MIN_EXECUTION_POWER,
    DEBT_INTEREST_RATE_ANNUAL, TURNS_PER_YEAR, TAX_APPROVAL_PENALTY_MULTIPLIER, TAX_REDUCTION_APPROVAL_BONUS_MULTIPLIER, MAX_TAX_CHANGE_PER_TURN,
    AUTHORITARIAN_BASE_SAVING_RATE, DEMOCRACY_BASE_SAVING_RATE,
    DEBT_REPAYMENT_CROWD_IN_MULTIPLIER, GOVERNMENT_CROWD_IN_MULTIPLIER, GOVERNMENT_CROWD_OUT_MULTIPLIER, BASE_INVESTMENT_RATE,
    ENDOGENOUS_GROWTH_ALPHA, DEBT_TO_GDP_PENALTY_THRESHOLD,
    BASE_MILITARY_MAINTENANCE_ALPHA, MAX_MILITARY_FATIGUE_ALPHA, BASE_MILITARY_GROWTH_RATE,
    INTEL_GROWTH_RATE, INTEL_MAINTENANCE_ALPHA,
    MINCER_RETURN_PRIMARY, MINCER_RETURN_SECONDARY, MINCER_RETURN_TERTIARY,
    MYS_GROWTH_RATE, MYS_DECAY_RATE,
    GDP_GROWTH_FLOOR_EARLY, GDP_GROWTH_FLOOR_NORMAL
)

def compute_pwt_hci(s: float) -> float:
    """Penn World Table 人的資本指数を算出する (Hall & Jones 1999, Psacharopoulos 1994).
    
    φ(s) = 区分線形ミンサー方程式に基づく収益率関数
    hc = e^φ(s)
    
    Args:
        s: 平均就学年数 (Mean Years of Schooling)
    Returns:
        人的資本指数 (hc)
    """
    s = max(0.0, s)
    if s <= 4.0:
        phi = MINCER_RETURN_PRIMARY * s
    elif s <= 8.0:
        phi = MINCER_RETURN_PRIMARY * 4.0 + MINCER_RETURN_SECONDARY * (s - 4.0)
    else:
        phi = (MINCER_RETURN_PRIMARY * 4.0 + MINCER_RETURN_SECONDARY * 4.0 
               + MINCER_RETURN_TERTIARY * (s - 8.0))
    return math.exp(phi)


class DomesticMixin:
    def _process_domestic(self, country_name: str, action: AgentAction):
        country = self.state.countries[country_name]
        
        # 秘密計画の更新
        if hasattr(action, 'update_hidden_plans') and action.update_hidden_plans:
            country.hidden_plans = action.update_hidden_plans
            # 秘密計画をDBに保存（該当国のみアクセス可能）
            if self.db_manager:
                self.db_manager.add_event(
                    turn=self.state.turn,
                    event_type="secret_plan",
                    content=f"{country_name}の極秘計画: {country.hidden_plans}",
                    is_private=True,
                    involved_countries=[country_name]
                )

        # --- 議会解散権の処理（民主主義国家かつ解散権を持つ国のみ） ---
        dissolution_executed = False
        if getattr(action.domestic_policy, 'dissolve_parliament', False) and country.government_type == GovernmentType.DEMOCRACY and country.has_dissolution_power:
            dissolution_executed = True
            old_approval = country.approval_rating
            
            # 選挙費用: GDP × 0.01〜0.02% を予算から天引き
            election_cost = country.economy * random.uniform(0.0001, 0.0002)
            country.government_budget = max(0.0, country.government_budget - election_cost)
            
            self.log_event(f"🗳️ {country_name}の指導者が議会解散を宣言しました！総選挙が実施されます。（現支持率: {old_approval:.1f}%, 選挙費用: {election_cost:.2f}）", involved_countries=[country_name, "global"])
            
            # 判定: 乱数(0〜100) <= 解散前支持率 → 成功
            roll = random.uniform(0.0, 100.0)
            
            if roll <= old_approval:
                # 成功（再任）: 支持率 = 50 + 解散前支持率/2
                new_approval = min(100.0, 50.0 + old_approval / 2.0)
                country.approval_rating = new_approval
                # 選挙タイマリセット
                if country.turns_until_election is not None:
                    country.turns_until_election = 16
                
                self.log_event(f"✅ 【解散総選挙結果】{country_name}の現政権が国民の信任を勝ち取り、再任されました！（支持率: {old_approval:.1f}% → {new_approval:.1f}%）", involved_countries=[country_name])
                self.sys_logs_this_turn.append(f"[{country_name} 議会解散] 乱数 {roll:.1f} <= 支持率 {old_approval:.1f} により再任。新支持率: {new_approval:.1f}%。選挙費用: {election_cost:.2f}")
            else:
                # 失敗（新政権誕生）: 支持率 = 100 - 解散前支持率/2
                new_approval = max(0.0, min(100.0, 100.0 - old_approval / 2.0))
                country.approval_rating = new_approval
                country.regime_duration = 0
                
                # 選挙タイマリセット
                if country.turns_until_election is not None:
                    country.turns_until_election = 16
                
                # イデオロギーの刷新フラグ
                country.ideology = f"[新政権樹立フェーズ] 解散総選挙で旧政権({country.ideology})が敗北。新政府の指針を策定中"
                country.hidden_plans = "解散総選挙による政権交代。新たな国家戦略を立案せよ。"
                
                self.log_event(f"🔄 【解散総選挙・政権交代】{country_name}の解散総選挙で現政権が敗北！新たな指導者が選出されました。（支持率: {old_approval:.1f}% → {new_approval:.1f}%）", involved_countries=[country_name, "global"])
                self.sys_logs_this_turn.append(f"[{country_name} 議会解散] 乱数 {roll:.1f} > 支持率 {old_approval:.1f} により落選。新政権誕生。新支持率: {new_approval:.1f}%。選挙費用: {election_cost:.2f}")
                
                # 新政権誕生フラグを立てる（AIプロンプトフェーズで新イデオロギー生成用）
                if hasattr(self, 'pending_elections'):
                    self.pending_elections.append(country_name)

        # --- 税率調整と政治的コスト（支持率ペナルティ） ---
        old_tax_rate = country.tax_rate
        try:
            new_tax_rate = float(action.domestic_policy.tax_rate)
        except (TypeError, ValueError):
            new_tax_rate = old_tax_rate
        
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

        # --- 関税率の更新（財務大臣の決定を反映） ---
        target_tariffs = getattr(action.domestic_policy, 'target_tariff_rates', {})
        if target_tariffs:
            for trade in self.state.active_trades:
                if trade.country_a == country_name:
                    target_country = trade.country_b
                    if target_country in target_tariffs:
                        new_tariff = max(0.0, target_tariffs[target_country])
                        # 1ターンあたりの関税率変動を±5%に制限
                        old_tariff = trade.tariff_a_to_b
                        clamped_tariff = max(old_tariff - 0.05, min(old_tariff + 0.05, new_tariff))
                        trade.tariff_a_to_b = clamped_tariff
                        if abs(clamped_tariff - old_tariff) > 0.001:
                            self.sys_logs_this_turn.append(f"[{country_name} 関税変更] 対{target_country}: {old_tariff:.1%}→{clamped_tariff:.1%}")
                elif trade.country_b == country_name:
                    target_country = trade.country_a
                    if target_country in target_tariffs:
                        new_tariff = max(0.0, target_tariffs[target_country])
                        old_tariff = trade.tariff_b_to_a
                        clamped_tariff = max(old_tariff - 0.05, min(old_tariff + 0.05, new_tariff))
                        trade.tariff_b_to_a = clamped_tariff
                        if abs(clamped_tariff - old_tariff) > 0.001:
                            self.sys_logs_this_turn.append(f"[{country_name} 関税変更] 対{target_country}: {old_tariff:.1%}→{clamped_tariff:.1%}")

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
        
        # 注: 利払いと予算算出は engine/core.py の process_turn() で四半期化して実行済み
        # ここでは government_budget は利払い後の可処分予算として使用する
        # 税収T = GDP * 税率 (※前ターンのGDPをベースにする)
        # 報道の自由度の更新とペナルティ計算
        # 自由度を急激に制限（下げる）すると、国民の不満によって支持率が大きく下落する
        try:
            target_freedom = float(getattr(action.domestic_policy, 'target_press_freedom', country.press_freedom) or country.press_freedom)
        except (TypeError, ValueError):
            target_freedom = country.press_freedom
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
        
        # 経済投資（LLMがstr型で返す場合の安全変換）
        def _safe_float(val, default=0.0):
            try:
                return float(val if val is not None else default)
            except (TypeError, ValueError):
                return default
        
        inv_econ = _safe_float(action.domestic_policy.invest_economy, 0.25)
        inv_mil = _safe_float(action.domestic_policy.invest_military, 0.25)
        inv_wel = _safe_float(action.domestic_policy.invest_welfare, 0.25)
        inv_intel = _safe_float(getattr(action.domestic_policy, 'invest_intelligence', 0.0))
        inv_edu = _safe_float(getattr(action.domestic_policy, 'invest_education_science', 0.0))
        
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

        # ===== 四半期スケールSNAモデル (Y_q = C_q + I_q + G_q + NX_q) =====
        # 全フロー変数を四半期ベースで統一することで、政府支出G（四半期予算）とのスケール整合を保証

        # 基礎貯蓄率 (政治体制と福祉投資による低下)
        base_s_rate = AUTHORITARIAN_BASE_SAVING_RATE if country.government_type == GovernmentType.AUTHORITARIAN else DEMOCRACY_BASE_SAVING_RATE
        saving_rate = max(0.15, base_s_rate - (inv_wel * 0.15))

        quarterly_gdp = old_gdp / TURNS_PER_YEAR
        tax_revenue_q = old_gdp * country.tax_rate / TURNS_PER_YEAR  # 四半期税収

        # 1. 民間消費 (C_q)
        # ケインズ型消費関数: C = (Y_q - T_q) * (1 - s)
        # 増税すると即座に消費が減る。減税すると消費が大きく活性化するボーナスを追加。
        C = max(0.0, (quarterly_gdp - tax_revenue_q) * (1.0 - saving_rate))
        if tax_diff < 0:
            consumption_bonus_multiplier = 1.0 + (abs(tax_diff) * 2.0)
            C *= consumption_bonus_multiplier
            
        S_private = max(0.0, (quarterly_gdp - tax_revenue_q) - C)

        # --- SNAマクロ経済モデル: 民間投資 (I_q) ---
        # [Harrod 1939; Domar 1946] 貯蓄=投資均衡仮定の下、民間貯蓄の一部が
        # 資本市場を通じて国内投資へ還流すると仮定。係数0.95は国内投資率を表し、
        # 残5%は海外流出・現預金積み上げ等として処理。
        # ベース投資(BASE_INVESTMENT_RATE)を生命線として底板に設定する。
        # 政府の経済投資は民間投資を誘発（クラウドイン）し、軍事費が民間投資を押し出す（クラウドアウト）。
        # 民間貯蓄に加え、政府の未執行予算(S_gov)が金融市場を通じて民間投資に還流する
        
        # --- 利払いリーケージ修正 ---
        # 税収のうち利払いに使われた分は、債権者（国内銀行・年金基金・個人投資家）への
        # 所得移転であり、その一定割合（INTEREST_REINVESTMENT_RATE=70%）が
        # 資本市場を通じて国内民間投資に再投資される [Mankiw "Macroeconomics" Ch.3]
        interest_leakage = max(0.0, tax_revenue_q - budget)
        interest_reinvested = interest_leakage * INTEREST_REINVESTMENT_RATE
        
        induced_investment = (S_private * 0.95 
                              + interest_reinvested
                              + (S_gov * DEBT_REPAYMENT_CROWD_IN_MULTIPLIER) 
                              + (g_econ * GOVERNMENT_CROWD_IN_MULTIPLIER) 
                              - (g_mil * GOVERNMENT_CROWD_OUT_MULTIPLIER))
        base_investment = quarterly_gdp * BASE_INVESTMENT_RATE
        I = max(0.0, max(base_investment, induced_investment))
        
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

        # --- PWT HCIによる人的資本の限界効用逓減 (Mankiw, Romer, and Weil 1992) ---
        # 初期HCIに対する現在HCIの比率。PWT HCIスケール(≈1.0-4.5)で安定。
        base_h_ratio = country.human_capital_index / max(1.0, country.initial_human_capital_index)
        
        # 物理的なインフレ上限の設定
        # log2を使うことで、指数関数的成長に対して強力にブレーキをかけ、実質的なシステムキャップとする
        # 例: ratio=2で+5%, ratio=4で+10%, ratio=32(3200%)でようやく+25%
        if base_h_ratio > 1.0:
            h_ratio_capped = 1.0 + math.log2(base_h_ratio) * 0.05
        else:
            h_ratio_capped = max(0.5, base_h_ratio)

        # マクロ需要ベースライン (C_q+I_q+G_q 全体に強力なキャップをかけた教育バフを乗ずる)
        base_aggregated_demand_q = (C + I + G) * h_ratio_capped

        # --- 内生的成長理論 (Romer model) によるイノベーション効果 ---
        # そのターンの教育・科学投資(g_edu)が四半期GDPに対して占める割合が、技術進歩（基礎成長率）を押し上げる
        edu_investment_ratio = g_edu / max(1.0, quarterly_gdp)
        
        # 成長率バフへの変換式。対数を用いて異常な投資への耐性を持たせる
        # 例: 投資率0.05(5%)投入 -> log1p(0.5)*0.05 = 約2.0%の追加成長
        endogenous_growth_bonus = math.log1p(edu_investment_ratio * 10.0) * ENDOGENOUS_GROWTH_ALPHA

        # 四半期の総需要に内生的な技術進歩を掛け合わせ、純輸出を足して四半期GDPを算出
        new_quarterly_gdp = base_aggregated_demand_q * (1.0 + endogenous_growth_bonus) + country.last_turn_nx
        
        # 四半期GDPを年間GDPに変換して country.economy に格納
        new_gdp_provisional = new_quarterly_gdp * TURNS_PER_YEAR
        
        # --- SNAモデル ブレークダウンログ ---
        sna_growth_raw = (new_gdp_provisional - old_gdp) / max(1.0, old_gdp) * 100
        self.sys_logs_this_turn.append(
            f"[{country.name} SNA詳細] "
            f"旧GDP(年):{old_gdp:.1f} → 新GDP(年):{new_gdp_provisional:.1f} (生成長率:{sna_growth_raw:+.1f}%)\n"
            f"  四半期GDP:{quarterly_gdp:.1f} | 税収_q:{tax_revenue_q:.1f} | 貯蓄率:{saving_rate:.2f}\n"
            f"  C_q:{C:.1f} ({C/quarterly_gdp*100:.1f}%GDP) | "
            f"I_q:{I:.1f} ({I/quarterly_gdp*100:.1f}%GDP) [base:{base_investment:.1f}, induced:{induced_investment:.1f}] | "
            f"G_q:{G:.1f} ({G/quarterly_gdp*100:.1f}%GDP)\n"
            f"  利払い漏出:{interest_leakage:.1f} → 還流(70%):{interest_reinvested:.1f} | "
            f"NX:{country.last_turn_nx:+.1f} | HCI乗数:{h_ratio_capped:.3f} | "
            f"内生成長:{endogenous_growth_bonus:.4f} | "
            f"C+I+G(q):{C+I+G:.1f} → 需要_q:{base_aggregated_demand_q:.1f} → 新Q:{new_quarterly_gdp:.1f}\n"
            f"  投資配分: 経済{inv_econ:.0%} 軍事{inv_mil:.0%} 福祉{inv_wel:.0%} 教育{inv_edu:.0%} 諜報{inv_intel:.0%} | "
            f"実行力:{execution_power:.2f} | "
            f"g_econ:{g_econ:.1f} g_mil:{g_mil:.1f} g_wel:{g_wel:.1f} g_edu:{g_edu:.1f}"
        )
        
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
        birth_rate_reduction = min(0.015, (math.log10(max(1.0, gdp_per_capita)) * 0.002) + (country.mean_years_schooling / 20.0 * 0.005))
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
            # GDP蒸発（産業空洞化・労働力不足）
            # [Müller 1970 / Dunne et al.] 最大-10%/四半期（年換算で概ね-35〜40%に相当）
            mobilization_penalty = min(0.10, excess_mobilization * 0.75)
            country.economy = max(1.0, country.economy * (1.0 - mobilization_penalty))

            # 支持率への影響: 直接ペナルティは生活悪化の認識分のみ（最大-5pt）
            # [Müller 1970] ラリー効果により動員直後の即時大幅低下は非現実的
            direct_approval_drop = min(5.0, excess_mobilization * 50.0)
            country.approval_rating = max(0.0, country.approval_rating - direct_approval_drop)

            mobilization_penalty_text = (
                f" | [過剰動員ペナルティ] 動員限界突破({mobilization_rate:.1%}) "
                f"GDP-{mobilization_penalty*100:.1f}%, 支持率-{direct_approval_drop:.1f}pt"
            )
            self.sys_logs_this_turn.append(
                f"[{country.name} 極限動員] 動員率{mobilization_rate:.1%}。"
                f"労働力不足→経済力-{mobilization_penalty*100:.1f}% | "
                f"支持率-{direct_approval_drop:.1f}pt (即時)"
            )

        # 成長率ボーナスの計算 (総GDPではなく1人当たりGDPの成長率を使用し、人口増による豊かさの希釈と過剰動員ペナルティを反映)
        new_gdp_per_capita = country.economy / max(0.1, country.population)
        gdp_growth_rate = (new_gdp_per_capita - gdp_per_capita) / max(1.0, gdp_per_capita) * 100.0

        # --- GDP成長率のフロア設定 (Álvarez-Pereira et al. 2022) ---
        # 分裂直後（2ターン以内）は四半期あたり-10%、通常時は-5%をフロアとする
        if country.regime_duration <= 2:
            growth_floor = GDP_GROWTH_FLOOR_EARLY
        else:
            growth_floor = GDP_GROWTH_FLOOR_NORMAL

        if gdp_growth_rate < growth_floor:
            target_gdp_per_capita = gdp_per_capita * (1.0 + growth_floor / 100.0)
            country.economy = max(1.0, target_gdp_per_capita * country.population)
            new_gdp_per_capita = country.economy / max(0.1, country.population)
            self.sys_logs_this_turn.append(
                f"[{country.name} GDP成長フロア適用] 成長率 {gdp_growth_rate:.1f}% → {growth_floor:.1f}% に制限 "
                f"(学術的根拠: Álvarez-Pereira et al. 2022)"
            )
            gdp_growth_rate = growth_floor

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

        # --- PWT HCI: 教育投資 → 平均就学年数(MYS) → 人的資本指数(HCI) の更新 ---
        # [学術的根拠] Jackson et al. (2016, QJE): 教育支出10%増 → 完了就学年数+0.27~0.43年
        old_mys = country.mean_years_schooling
        old_hci = country.human_capital_index
        
        # Step 1: 教育投資のGDP比から就学年数の増加量を算出
        edu_investment_ratio = g_edu / max(1.0, old_gdp)
        delta_mys = math.log1p(edu_investment_ratio * 10.0) * MYS_GROWTH_RATE
        
        # Step 2: 自然減衰（退職・知識陳腐化）を適用して新MYSを算出
        country.mean_years_schooling = max(0.0, 
            country.mean_years_schooling * (1.0 - MYS_DECAY_RATE) + delta_mys)
        
        # Step 3: PWT HCI の再計算（ミンサー区分線形関数）
        country.human_capital_index = compute_pwt_hci(country.mean_years_schooling)
            
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
            f"税率:{new_tax_rate:.1%} (税収:{tax_revenue_q:.1f}) | 予算(G):{budget:.1f} | "
            f"1人当GDP:{gdp_per_capita:.1f} -> {new_gdp_per_capita:.1f} ({gdp_growth_rate:+.1f}%) | "
            f"人口:{old_pop:.1f} -> {country.population:.1f} ({pop_growth_rate*100:+.2f}%) | "
            f"動員率:{mobilization_rate:.1%}{mobilization_penalty_text}\n"
            f"  > 軍事力:{old_military:.1f} -> {country.military:.1f} (+{military_growth:.1f}, 維持費: -{alpha*100:.1f}%), "
            f"諜報:{old_intel:.1f} -> {country.intelligence_level:.1f}, "
            f"HCI:{old_hci:.3f} -> {country.human_capital_index:.3f} (MYS:{old_mys:.2f} -> {country.mean_years_schooling:.2f}), "
            f"支持率:{old_approval:.1f}% -> {country.approval_rating:.1f}%"
        )

        # ===== 情報偽装（対外発表値）の更新 =====
        # AIが report_* を設定した場合、reported_* に保存する（クランプなし）
        dp = action.domestic_policy
        _deception_logs = []

        def _save_reported(field_name, attr_name, true_val, unit=""):
            val = getattr(dp, field_name, None)
            if val is not None:
                setattr(country, attr_name, max(0.0, float(val)))
                dev = abs(getattr(country, attr_name) - true_val) / max(1.0, abs(true_val)) * 100.0
                _deception_logs.append(
                    f"{attr_name.replace('reported_','')}: 発表={getattr(country, attr_name):.1f}{unit} / 真値={true_val:.1f}{unit} (乖離={dev:.1f}%)"
                )

        _save_reported('report_economy',           'reported_economy',           country.economy)
        _save_reported('report_military',          'reported_military',          country.military)
        _save_reported('report_approval_rating',   'reported_approval_rating',   country.approval_rating, "%")
        _save_reported('report_intelligence_level','reported_intelligence_level',country.intelligence_level)
        _save_reported('report_gdp_per_capita',    'reported_gdp_per_capita',    new_gdp_per_capita)

        if _deception_logs:
            self.sys_logs_this_turn.append(
                f"[{country_name} 情報偽装] " + " | ".join(_deception_logs)
            )

