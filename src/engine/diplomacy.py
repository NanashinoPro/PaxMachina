import math
import random
from typing import Dict, List, Any
from models import (
    AgentAction, GovernmentType, RelationType, WarState, TradeState,
    SanctionState, SummitProposal, AllianceProposal, AnnexationProposal, CountryState,
    PendingAidProposal
)

class DiplomacyMixin:
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
            
            # 軍事侵攻比率の変更（交戦中の場合）
            if getattr(dip, 'war_commitment_ratio', None) is not None:
                from .constants import MIN_COMMITMENT_RATIO
                new_ratio = max(MIN_COMMITMENT_RATIO, min(1.0, dip.war_commitment_ratio))
                for w in self.state.active_wars:
                    if w.aggressor == country_name and w.defender == target_name:
                        old_ratio = w.aggressor_commitment_ratio
                        w.aggressor_commitment_ratio = new_ratio
                        self.sys_logs_this_turn.append(f"[{country_name} 投入比率変更] 対{target_name}戦: {old_ratio:.0%} → {new_ratio:.0%}")
                        self.log_event(f"📊 {country_name}が対{target_name}戦への軍事投入比率を{old_ratio:.0%}から{new_ratio:.0%}に変更しました。", involved_countries=[country_name, target_name, "global"])
                        break
                    elif w.defender == country_name and w.aggressor == target_name:
                        old_ratio = w.defender_commitment_ratio
                        w.defender_commitment_ratio = new_ratio
                        self.sys_logs_this_turn.append(f"[{country_name} 投入比率変更] 対{target_name}戦: {old_ratio:.0%} → {new_ratio:.0%}")
                        self.log_event(f"📊 {country_name}が対{target_name}戦への軍事投入比率を{old_ratio:.0%}から{new_ratio:.0%}に変更しました。", involved_countries=[country_name, target_name, "global"])
                        break
                    
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
            
            strategy = action.espionage_sabotage_strategy.lower()
            
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
        
        # 関連するデータのクリーンアップ
        self.state.active_wars = [w for w in self.state.active_wars if w.aggressor != absorbed_name and w.defender != absorbed_name]
        self.state.active_trades = [t for t in self.state.active_trades if t.country_a != absorbed_name and t.country_b != absorbed_name]
        self.state.active_sanctions = [s for s in self.state.active_sanctions if s.imposer != absorbed_name and s.target != absorbed_name]
        self.state.pending_summits = [s for s in self.state.pending_summits if s.proposer != absorbed_name and s.target != absorbed_name]
        self.state.pending_alliances = [a for a in self.state.pending_alliances if a.proposer != absorbed_name and a.target != absorbed_name]
        self.state.pending_annexations = [a for a in self.state.pending_annexations if a.proposer != absorbed_name and a.target != absorbed_name]
