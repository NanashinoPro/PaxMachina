"""
src/engine/energy.py  — エネルギー備蓄システム (v1-2)

担当処理:
  1. 起動時に data/energy_import_sources.json を読み込み各国フィールドを初期化
  2. 毎ターン実効エネルギー供給率を計算し備蓄を更新
  3. 危機ステージ遷移時にニュースイベントを発行
  4. タスクエージェント制AIの海峡封鎖宣言・解除を処理
     （diplomatic_policiesの__STRAIT_DECLARE__/__STRAIT_RESOLVE__仮想ターゲット方式）
  5. domestic.py に渡す economy/approval ペナルティを計算・適用
"""

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import WorldState

from .constants import (
    STRAIT_BLOCKADE_MAP,
    STRAIT_EXPORT_BLOCKED_COUNTRIES,
    STRAIT_BLOCKADE_ELIGIBLE_COUNTRIES,
    ENERGY_WARNING_RATIO,
    ENERGY_CRITICAL_RATIO,
    ENERGY_ECONOMY_PENALTY_LINEAR,
    ENERGY_ECONOMY_PENALTY_NONLINEAR,
    ENERGY_APPROVAL_PENALTY_COEFF,
)

# energy_import_sources.json の絶対パスを解決
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_IMPORT_SOURCES_PATH = os.path.join(_DATA_DIR, "energy_import_sources.json")


class EnergyMixin:
    """
    エネルギー備蓄・海峡封鎖システムを提供する Mixin クラス。
    SimulationEngine に多重継承させて使用する。
    """

    # ------------------------------------------------------------------
    # 初期化
    # ------------------------------------------------------------------
    def _init_energy_import_sources(self) -> None:
        """
        シミュレーション開始時に energy_import_sources.json を読み込み、
        各国の CountryState.energy_import_sources を設定する。
        JSONに記載されていない国はデフォルト値（空辞書）のまま。
        """
        if not os.path.exists(_IMPORT_SOURCES_PATH):
            self._add_log(
                f"[EnergyMixin] energy_import_sources.json が見つかりません: {_IMPORT_SOURCES_PATH}"
            )
            return

        with open(_IMPORT_SOURCES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        for country_name, sources in data.items():
            if country_name.startswith("_"):
                continue  # _comment, _format 等のメタキーをスキップ
            if country_name in self.state.countries:
                # _note 等のメタキー（_ 始まり）を除外。
                # ただし __中東 / __その他 等の域外ソースキー（__ 始まり）は除外しない。
                clean = {}
                for k, v in sources.items():
                    if k.startswith("_") and not k.startswith("__"):
                        continue  # _note, _comment 等のメタキーをスキップ
                    try:
                        clean[k] = float(v)
                    except (TypeError, ValueError):
                        pass
                self.state.countries[country_name].energy_import_sources = clean

        self._add_log("[EnergyMixin] energy_import_sources.json を読み込みました。")

    # ------------------------------------------------------------------
    # 毎ターン: 備蓄更新
    # ------------------------------------------------------------------
    def _process_energy_reserves(self) -> None:
        """
        毎ターン呼び出す。
        1. 実効エネルギー供給率を計算
        2. deficit > 0 なら備蓄を消費
        3. deficit = 0 なら備蓄を目標値にリセット
        4. ステージ遷移時にニュースイベントを発行
        """
        blockades = self.state.active_strait_blockades

        # 封鎖中の域外ソースキーをセット化
        blocked_external_keys: set = set()
        for strait in blockades:
            blocked_external_keys.update(STRAIT_BLOCKADE_MAP.get(strait, []))

        for country_name, country in self.state.countries.items():
            target = country.energy_reserve_target_turns
            old_reserve = country.energy_reserve_turns

            # --- 実効供給率を計算 ---
            supply = country.energy_self_sufficiency

            for source, ratio in country.energy_import_sources.items():
                if source.startswith("__"):
                    # 域外ソース: 海峡封鎖のみ影響
                    if source not in blocked_external_keys:
                        supply += ratio
                else:
                    # シミュ内国家: 輸出封鎖・戦争・制裁で遮断
                    if not self._is_energy_supply_disrupted(country_name, source):
                        supply += ratio

            net_deficit = max(0.0, 1.0 - supply)

            # --- 備蓄を更新 ---
            if net_deficit <= 0.0:
                # 供給正常 → 目標値にリセット（通常時は蓄積しない）
                country.energy_reserve_turns = target
            else:
                # 供給不足 → 備蓄を消費
                country.energy_reserve_turns = max(0.0, old_reserve - net_deficit)
                self._add_log(
                    f"[{country_name} エネルギー] supply={supply:.2f} "
                    f"deficit={net_deficit:.2f} "
                    f"備蓄: {old_reserve:.2f}→{country.energy_reserve_turns:.2f}T"
                )

            # --- ステージ遷移ニュース ---
            new_reserve = country.energy_reserve_turns
            warn_threshold = target * ENERGY_WARNING_RATIO
            crit_threshold = target * ENERGY_CRITICAL_RATIO

            if new_reserve <= 0.0 and old_reserve > 0.0:
                self._add_news(
                    f"💥【エネルギー枯渇】{country_name}のエネルギーが尽きた！"
                    "インフラ崩壊・工場停止が全土に広がっています！"
                )
            elif new_reserve <= crit_threshold and old_reserve > crit_threshold:
                self._add_news(
                    f"🔴【エネルギー危機】{country_name}の備蓄が目標の25%未満に！"
                    "停電・工場停止が相次いでいます。"
                )
            elif new_reserve <= warn_threshold and old_reserve > warn_threshold:
                self._add_news(
                    f"⚠️【エネルギー警戒】{country_name}の備蓄が目標の50%未満に低下。"
                    "節電要請・燃料費高騰が始まっています。"
                )

    # ------------------------------------------------------------------
    # 毎ターン: economy/approval ペナルティ適用
    # ------------------------------------------------------------------
    def _apply_energy_penalties(self, country_name: str) -> None:
        """
        domestic.py の _process_domestic 内から呼び出す。
        現在の備蓄残量に応じて economy と approval_rating にペナルティを適用する。
        """
        country = self.state.countries.get(country_name)
        if country is None:
            return

        target = country.energy_reserve_target_turns
        if target <= 0.0:
            return

        reserve_ratio = country.energy_reserve_turns / target
        # deficit_ratio: 目標に対してどれだけ不足しているか（0〜1）
        deficit_ratio = max(0.0, 1.0 - reserve_ratio)

        if deficit_ratio <= 0.0:
            return  # 正常: ペナルティなし

        # economy ペナルティ（非線形）
        if deficit_ratio >= 0.5:
            eco_penalty = deficit_ratio * ENERGY_ECONOMY_PENALTY_NONLINEAR
        else:
            eco_penalty = deficit_ratio * ENERGY_ECONOMY_PENALTY_LINEAR

        country.economy = max(1.0, country.economy * (1.0 - eco_penalty))

        # approval_rating ペナルティ
        app_penalty = deficit_ratio * ENERGY_APPROVAL_PENALTY_COEFF
        country.approval_rating = max(0.0, country.approval_rating - app_penalty)

        stage = (
            "枯渇" if reserve_ratio <= 0.0
            else "危機" if reserve_ratio <= ENERGY_CRITICAL_RATIO
            else "警戒"
        )
        self._add_log(
            f"[{country_name} エネルギー{stage}] "
            f"備蓄{country.energy_reserve_turns:.2f}/{target:.2f}T "
            f"economy -{eco_penalty*100:.1f}% "
            f"approval -{app_penalty:.1f}pt"
        )

    # ------------------------------------------------------------------
    # 毎ターン: 大統領AIの海峡封鎖アクション処理
    # ------------------------------------------------------------------
    def _process_strait_blockade_actions(self, actions: dict = None) -> None:
        """
        各国のAgentAction.diplomatic_policiesに含まれる仮想ターゲットを処理する。
        - target_country が '__STRAIT_DECLARE__<海峡名>' → 封鎖宣言
        - target_country が '__STRAIT_RESOLVE__<海峡名>' → 封鎖解除

        main.py の turn 処理ループから呼び出す。
        actions: {国名: AgentAction} の辞書
        """
        if not actions:
            return

        for country_name, agent_action in actions.items():
            dipls = getattr(agent_action, "diplomatic_policies", []) or []
            for dp in dipls:
                tc = dp.target_country or ""

                # --- 封鎖宣言 ---
                if tc.startswith("__STRAIT_DECLARE__"):
                    strait_name = tc[len("__STRAIT_DECLARE__"):]
                    if strait_name:
                        self._try_declare_blockade(country_name, strait_name)

                # --- 封鎖解除 ---
                elif tc.startswith("__STRAIT_RESOLVE__"):
                    strait_name = tc[len("__STRAIT_RESOLVE__"):]
                    if strait_name:
                        self._try_resolve_blockade(country_name, strait_name)

    def _try_declare_blockade(self, country_name: str, strait_name: str) -> None:
        """海峡封鎖を宣言する。資格チェックあり。"""
        eligible = STRAIT_BLOCKADE_ELIGIBLE_COUNTRIES.get(strait_name, [])
        if country_name not in eligible:
            self._add_log(
                f"[{country_name}] {strait_name}封鎖を試みたが資格なし。"
                f"封鎖可能国: {eligible}"
            )
            return

        if strait_name in self.state.active_strait_blockades:
            self._add_log(
                f"[{country_name}] {strait_name}はすでに封鎖中。"
            )
            return

        # 封鎖を発動
        self.state.active_strait_blockades.append(strait_name)
        self.state.strait_blockade_owners[strait_name] = country_name

        # 産油国の輸出を停止
        for blocked_country in STRAIT_EXPORT_BLOCKED_COUNTRIES.get(strait_name, []):
            if blocked_country in self.state.countries:
                self.state.countries[blocked_country].energy_export_blocked = True

        self._add_news(
            f"🚨【{strait_name}封鎖】{country_name}が{strait_name}の封鎖を宣言！"
            f"中東産油国からのエネルギー輸入が遮断されました。"
            f"日本・フィリピン・インドなど輸入依存国に深刻な影響が及ぶ見通しです。"
        )
        self._add_log(
            f"[EnergyMixin] {strait_name}封鎖 → {country_name}が宣言。"
            f"輸出停止国: {STRAIT_EXPORT_BLOCKED_COUNTRIES.get(strait_name, [])}"
        )

    def _try_resolve_blockade(self, country_name: str, strait_name: str) -> None:
        """海峡封鎖を解除する。宣言国のみ解除可能。"""
        owner = self.state.strait_blockade_owners.get(strait_name)
        if owner != country_name:
            self._add_log(
                f"[{country_name}] {strait_name}の解除を試みたが、"
                f"封鎖宣言国は{owner}のため解除不可。"
            )
            return

        # 封鎖を解除
        if strait_name in self.state.active_strait_blockades:
            self.state.active_strait_blockades.remove(strait_name)
        self.state.strait_blockade_owners.pop(strait_name, None)

        # 産油国の輸出停止を解除
        for blocked_country in STRAIT_EXPORT_BLOCKED_COUNTRIES.get(strait_name, []):
            if blocked_country in self.state.countries:
                self.state.countries[blocked_country].energy_export_blocked = False

        self._add_news(
            f"✅【{strait_name}封鎖解除】{country_name}が{strait_name}の封鎖を解除。"
            f"エネルギー輸入が再開されます。"
            f"各国の備蓄は次ターンから目標値に回復します。"
        )
        self._add_log(f"[EnergyMixin] {strait_name}封鎖 → {country_name}が解除。")

    # ------------------------------------------------------------------
    # ヘルパー
    # ------------------------------------------------------------------
    def _is_energy_supply_disrupted(self, importer: str, source: str) -> bool:
        """
        シミュ内国家からの輸入が遮断されているか判定する。
        以下のいずれかに該当すれば遮断とみなす:
          1. source 国の energy_export_blocked = True（海峡封鎖の影響）
          2. importer と source が戦争状態
          3. source が importer に制裁を課している
        """
        source_country = self.state.countries.get(source)
        if source_country and source_country.energy_export_blocked:
            return True

        for war in self.state.active_wars:
            parties = {war.aggressor, war.defender}
            if importer in parties and source in parties:
                return True

        for sanction in self.state.active_sanctions:
            if sanction.imposer == source and sanction.target == importer:
                return True

        return False

    def _add_news(self, message: str) -> None:
        """ニュースイベントを追加する（WorldState.news_events）。"""
        self.state.news_events.append(message)
        # sys_logs_this_turn があれば同時に記録（engine.core が持つ）
        logs = getattr(self, "sys_logs_this_turn", None)
        if logs is not None:
            logs.append(f"[NEWS] {message}")

    def _add_log(self, message: str) -> None:
        """システムログのみに追加する。"""
        logs = getattr(self, "sys_logs_this_turn", None)
        if logs is not None:
            logs.append(message)
