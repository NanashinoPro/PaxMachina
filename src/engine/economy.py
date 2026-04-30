import math
from models import RelationType

from .constants import (
    GRAVITY_TARIFF_ELASTICITY, GRAVITY_ALLIANCE_DISTANCE_FACTOR,
    GRAVITY_SANCTION_DISTANCE_FACTOR, GRAVITY_TRADE_SCALE,
    DEFAULT_TARIFF_RATE,
    SANCTION_TARGET_DAMAGE_PER_CASE, SANCTION_TARGET_MAX_PER_CASE,
    SANCTION_TARGET_MAX_CUMULATIVE,
    SANCTION_SENDER_COST_PER_CASE, SANCTION_SENDER_MAX_COST
)


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点間のHaversine距離（km）を算出"""
    R = 6371.0  # 地球の半径 (km)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


class EconomyMixin:
    def _process_trade_and_sanctions(self):
        # 期限切れ提案のクリア（1ターンのみ有効）
        self.state.pending_summits = [s for s in self.state.pending_summits if s not in self.summits_to_run_this_turn]
        
        # 当期のNXと関税収入をリセット
        for c_name, country in self.state.countries.items():
            country.last_turn_nx = 0.0
            country.tariff_revenue = 0.0

        # 距離キャッシュの構築（起動時に1回のみ計算）
        if not hasattr(self, '_distance_cache'):
            self._distance_cache = {}
            country_names = list(self.state.countries.keys())
            for i, name_a in enumerate(country_names):
                ca = self.state.countries[name_a]
                for j, name_b in enumerate(country_names):
                    if i >= j:
                        continue
                    cb = self.state.countries[name_b]
                    dist = _haversine_distance(ca.capital_lat, ca.capital_lon, cb.capital_lat, cb.capital_lon)
                    # 座標が未設定(0,0)の場合はデフォルト距離を使用
                    if dist < 100:
                        dist = 10000.0  # デフォルト10000km
                    self._distance_cache[(name_a, name_b)] = dist
                    self._distance_cache[(name_b, name_a)] = dist
            # 距離ログ
            for (na, nb), d in self._distance_cache.items():
                if na < nb:  # 重複を避ける
                    self.sys_logs_this_turn.append(f"[Trade Distance] {na} ↔ {nb}: {d:.0f} km")

        # === 拡張重力モデルによる貿易 (Anderson & van Wincoop 2003) ===
        for trade in self.state.active_trades:
            if trade.country_a not in self.state.countries or trade.country_b not in self.state.countries:
                continue
            ca = self.state.countries[trade.country_a]
            cb = self.state.countries[trade.country_b]
            rel = self._get_relation(trade.country_a, trade.country_b)
            
            # 実効距離の算出
            raw_dist = self._distance_cache.get((trade.country_a, trade.country_b), 10000.0)
            
            # 関係性による実効距離調整（生km単位）
            if rel == RelationType.ALLIANCE:
                effective_dist = raw_dist * GRAVITY_ALLIANCE_DISTANCE_FACTOR
            else:
                effective_dist = raw_dist
            
            # 制裁存在チェック
            sanctions_exist = any(s for s in self.state.active_sanctions if 
                                 (s.imposer == trade.country_a and s.target == trade.country_b) or
                                 (s.imposer == trade.country_b and s.target == trade.country_a))
            if sanctions_exist:
                effective_dist *= GRAVITY_SANCTION_DISTANCE_FACTOR
            
            # ゼロ距離防止
            effective_dist = max(0.01, effective_dist)
            
            # 関税率の取得
            tariff_a_to_b = trade.tariff_a_to_b  # 国Aが国Bからの輸入に課す関税
            tariff_b_to_a = trade.tariff_b_to_a  # 国Bが国Aからの輸入に課す関税
            
            # 拡張重力モデル: V_ij = SCALE × √(GDP_i × GDP_j) / (dist_km × (1+tariff)^θ)
            # V_ab: AからBへの輸出（Bが輸入するのでBの関税が適用）
            gdp_geometric = math.sqrt(ca.economy * cb.economy)
            tariff_factor_b_imports = (1.0 + tariff_b_to_a) ** GRAVITY_TARIFF_ELASTICITY
            v_a_to_b = GRAVITY_TRADE_SCALE * gdp_geometric / (effective_dist * tariff_factor_b_imports)
            
            # V_ba: BからAへの輸出（Aが輸入するのでAの関税が適用）
            tariff_factor_a_imports = (1.0 + tariff_a_to_b) ** GRAVITY_TARIFF_ELASTICITY
            v_b_to_a = GRAVITY_TRADE_SCALE * gdp_geometric / (effective_dist * tariff_factor_a_imports)
            
            # 関税収入の計算
            tariff_rev_a = v_b_to_a * tariff_a_to_b  # 国Aの関税収入（Bからの輸入に課税）
            tariff_rev_b = v_a_to_b * tariff_b_to_a  # 国Bの関税収入（Aからの輸入に課税）
            ca.tariff_revenue += tariff_rev_a
            cb.tariff_revenue += tariff_rev_b
            
            # NXの計算: 輸出 - 輸入
            ca_nx = v_a_to_b - v_b_to_a  # Aの純輸出
            cb_nx = v_b_to_a - v_a_to_b  # Bの純輸出（= -ca_nx）
            
            # マクロ経済的ガードレール (サドン・ストップ防止): 1ターンの流出はGDPの3%上限
            limit_a = ca.economy * 0.03
            limit_b = cb.economy * 0.03
            if ca_nx < -limit_a:
                ca_nx = -limit_a
                cb_nx = limit_a
            elif cb_nx < -limit_b:
                cb_nx = -limit_b
                ca_nx = limit_b
            
            # 貿易による共通の経済効率化ボーナス
            total_volume = v_a_to_b + v_b_to_a
            mutual_bonus = total_volume * 0.0025
            ca_nx += mutual_bonus
            cb_nx += mutual_bonus
            
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
            if ca_nx < 0:
                ca_support = 1.0  # 赤字国は安い輸入品の恩恵
            if cb_nx < 0:
                cb_support = 1.0
                
            if trade.country_a in self.turn_domestic_factors:
                self.turn_domestic_factors[trade.country_a]["trade_support_bonus"] += ca_support
            if trade.country_b in self.turn_domestic_factors:
                self.turn_domestic_factors[trade.country_b]["trade_support_bonus"] += cb_support
                
            self.sys_logs_this_turn.append(
                f"[Trade Gravity] {trade.country_a} vs {trade.country_b} | "
                f"Dist:{raw_dist:.0f}km(eff:{effective_dist:.2f}), "
                f"Tariff A→B:{tariff_a_to_b:.1%} B→A:{tariff_b_to_a:.1%} | "
                f"V(A→B):{v_a_to_b:.1f} V(B→A):{v_b_to_a:.1f} | "
                f"{trade.country_a} NX:{ca_nx:+.1f} TariffRev:{tariff_rev_a:.1f}, "
                f"{trade.country_b} NX:{cb_nx:+.1f} TariffRev:{tariff_rev_b:.1f}"
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
            
        # Sanctions (Damage Model) — 非貿易チャネルの残余ダメージ
        # [学術的根拠] Neuenkirch & Neumeier (2015), Gutmann et al. (2021)
        # 貿易チャネル（NX）は重力モデル(GRAVITY_SANCTION_DISTANCE_FACTOR=10.0)で処理済み。
        # ここでは投資萎縮・金融遮断・管理コスト等の非貿易チャネル分を適用する。
        # 複数制裁の累積をキャップすることで、学術的上限（年-8%）を超えないよう制御。

        # Phase 1: 各国が受ける制裁ダメージを加算方式で集計
        sanction_damage_accumulator = {}   # {target_name: total_damage_percent}
        sanction_sender_count = {}         # {imposer_name: count}

        for sanction in self.state.active_sanctions:
            if sanction.imposer not in self.state.countries or sanction.target not in self.state.countries:
                continue
            imposer = self.state.countries[sanction.imposer]
            target = self.state.countries[sanction.target]

            # 制裁1件あたりのダメージ: GDP比率に応じて算出、上限SANCTION_TARGET_MAX_PER_CASE
            ratio = imposer.economy / max(1.0, target.economy)
            damage_percent = min(SANCTION_TARGET_MAX_PER_CASE, SANCTION_TARGET_DAMAGE_PER_CASE * ratio)

            sanction_damage_accumulator.setdefault(sanction.target, 0.0)
            sanction_damage_accumulator[sanction.target] += damage_percent

            sanction_sender_count.setdefault(sanction.imposer, 0)
            sanction_sender_count[sanction.imposer] += 1

            # 制裁による支持率ペナルティ（ARCHITECTURE.md §2.3 準拠）
            target_approval_penalty = min(5.0, 1.0 * ratio)
            imposer_approval_penalty = 0.5
            target.approval_rating = max(0.0, target.approval_rating - target_approval_penalty)
            imposer.approval_rating = max(0.0, imposer.approval_rating - imposer_approval_penalty)

            self.sys_logs_this_turn.append(
                f"[制裁ダメージ] {sanction.imposer} -> {sanction.target} | "
                f"個別デバフ: -{damage_percent:.2f}% | "
                f"支持率ペナルティ: 対象国 -{target_approval_penalty:.1f}%, 発動国 -{imposer_approval_penalty:.1f}%"
            )

        # Phase 2: 累積キャップを適用しGDPを一括調整
        for target_name, raw_damage in sanction_damage_accumulator.items():
            capped_damage = min(SANCTION_TARGET_MAX_CUMULATIVE, raw_damage)
            self.state.countries[target_name].economy *= (1.0 - capped_damage / 100.0)
            if raw_damage > SANCTION_TARGET_MAX_CUMULATIVE:
                self.sys_logs_this_turn.append(
                    f"[制裁キャップ] {target_name}: 累積制裁 -{raw_damage:.1f}% → キャップ -{capped_damage:.1f}% に制限"
                )

        # 発動国コスト: サプライチェーン断絶・管理コスト等（非貿易チャネル残余）
        for imposer_name, count in sanction_sender_count.items():
            total_cost = min(SANCTION_SENDER_MAX_COST, SANCTION_SENDER_COST_PER_CASE * count)
            self.state.countries[imposer_name].economy *= (1.0 - total_cost)

