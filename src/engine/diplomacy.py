import math
import random
from typing import Dict, List, Any
from models import (
    AgentAction, GovernmentType, RelationType, WarState, TradeState,
    SanctionState, SummitProposal, AllianceProposal, AnnexationProposal, CountryState,
    PendingAidProposal, CeasefireProposal, SurrenderDemand
)

class DiplomacyMixin:
    def _get_distance(self, country_a: str, country_b: str) -> float:
        """2国間のHaversine距離（km）を取得。キャッシュがあればそれを使い、なければ計算してキャッシュに追加。"""
        from .economy import _haversine_distance
        
        # economy.pyで構築された距離キャッシュを参照
        if hasattr(self, '_distance_cache') and (country_a, country_b) in self._distance_cache:
            return self._distance_cache[(country_a, country_b)]
        
        # キャッシュにない場合（分裂で新国家が誕生した場合等）はその場で計算
        ca = self.state.countries.get(country_a)
        cb = self.state.countries.get(country_b)
        if ca and cb and hasattr(ca, 'capital_lat') and hasattr(cb, 'capital_lat'):
            dist = _haversine_distance(ca.capital_lat, ca.capital_lon, cb.capital_lat, cb.capital_lon)
            if dist < 100:
                dist = 10000.0  # 座標未設定の場合のデフォルト
            # キャッシュに追加
            if not hasattr(self, '_distance_cache'):
                self._distance_cache = {}
            self._distance_cache[(country_a, country_b)] = dist
            self._distance_cache[(country_b, country_a)] = dist
            return dist
        
        return 10000.0  # フォールバック値

    def _process_foreign_aid(self, actions: Dict[str, AgentAction]):
        """
        対外援助の処理（翌ターン承認制）
        処理順序が重要:
          1. まず前ターンの pending_aid_proposals を承認処理（受入率適用、天引き、オランダ病等）
          2. 次に今ターンの新規援助申請を PendingAidProposal として登録（天引きなし）
        この順序により、今ターンの新規申請が同一ターン内で処理されることを防ぐ。
        """
        # ============================================================
        # ステップ1: 前ターンの援助申請の承認処理
        # ============================================================
        received_aid_econ = {name: 0.0 for name in self.state.countries}
        received_aid_mil = {name: 0.0 for name in self.state.countries}
        
        # 前ターンの pending_aid_proposals をすべて処理して空にする
        proposals_to_process = list(self.state.pending_aid_proposals)
        self.state.pending_aid_proposals = []  # 全てクリア（新規分はステップ2で追加）
        
        for proposal in proposals_to_process:
            donor_name = proposal.donor
            target_name = proposal.target
            
            # 援助元または受取国が消滅している場合はスキップ
            if donor_name not in self.state.countries or target_name not in self.state.countries:
                continue
            
            donor = self.state.countries[donor_name]
            target = self.state.countries[target_name]
            
            # 受取国のアクションから受入率を取得
            acceptance_ratio = 1.0  # デフォルト: 全額受入
            if target_name in actions:
                target_action = actions[target_name]
                for target_dip in target_action.diplomatic_policies:
                    if target_dip.target_country == donor_name:
                        acceptance_ratio = getattr(target_dip, 'aid_acceptance_ratio', 1.0)
                        break
            
            req_econ = proposal.amount_economy * acceptance_ratio
            req_mil = proposal.amount_military * acceptance_ratio
            total_accepted = req_econ + req_mil
            
            # 受入率が0の場合（全拒否）
            if total_accepted <= 0:
                self.sys_logs_this_turn.append(f"[{target_name} 援助拒否] {donor_name}からの援助（経済:{proposal.amount_economy:.1f}, 軍事:{proposal.amount_military:.1f}）を全額拒否")
                self.log_event(f"🚫 【援助拒否】{target_name}が{donor_name}からの援助申請を拒否しました。", involved_countries=[donor_name, target_name])
                continue
            
            # 一部拒否のログ
            if acceptance_ratio < 1.0:
                rejected_econ = proposal.amount_economy * (1.0 - acceptance_ratio)
                rejected_mil = proposal.amount_military * (1.0 - acceptance_ratio)
                self.sys_logs_this_turn.append(f"[{target_name} 援助一部受入] {donor_name}からの援助を{acceptance_ratio*100:.0f}%受入 (拒否分: 経済:{rejected_econ:.1f}, 軍事:{rejected_mil:.1f})")
                self.log_event(f"💰 【援助一部受入】{target_name}が{donor_name}からの援助を{acceptance_ratio*100:.0f}%受け入れました（経済:{req_econ:.1f}, 軍事:{req_mil:.1f}）。", involved_countries=[donor_name, target_name])
            else:
                self.log_event(f"💰 【援助受入】{target_name}が{donor_name}からの援助（経済:{req_econ:.1f}, 軍事:{req_mil:.1f}）を全額受け入れました。", involved_countries=[donor_name, target_name])
            
            # 援助元の予算から承認分のみ天引き
            if total_accepted > donor.government_budget:
                ratio = donor.government_budget / total_accepted
                req_econ *= ratio
                req_mil *= ratio
                total_accepted = donor.government_budget
            
            donor.government_budget -= total_accepted
            received_aid_econ[target_name] += req_econ
            received_aid_mil[target_name] += req_mil
            
            # 依存度の加算
            dependency_addition = total_accepted / max(1.0, target.economy)
            target.dependency_ratio[donor_name] = target.dependency_ratio.get(donor_name, 0.0) + dependency_addition
            
            self.sys_logs_this_turn.append(f"[{donor_name} -> {target_name} 援助実行] 経済: {req_econ:.1f}, 軍事: {req_mil:.1f} (依存度 +{dependency_addition*100:.1f}%)")

        # 援助の流入処理、支持率ボーナス、オランダ病判定
        for target_name, target in self.state.countries.items():
            total_econ = received_aid_econ.get(target_name, 0.0)
            total_mil = received_aid_mil.get(target_name, 0.0)
            total_received = total_econ + total_mil
            
            if total_received <= 0:
                continue
            
            # 援助受取の支持率ボーナス（Blair & Roessler 2021）
            # 政府経由の援助 → 「政府が支援を引き出す能力がある」と評価され、支持率にプラス
            # log1p で逓減効果を実現し、巨額援助でも支持率が無限に上がらないようにする
            aid_to_gdp_ratio = total_received / max(1.0, target.economy)
            approval_bonus = min(3.0, math.log1p(aid_to_gdp_ratio * 10.0) * 1.5)
            target.approval_rating = min(100.0, target.approval_rating + approval_bonus)
            self.sys_logs_this_turn.append(f"[{target_name} 援助受取ボーナス] 支持率 +{approval_bonus:.1f}% (Blair & Roessler 2021)")
                
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
            
            for donor_name, dep_ratio in target.dependency_ratio.items():
                if dep_ratio > 0.60 and target.suzerain != donor_name:
                    target.suzerain = donor_name
                    self.log_event(f"👑 【属国化】{target_name}は{donor_name}からの巨額の経済・軍事支援により主権を喪失し、完全に{donor_name}の属国（傀儡国家）となりました。", involved_countries=[target_name, donor_name, "global"])
                    self.sys_logs_this_turn.append(f"[{target_name} 属国化] {donor_name}への依存度が {dep_ratio*100:.1f}% に達し、主権喪失。")




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
                    if self.db_manager:
                        self.db_manager.add_event(self.state.turn, "secret_message", f"【{country_name}からの極秘通信】\n{dip.message}", True, [country_name, target_name])
                else:
                    self.log_event(f"[{country_name} -> {target_name}] メッセージ送信: {dip.message}", involved_countries=[country_name, target_name])
                
            # 同盟提案の処理 (相互合意メカニズム: 相手も同ターンまたは前ターンにpropose_allianceしていれば成立)
            if dip.propose_alliance:
                rel = self._get_relation(country_name, target_name)
                if rel == RelationType.AT_WAR:
                    self.log_event(f"⚠️ {country_name}から{target_name}への同盟提案は戦争状態のため無効です。", involved_countries=[country_name, target_name])
                elif rel == RelationType.ALLIANCE:
                    pass  # 既に同盟済み
                else:
                    # 前ターンに相手から提案が来ているか確認
                    matched = [a for a in self.state.pending_alliances if a.proposer == target_name and a.target == country_name]
                    if matched:
                        # 双方合意成立！
                        self._update_relation(country_name, target_name, RelationType.ALLIANCE)
                        self.log_event(f"🤝 {country_name}と{target_name}が相互合意の上、軍事同盟を締結しました。", involved_countries=[country_name, target_name, "global"])
                        self.state.pending_alliances.remove(matched[0])
                    else:
                        # 提案をキューに積む（翌ターン以降に相手が受諾すれば成立）
                        existing = [a for a in self.state.pending_alliances if a.proposer == country_name and a.target == target_name]
                        if not existing:
                            self.state.pending_alliances.append(AllianceProposal(proposer=country_name, target=target_name))
                            self.log_event(f"✉️ {country_name}が{target_name}に対して軍事同盟を提案しました。（相手の合意を待機中）", involved_countries=[country_name, target_name])
                
            # 宣戦布告
            if dip.declare_war:
                rel = self._get_relation(country_name, target_name)
                if rel != RelationType.AT_WAR:
                    self._update_relation(country_name, target_name, RelationType.AT_WAR)
                    # 新しい戦争を作成（デフォルト投入比率を適用）
                    from .constants import DEFAULT_AGGRESSOR_COMMITMENT, DEFAULT_DEFENDER_COMMITMENT
                    new_war = WarState(
                        aggressor=country_name, defender=target_name,
                        aggressor_commitment_ratio=DEFAULT_AGGRESSOR_COMMITMENT,
                        defender_commitment_ratio=DEFAULT_DEFENDER_COMMITMENT
                    )
                    self.state.active_wars.append(new_war)
                    self.log_event(f"⚔️ 【開戦】{country_name}が{target_name}に対して宣戦布告しました！（投入率: 攻撃側{DEFAULT_AGGRESSOR_COMMITMENT:.0%}, 防衛側{DEFAULT_DEFENDER_COMMITMENT:.0%}）", involved_countries=[country_name, target_name, "global"])
            
            # 共同防衛参加（join_ally_defense）— 有志連合型
            # 攻撃国と交戦中でない限り、任意の防衛側の戦争に防衛支援国として合流可能。
            # target_countryは攻撃国（敵国）を指定。攻撃国との直接戦争は発生しない。
            if getattr(dip, 'join_ally_defense', False):
                attacker_name = target_name  # target_country = 攻撃国（敵国）
                support_commit = getattr(dip, 'defense_support_commitment', None) or 0.10
                support_commit = max(0.01, min(0.50, support_commit))
                
                # 攻撃国が防衛側の戦争を検索（同盟制限なし）
                joined = False
                for w in self.state.active_wars:
                    if w.aggressor == attacker_name:
                        # 自国が攻撃国と交戦中でないかチェック（自己矛盾防止）
                        rel_with_attacker = self._get_relation(country_name, attacker_name)
                        if rel_with_attacker == RelationType.AT_WAR:
                            self.sys_logs_this_turn.append(
                                f"[{country_name}] 共同防衛失敗: {attacker_name}とは既に交戦中のため、"
                                f"防衛支援国としての参加は不可"
                            )
                            break
                        
                        # 自国が防衛側本人の場合はスキップ（自分の戦争に支援国として参加する矛盾防止）
                        if w.defender == country_name:
                            continue
                        
                        # 既に支援国として参加しているかチェック
                        if country_name in w.defender_supporters:
                            self.sys_logs_this_turn.append(
                                f"[{country_name}] 既に{w.defender}の防衛に参加中。投入率更新: {w.defender_supporters[country_name]:.0%} → {support_commit:.0%}"
                            )
                            w.defender_supporters[country_name] = support_commit
                        else:
                            w.defender_supporters[country_name] = support_commit
                            rel_with_defender = self._get_relation(country_name, w.defender)
                            rel_label = "同盟国" if rel_with_defender == RelationType.ALLIANCE else "友好国"
                            self.log_event(
                                f"🛡️ 【共同防衛】{country_name}が{rel_label}{w.defender}の防衛に参加！"
                                f"（対{attacker_name}戦に{support_commit:.0%}の戦力を投入）",
                                involved_countries=[country_name, w.defender, attacker_name, "global"]
                            )
                            self.sys_logs_this_turn.append(
                                f"[共同防衛] {country_name}が{w.defender}の防衛支援国として参加 "
                                f"(対{attacker_name}戦, 投入率{support_commit:.0%}, 関係={rel_with_defender.value})"
                            )
                        joined = True
                        break
                
                if not joined:
                    self.sys_logs_this_turn.append(
                        f"[{country_name}] 共同防衛失敗: {attacker_name}が攻撃側の戦争が見つかりません"
                    )
            
            # 軍事侵攻比率の変更（交戦中の場合）— Rate Limiter適用
            if getattr(dip, 'war_commitment_ratio', None) is not None:
                from .constants import MIN_COMMITMENT_RATIO, MAX_COMMITMENT_CHANGE_PER_TURN
                new_ratio = max(MIN_COMMITMENT_RATIO, min(1.0, dip.war_commitment_ratio))
                for w in self.state.active_wars:
                    if w.aggressor == country_name and w.defender == target_name:
                        old_ratio = w.aggressor_commitment_ratio
                        # Rate Limiter: 1ターンあたり±MAX_COMMITMENT_CHANGE_PER_TURNに制限
                        clamped_ratio = max(old_ratio - MAX_COMMITMENT_CHANGE_PER_TURN,
                                            min(old_ratio + MAX_COMMITMENT_CHANGE_PER_TURN, new_ratio))
                        clamped_ratio = max(MIN_COMMITMENT_RATIO, min(1.0, clamped_ratio))
                        w.aggressor_commitment_ratio = clamped_ratio
                        if abs(clamped_ratio - new_ratio) > 0.001:
                            self.sys_logs_this_turn.append(f"[{country_name} 投入比率変更 ⚠️Rate Limit] 対{target_name}戦: {old_ratio:.0%} → {clamped_ratio:.0%} (要求値{new_ratio:.0%}は±{MAX_COMMITMENT_CHANGE_PER_TURN:.0%}制限により却下)")
                        else:
                            self.sys_logs_this_turn.append(f"[{country_name} 投入比率変更] 対{target_name}戦: {old_ratio:.0%} → {clamped_ratio:.0%}")
                        self.log_event(f"📊 {country_name}が対{target_name}戦への軍事投入比率を{old_ratio:.0%}から{clamped_ratio:.0%}に変更しました。", involved_countries=[country_name, target_name, "global"])
                        break
                    elif w.defender == country_name and w.aggressor == target_name:
                        old_ratio = w.defender_commitment_ratio
                        # Rate Limiter: 1ターンあたり±MAX_COMMITMENT_CHANGE_PER_TURNに制限
                        clamped_ratio = max(old_ratio - MAX_COMMITMENT_CHANGE_PER_TURN,
                                            min(old_ratio + MAX_COMMITMENT_CHANGE_PER_TURN, new_ratio))
                        clamped_ratio = max(MIN_COMMITMENT_RATIO, min(1.0, clamped_ratio))
                        w.defender_commitment_ratio = clamped_ratio
                        if abs(clamped_ratio - new_ratio) > 0.001:
                            self.sys_logs_this_turn.append(f"[{country_name} 投入比率変更 ⚠️Rate Limit] 対{target_name}戦: {old_ratio:.0%} → {clamped_ratio:.0%} (要求値{new_ratio:.0%}は±{MAX_COMMITMENT_CHANGE_PER_TURN:.0%}制限により却下)")
                        else:
                            self.sys_logs_this_turn.append(f"[{country_name} 投入比率変更] 対{target_name}戦: {old_ratio:.0%} → {clamped_ratio:.0%}")
                        self.log_event(f"📊 {country_name}が対{target_name}戦への軍事投入比率を{old_ratio:.0%}から{clamped_ratio:.0%}に変更しました。", involved_countries=[country_name, target_name, "global"])
                        break
                    
            # 停戦提案（同盟提案と同じ双方向メカニズム）
            if getattr(dip, 'propose_ceasefire', False):
                # 交戦中か確認
                war = self._find_war(country_name, target_name)
                if war:
                    # 相手から同一ターンまたは前ターンに既に提案が来ているか確認
                    matched = [c for c in self.state.pending_ceasefires if c.proposer == target_name and c.target == country_name]
                    if matched:
                        # 双方合意 → 講和会談を実行
                        self.log_event(f"🕊️ {country_name}と{target_name}が停戦に合意しました。講和会談が開催されます。", involved_countries=[country_name, target_name, "global"])
                        self._execute_peace_conference(war)
                        self.state.pending_ceasefires.remove(matched[0])
                    else:
                        # 提案をキューに積む（翌ターン以降に相手が受諾すれば成立）
                        existing = [c for c in self.state.pending_ceasefires if c.proposer == country_name and c.target == target_name]
                        if not existing:
                            self.state.pending_ceasefires.append(CeasefireProposal(proposer=country_name, target=target_name))
                            self.log_event(f"🏳️ {country_name}が{target_name}に対して停戦を提案しました。（相手の合意を待機中）", involved_countries=[country_name, target_name, "global"])
                else:
                    self.sys_logs_this_turn.append(f"[{country_name}] 停戦提案: {target_name}と交戦中ではないためスキップ")
            
            # 停戦受諾
            if getattr(dip, 'accept_ceasefire', False):
                matched = [c for c in self.state.pending_ceasefires if c.proposer == target_name and c.target == country_name]
                if matched:
                    war = self._find_war(country_name, target_name)
                    if war:
                        self.log_event(f"🕊️ {country_name}が{target_name}からの停戦提案を受諾しました。講和会談が開催されます。", involved_countries=[country_name, target_name, "global"])
                        self._execute_peace_conference(war)
                        self.state.pending_ceasefires.remove(matched[0])
            
            # 降伏勧告（攻撃側のみ）
            if getattr(dip, 'demand_surrender', False):
                war = self._find_war_as_aggressor(country_name, target_name)
                if war:
                    existing = [s for s in self.state.pending_surrenders if s.aggressor == country_name and s.defender == target_name]
                    if not existing:
                        self.state.pending_surrenders.append(SurrenderDemand(aggressor=country_name, defender=target_name))
                        self.log_event(f"⚠️ 【降伏勧告】{country_name}が{target_name}に対して無条件降伏を要求しました！", involved_countries=[country_name, target_name, "global"])
                        # 防衛側のprivate_messagesに通知
                        if target_name in self.state.countries:
                            self.state.countries[target_name].private_messages.append(f"【{country_name}からの降伏勧告】\n我が国は貴国に対し、即時の無条件降伏を要求する。受諾すれば国家は消滅する。")
                else:
                    self.sys_logs_this_turn.append(f"[{country_name}] 降伏勧告: {target_name}への攻撃側ではないためスキップ")
            
            # 降伏受諾
            if getattr(dip, 'accept_surrender', False):
                matched = [s for s in self.state.pending_surrenders if s.aggressor == target_name and s.defender == country_name]
                if matched:
                    war = self._find_war(country_name, target_name)
                    if war:
                        # 占領率を即時100%に設定 → _process_warsで_handle_defeatが自動適用
                        war.target_occupation_progress = 100.0
                        self.log_event(f"💀 【降伏受諾】{country_name}が{target_name}の降伏勧告を受諾しました。占領率が即座に100%に設定されます。", involved_countries=[country_name, target_name, "global"])
                    self.state.pending_surrenders.remove(matched[0])

            # 諜報工作
            if dip.espionage_gather_intel or dip.espionage_sabotage:
                self._process_espionage(country_name, target_name, dip)

            # 貿易・制裁
            if getattr(dip, 'propose_trade', False):
                self.log_event(f"🤝 {country_name}から{target_name}へ貿易・経済協力の提案がなされました。", involved_countries=[country_name, target_name])
                rel = self._get_relation(country_name, target_name)
                if rel != RelationType.AT_WAR:
                    existing = [t for t in self.state.active_trades if (t.country_a == country_name and t.country_b == target_name) or (t.country_a == target_name and t.country_b == country_name)]
                    if not existing:
                        self.state.active_trades.append(TradeState(country_a=country_name, country_b=target_name))
                        self.log_event(f"🚢 {country_name}と{target_name}の間で貿易協定が開始されました。", involved_countries=[country_name, target_name, "global"])
            
            if getattr(dip, 'cancel_trade', False):
                self.log_event(f"⚠️ {country_name}が{target_name}との貿易協定を破棄しました。", involved_countries=[country_name, target_name, "global"])
                self.state.active_trades = [t for t in self.state.active_trades if not ((t.country_a == country_name and t.country_b == target_name) or (t.country_a == target_name and t.country_b == country_name))]
            
            if getattr(dip, 'impose_sanctions', False):
                self.log_event(f"⛔ {country_name}が{target_name}に対して本格的な経済制裁を発動しました。", involved_countries=[country_name, target_name, "global"])
                existing = [s for s in self.state.active_sanctions if s.imposer == country_name and s.target == target_name]
                if not existing:
                    self.state.active_sanctions.append(SanctionState(imposer=country_name, target=target_name))
            
            if getattr(dip, 'lift_sanctions', False):
                self.log_event(f"✅ {country_name}が{target_name}への経済制裁を解除しました。", involved_countries=[country_name, target_name, "global"])
                self.state.active_sanctions = [s for s in self.state.active_sanctions if not (s.imposer == country_name and s.target == target_name)]

            # 首脳会談の提案
            if dip.propose_summit:
                is_private_summit = getattr(dip, 'is_private', False)
                self.state.pending_summits.append(SummitProposal(proposer=country_name, target=target_name, topic=dip.summit_topic, is_private=is_private_summit))
                if is_private_summit:
                    self.sys_logs_this_turn.append(f"[非公開会談提案] {country_name} -> {target_name}: {dip.summit_topic}")
                    if target_name in self.state.countries:
                        self.state.countries[target_name].private_messages.append(f"【{country_name}からの極秘の会談提案】\n議題: {dip.summit_topic}")
                    if self.db_manager:
                        self.db_manager.add_event(self.state.turn, "summit_proposal", f"【{country_name}からの極秘の会談提案】\n議題: {dip.summit_topic}", True, [country_name, target_name])
                else:
                    self.log_event(f"✉️ {country_name}が{target_name}に対して首脳会談を提案しました。議題: {dip.summit_topic}", involved_countries=[country_name, target_name])

            # 首脳会談の受諾（2国間・多国間共通）
            if dip.accept_summit:
                # 2国間会談の受諾
                matched = [s for s in self.state.pending_summits if s.proposer == target_name and s.target == country_name and not s.participants]
                if matched:
                    proposal = matched[0]
                    self.summits_to_run_this_turn.append(proposal)
                    if proposal.is_private:
                        self.sys_logs_this_turn.append(f"[非公開会談受諾] {country_name}が{target_name}からの提案を受諾。")
                        if self.db_manager:
                             self.db_manager.add_event(self.state.turn, "summit_accept", f"【非公開の会談成立】{country_name}が{target_name}との極秘会談（議題: {proposal.topic}）について受諾した", True, [country_name, target_name])
                    else:
                        self.log_event(f"✅ {country_name}が{target_name}からの首脳会談の提案（議題: {proposal.topic}）を受諾しました。会談が開催されます。", involved_countries=[country_name, target_name, "global"])
                    self.state.pending_summits.remove(proposal)
                
                # 多国間会談の受諾（自国がparticipantsに含まれている提案を探す）
                for s in list(self.state.pending_summits):
                    if s.participants and country_name in s.participants and country_name not in s.accepted_participants:
                        s.accepted_participants.append(country_name)
                        if s.is_private:
                            self.sys_logs_this_turn.append(f"[多国間非公開会談受諾] {country_name}が{s.proposer}主催の多国間会談を受諾。")
                        else:
                            self.log_event(f"✅ {country_name}が{s.proposer}主催の多国間首脳会談（議題: {s.topic}）への参加を表明しました。", involved_countries=[country_name, s.proposer])
            
            # 多国間首脳会談の提案
            if getattr(dip, 'propose_multilateral_summit', False):
                summit_participants_list = getattr(dip, 'summit_participants', [])
                if not summit_participants_list:
                    # summit_participantsが空の場合、target_countryを唯一の参加者として扱う
                    summit_participants_list = [target_name]
                
                # ホスト国を含む全参加国リストを構築
                all_participants = [country_name] + [p for p in summit_participants_list if p != country_name and p in self.state.countries]
                
                if len(all_participants) >= 2:
                    is_private_summit = getattr(dip, 'is_private', False)
                    new_proposal = SummitProposal(
                        proposer=country_name,
                        target="",
                        topic=dip.summit_topic or "多国間協議",
                        is_private=is_private_summit,
                        participants=all_participants,
                        accepted_participants=[country_name]  # ホスト国は自動受諾
                    )
                    self.state.pending_summits.append(new_proposal)
                    
                    invited_names = ", ".join(p for p in all_participants if p != country_name)
                    if is_private_summit:
                        self.sys_logs_this_turn.append(f"[非公開多国間会談提案] {country_name} -> {invited_names}: {new_proposal.topic}")
                        for p in all_participants:
                            if p != country_name and p in self.state.countries:
                                self.state.countries[p].private_messages.append(f"【{country_name}からの極秘の多国間会談招待】\n議題: {new_proposal.topic}\n参加国: {', '.join(all_participants)}")
                    else:
                        self.log_event(f"🌐 {country_name}が{invited_names}を招待し、多国間首脳会談を提案しました。議題: {new_proposal.topic}", involved_countries=all_participants)
                    
            # 平和的統合（吸収合併）の提案
            if getattr(dip, 'propose_annexation', False):
                existing = [a for a in self.state.pending_annexations if a.proposer == country_name and a.target == target_name]
                if not existing:
                    self.state.pending_annexations.append(AnnexationProposal(proposer=country_name, target=target_name))
                    if getattr(dip, 'is_private', False):
                         self.sys_logs_this_turn.append(f"[非公開統合提案] {country_name} -> {target_name}")
                         if target_name in self.state.countries:
                             self.state.countries[target_name].private_messages.append(f"【{country_name}からの極秘の国家統合提案】\n我が国への合流を提案する。")
                         if self.db_manager:
                             self.db_manager.add_event(self.state.turn, "annexation_proposal", f"【{country_name}からの極秘の統合提案】\n{target_name}に対して国家の統合を提案。秘密裏に行われた。", True, [country_name, target_name])
                    else:
                         self.log_event(f"📜 {country_name}が{target_name}に対して平和的で対等な「国家統合」を提案しました。（{target_name}の合意を待機中）", involved_countries=[country_name, target_name, "global"])

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
                            self.log_event(f"❌ {country_name}の指導部が{target_name}との国家統合を試みましたが、国民投票および議会で反対多数により否決され、統合は白紙となりました。", involved_countries=[country_name, target_name, "global"])
                            self.sys_logs_this_turn.append(f"[{country_name} 統合否決] 乱数 {roll:.1f} > 支持率 {country.approval_rating:.1f}")
                            continue # 次のdiplomatic policyへ
                        else:
                            self.sys_logs_this_turn.append(f"[{country_name} 統合承認] 乱数 {roll:.1f} <= 支持率 {country.approval_rating:.1f}")

                    self._handle_peaceful_annexation(target_name, country_name)
                    # 統合された国はすでにself.state.countriesから削除されているため、これ以上ループを進めない
                    break

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
            
            strategy = (action.espionage_sabotage_strategy or "").lower()
            
            if is_success:
                dmg_approval = random.uniform(5.0, 15.0)
                dmg_econ_multiplier = 0.95
                
                if any(k in strategy for k in ["sns", "情報", "フェイク", "デマ", "世論", "プロパガンダ", "インフル", "選挙", "メディア", "認知戦"]):
                    dmg_approval = random.uniform(10.0, 20.0)
                    dmg_econ_multiplier = 0.98
                    self.log_event(f"📱 {target_name}のネット空間や社会で大規模な混乱や不審な世論操作の痕跡が確認され、政権支持率が急落しています。", involved_countries=[target_name, "global"])
                elif any(k in strategy for k in ["インフラ", "爆破", "物理", "暗殺", "テロ", "マルウェア", "ハッキング", "システム", "電力", "サイバー", "通信", "ネットワーク"]):
                    dmg_econ_multiplier = 0.90
                    dmg_approval = random.uniform(2.0, 6.0)
                    self.log_event(f"💻 {target_name}の社会インフラ・主要システムに原因不明の重大な障害が発生しました。", involved_countries=[target_name, "global"])
                else:
                    self.log_event(f"💣 {target_name}で社会不安を高める不審な事件が連続して発生しています。", involved_countries=[target_name, "global"])
                    
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
                    self.log_event(f"🚨 【重大事態】{target_name}を襲った一連の事件について、当局の捜査により{attacker_name}の工作機関による関与であったことが特定され、白日の下に晒されました！", involved_countries=[target_name, attacker_name, "global"])
                else:
                    self.log_event(f"🚨 【工作未遂・発覚】{target_name}の防諜機関が、{attacker_name}による工作計画「{action.espionage_sabotage_strategy}」を未然に阻止し、大々的に摘発しました！", involved_countries=[target_name, attacker_name, "global"])
            else:
                if not is_success:
                     # 失敗かつ未発覚：相手のニュースにも自国のニュースにも出ない扱いとし、エージェントの思考ループを防ぐためプロンプトにはフィードバックしない
                     pass

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

            # 発覚処理
            if is_discovered:
                if is_success:
                    self.log_event(f"🚨 【情報漏洩発覚】{target_name}の政府システムや要人周辺から、{attacker_name}へと何らかの機密情報が流出していた痕跡が発見されました。", involved_countries=[target_name, attacker_name, "global"])
                else:
                    self.log_event(f"🚨 【スパイ摘発】{attacker_name}の諜報員が{target_name}にて機密情報を探っていたところを現地当局に発見され、強制排除されました。情報の流出は阻止されました。", involved_countries=[target_name, attacker_name, "global"])

    def _handle_peaceful_annexation(self, absorber_name: str, absorbed_name: str):
        absorber = self.state.countries[absorber_name]
        absorbed = self.state.countries[absorbed_name]
        
        self.log_event(f"🕊️ 【国家統合】歴史的合意に基づき、{absorbed_name}は国家を解散し、{absorber_name}と平和的に統合しました！", involved_countries=[absorbed_name, absorber_name, "global"])
        
        # 併合ボーナス (リソースの完全引継ぎ)
        absorber.economy += absorbed.economy
        absorber.military += absorbed.military
        absorber.population += absorbed.population
        absorber.initial_population += absorbed.initial_population
        # 行政の効率化・技術の統合：諜報や教育は（平均ではなく）高い方をベースにボーナスを加える等も考えられるが、ここでは現状を維持しつつ少し微増させる
        absorber.intelligence_level = max(absorber.intelligence_level, absorbed.intelligence_level) + 1.0
        
        # 国債の引継ぎ
        absorber.national_debt += absorbed.national_debt
        
        self.log_event(f"📈 {absorber_name}は{absorbed_name}の全領土、インフラ、そして市民を迎え入れ、新たな大国家として生まれ変わりました。", involved_countries=[absorbed_name, absorber_name, "global"])
        
        # 吸収された国を世界から削除
        del self.state.countries[absorbed_name]
        
        # 共通クリーンアップ関数で関連データを一括削除
        self._cleanup_eliminated_country(absorbed_name)

    def _resolve_vacuum_auctions(self, actions):
        """パワー・バキューム・オークションの解決（Tullock Contest Success Function）
        
        [学術的根拠]
        - Tullock, G. (1980). Efficient Rent Seeking.
        - Hirshleifer, J. (1989). Conflict and Rent-Seeking Success Functions.
        - Wolfers & Morgenthau: パワー・バキュームは周辺大国を引き寄せる重力を持つ。
        
        各大国のベット（vacuum_bid）と新国家の軍事力（独立防衛ベット）を集計し、
        Tullock CSF で確率的に吸収 or 独立を決定する。
        """
        import math
        
        for auction in list(self.state.pending_vacuum_auctions):
            new_name = auction["new_country"]
            old_name = auction["old_country"]
            new_mil = auction["new_military"]  # 新国家の独立防衛ベット（全軍事力）
            
            if new_name not in self.state.countries:
                continue
            
            # 全国のベットを集計
            bids = {}
            for country_name, action in actions.items():
                if country_name == new_name:
                    continue
                if country_name not in self.state.countries:
                    continue
                    
                for dip in action.diplomatic_policies:
                    if dip.target_country == new_name:
                        raw_bid = getattr(dip, 'vacuum_bid', 0.0)
                        if raw_bid <= 0:
                            continue
                        
                        # ベット上限 = 自国軍事力
                        bid = min(raw_bid, self.state.countries[country_name].military)
                        
                        # 地理的距離ペナルティ（遠い国ほど介入コストが高い）
                        distance = self._get_distance(country_name, new_name)
                        distance_penalty = 1.0 / (1.0 + distance / 5000.0)
                        
                        # 同盟関係ボーナス
                        rel = self._get_relation(country_name, old_name)
                        if rel == RelationType.ALLIANCE:
                            alliance_bonus = 1.5  # 同盟国の混乱 → 保護下に置く動機
                        elif rel == RelationType.AT_WAR:
                            alliance_bonus = 2.0  # 敵国の分裂 → 漁夫の利
                        else:
                            alliance_bonus = 1.0
                        
                        effective_bid = bid * distance_penalty * alliance_bonus
                        bids[country_name] = {
                            "raw_bid": bid,
                            "effective_bid": effective_bid,
                            "distance": distance,
                            "distance_penalty": distance_penalty,
                            "alliance_bonus": alliance_bonus,
                        }
            
            # Tullock CSF で確率計算
            total_effective = sum(b["effective_bid"] for b in bids.values()) + new_mil
            if total_effective <= 0:
                continue
            
            # 確率テーブルを作成
            outcomes = {}
            outcomes["🗽独立"] = new_mil / total_effective
            for bidder, bid_info in bids.items():
                outcomes[bidder] = bid_info["effective_bid"] / total_effective
            
            # ログ出力（確率テーブル）
            prob_log = ", ".join([f"{k}: {v:.1%}" for k, v in outcomes.items()])
            self.sys_logs_this_turn.append(
                f"[パワー・バキューム・オークション] {new_name} (旧:{old_name}): {prob_log}"
            )
            for bidder, bid_info in bids.items():
                self.sys_logs_this_turn.append(
                    f"  └ {bidder}: raw_bid={bid_info['raw_bid']:.1f}, "
                    f"距離={bid_info['distance']:.0f}km(x{bid_info['distance_penalty']:.2f}), "
                    f"同盟補正(x{bid_info['alliance_bonus']:.1f}) → effective={bid_info['effective_bid']:.1f}"
                )
            
            # 乱数で決定
            roll = random.random()
            cumulative = 0.0
            winner = "🗽独立"
            for name, prob in outcomes.items():
                cumulative += prob
                if roll < cumulative:
                    winner = name
                    break
            
            self.sys_logs_this_turn.append(
                f"[パワー・バキューム結果] roll={roll:.4f} → 勝者: {winner}"
            )
            
            if winner == "🗽独立":
                self.log_event(
                    f"🗽 【独立確定】{new_name}は全ての大国の介入を退け、"
                    f"独立を勝ち取りました！（独立確率: {outcomes['🗽独立']:.1%}）",
                    involved_countries=[new_name, "global"]
                )
            else:
                # 吸収処理
                absorb_prob = outcomes.get(winner, 0.0)
                self.log_event(
                    f"🏴 【日和見的併合】{winner}が{new_name}の混乱に乗じて軍事介入！"
                    f"パワー・バキュームを埋め、同地域を自国に編入しました！"
                    f"（吸収確率: {absorb_prob:.1%}）",
                    involved_countries=[winner, new_name, old_name, "global"]
                )
                self._handle_peaceful_annexation(winner, new_name)
        
        # オークションリストをクリア
        self.state.pending_vacuum_auctions.clear()

    def _resolve_influence_auctions(self, actions):
        """影響力介入オークションの解決（軽量版パワー・バキューム）
        
        [学術的根拠]
        - Morgenthau, H. (1948). Politics Among Nations: パワー・バキュームは周辺大国の介入を誘発する。
        - Tullock, G. (1980). Efficient Rent Seeking: コンテスト成功関数。
        - 歴史的実例: ウクライナ政変(2014)→ロシア介入、エジプト政変(2013)→サウジ/UAE影響力拡大
        
        クーデター/革命で政変が発生した国に対し、周辺国が vacuum_bid で介入。
        分裂版と異なり、結果は「依存度の上昇」であり領土併合は発生しない。
        """
        from .constants import INFLUENCE_AUCTION_DEPENDENCY_GAIN, INFLUENCE_AUCTION_INDEPENDENCE_BONUS
        
        for auction in list(self.state.pending_influence_auctions):
            target_name = auction["target_country"]
            target_economy = auction["target_economy"]  # GDP = 独立防衛ベット
            
            if target_name not in self.state.countries:
                continue
            
            target = self.state.countries[target_name]
            
            # 全国のベットを集計
            bids = {}
            for country_name, action in actions.items():
                if country_name == target_name:
                    continue
                if country_name not in self.state.countries:
                    continue
                    
                for dip in action.diplomatic_policies:
                    if dip.target_country == target_name:
                        raw_bid = getattr(dip, 'vacuum_bid', 0.0)
                        if raw_bid <= 0:
                            continue
                        
                        # ベット上限 = 自国軍事力
                        bid = min(raw_bid, self.state.countries[country_name].military)
                        
                        # 地理的距離ペナルティ（遠い国ほど介入コストが高い）
                        distance = self._get_distance(country_name, target_name)
                        distance_penalty = 1.0 / (1.0 + distance / 5000.0)
                        
                        # 関係性ボーナス
                        rel = self._get_relation(country_name, target_name)
                        if rel == RelationType.ALLIANCE:
                            rel_bonus = 1.5  # 同盟国の混乱 → 保護下に置く動機
                        elif rel == RelationType.AT_WAR:
                            rel_bonus = 2.0  # 敵国の政変 → 漁夫の利
                        else:
                            rel_bonus = 1.0
                        
                        effective_bid = bid * distance_penalty * rel_bonus
                        bids[country_name] = {
                            "raw_bid": bid,
                            "effective_bid": effective_bid,
                            "distance": distance,
                            "distance_penalty": distance_penalty,
                            "rel_bonus": rel_bonus,
                        }
            
            # GDP防衛ベット: GDPが高い国ほど外部介入に抵抗できる
            # スケール調整: GDPをそのまま使うと大国すぎて常に独立になるため、ログスケールで圧縮
            defense_bet = math.log1p(target_economy) * 10.0
            
            # Tullock CSF で確率計算
            total_effective = sum(b["effective_bid"] for b in bids.values()) + defense_bet
            if total_effective <= 0:
                continue
            
            # 確率テーブルを作成
            outcomes = {}
            outcomes["🛡️自力回復"] = defense_bet / total_effective
            for bidder, bid_info in bids.items():
                outcomes[bidder] = bid_info["effective_bid"] / total_effective
            
            # ログ出力（確率テーブル）
            prob_log = ", ".join([f"{k}: {v:.1%}" for k, v in outcomes.items()])
            self.sys_logs_this_turn.append(
                f"[影響力介入オークション] {target_name} (政変): 防衛GDP={target_economy:.1f}→defense_bet={defense_bet:.1f}: {prob_log}"
            )
            for bidder, bid_info in bids.items():
                self.sys_logs_this_turn.append(
                    f"  └ {bidder}: raw_bid={bid_info['raw_bid']:.1f}, "
                    f"距離={bid_info['distance']:.0f}km(x{bid_info['distance_penalty']:.2f}), "
                    f"関係補正(x{bid_info['rel_bonus']:.1f}) → effective={bid_info['effective_bid']:.1f}"
                )
            
            # 乱数で決定
            roll = random.random()
            cumulative = 0.0
            winner = "🛡️自力回復"
            for name, prob in outcomes.items():
                cumulative += prob
                if roll < cumulative:
                    winner = name
                    break
            
            self.sys_logs_this_turn.append(
                f"[影響力介入結果] roll={roll:.4f} → 勝者: {winner}"
            )
            
            if winner == "🛡️自力回復":
                # 外部介入を退けた → 支持率ボーナス
                target.approval_rating = min(100.0, target.approval_rating + INFLUENCE_AUCTION_INDEPENDENCE_BONUS)
                self.log_event(
                    f"🛡️ 【外部介入阻止】{target_name}は政変の混乱期において全ての大国の干渉を退け、"
                    f"自力で国内秩序を回復しました。（抵抗確率: {outcomes['🛡️自力回復']:.1%}）",
                    involved_countries=[target_name, "global"]
                )
            else:
                # 勝者が影響力を獲得 → 依存度上昇
                old_dep = target.dependency_ratio.get(winner, 0.0)
                new_dep = min(1.0, old_dep + INFLUENCE_AUCTION_DEPENDENCY_GAIN)
                target.dependency_ratio[winner] = new_dep
                
                influence_prob = outcomes.get(winner, 0.0)
                self.log_event(
                    f"🕸️ 【影響力拡大】{winner}が{target_name}の政変に乗じて介入！"
                    f"経済・軍事支援を通じて同国への影響力を大幅に拡大しました。"
                    f"（依存度: {old_dep*100:.1f}% → {new_dep*100:.1f}%, 介入確率: {influence_prob:.1%}）",
                    involved_countries=[winner, target_name, "global"]
                )
                
                self.sys_logs_this_turn.append(
                    f"[影響力介入] {winner} → {target_name}: 依存度 {old_dep*100:.1f}% → {new_dep*100:.1f}% "
                    f"(+{INFLUENCE_AUCTION_DEPENDENCY_GAIN*100:.0f}%)"
                )
                
                # 依存度60%超で属国化チェック（既存ロジックが次ターンで自動適用される）
                if new_dep >= 0.6:
                    self.sys_logs_this_turn.append(
                        f"[⚠️ 属国化リスク] {target_name}の{winner}への依存度が{new_dep*100:.1f}%に到達。"
                        f"次ターン以降、属国化判定が行われます。"
                    )
        
        # オークションリストをクリア
        self.state.pending_influence_auctions.clear()

    def _find_war(self, country_a: str, country_b: str):
        """2国間の戦争を検索（攻撃/防衛の順序は問わない）"""
        for w in self.state.active_wars:
            if (w.aggressor == country_a and w.defender == country_b) or \
               (w.aggressor == country_b and w.defender == country_a):
                return w
        return None

    def _find_war_as_aggressor(self, aggressor: str, defender: str):
        """指定国が攻撃側である戦争を検索"""
        for w in self.state.active_wars:
            if w.aggressor == aggressor and w.defender == defender:
                return w
        return None

    def _execute_peace_conference(self, war: WarState):
        """
        講和会談フェーズ:
        1. 国境線の引き直し + 人口移転（占領率に基づく）
        2. 賠償金の精算
        3. 関係値のリセット（at_war → neutral）
        4. 戦争リストからの削除
        5. 関連する停戦提案・降伏勧告のクリーンアップ
        """
        aggressor = self.state.countries.get(war.aggressor)
        defender = self.state.countries.get(war.defender)
        
        if not aggressor or not defender:
            return
        
        occupation = war.target_occupation_progress  # 0-100スケール
        
        # --- 1. 国境線の引き直し + 人口移転 ---
        if occupation >= 3.0:
            # 占領率3%以上: 占領率に応じた領土と人口を攻撃側に移転
            transfer_ratio = occupation / 100.0
            
            # 領土の移転
            transferred_area = defender.area * transfer_ratio
            defender.area -= transferred_area
            aggressor.area += transferred_area
            
            # 人口の移転（占領地域の住民が攻撃側の管轄下に入る）
            transferred_pop = defender.population * transfer_ratio
            defender.population -= transferred_pop
            aggressor.population += transferred_pop
        else:
            # 占有率3%未満: 防衛成功。領土・人口の変更なし
            transferred_area = 0.0
            transferred_pop = 0.0
        
        # --- 2. 賠償金の精算 ---
        PUNITIVE_MULTIPLIER = 1.2
        if occupation < 3.0:
            # 防衛成功: 防衛側が賠償金を請求
            reparation = (war.defender_cumulative_military_loss 
                         + war.defender_cumulative_civilian_gdp_loss) * PUNITIVE_MULTIPLIER
            payer_state = aggressor
            receiver_state = defender
            payer_name = war.aggressor
            receiver_name = war.defender
        else:
            # 占領成功: 攻撃側が賠償金を請求
            reparation = (war.aggressor_cumulative_military_loss 
                         + war.aggressor_cumulative_civilian_gdp_loss) * PUNITIVE_MULTIPLIER
            payer_state = defender
            receiver_state = aggressor
            payer_name = war.defender
            receiver_name = war.aggressor
        
        # 賠償金の支払い処理
        payer_state.government_budget -= reparation
        receiver_state.government_budget += reparation
        if payer_state.government_budget < 0:
            payer_state.national_debt += abs(payer_state.government_budget)
            payer_state.government_budget = 0.0
        
        # --- 3. 関係値のリセット ---
        self._update_relation(war.aggressor, war.defender, RelationType.NEUTRAL)
        
        # --- 4. 戦争リストから削除 ---
        self.state.active_wars = [
            w for w in self.state.active_wars 
            if not (w.aggressor == war.aggressor and w.defender == war.defender)
        ]
        
        # --- 5. 関連する停戦提案・降伏勧告のクリーンアップ ---
        self.state.pending_ceasefires = [
            c for c in self.state.pending_ceasefires
            if not ((c.proposer == war.aggressor and c.target == war.defender) or
                    (c.proposer == war.defender and c.target == war.aggressor))
        ]
        self.state.pending_surrenders = [
            s for s in self.state.pending_surrenders
            if not (s.aggressor == war.aggressor and s.defender == war.defender)
        ]
        
        # --- 6. ニュースイベント ---
        war_duration_years = war.war_turns_elapsed / 4.0  # ターン→年換算
        
        if occupation < 3.0:
            self.log_event(
                f"🕊️ 【講和成立・防衛成功】{war.aggressor}と{war.defender}の戦争が"
                f"{war_duration_years:.1f}年間の交戦を経て終結！"
                f"占領率{occupation:.1f}%は3%未満のため防衛成功と認定。"
                f"{war.defender}は全領土を維持。"
                f"{war.aggressor}は賠償金{reparation:.1f}Bドルを{war.defender}に支払います。",
                involved_countries=[war.aggressor, war.defender, "global"]
            )
        else:
            self.log_event(
                f"🕊️ 【講和成立】{war.aggressor}と{war.defender}の戦争が"
                f"{war_duration_years:.1f}年間の交戦を経て終結！"
                f"占領率{occupation:.1f}%に基づき、{transferred_area:.0f}km²の領土と"
                f"{transferred_pop:.2f}M人の人口が{war.aggressor}に移転。"
                f"{payer_name}は賠償金{reparation:.1f}Bドルを{receiver_name}に支払います。",
                involved_countries=[war.aggressor, war.defender, "global"]
            )
        
        self.sys_logs_this_turn.append(
            f"[講和会談] {war.aggressor} vs {war.defender}: "
            f"占領率={occupation:.1f}%, 領土移転={transferred_area:.0f}km², "
            f"人口移転={transferred_pop:.2f}M, 賠償金={reparation:.1f}B "
            f"(累積損害: 攻撃側軍事={war.aggressor_cumulative_military_loss:.1f}, "
            f"攻撃側民間={war.aggressor_cumulative_civilian_gdp_loss:.1f}, "
            f"防衛側軍事={war.defender_cumulative_military_loss:.1f}, "
            f"防衛側民間={war.defender_cumulative_civilian_gdp_loss:.1f})"
        )
