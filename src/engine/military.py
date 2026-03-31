import random
from typing import Dict

from models import (
    AgentAction, MilitaryDeploymentState, ForceAllocation,
    MilitaryDeploymentOrder, DeploymentType, NavalMission, AirMission
)
from .constants import (
    DEFENDER_ADVANTAGE_MULTIPLIER,
    MIN_COMMITMENT_RATIO,
    COMMITMENT_ECONOMIC_DRAIN
)

class MilitaryMixin:
    
    def _process_military_deployments(self, actions: Dict[str, AgentAction]):
        """全国のAI出力から軍事配備状態を更新（バリデーション付き）"""
        for country_name, action in actions.items():
            country = self.state.countries.get(country_name)
            if not country:
                continue
            
            # force_allocation の更新（指定があれば）
            if action.force_allocation:
                fa = action.force_allocation
                total = fa.army_ratio + fa.navy_ratio + fa.air_ratio
                if total > 0:
                    # 合計が1.0を超える場合は正規化
                    if total > 1.0:
                        fa.army_ratio /= total
                        fa.navy_ratio /= total
                        fa.air_ratio /= total
                    # 海岸線がない国はnavy_ratio=0
                    if not country.has_coastline and fa.navy_ratio > 0:
                        surplus = fa.navy_ratio
                        fa.navy_ratio = 0.0
                        fa.army_ratio += surplus * 0.7
                        fa.air_ratio += surplus * 0.3
                        self.sys_logs_this_turn.append(
                            f"[{country_name} 配備] 内陸国のため海軍比率を陸空に再配分"
                        )
                    country.military_deployment.force_allocation = fa
            
            # ユニット上限の計算
            fa = country.military_deployment.force_allocation
            mil = country.military
            gdp_per_capita = country.economy / max(0.01, country.population)
            
            # 陸軍: 師団数 = (軍事力 × 陸軍比率) / (一人当たりGDP × 3.4) × 1000 / 10000
            total_personnel = mil * fa.army_ratio / max(1.0, gdp_per_capita * 3.4)
            max_divisions = max(1, int(total_personnel * 1000 / 10000))
            
            # 海軍: 艦隊数
            naval_power = mil * fa.navy_ratio
            max_fleets = max(0, int(naval_power / 50)) if country.has_coastline else 0
            
            # 空軍: 飛行隊数
            air_power = mil * fa.air_ratio
            max_squadrons = max(0, int(air_power / 30))
            
            # deployments のバリデーションとスケールダウン
            valid_deployments = []
            total_divs = 0
            total_fleets_used = 0
            total_sq = 0
            
            # 戦争中かどうかの判定
            at_war_with = set()
            for war in self.state.active_wars:
                if war.aggressor == country_name:
                    at_war_with.add(war.defender)
                elif war.defender == country_name:
                    at_war_with.add(war.aggressor)
            
            for d in action.deployments:
                # 対象国が存在するか確認
                if d.target_country not in self.state.countries:
                    self.sys_logs_this_turn.append(
                        f"[{country_name} 配備エラー] 対象国 '{d.target_country}' が存在しません。スキップ"
                    )
                    continue
                
                is_at_war_with_target = d.target_country in at_war_with
                d_type = d.type.value if hasattr(d.type, 'value') else str(d.type)
                
                if d_type == "army":
                    if total_divs + d.divisions > max_divisions:
                        d.divisions = max(0, max_divisions - total_divs)
                    total_divs += d.divisions
                    if d.divisions > 0:
                        valid_deployments.append(d)
                        
                elif d_type == "navy":
                    if not country.has_coastline:
                        continue
                    # 戦時のみミッションのチェック
                    if d.naval_mission and d.naval_mission.value in (
                        "blockade", "naval_engagement", "amphibious_support", "shore_bombardment"
                    ) and not is_at_war_with_target:
                        d.naval_mission = NavalMission.PATROL
                        self.sys_logs_this_turn.append(
                            f"[{country_name} 配備] 戦時のみミッション → patrol にフォールバック (対{d.target_country})"
                        )
                    if total_fleets_used + d.fleets > max_fleets:
                        d.fleets = max(0, max_fleets - total_fleets_used)
                    total_fleets_used += d.fleets
                    if d.fleets > 0:
                        valid_deployments.append(d)
                        
                elif d_type == "air":
                    # 戦時のみミッションのチェック
                    if d.air_mission and d.air_mission.value in (
                        "ground_support", "strategic_bombing"
                    ) and not is_at_war_with_target:
                        d.air_mission = AirMission.AIR_SUPERIORITY
                        self.sys_logs_this_turn.append(
                            f"[{country_name} 配備] 戦時のみミッション → air_superiority にフォールバック (対{d.target_country})"
                        )
                    if total_sq + d.squadrons > max_squadrons:
                        d.squadrons = max(0, max_squadrons - total_sq)
                    total_sq += d.squadrons
                    if d.squadrons > 0:
                        valid_deployments.append(d)
            
            # 配備状態の更新
            country.military_deployment.deployments = valid_deployments
            
            self.sys_logs_this_turn.append(
                f"[{country_name} 配備完了] "
                f"陸軍: {total_divs}/{max_divisions}師団, "
                f"海軍: {total_fleets_used}/{max_fleets}艦隊, "
                f"空軍: {total_sq}/{max_squadrons}飛行隊, "
                f"配備先: {len(valid_deployments)}件"
            )
    def _process_wars(self):
        surviving_wars = []
        
        for war in self.state.active_wars:
            aggressor = self.state.countries.get(war.aggressor)
            defender = self.state.countries.get(war.defender)
            
            if not aggressor or not defender:
                continue # 国が既に滅亡している等
            
            # 投入比率の適用（最小値を保証）
            agg_commit = max(MIN_COMMITMENT_RATIO, war.aggressor_commitment_ratio)
            def_commit = max(MIN_COMMITMENT_RATIO, war.defender_commitment_ratio)
                
            # ダメージ計算（投入分の軍事力のみで戦闘）
            agg_committed = aggressor.military * agg_commit
            def_committed = defender.military * def_commit
            
            # 防衛側ボーナス
            def_power = def_committed * DEFENDER_ADVANTAGE_MULTIPLIER
            agg_power = agg_committed
            
            agg_damage_raw = def_power * random.uniform(0.05, 0.15)
            def_damage_raw = agg_power * random.uniform(0.05, 0.15)
            
            # 損害は投入分のみに適用（後方予備軍は温存）
            # ダメージが投入戦力を超えた場合、投入分の消滅のみで予備軍には波及しない
            agg_damage = min(agg_damage_raw, agg_committed)
            def_damage = min(def_damage_raw, def_committed)
            
            aggressor.military = max(0.0, aggressor.military - agg_damage)
            defender.military = max(0.0, defender.military - def_damage)
            
            # 人口減少計算（軍事ダメージ割合に比例。防衛側は戦場となるため民間人被害が大きい）
            agg_pop_loss = aggressor.population * (agg_damage / max(1.0, agg_committed)) * 0.05
            def_pop_loss = defender.population * (def_damage / max(1.0, def_committed)) * 0.15
            
            aggressor.population = max(0.1, aggressor.population - agg_pop_loss)
            defender.population = max(0.1, defender.population - def_pop_loss)
            
            # 経済デバフ（戦争状態による疲弊 + 投入比率に応じた追加負担）
            agg_war_drain = 1.0 - (COMMITMENT_ECONOMIC_DRAIN * agg_commit)
            def_war_drain = 1.0 - (COMMITMENT_ECONOMIC_DRAIN * def_commit)
            aggressor.economy *= max(0.90, 0.98 * agg_war_drain)
            defender.economy *= max(0.90, 0.98 * def_war_drain)
            
            # 支持率デバフ/ボーナス
            # 攻撃側: 長引く戦争の不満
            aggressor.approval_rating -= 1.0
            
            # 防衛側: Rally 'round the flag 効果 (Mueller 1970, 1973)
            # 自国が侵攻を受けると国民が一致団結し、支持率が一時的に急上昇する。
            # 効果は時間と共に減衰し、長期化すると戦争疲弊（War Fatigue）に転じる。
            war_turns = getattr(war, 'war_turns_elapsed', 0)
            if war_turns <= 4:
                # 初期ラリー効果（最初の4ターン=1年）: 最大+10%→減衰
                rally_bonus = max(0.0, 10.0 - (war_turns * 2.5))  # +10, +7.5, +5.0, +2.5, +0.0
                defender.approval_rating = min(100.0, defender.approval_rating + rally_bonus)
                if rally_bonus > 0:
                    self.sys_logs_this_turn.append(
                        f"[Rally効果] {defender.name}: 国民の結束により支持率 +{rally_bonus:.1f}% "
                        f"(Mueller 1970, 経過{war_turns}ターン)"
                    )
            else:
                # 戦争疲弊期（5ターン目以降）: -1.5%/ターン
                defender.approval_rating -= 1.5
            
            # 戦争経過ターンのカウントアップ
            war.war_turns_elapsed = war_turns + 1
            
            # 占領進捗率の更新 (投入済み戦力の差による)
            power_diff = agg_power - def_power
            progress_change = power_diff / max(1, def_power) * 5.0
            
            war.target_occupation_progress = max(0.0, min(100.0, war.target_occupation_progress + progress_change))
            
            self.log_event(
                f"🔥 【戦況報告】{war.aggressor} vs {war.defender} | "
                f"占領進捗: {war.target_occupation_progress:.1f}% | "
                f"投入率: {war.aggressor}={agg_commit:.0%}, {war.defender}={def_commit:.0%} | "
                f"(両軍損害: {aggressor.name}軍残{aggressor.military:.0f} / {defender.name}軍残{defender.military:.0f} | "
                f"民間人犠牲: {aggressor.name} {agg_pop_loss:.2f}M, {defender.name} {def_pop_loss:.2f}M)",
                involved_countries=[war.aggressor, war.defender, "global"]
            )
            
            self.sys_logs_this_turn.append(
                f"[戦争ダメージ] {war.aggressor}(投入率{agg_commit:.0%}, 投入戦力{agg_committed:.0f}) vs "
                f"{war.defender}(投入率{def_commit:.0%}, 投入戦力{def_committed:.0f}, 防衛ボーナス込み{def_power:.0f}). "
                f"経済負担: {war.aggressor} x{agg_war_drain:.3f}, {war.defender} x{def_war_drain:.3f}"
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
        
        self.log_event(f"💀 【国家崩壊】{loser_name}の政府は崩壊し、{winner_name}に対して無条件降伏しました！", involved_countries=[loser_name, winner_name, "global"])
        
        # 併合ボーナス (経済力の吸収)
        winner.economy += loser.economy * 0.5
        winner.military += loser.military * 0.2
        winner.population += loser.population
        winner.initial_population += loser.initial_population
        self.log_event(f"📈 {winner_name}は{loser_name}の領土と人口({loser.population:.1f}M)を併合しました。", involved_countries=[loser_name, winner_name, "global"])
        
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
                pass
