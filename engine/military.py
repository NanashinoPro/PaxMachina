import random

from .constants import DEFENDER_ADVANTAGE_MULTIPLIER

class MilitaryMixin:
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
            
            agg_damage = def_power * random.uniform(0.05, 0.15)
            def_damage = agg_power * random.uniform(0.05, 0.15)
            
            # 人口減少計算（軍事ダメージ割合に比例。防衛側は戦場となるため民間人被害が大きい）
            agg_pop_loss = aggressor.population * (agg_damage / max(1.0, aggressor.military)) * 0.05
            def_pop_loss = defender.population * (def_damage / max(1.0, defender.military)) * 0.15
            
            aggressor.military = max(0.0, aggressor.military - agg_damage)
            defender.military = max(0.0, defender.military - def_damage)
            
            aggressor.population = max(0.1, aggressor.population - agg_pop_loss)
            defender.population = max(0.1, defender.population - def_pop_loss)
            
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
                f"(両軍損害: {aggressor.name}軍残{aggressor.military:.0f} / {defender.name}軍残{defender.military:.0f} | "
                f"民間人犠牲: {aggressor.name} {agg_pop_loss:.2f}M, {defender.name} {def_pop_loss:.2f}M)",
                involved_countries=[war.aggressor, war.defender, "global"]
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
                # 原産国が滅んでも技術自体は普及し続ける可能性があるが、ここでは伝播を維持し、原産国の表示のみ考慮
                pass
