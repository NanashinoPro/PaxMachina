"""
核兵器システムエンジン（v1-3追加）

核開発パイプライン（4段階）、核弾頭量産、戦術核/戦略核の実戦使用ダメージ、
ミサイル防衛（ABM: 軍事力から自動算出）、核配備（核の傘）を処理する。

学術的根拠:
  - Manhattan Project cost structure (DoE archives)
  - Wright's Law (1936): 生産コストの学習曲線
  - Glasstone & Dolan (1977): The Effects of Nuclear Weapons
  - SIPRI Yearbook 2025: 各国核弾頭データ
  - Missile Defense Advocacy Alliance: THAAD/Aegis実績データ
"""

import math
import random
from typing import Dict

from .constants import (
    NUCLEAR_DEV_STEP_COSTS,
    NUCLEAR_PRODUCTION_BASE_GDP_RATIO,
    NUCLEAR_PRODUCTION_SCALE_FACTOR,
    NUCLEAR_TACTICAL_DAMAGE_RATIO,
    NUCLEAR_TACTICAL_MAX_WARHEADS,
    NUCLEAR_STRATEGIC_ECON_DAMAGE,
    NUCLEAR_STRATEGIC_POP_DAMAGE,
    NUCLEAR_STRATEGIC_MIL_DAMAGE,
    NUCLEAR_STRATEGIC_DEFAULT_WARHEADS,
    NUCLEAR_MAX_ECON_DAMAGE_RATIO,
    NUCLEAR_MAX_POP_DAMAGE_RATIO,
    NUCLEAR_MAX_MIL_DAMAGE_RATIO,
    NUCLEAR_ABM_MILITARY_RATIO,
    WARHEAD_PENETRATION_FACTOR,
    NUCLEAR_ABM_MAX_INTERCEPT,
)


class NuclearMixin:
    """核兵器関連の全処理を担当するMixin"""

    def _process_nuclear_development(self, actions: Dict):
        """核開発パイプラインの進捗処理（invest_nuclear に基づく）"""
        for country_name, country in list(self.state.countries.items()):
            # Step4（核保有国）は開発不要 → 量産フェーズへ
            if country.nuclear_dev_step >= 4:
                self._process_nuclear_production(country_name, country, actions)
                continue

            # Step0（未着手）の場合、invest_nuclear > 0 なら Step1 に自動遷移
            if country.nuclear_dev_step == 0:
                invest = self._get_nuclear_investment(country_name, actions)
                if invest > 0:
                    country.nuclear_dev_step = 1
                    step_info = NUCLEAR_DEV_STEP_COSTS[1]
                    country.nuclear_dev_target = country.economy * step_info["gdp_ratio"] * step_info["turns"]
                    country.nuclear_dev_invested = 0.0
                    self.log_event(
                        f"☢️ 【核開発開始】{country_name}がウラン濃縮プログラムを秘密裏に始動！"
                        f"（目標投資額: {country.nuclear_dev_target:.1f}）",
                        involved_countries=[country_name, "global"]
                    )
                    self.sys_logs_this_turn.append(
                        f"[{country_name} 核開発] Step0→1 遷移。目標: {country.nuclear_dev_target:.1f}"
                    )
                continue

            # Step 1-3: 投資の累積
            invest = self._get_nuclear_investment(country_name, actions)
            if invest <= 0:
                continue

            invest_amount = country.government_budget * invest
            country.nuclear_dev_invested += invest_amount

            self.sys_logs_this_turn.append(
                f"[{country_name} 核開発] Step{country.nuclear_dev_step}: "
                f"投資 +{invest_amount:.1f} (累計: {country.nuclear_dev_invested:.1f} / 目標: {country.nuclear_dev_target:.1f})"
            )

            # 目標達成チェック
            if country.nuclear_dev_invested >= country.nuclear_dev_target:
                old_step = country.nuclear_dev_step
                country.nuclear_dev_step += 1
                country.nuclear_dev_invested = 0.0

                step_names = {1: "ウラン濃縮", 2: "核実験", 3: "実戦配備", 4: "核保有国"}
                completed_name = step_names.get(old_step, f"Step{old_step}")
                new_name = step_names.get(country.nuclear_dev_step, f"Step{country.nuclear_dev_step}")

                if country.nuclear_dev_step >= 4:
                    # 核保有国に到達！初弾頭1発を付与
                    country.nuclear_warheads = max(1, country.nuclear_warheads)
                    country.nuclear_dev_target = 0.0
                    self.log_event(
                        f"☢️💣 【核保有国宣言】{country_name}が核兵器の実戦配備を完了し、"
                        f"世界に核保有を宣言しました！（保有弾頭数: {country.nuclear_warheads}発）",
                        involved_countries=[country_name, "global"]
                    )
                else:
                    # 次のステップへ
                    next_info = NUCLEAR_DEV_STEP_COSTS.get(country.nuclear_dev_step)
                    if next_info:
                        country.nuclear_dev_target = country.economy * next_info["gdp_ratio"] * next_info["turns"]
                    self.log_event(
                        f"☢️ 【核開発進展】{country_name}が{completed_name}段階を完了し、"
                        f"{new_name}段階に移行しました。",
                        involved_countries=[country_name, "global"]
                    )

                self.sys_logs_this_turn.append(
                    f"[{country_name} 核開発] Step{old_step}→{country.nuclear_dev_step} 完了。"
                    f"次目標: {country.nuclear_dev_target:.1f}"
                )

    def _process_nuclear_production(self, country_name: str, country, actions: Dict):
        """核弾頭の量産処理（Step4の核保有国のみ）"""
        invest = self._get_nuclear_investment(country_name, actions)
        if invest <= 0:
            return

        invest_amount = country.government_budget * invest

        # 量産コスト = base_cost / (1 + scale_factor × sqrt(既存弾頭数))
        base_cost = country.economy * NUCLEAR_PRODUCTION_BASE_GDP_RATIO
        scale_divisor = 1.0 + NUCLEAR_PRODUCTION_SCALE_FACTOR * math.sqrt(max(1, country.nuclear_warheads))
        unit_cost = base_cost / scale_divisor

        if unit_cost <= 0:
            return

        # 今期生産可能な弾頭数（1四半期あたり最大50発にキャップ）
        MAX_WARHEADS_PER_TURN = 50
        new_warheads = min(MAX_WARHEADS_PER_TURN, int(invest_amount / unit_cost))
        if new_warheads > 0:
            actual_cost = new_warheads * unit_cost
            country.nuclear_warheads += new_warheads
            # 予算から差し引き（核量産バグ修正）
            country.government_budget = max(0.0, country.government_budget - actual_cost)
            self.log_event(
                f"☢️ 【核弾頭生産】{country_name}が{new_warheads}発の核弾頭を新たに製造。"
                f"（総保有数: {country.nuclear_warheads}発、1発コスト: {unit_cost:.1f}、総費用: {actual_cost:.1f}）",
                involved_countries=[country_name]
            )
            self.sys_logs_this_turn.append(
                f"[{country_name} 核量産] +{new_warheads}発 (投資: {invest_amount:.1f}, "
                f"実費: {actual_cost:.1f}, 単価: {unit_cost:.1f}, 総数: {country.nuclear_warheads})"
            )

    def _process_nuclear_strikes(self, actions: Dict):
        """核使用の実行処理（大統領のlaunch_tactical/strategic_nuclearに基づく）"""
        for country_name, action in actions.items():
            country = self.state.countries.get(country_name)
            if not country:
                continue

            # major_diplomatic_actions内のP-02結果から核使用フラグを取得
            # （_merge_allで格納された情報を参照）
            launch_tactical = None
            tactical_count = 1
            launch_strategic = None
            strategic_count = NUCLEAR_STRATEGIC_DEFAULT_WARHEADS

            # actionsのdiplomatic_policiesからP-02由来のフラグを解析
            for dp in action.diplomatic_policies:
                tc = dp.target_country
                if tc.startswith("__NUCLEAR_TACTICAL__"):
                    parts = tc.replace("__NUCLEAR_TACTICAL__", "").split(":")
                    launch_tactical = parts[0]
                    if len(parts) > 1:
                        try:
                            tactical_count = int(parts[1])
                        except ValueError:
                            pass
                elif tc.startswith("__NUCLEAR_STRATEGIC__"):
                    parts = tc.replace("__NUCLEAR_STRATEGIC__", "").split(":")
                    launch_strategic = parts[0]
                    if len(parts) > 1:
                        try:
                            strategic_count = int(parts[1])
                        except ValueError:
                            pass

            # 戦術核使用
            if launch_tactical and country.nuclear_warheads >= 1:
                self._execute_tactical_nuclear(country_name, country, launch_tactical, tactical_count)

            # 戦略核使用
            if launch_strategic and country.nuclear_warheads >= strategic_count:
                self._execute_strategic_nuclear(country_name, country, launch_strategic, strategic_count)

    def _execute_tactical_nuclear(self, attacker_name: str, attacker, target_name: str, warheads_count: int = 1):
        """戦術核の実行: 前線投入中の敵軍事力に大ダメージ（弾頭数指定可能）"""
        target = self.state.countries.get(target_name)
        if not target:
            return

        # 使用弾頭数を保有数以内に制限
        warheads_count = min(warheads_count, attacker.nuclear_warheads)
        if warheads_count <= 0:
            return

        # 交戦中か確認
        war = None
        for w in self.state.active_wars:
            if (w.aggressor == attacker_name and w.defender == target_name) or \
               (w.aggressor == target_name and w.defender == attacker_name):
                war = w
                break

        if not war:
            self.sys_logs_this_turn.append(
                f"[{attacker_name} 戦術核] {target_name}と交戦中ではないため不発"
            )
            return

        # 敵の投入率を取得
        if war.aggressor == target_name:
            commitment = war.aggressor_commitment_ratio
        else:
            commitment = war.defender_commitment_ratio

        # ABM迎撃判定
        intercepted = self._calculate_abm_intercept(target, warheads_count)
        effective_warheads = warheads_count - intercepted

        if intercepted > 0:
            self.log_event(
                f"🛡️☢️ 【ミサイル防衛作動】{target_name}のABMシステムが"
                f"{intercepted}/{warheads_count}発の戦術核弾頭を迎撃！",
                involved_countries=[attacker_name, target_name, "global"]
            )

        if effective_warheads <= 0:
            attacker.nuclear_warheads -= warheads_count
            self.log_event(
                f"🛡️ 【全弾迎撃成功】{target_name}が{attacker_name}の戦術核攻撃を完全に阻止！",
                involved_countries=[attacker_name, target_name, "global"]
            )
            return

        # ダメージ計算: 前線軍事力 × 投入率 × 25% × 弾頭数（対数スケーリング）
        # 弾頭数が増えるほどダメージは増加するが、対数的に逓減
        warhead_multiplier = math.log2(effective_warheads + 1)
        damage = target.military * commitment * NUCLEAR_TACTICAL_DAMAGE_RATIO * warhead_multiplier
        damage = min(damage, target.military * NUCLEAR_MAX_MIL_DAMAGE_RATIO)

        target.military = max(0.0, target.military - damage)
        attacker.nuclear_warheads -= warheads_count

        self.log_event(
            f"☢️💥 【戦術核使用】{attacker_name}が{target_name}の前線軍事拠点に"
            f"戦術核{effective_warheads}発を使用！"
            f"（軍事力ダメージ: -{damage:.1f}、残存: {target.military:.1f}、"
            f"消費弾頭: {warheads_count}発、迎撃: {intercepted}発）",
            involved_countries=[attacker_name, target_name, "global"]
        )
        self.sys_logs_this_turn.append(
            f"[{attacker_name} 戦術核] 対{target_name}: {warheads_count}発使用(迎撃{intercepted}) "
            f"軍事ダメージ {damage:.1f} "
            f"(前線軍事力 {target.military + damage:.1f} × 投入率 {commitment:.0%} × "
            f"{NUCLEAR_TACTICAL_DAMAGE_RATIO} × log2({effective_warheads}+1))"
        )

    def _execute_strategic_nuclear(self, attacker_name: str, attacker, target_name: str, warheads_count: int):
        """戦略核の実行: 敵の経済・人口・軍事力全体に壊滅的ダメージ"""
        target = self.state.countries.get(target_name)
        if not target:
            return

        # 交戦中か確認
        is_at_war = any(
            (w.aggressor == attacker_name and w.defender == target_name) or
            (w.aggressor == target_name and w.defender == attacker_name)
            for w in self.state.active_wars
        )
        if not is_at_war:
            self.sys_logs_this_turn.append(
                f"[{attacker_name} 戦略核] {target_name}と交戦中ではないため不発"
            )
            return

        actual_warheads = min(warheads_count, attacker.nuclear_warheads)

        # ABM迎撃判定
        intercepted = self._calculate_abm_intercept(target, actual_warheads)
        effective_warheads = actual_warheads - intercepted

        if intercepted > 0:
            self.log_event(
                f"🛡️☢️ 【ミサイル防衛作動】{target_name}のABMシステムが{intercepted}発の核弾頭を迎撃！"
                f"（突破: {effective_warheads}発/{actual_warheads}発）",
                involved_countries=[attacker_name, target_name, "global"]
            )

        if effective_warheads <= 0:
            attacker.nuclear_warheads -= actual_warheads
            self.log_event(
                f"🛡️ 【全弾迎撃成功】{target_name}が{attacker_name}の戦略核攻撃を完全に阻止！",
                involved_countries=[attacker_name, target_name, "global"]
            )
            return

        # ダメージ計算 (Glasstone & Dolan簡略モデル)
        # log2スケーリング: 弾頭数増加による対数的ダメージ増加
        log_scale = math.log2(effective_warheads + 1) / math.log2(NUCLEAR_STRATEGIC_DEFAULT_WARHEADS + 1)

        econ_damage = min(
            target.economy * NUCLEAR_MAX_ECON_DAMAGE_RATIO,
            target.economy * NUCLEAR_STRATEGIC_ECON_DAMAGE * log_scale
        )
        pop_damage = min(
            target.population * NUCLEAR_MAX_POP_DAMAGE_RATIO,
            target.population * NUCLEAR_STRATEGIC_POP_DAMAGE * log_scale
        )
        mil_damage = min(
            target.military * NUCLEAR_MAX_MIL_DAMAGE_RATIO,
            target.military * NUCLEAR_STRATEGIC_MIL_DAMAGE
        )

        target.economy = max(1.0, target.economy - econ_damage)
        target.population = max(0.1, target.population - pop_damage)
        target.military = max(0.0, target.military - mil_damage)
        attacker.nuclear_warheads -= actual_warheads

        self.log_event(
            f"☢️💀 【戦略核攻撃】{attacker_name}が{target_name}に対し{effective_warheads}発の戦略核を発射！\n"
            f"　経済ダメージ: -{econ_damage:.1f} (残存: {target.economy:.1f})\n"
            f"　人口被害: -{pop_damage:.2f}M (残存: {target.population:.2f}M)\n"
            f"　軍事ダメージ: -{mil_damage:.1f} (残存: {target.military:.1f})\n"
            f"　消費弾頭: {actual_warheads}発 (攻撃国残弾: {attacker.nuclear_warheads}発)",
            involved_countries=[attacker_name, target_name, "global"]
        )
        self.sys_logs_this_turn.append(
            f"[{attacker_name} 戦略核] 対{target_name}: "
            f"弾頭{actual_warheads}発(迎撃{intercepted}, 突破{effective_warheads}) "
            f"経済-{econ_damage:.1f} 人口-{pop_damage:.2f}M 軍事-{mil_damage:.1f}"
        )

    def _calculate_abm_intercept(self, defender_country, incoming_warheads: int) -> int:
        """ABM迎撃判定: 軍事力から自動算出した迎撃能力で弾頭を確率的に撃墜"""
        abm_capability = defender_country.military * NUCLEAR_ABM_MILITARY_RATIO
        if abm_capability <= 0:
            return 0

        # 迎撃率 = ABM能力 / (ABM能力 + 弾頭数 × 突破力係数)
        intercept_rate = min(
            NUCLEAR_ABM_MAX_INTERCEPT,
            abm_capability / (abm_capability + incoming_warheads * WARHEAD_PENETRATION_FACTOR)
        )

        intercepted = 0
        for _ in range(incoming_warheads):
            if random.random() < intercept_rate:
                intercepted += 1

        return intercepted

    def _process_nuclear_deployment(self, actions: Dict):
        """核配備（核の傘）の処理: 同盟国への核配備・撤去"""
        for country_name, action in actions.items():
            country = self.state.countries.get(country_name)
            if not country:
                continue

            # P-02由来の核配備フラグを取得
            for dp in action.diplomatic_policies:
                tc = dp.target_country
                # 配備
                if tc.startswith("__NUCLEAR_DEPLOY__"):
                    parts = tc.replace("__NUCLEAR_DEPLOY__", "").split(":")
                    ally_name = parts[0]
                    deploy_count = int(parts[1]) if len(parts) > 1 else 10

                    ally = self.state.countries.get(ally_name)
                    if not ally:
                        continue

                    # 同盟チェック（RelationType enum の .value で比較）
                    rel = self.state.relations.get(country_name, {}).get(ally_name)
                    if rel is None or rel.value != "alliance":
                        self.sys_logs_this_turn.append(
                            f"[{country_name} 核配備] {ally_name}は同盟国ではないため拒否"
                        )
                        continue

                    # 配備実行
                    actual_deploy = min(deploy_count, country.nuclear_warheads)
                    if actual_deploy <= 0:
                        continue

                    country.nuclear_warheads -= actual_deploy
                    ally.nuclear_host_provider = country_name
                    ally.nuclear_hosted_warheads += actual_deploy

                    self.log_event(
                        f"☢️🤝 【核配備】{country_name}が{ally_name}の領土に"
                        f"{actual_deploy}発の核弾頭を配備しました。",
                        involved_countries=[country_name, ally_name, "global"]
                    )

                # 撤去
                elif tc == "__NUCLEAR_REMOVE_HOSTED__":
                    if country.nuclear_host_provider and country.nuclear_hosted_warheads > 0:
                        provider = country.nuclear_host_provider
                        provider_country = self.state.countries.get(provider)
                        returned = country.nuclear_hosted_warheads

                        if provider_country:
                            provider_country.nuclear_warheads += returned

                        self.log_event(
                            f"☢️🚫 【核撤去】{country_name}が{provider}の核兵器"
                            f"({returned}発)の撤去を完了しました。",
                            involved_countries=[country_name, provider, "global"]
                        )
                        country.nuclear_host_provider = None
                        country.nuclear_hosted_warheads = 0

    def _process_nuclear_alliance_cleanup(self):
        """同盟破棄時の核配備自動撤去"""
        for country_name, country in self.state.countries.items():
            if country.nuclear_host_provider:
                provider = country.nuclear_host_provider
                # 同盟関係チェック（RelationType enum の .value で比較）
                rel = self.state.relations.get(country_name, {}).get(provider)
                if rel is None or rel.value != "alliance":
                    # 同盟が破棄された → 核配備自動撤去
                    provider_country = self.state.countries.get(provider)
                    returned = country.nuclear_hosted_warheads
                    if provider_country and returned > 0:
                        provider_country.nuclear_warheads += returned
                    self.log_event(
                        f"☢️⚠️ 【核配備自動撤去】{country_name}と{provider}の同盟破棄に伴い、"
                        f"配備されていた{returned}発の核弾頭が{provider}に返還されました。",
                        involved_countries=[country_name, provider, "global"]
                    )
                    country.nuclear_host_provider = None
                    country.nuclear_hosted_warheads = 0

    def _get_nuclear_investment(self, country_name: str, actions: Dict) -> float:
        """アクションから核開発投資率を取得"""
        action = actions.get(country_name)
        if not action:
            return 0.0

        # DomesticAction内にinvest_nuclearがある場合（将来の拡張用）
        domestic = getattr(action, 'domestic_policy', None)
        if domestic and hasattr(domestic, 'invest_nuclear'):
            return getattr(domestic, 'invest_nuclear', 0.0)

        # diplomatic_policiesから__NUCLEAR_INVEST__フラグを検索
        for dp in action.diplomatic_policies:
            if dp.target_country.startswith("__NUCLEAR_INVEST__"):
                try:
                    return float(dp.target_country.replace("__NUCLEAR_INVEST__", ""))
                except ValueError:
                    pass

        return 0.0
