import os
import json
import traceback
import time
from typing import Dict, Any, List, Tuple, Optional

from google import genai
from google.genai import types
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.ollama_client import OllamaClient

from models import (
    WorldState, CountryState, AgentAction, DomesticAction, DiplomaticAction,
    PresidentPolicy,
    MinisterDecisionForeign, MinisterDecisionDefense,
    MinisterDecisionEconomic, MinisterDecisionFinance, PresidentDecision
)
from logger import SimulationLogger

from agent.prompts.analyst import build_analyst_prompt
from agent.prompts.president_policy import build_president_policy_prompt
from agent.prompts.major_diplomacy import build_major_diplomacy_prompt
from agent.prompts.budget_normalize import build_budget_normalize_prompt

# domestic
from agent.prompts.domestic.tax_rate import build_tax_rate_prompt
from agent.prompts.domestic.tariff import build_tariff_prompt
from agent.prompts.domestic.invest import (
    build_economy_invest_prompt,
    build_welfare_invest_prompt,
    build_education_invest_prompt,
)
from agent.prompts.domestic.governance import (
    build_press_freedom_prompt,
    build_deception_prompt,
    build_parliament_prompt,
)

# military
from agent.prompts.military.tasks import (
    build_military_invest_prompt,
    build_intel_invest_prompt,
    build_war_commitment_prompt,
    build_espionage_gather_prompt,
    build_espionage_sabotage_prompt,
)

# diplomatic
from agent.prompts.diplomatic.tasks import (
    build_message_prompt,
    build_trade_prompt,
    build_sanctions_prompt,
    build_summit_prompt,
    build_multilateral_summit_prompt,
    build_aid_donor_prompt,
    build_aid_acceptance_prompt,
    build_power_vacuum_prompt,
)

from agent.modules.media import GeminiSentimentAnalyzer
from agent.modules import summit, media, intelligence

load_dotenv()


class AgentSystem:
    """タスクエージェント制: 大統領施政方針(Pro) → 各タスクエージェント(flash/flash-lite) の多段構造"""

    def __init__(self, logger: SimulationLogger = None, model_name: str = "gemini-2.5-pro", db_manager=None):
        self.logger = logger
        self.db_manager = db_manager

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            if logger is None:
                self.client = None
                self.model_name = model_name
                self.sentiment_analyzer = None
                self.token_usage = {}
                self.ollama_client = None
                return
            raise ValueError("GEMINI_API_KEYが環境変数に設定されていません。")

        self.client = genai.Client(api_key=api_key, http_options={'timeout': 60000})
        self.model_name = model_name
        self.token_usage = {}

        sub_api_key = os.environ.get("GEMINI_API_KEY_SUB")
        if sub_api_key:
            self.client_sub = genai.Client(api_key=sub_api_key, http_options={'timeout': 60000})
            if self.logger:
                self.logger.sys_log("[System] サブAPIキー検出 → フォールバック用クライアント初期化完了")
        else:
            self.client_sub = None
            if self.logger:
                self.logger.sys_log("[System] サブAPIキー未設定 → フォールバック無効")

        self.sentiment_analyzer = GeminiSentimentAnalyzer(self.client, client_sub=self.client_sub, token_usage=self.token_usage)

        try:
            self.ollama_client = OllamaClient()
            if self.logger:
                self.logger.sys_log("[System] Ollamaクライアント初期化完了 (mistral-small3.1)")
        except ConnectionError as e:
            if self.logger:
                self.logger.sys_log(f"[System] Ollamaクライアント初期化エラー: {e}", "ERROR")
            self.ollama_client = None

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=4, max=30))
    def _generate_with_retry_internal(self, client, model: str, contents: str, config: types.GenerateContentConfig = None, category: str = "default") -> Any:
        if model.startswith("mistral-small") and self.ollama_client:
            json_mode = config and hasattr(config, 'response_mime_type') and getattr(config, 'response_mime_type', None) == "application/json"
            temperature = getattr(config, 'temperature', 0.4) if config else 0.4
            response = self.ollama_client.generate(
                prompt=contents,
                model=model,
                temperature=temperature,
                json_mode=json_mode,
            )
        elif config:
            response = client.models.generate_content(model=model, contents=contents, config=config)
        else:
            response = client.models.generate_content(model=model, contents=contents)

        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            meta = response.usage_metadata
            if category not in self.token_usage:
                self.token_usage[category] = {"prompt_tokens": 0, "candidates_token_count": 0, "thoughts_token_count": 0, "model": model}
            self.token_usage[category]["prompt_tokens"] += getattr(meta, 'prompt_token_count', 0)
            self.token_usage[category]["candidates_token_count"] += getattr(meta, 'candidates_token_count', 0)
            self.token_usage[category]["thoughts_token_count"] += getattr(meta, 'thoughts_token_count', 0) or 0

        return response

    def _generate_with_retry(self, model: str, contents: str, config: types.GenerateContentConfig = None, category: str = "default") -> Any:
        try:
            return self._generate_with_retry_internal(self.client, model, contents, config, category)
        except Exception as main_error:
            if self.client_sub is None:
                raise
            if self.logger:
                self.logger.sys_log(f"[API Fallback] メインキーで全リトライ失敗 ({type(main_error).__name__}: {main_error})。サブAPIキーで再試行します...", "WARNING")
            try:
                response = self._generate_with_retry_internal(self.client_sub, model, contents, config, category)
                if self.logger:
                    self.logger.sys_log("[API Fallback] サブAPIキーでの呼び出しに成功しました。")
                return response
            except Exception as sub_error:
                if self.logger:
                    self.logger.sys_log(f"[API Fallback] サブAPIキーでも失敗しました ({type(sub_error).__name__}: {sub_error})。", "ERROR")
                raise

    def _create_search_tool(self, country_name: str, role: str = ""):
        db_manager = getattr(self, "db_manager", None)

        def search_historical_events(query: str) -> str:
            """過去の重要な外交、内政、諜報に関する出来事の記録やニュースをデータベースから検索します。"""
            if not db_manager:
                return "データベースが利用できません。"
            role_str = f":{role}" if role else ""
            self.logger.sys_log(f"[{country_name}{role_str}] Tool Call: 過去の記録を検索中... (クエリ: '{query}')")
            try:
                results = db_manager.search_events(searcher_country=country_name, query=query, limit=3)
                if not results:
                    self.logger.sys_log(f"[{country_name}{role_str}] 検索結果: 該当なし")
                    return "該当する記録は見つかりませんでした。"
                res_str = "---検索結果---\n"
                for r in results:
                    t = r.get("turn", "?")
                    cnt = r.get("content", "")
                    res_str += f"[Turn {t}] {cnt}\n"
                self.logger.sys_log_detail(f"[{country_name}{role_str}] DB Search Result for '{query}'", res_str)
                self.logger.sys_log(f"[{country_name}{role_str}] Tool Call: 検索完了 (クエリ: '{query}', 見つかった件数: {len(results)}件)")
                return res_str
            except Exception as e:
                self.logger.sys_log(f"[{country_name}{role_str}] 検索中にエラーが発生しました: {e}", "ERROR")
                return f"検索中にエラーが発生しました: {e}"
        return search_historical_events if db_manager else None

    def _execute_agent(self, country_name: str, role: str, prompt: str, category: str, override_model: Optional[str] = None) -> str:
        """エージェントの推論を実行し、必要に応じて検索ツールを呼び出す"""
        start_time = time.time()
        self.logger.sys_log(f"[{country_name}:{role}] API推論開始...")

        search_tool = self._create_search_tool(country_name, role)
        tools = [search_tool] if search_tool else None

        target_model = override_model if override_model else self.model_name

        try:
            response = self._generate_with_retry(
                model=target_model,
                contents=prompt,
                config=types.GenerateContentConfig(tools=tools, temperature=0.4),
                category=category
            )

            if getattr(response, 'function_calls', None):
                for function_call in response.function_calls:
                    if function_call.name == "search_historical_events":
                        args = function_call.args if isinstance(function_call.args, dict) else dict(function_call.args)
                        query = args.get("query", "")
                        tool_result = search_tool(query)
                        follow_up_prompt = prompt + f"\n\nエージェントツールからの検索結果 '{query}':\n{tool_result}\n\nこれらを踏まえ、最終的な意思決定を指示されたJSONフォーマットで行ってください。"
                        response = self._generate_with_retry(
                            model=target_model,
                            contents=follow_up_prompt,
                            config=types.GenerateContentConfig(temperature=0.4),
                            category=category
                        )
                        break

            response_text = response.text.strip() if response and hasattr(response, 'text') else "{}"
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]

            elapsed = time.time() - start_time
            self.logger.sys_log(f"[{country_name}:{role}] レスポンス受信完了 (所要時間: {elapsed:.2f}秒)")
            response_text = response_text.strip()

            # --- タスクログバッファに自動収集 ---
            if not hasattr(self, '_task_log_buffer'):
                self._task_log_buffer: Dict[str, Dict[str, str]] = {}
            buf = self._task_log_buffer.setdefault(country_name, {})
            # ロール名をキー、raw JSONテキストを値として保存
            buf[role] = response_text

            return response_text

        except Exception as e:
            self.logger.sys_log(f"[{country_name}:{role}] APIエラー発生: {e}", "ERROR")
            # エラー時もバッファに記録
            if not hasattr(self, '_task_log_buffer'):
                self._task_log_buffer: Dict[str, Dict[str, str]] = {}
            self._task_log_buffer.setdefault(country_name, {})[role] = f"ERROR: {e}"
            return "{}"

    @staticmethod
    def _safe_json(text: str) -> dict:
        try:
            t = text.strip()
            if t.startswith("```json"): t = t[7:]
            if t.startswith("```"): t = t[3:]
            if t.endswith("```"): t = t[:-3]
            return json.loads(t.strip())
        except Exception:
            return {}

    # =================================================================
    # Phase 0: 大統領施政方針 + 重大外交
    # =================================================================

    def _run_phase0_policy(
        self, country_name: str, country_state: CountryState,
        world_state: WorldState, past_news: List[str]
    ) -> PresidentPolicy:
        """P-01: 大統領施政方針（Pro）"""
        prompt = build_president_policy_prompt(country_name, country_state, world_state, past_news)
        raw = self._execute_agent(country_name, "大統領施政方針(P-01)", prompt, "policy", self.model_name)
        d = self._safe_json(raw)
        try:
            policy = PresidentPolicy(
                stance=d.get("stance", "防御型"),
                directives=d.get("directives", []),
                hidden_plans=d.get("hidden_plans", ""),
                sns_posts=d.get("sns_posts", []),
            )
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:P-01] パースエラー: {e}", "ERROR")
            policy = PresidentPolicy(stance="防御型", directives=["現状維持"], hidden_plans="", sns_posts=[])
        self.logger.sys_log_detail(f"{country_name} P-01 Policy", raw)
        return policy

    def _run_phase0_major_diplomacy(
        self, country_name: str, country_state: CountryState,
        world_state: WorldState, policy: PresidentPolicy, past_news: List[str]
    ) -> dict:
        """P-02: 重大外交決定（flash） → dict形式で返す"""
        prompt = build_major_diplomacy_prompt(country_name, country_state, world_state, policy, past_news)
        raw = self._execute_agent(country_name, "重大外交(P-02)", prompt, "major_diplomacy", "gemini-2.5-flash")
        d = self._safe_json(raw)
        self.logger.sys_log_detail(f"{country_name} P-02 MajorDiplomacy", raw)
        return d

    # =================================================================
    # Phase 1-A: 分析官レポート
    # =================================================================

    def _run_phase1a_analysis(
        self, country_name: str, country_state: CountryState,
        world_state: WorldState, past_news: List[str]
    ) -> Dict[str, str]:
        """A-01: 分析官レポート（flash-lite × 他国数）"""
        import random
        analyst_reports: Dict[str, str] = {}
        other_countries = [n for n in world_state.countries if n != country_name]
        if not other_countries:
            return analyst_reports

        self.logger.sys_log(f"[{country_name}] Phase1-A: 分析官起動 ({len(other_countries)}カ国)")
        for target_name in other_countries:
            try:
                target_state = world_state.countries.get(target_name)
                has_deception = target_state is not None and any([
                    target_state.reported_economy is not None,
                    target_state.reported_military is not None,
                    target_state.reported_approval_rating is not None,
                    target_state.reported_intelligence_level is not None,
                    target_state.reported_gdp_per_capita is not None,
                ])
                use_real_stats = False
                if has_deception and target_state is not None:
                    my_intel = max(1.0, country_state.intelligence_level)
                    enemy_intel = max(1.0, target_state.intelligence_level)
                    success_prob = my_intel / (my_intel + enemy_intel)
                    roll = random.random()
                    use_real_stats = (roll < success_prob)
                    result_str = "✅ 諜報成功（真値取得）" if use_real_stats else "❌ 諜報失敗（偽装値のまま）"
                    self.logger.sys_log(
                        f"[{country_name}→{target_name} 諜報判定] "
                        f"自国:{my_intel:.1f} / 相手:{enemy_intel:.1f} "
                        f"成功確率:{success_prob:.1%} | roll:{roll:.3f} → {result_str}"
                    )

                analyst_prompt = build_analyst_prompt(
                    country_name, country_state, world_state,
                    target_name, past_news, use_real_stats=use_real_stats
                )
                report = self._execute_agent(
                    country_name, f"分析官(対{target_name})",
                    analyst_prompt, "analyst", "gemini-2.5-flash-lite"
                )
                analyst_reports[target_name] = report
                self.logger.sys_log_detail(f"{country_name} Analyst Report (vs {target_name})", report)
            except Exception as exc:
                self.logger.sys_log(f"[{country_name}:分析官(対{target_name})] 例外: {exc}", "ERROR")
                analyst_reports[target_name] = "分析データなし（エラー）"

        self.logger.sys_log(f"[{country_name}] Phase1-A完了: {len(analyst_reports)}カ国分析済")
        return analyst_reports

    # =================================================================
    # Phase 1-B: 外交タスク群（D-01〜D-08）
    # =================================================================

    def _run_phase1b_diplomacy(
        self, country_name: str, country_state: CountryState,
        world_state: WorldState, policy: PresidentPolicy,
        analyst_reports: Dict[str, str], past_news: List[str]
    ) -> List[DiplomaticAction]:
        """D-01〜D-08: 外交タスク群を実行しDiplomaticActionリストにマージ"""
        merged: Dict[str, DiplomaticAction] = {}

        def get_or_create(tc: str) -> DiplomaticAction:
            if tc not in merged:
                merged[tc] = DiplomaticAction(target_country=tc, reason="タスクエージェント統合")
            return merged[tc]

        # D-01: メッセージ送信
        try:
            raw = self._execute_agent(country_name, "外交:メッセージ(D-01)",
                build_message_prompt(country_name, country_state, world_state, policy, analyst_reports, past_news),
                "dipl_message", "gemini-2.5-flash-lite")
            d = self._safe_json(raw)
            for m in d.get("messages", []):
                tc = m.get("target_country", "")
                if not tc: continue
                a = get_or_create(tc)
                a.message = m.get("message")
                a.is_private = m.get("is_private", False)
                a.reason = m.get("reason", a.reason)
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:D-01] エラー: {e}", "ERROR")

        # D-02: 貿易協定
        try:
            raw = self._execute_agent(country_name, "外交:貿易(D-02)",
                build_trade_prompt(country_name, country_state, world_state, policy, past_news),
                "dipl_trade", "gemini-2.5-flash-lite")
            d = self._safe_json(raw)
            for t in d.get("trade_actions", []):
                tc = t.get("target_country", "")
                if not tc: continue
                a = get_or_create(tc)
                a.propose_trade = t.get("propose_trade", False)
                a.cancel_trade = t.get("cancel_trade", False)
                if t.get("reason"): a.reason = t["reason"]
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:D-02] エラー: {e}", "ERROR")

        # D-03: 経済制裁
        try:
            raw = self._execute_agent(country_name, "外交:制裁(D-03)",
                build_sanctions_prompt(country_name, country_state, world_state, policy, past_news),
                "dipl_sanctions", "gemini-2.5-flash-lite")
            d = self._safe_json(raw)
            for s in d.get("sanction_actions", []):
                tc = s.get("target_country", "")
                if not tc: continue
                a = get_or_create(tc)
                a.impose_sanctions = s.get("impose_sanctions", False)
                a.lift_sanctions = s.get("lift_sanctions", False)
                if s.get("reason"): a.reason = s["reason"]
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:D-03] エラー: {e}", "ERROR")

        # D-04: 首脳会談
        try:
            raw = self._execute_agent(country_name, "外交:首脳会談(D-04)",
                build_summit_prompt(country_name, country_state, world_state, policy, past_news),
                "dipl_summit", "gemini-2.5-flash-lite")
            d = self._safe_json(raw)
            for s in d.get("summit_actions", []):
                tc = s.get("target_country", "")
                if not tc: continue
                a = get_or_create(tc)
                a.propose_summit = s.get("propose_summit", False)
                a.accept_summit = s.get("accept_summit", False)
                if s.get("summit_topic"): a.summit_topic = s["summit_topic"]
                if s.get("reason"): a.reason = s["reason"]
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:D-04] エラー: {e}", "ERROR")

        # D-05: 多国間首脳会談
        try:
            raw = self._execute_agent(country_name, "外交:多国間会談(D-05)",
                build_multilateral_summit_prompt(country_name, country_state, world_state, policy, past_news),
                "dipl_multilateral", "gemini-2.5-flash")
            d = self._safe_json(raw)
            for s in d.get("multilateral_actions", []):
                tc = s.get("target_country", "")
                if not tc: continue
                a = get_or_create(tc)
                a.propose_multilateral_summit = s.get("propose_multilateral_summit", False)
                a.accept_summit = a.accept_summit or s.get("accept_summit", False)
                participants = s.get("summit_participants", [])
                if participants: a.summit_participants = participants
                if s.get("summit_topic"): a.summit_topic = s["summit_topic"]
                if s.get("reason"): a.reason = s["reason"]
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:D-05] エラー: {e}", "ERROR")

        # D-06: 対外援助（送り手）
        try:
            raw = self._execute_agent(country_name, "外交:援助送付(D-06)",
                build_aid_donor_prompt(country_name, country_state, world_state, policy, past_news),
                "dipl_aid_donor", "gemini-2.5-flash")
            d = self._safe_json(raw)
            for aid in d.get("aid_actions", []):
                tc = aid.get("target_country", "")
                if not tc: continue
                a = get_or_create(tc)
                if aid.get("aid_amount_economy", 0.0) > 0.0:
                    a.aid_amount_economy = float(aid["aid_amount_economy"])
                if aid.get("aid_amount_military", 0.0) > 0.0:
                    a.aid_amount_military = float(aid["aid_amount_military"])
                a.aid_cancel = aid.get("aid_cancel", False)
                if aid.get("reason"): a.reason = aid["reason"]
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:D-06] エラー: {e}", "ERROR")

        # D-07: 援助受入率（受け手）
        try:
            prompt_d07 = build_aid_acceptance_prompt(country_name, country_state, world_state, policy, past_news)
            if prompt_d07:  # 援助なし時は空文字
                raw = self._execute_agent(country_name, "外交:援助受入(D-07)",
                    prompt_d07, "dipl_aid_accept", "gemini-2.5-flash-lite")
                d = self._safe_json(raw)
                for acc in d.get("acceptance_actions", []):
                    tc = acc.get("target_country", "")
                    if not tc: continue
                    a = get_or_create(tc)
                    a.aid_acceptance_ratio = float(acc.get("aid_acceptance_ratio", 1.0))
                    if acc.get("reason"): a.reason = acc["reason"]
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:D-07] エラー: {e}", "ERROR")

        # D-08: パワーバキューム入札
        try:
            prompt_d08 = build_power_vacuum_prompt(country_name, country_state, world_state, policy, past_news)
            if prompt_d08:
                raw = self._execute_agent(country_name, "外交:パワーバキューム(D-08)",
                    prompt_d08, "dipl_vacuum", "gemini-2.5-flash")
                d = self._safe_json(raw)
                for v in d.get("vacuum_actions", []):
                    tc = v.get("target_country", "")
                    if not tc: continue
                    a = get_or_create(tc)
                    a.vacuum_bid = float(v.get("vacuum_bid", 0.0))
                    if v.get("reason"): a.reason = v["reason"]
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:D-08] エラー: {e}", "ERROR")

        return list(merged.values())

    # =================================================================
    # Phase 1-C: 軍事・諜報タスク群（M-01〜M-05）
    # =================================================================

    def _run_phase1c_military(
        self, country_name: str, country_state: CountryState,
        world_state: WorldState, policy: PresidentPolicy,
        analyst_reports: Dict[str, str], past_news: List[str]
    ) -> dict:
        """M-01〜M-05: 軍事・諜報タスク群を実行して辞書で返す"""
        result = {
            "invest_military": 0.15,
            "reasoning_for_military_investment": "デフォルト",
            "invest_intelligence": 0.05,
            "invest_nuclear": 0.0,  # v1-3: 核開発投資
            "war_commitment_ratios": {},
            "espionage_actions": [],  # List[dict] {target, gather, gather_strategy, sabotage, sabotage_strategy, sabotage_reasoning}
        }

        # M-01: 軍事投資
        try:
            raw = self._execute_agent(country_name, "軍事:投資(M-01)",
                build_military_invest_prompt(country_name, country_state, world_state, policy, analyst_reports, past_news),
                "mil_invest", "gemini-2.5-flash")
            d = self._safe_json(raw)
            result["invest_military"] = float(d.get("invest_military", 0.15))
            result["reasoning_for_military_investment"] = d.get("reasoning_for_military_investment") or ""
            # v1-3: 核開発投資と核使用提言
            result["invest_nuclear"] = float(d.get("invest_nuclear", 0.0))
            nuke_rec = d.get("nuclear_use_recommendation")
            if nuke_rec:
                self.logger.sys_log(f"[{country_name}:M-01] 核使用提言: {nuke_rec}")
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:M-01] エラー: {e}", "ERROR")

        # M-02: 諜報投資
        try:
            raw = self._execute_agent(country_name, "軍事:諜報投資(M-02)",
                build_intel_invest_prompt(country_name, country_state, world_state, policy, past_news),
                "mil_intel", "gemini-2.5-flash-lite")
            d = self._safe_json(raw)
            result["invest_intelligence"] = float(d.get("invest_intelligence", 0.05))
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:M-02] エラー: {e}", "ERROR")

        # M-03: 前線投入比率（交戦中のみ）
        is_at_war = any(
            w.aggressor == country_name or w.defender == country_name
            for w in world_state.active_wars
        )
        if is_at_war:
            try:
                raw = self._execute_agent(country_name, "軍事:前線投入(M-03)",
                    build_war_commitment_prompt(country_name, country_state, world_state, policy, past_news),
                    "mil_commitment", "gemini-2.5-flash")
                d = self._safe_json(raw)
                ratios = d.get("war_commitment_ratios", {})
                result["war_commitment_ratios"] = {k: float(v) for k, v in ratios.items()}
            except Exception as e:
                self.logger.sys_log(f"[{country_name}:M-03] エラー: {e}", "ERROR")

        # M-04 + M-05: 諜報収集・破壊工作（他国ごと）
        other_countries = [n for n in world_state.countries if n != country_name]
        for target_name in other_countries:
            esp_entry = {"target": target_name, "gather": False, "gather_strategy": None,
                         "sabotage": False, "sabotage_strategy": None, "sabotage_reasoning": ""}
            ar_text = analyst_reports.get(target_name, "")

            # M-04
            try:
                raw = self._execute_agent(country_name, f"諜報:収集(M-04)→{target_name}",
                    build_espionage_gather_prompt(country_name, country_state, world_state, target_name, policy, ar_text, past_news),
                    "mil_esp_gather", "gemini-2.5-flash-lite")
                d = self._safe_json(raw)
                esp_entry["gather"] = bool(d.get("espionage_gather_intel", False))
                esp_entry["gather_strategy"] = d.get("espionage_intel_strategy")
            except Exception as e:
                self.logger.sys_log(f"[{country_name}:M-04→{target_name}] エラー: {e}", "ERROR")

            # M-05
            try:
                raw = self._execute_agent(country_name, f"諜報:破壊工作(M-05)→{target_name}",
                    build_espionage_sabotage_prompt(country_name, country_state, world_state, target_name, policy, ar_text, past_news),
                    "mil_esp_sabotage", "gemini-2.5-flash")
                d = self._safe_json(raw)
                esp_entry["sabotage"] = bool(d.get("espionage_sabotage", False))
                esp_entry["sabotage_strategy"] = d.get("espionage_sabotage_strategy")
                esp_entry["sabotage_reasoning"] = d.get("reasoning_for_sabotage", "")
            except Exception as e:
                self.logger.sys_log(f"[{country_name}:M-05→{target_name}] エラー: {e}", "ERROR")

            result["espionage_actions"].append(esp_entry)

        return result

    # =================================================================
    # Phase 1-D: 内政タスク群（I-01〜I-08）
    # =================================================================

    def _run_phase1d_domestic(
        self, country_name: str, country_state: CountryState,
        world_state: WorldState, policy: PresidentPolicy, past_news: List[str]
    ) -> DomesticAction:
        """I-01〜I-08: 内政タスク群を実行しDomesticActionに統合"""
        # デフォルト値
        tax_rate = country_state.tax_rate
        target_tariff_rates: Dict[str, float] = {}
        invest_economy = 0.35
        invest_welfare = 0.25
        invest_education_science = 0.05
        target_press_freedom = country_state.press_freedom
        report_economy = None; report_military = None
        report_approval_rating = None; report_intelligence_level = None; report_gdp_per_capita = None
        deception_reason = ""
        dissolve_parliament = False
        reason = "タスクエージェント統合"

        # I-01: 税率
        try:
            raw = self._execute_agent(country_name, "内政:税率(I-01)",
                build_tax_rate_prompt(country_name, country_state, world_state, policy, past_news),
                "dom_tax", "gemini-2.5-flash-lite")
            d = self._safe_json(raw)
            tax_rate = float(d.get("tax_rate", tax_rate))
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:I-01] エラー: {e}", "ERROR")

        # I-02: 関税率
        try:
            raw = self._execute_agent(country_name, "内政:関税(I-02)",
                build_tariff_prompt(country_name, country_state, world_state, policy, past_news),
                "dom_tariff", "gemini-2.5-flash-lite")
            d = self._safe_json(raw)
            raw_tariffs = d.get("target_tariff_rates", {})
            target_tariff_rates = {k: float(v) for k, v in raw_tariffs.items()}
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:I-02] エラー: {e}", "ERROR")

        # I-03: 経済投資
        try:
            raw = self._execute_agent(country_name, "内政:経済投資(I-03)",
                build_economy_invest_prompt(country_name, country_state, world_state, policy, past_news),
                "dom_econ", "gemini-2.5-flash-lite")
            d = self._safe_json(raw)
            invest_economy = float(d.get("invest_economy", invest_economy))
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:I-03] エラー: {e}", "ERROR")

        # I-04: 福祉投資
        try:
            raw = self._execute_agent(country_name, "内政:福祉投資(I-04)",
                build_welfare_invest_prompt(country_name, country_state, world_state, policy, past_news),
                "dom_welfare", "gemini-2.5-flash-lite")
            d = self._safe_json(raw)
            invest_welfare = float(d.get("invest_welfare", invest_welfare))
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:I-04] エラー: {e}", "ERROR")

        # I-05: 教育・科学投資
        try:
            raw = self._execute_agent(country_name, "内政:教育投資(I-05)",
                build_education_invest_prompt(country_name, country_state, world_state, policy, past_news),
                "dom_edu", "gemini-2.5-flash-lite")
            d = self._safe_json(raw)
            invest_education_science = float(d.get("invest_education_science", invest_education_science))
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:I-05] エラー: {e}", "ERROR")

        # I-06: 報道の自由度
        try:
            raw = self._execute_agent(country_name, "内政:報道統制(I-06)",
                build_press_freedom_prompt(country_name, country_state, world_state, policy, past_news),
                "dom_press", "gemini-2.5-flash-lite")
            d = self._safe_json(raw)
            target_press_freedom = float(d.get("target_press_freedom", target_press_freedom))
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:I-06] エラー: {e}", "ERROR")

        # I-07: 情報偽装
        try:
            raw = self._execute_agent(country_name, "内政:情報偽装(I-07)",
                build_deception_prompt(country_name, country_state, world_state, policy, past_news),
                "dom_deception", "gemini-2.5-flash")
            d = self._safe_json(raw)
            report_economy = d.get("report_economy")
            report_military = d.get("report_military")
            report_approval_rating = d.get("report_approval_rating")
            report_intelligence_level = d.get("report_intelligence_level")
            report_gdp_per_capita = d.get("report_gdp_per_capita")
            # LLMが null を返した場合 None になるので空文字列にフォールバック
            deception_reason = d.get("deception_reason") or ""
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:I-07] エラー: {e}", "ERROR")

        # I-08: 議会解散（民主主義のみ）
        if country_state.government_type.value == "democracy":
            try:
                raw = self._execute_agent(country_name, "内政:議会解散(I-08)",
                    build_parliament_prompt(country_name, country_state, world_state, policy, past_news),
                    "dom_parliament", "gemini-2.5-flash-lite")
                d = self._safe_json(raw)
                dissolve_parliament = bool(d.get("dissolve_parliament", False))
            except Exception as e:
                self.logger.sys_log(f"[{country_name}:I-08] エラー: {e}", "ERROR")

        return DomesticAction(
            tax_rate=tax_rate,
            target_tariff_rates=target_tariff_rates,
            invest_economy=invest_economy,
            invest_welfare=invest_welfare,
            invest_education_science=invest_education_science,
            target_press_freedom=target_press_freedom,
            report_economy=report_economy,
            report_military=report_military,
            report_approval_rating=report_approval_rating,
            report_intelligence_level=report_intelligence_level,
            report_gdp_per_capita=report_gdp_per_capita,
            deception_reason=deception_reason or "",  # None安全
            dissolve_parliament=dissolve_parliament,
            invest_military=0.15,        # 後でPhase1-Eで上書きされる
            invest_intelligence=0.05,    # 後でPhase1-Eで上書きされる
            reasoning_for_military_investment="Phase1-Cより取得",
            reason=reason,
        )

    # =================================================================
    # Phase 1-E: 予算正規化（B-01）
    # =================================================================

    def _run_phase1e_normalize(
        self, country_name: str, policy: PresidentPolicy,
        invest_military: float, invest_intelligence: float,
        invest_economy: float, invest_welfare: float, invest_education_science: float,
    ) -> dict:
        """B-01: 予算正規化（flash-lite）- 合計>1.0の場合のみLLM呼び出し"""
        total = invest_military + invest_intelligence + invest_economy + invest_welfare + invest_education_science
        base = {
            "invest_military": invest_military,
            "invest_intelligence": invest_intelligence,
            "invest_economy": invest_economy,
            "invest_welfare": invest_welfare,
            "invest_education_science": invest_education_science,
        }
        if total <= 1.001:
            self.logger.sys_log(f"[{country_name}:B-01] 予算合計={total:.3f} ≤ 1.0 → 正規化スキップ")
            return base

        self.logger.sys_log(f"[{country_name}:B-01] 予算合計={total:.3f} > 1.0 → LLM正規化実行")
        try:
            prompt = build_budget_normalize_prompt(
                country_name, policy,
                invest_military, invest_intelligence,
                invest_economy, invest_welfare, invest_education_science,
            )
            raw = self._execute_agent(country_name, "予算正規化(B-01)", prompt, "budget_norm", "gemini-2.5-flash-lite")
            d = self._safe_json(raw)
            normalized = {
                "invest_military": float(d.get("invest_military", invest_military)),
                "invest_intelligence": float(d.get("invest_intelligence", invest_intelligence)),
                "invest_economy": float(d.get("invest_economy", invest_economy)),
                "invest_welfare": float(d.get("invest_welfare", invest_welfare)),
                "invest_education_science": float(d.get("invest_education_science", invest_education_science)),
            }
            # LLM結果でも超過している場合はフォールバックで単純按分
            new_total = sum(normalized.values())
            if new_total > 1.001:
                scale = 1.0 / new_total
                normalized = {k: round(v * scale, 4) for k, v in normalized.items()}
                self.logger.sys_log(f"[{country_name}:B-01] LLM結果も超過({new_total:.3f}) → 単純按分にフォールバック")
            return normalized
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:B-01] エラー: {e} → 単純按分", "ERROR")
            scale = 1.0 / total
            return {k: round(v * scale, 4) for k, v in base.items()}

    # =================================================================
    # マージ: 全タスク出力 → AgentAction
    # =================================================================

    def _merge_all(
        self,
        country_name: str,
        policy: PresidentPolicy,
        major_dipl_dict: dict,
        diplomacy_list: List[DiplomaticAction],
        military_data: dict,
        domestic_action: DomesticAction,
        normalized: dict,
    ) -> AgentAction:
        """全タスク出力をAgentActionに統合する"""
        # --- 予算の正規化値をDomesticActionに反映 ---
        domestic_action = domestic_action.model_copy(update={
            "invest_military":          normalized["invest_military"],
            "invest_intelligence":      normalized["invest_intelligence"],
            "invest_economy":           normalized["invest_economy"],
            "invest_welfare":           normalized["invest_welfare"],
            "invest_education_science": normalized["invest_education_science"],
            "reasoning_for_military_investment": military_data.get("reasoning_for_military_investment") or "",
        })

        # --- 外交リストにmilitary_dataの諜報アクションをマージ ---
        merged: Dict[str, DiplomaticAction] = {a.target_country: a for a in diplomacy_list}

        for esp in military_data.get("espionage_actions", []):
            tc = esp["target"]
            if tc not in merged:
                merged[tc] = DiplomaticAction(target_country=tc, reason="諜報タスク")
            a = merged[tc]
            a.espionage_gather_intel = esp.get("gather", False)
            a.espionage_intel_strategy = esp.get("gather_strategy")
            a.espionage_sabotage = esp.get("sabotage", False)
            a.espionage_sabotage_strategy = esp.get("sabotage_strategy")
            a.reasoning_for_sabotage = esp.get("sabotage_reasoning")

        # --- 前線投入比率をマージ ---
        for tc, ratio in military_data.get("war_commitment_ratios", {}).items():
            if tc not in merged:
                merged[tc] = DiplomaticAction(target_country=tc, reason="前線投入比率変更")
            merged[tc].war_commitment_ratio = ratio

        # --- P-02: 重大外交をマージ ---
        for ma in major_dipl_dict.get("major_diplomatic_actions", []):
            tc = ma.get("target_country", "")
            if not tc:
                continue
            if tc not in merged:
                merged[tc] = DiplomaticAction(target_country=tc, reason=ma.get("reason", "大統領決定"))
            a = merged[tc]
            if ma.get("declare_war"):       a.declare_war       = True
            if ma.get("propose_alliance"):  a.propose_alliance  = True
            if ma.get("join_ally_defense"):
                a.join_ally_defense          = True
                a.defense_support_commitment = ma.get("defense_support_commitment")
            if ma.get("propose_annexation"): a.propose_annexation = True
            if ma.get("accept_annexation"):  a.accept_annexation  = True
            if ma.get("propose_ceasefire"):  a.propose_ceasefire  = True
            if ma.get("accept_ceasefire"):   a.accept_ceasefire   = True
            if ma.get("demand_surrender"):   a.demand_surrender   = True
            if ma.get("accept_surrender"):   a.accept_surrender   = True
            if ma.get("reason"):             a.reason             = ma["reason"]

        # --- 海峡封鎖フラグをworld_state側でハンドリングするため、
        #     declare_strait_blockade / resolve_strait_blockade をDiplomaticActionの
        #     "STRAIT" 仮想ターゲットに格納する（engine側で解釈） ---
        declare_blockade = major_dipl_dict.get("declare_strait_blockade")
        resolve_blockade = major_dipl_dict.get("resolve_strait_blockade")
        if declare_blockade:
            strait_key = f"__STRAIT_DECLARE__{declare_blockade}"
            merged[strait_key] = DiplomaticAction(
                target_country=strait_key,
                reason=f"海峡封鎖宣言: {declare_blockade}"
            )
        if resolve_blockade:
            strait_key = f"__STRAIT_RESOLVE__{resolve_blockade}"
            merged[strait_key] = DiplomaticAction(
                target_country=strait_key,
                reason=f"海峡封鎖解除: {resolve_blockade}"
            )

        # --- v1-3: 核兵器フラグを仮想DiplomaticActionに変換（engine/nuclear.pyで解釈） ---
        launch_tactical = major_dipl_dict.get("launch_tactical_nuclear")
        if launch_tactical:
            tac_count = major_dipl_dict.get("tactical_nuclear_count", 1)
            nuke_key = f"__NUCLEAR_TACTICAL__{launch_tactical}:{tac_count}"
            merged[nuke_key] = DiplomaticAction(
                target_country=nuke_key,
                reason=f"戦術核使用: {launch_tactical} ({tac_count}発)"
            )

        launch_strategic = major_dipl_dict.get("launch_strategic_nuclear")
        if launch_strategic:
            count = major_dipl_dict.get("strategic_nuclear_count", 5)
            nuke_key = f"__NUCLEAR_STRATEGIC__{launch_strategic}:{count}"
            merged[nuke_key] = DiplomaticAction(
                target_country=nuke_key,
                reason=f"戦略核使用: {launch_strategic} ({count}発)"
            )

        deploy_ally = major_dipl_dict.get("deploy_nuclear_to_ally")
        if deploy_ally:
            deploy_count = major_dipl_dict.get("deploy_nuclear_count", 10)
            nuke_key = f"__NUCLEAR_DEPLOY__{deploy_ally}:{deploy_count}"
            merged[nuke_key] = DiplomaticAction(
                target_country=nuke_key,
                reason=f"核配備: {deploy_ally}に{deploy_count}発"
            )

        if major_dipl_dict.get("remove_hosted_nuclear"):
            merged["__NUCLEAR_REMOVE_HOSTED__"] = DiplomaticAction(
                target_country="__NUCLEAR_REMOVE_HOSTED__",
                reason="自国領土の他国核撤去"
            )

        # 核開発投資率を仮想フラグに変換（M-06のinvest_nuclearから取得）
        invest_nuclear = military_data.get("invest_nuclear", 0.0)
        if invest_nuclear > 0:
            nuke_key = f"__NUCLEAR_INVEST__{invest_nuclear}"
            merged[nuke_key] = DiplomaticAction(
                target_country=nuke_key,
                reason=f"核開発投資: {invest_nuclear:.2f}"
            )

        return AgentAction(
            thought_process=policy.hidden_plans or f"{country_name}の施政方針({policy.stance})",
            sns_posts=policy.sns_posts,
            update_hidden_plans=policy.hidden_plans,
            domestic_policy=domestic_action,
            diplomatic_policies=list(merged.values()),
        )

    # =================================================================
    # メイン: 1国の行動を決定する
    # =================================================================

    def _decide_country_action(
        self, country_name: str, country_state: CountryState,
        world_state: WorldState, past_news: List[str] = None
    ) -> Tuple[AgentAction, Dict[str, str]]:
        """大統領施政方針 → タスクエージェント群 → マージ の3段フロー"""

        self.logger.sys_log(f"[{country_name}] ===== ターン開始: タスクエージェント制 =====")

        # Phase 0: 施政方針 + 重大外交
        self.logger.sys_log(f"[{country_name}] Phase0: 大統領施政方針 + 重大外交")
        policy = self._run_phase0_policy(country_name, country_state, world_state, past_news or [])
        country_state.hidden_plans = policy.hidden_plans  # 施政方針メモを更新
        major_dipl_dict = self._run_phase0_major_diplomacy(country_name, country_state, world_state, policy, past_news or [])

        # Phase 1-A: 分析官
        self.logger.sys_log(f"[{country_name}] Phase1-A: 分析官レポート")
        analyst_reports = self._run_phase1a_analysis(country_name, country_state, world_state, past_news or [])

        # Phase 1-B: 外交タスク群
        self.logger.sys_log(f"[{country_name}] Phase1-B: 外交タスク群 (D-01〜D-08)")
        diplomacy_list = self._run_phase1b_diplomacy(country_name, country_state, world_state, policy, analyst_reports, past_news or [])

        # Phase 1-C: 軍事・諜報タスク群
        self.logger.sys_log(f"[{country_name}] Phase1-C: 軍事・諜報タスク群 (M-01〜M-05)")
        military_data = self._run_phase1c_military(country_name, country_state, world_state, policy, analyst_reports, past_news or [])

        # Phase 1-D: 内政タスク群
        self.logger.sys_log(f"[{country_name}] Phase1-D: 内政タスク群 (I-01〜I-08)")
        domestic_action = self._run_phase1d_domestic(country_name, country_state, world_state, policy, past_news or [])

        # Phase 1-E: 予算正規化
        self.logger.sys_log(f"[{country_name}] Phase1-E: 予算正規化 (B-01)")
        normalized = self._run_phase1e_normalize(
            country_name, policy,
            invest_military=military_data["invest_military"],
            invest_intelligence=military_data["invest_intelligence"],
            invest_economy=domestic_action.invest_economy,
            invest_welfare=domestic_action.invest_welfare,
            invest_education_science=domestic_action.invest_education_science,
        )

        # マージ
        try:
            action = self._merge_all(
                country_name, policy, major_dipl_dict,
                diplomacy_list, military_data, domestic_action, normalized
            )
        except Exception as e:
            self.logger.sys_log(f"[{country_name}] マージエラー: {e}", "ERROR")
            traceback.print_exc()
            action = self._create_fallback_action(country_name, country_state.tax_rate)

        self.logger.sys_log(f"[{country_name}] ===== ターン完了 =====")
        # タスクログをバッファから取得して返す
        task_logs = dict(self._task_log_buffer.get(country_name, {}))
        return action, analyst_reports, task_logs

    def generate_actions(
        self, world_state: WorldState, past_news: List[str] = None
    ) -> Tuple[Dict[str, AgentAction], Dict[str, Dict[str, str]], Dict[str, Dict[str, str]]]:
        """全国家の行動を生成し、(actions, all_analyst_reports, all_task_logs) のタプルで返す"""
        # ターン開始時にバッファをリセット
        self._task_log_buffer: Dict[str, Dict[str, str]] = {}

        actions: Dict[str, AgentAction] = {}
        all_analyst_reports: Dict[str, Dict[str, str]] = {}
        all_task_logs: Dict[str, Dict[str, str]] = {}
        for country_name, country_state in world_state.countries.items():
            try:
                action, analyst_reports, task_logs = self._decide_country_action(
                    country_name, country_state, world_state, past_news
                )
                actions[country_name] = action
                all_analyst_reports[country_name] = analyst_reports
                all_task_logs[country_name] = task_logs
            except Exception as e:
                self.logger.sys_log(f"⚠️ {country_name}の推論中にエラーが発生しました: {e}", "ERROR")
                traceback.print_exc()
                actions[country_name] = self._create_fallback_action(
                    country_name, current_tax_rate=country_state.tax_rate
                )
                all_analyst_reports[country_name] = {}
                all_task_logs[country_name] = {}
        return actions, all_analyst_reports, all_task_logs

    def _create_fallback_action(self, country_name: str, current_tax_rate: float = 0.30) -> AgentAction:
        return AgentAction(
            thought_process="APIエラーのため前ターンの政策を継続する（現状維持）。",
            domestic_policy=DomesticAction(
                tax_rate=current_tax_rate,
                target_press_freedom=0.5,
                invest_economy=0.50,
                reasoning_for_military_investment="状況が不確実なため、基本的な軍備維持に留める。",
                invest_military=0.10,
                invest_welfare=0.30,
                invest_intelligence=0.05,
                invest_education_science=0.05,
                reason="APIエラーによるフォールバック実行"
            ),
            diplomatic_policies=[]
        )

    # =================================================================
    # モジュール委譲メソッド（旧core.pyと同一インターフェース）
    # =================================================================

    def run_summit(self, proposal, state_a, state_b, world_state, past_news=None) -> Tuple[str, str]:
        search_tool_a = self._create_search_tool(proposal.proposer, "首脳会談")
        search_tool_b = self._create_search_tool(proposal.target, "首脳会談")
        return summit.run_summit(self._generate_with_retry, self.logger, self.db_manager, proposal, state_a, state_b, world_state, past_news, search_tool_a, search_tool_b)

    def run_multilateral_summit(self, proposal, country_states, world_state, past_news=None) -> Tuple[str, str]:
        participants = proposal.accepted_participants if proposal.accepted_participants else proposal.participants
        if proposal.proposer not in participants:
            participants = [proposal.proposer] + participants
        search_tools = {p: self._create_search_tool(p, "多国間会談") for p in participants}
        return summit.run_multilateral_summit(self._generate_with_retry, self.logger, self.db_manager, proposal, country_states, world_state, past_news, search_tools)

    def generate_espionage_report(self, attacker_name: str, target_name: str, target_hidden_plans: str, strategy: str) -> Tuple[str, Optional[str]]:
        return intelligence.generate_espionage_report(self._generate_with_retry, self.logger, attacker_name, target_name, target_hidden_plans, strategy)

    def generate_citizen_sns_posts(self, country_name: str, country_state: CountryState, world_state: WorldState, count: int) -> List[str]:
        return media.generate_citizen_sns_posts(self._generate_with_retry, self.logger, country_name, country_state, world_state, count)

    def generate_breakthrough_name(self, country_name: str, active_breakthroughs: List[Any], current_year: int) -> str:
        return media.generate_breakthrough_name(self._generate_with_retry, self.logger, country_name, active_breakthroughs, current_year)

    def generate_ideology_democracy(self, country_name: str, target_country_state: CountryState, world_state: WorldState, citizen_sns: List[str]) -> str:
        return media.generate_ideology_democracy(self._generate_with_retry, self.logger, country_name, target_country_state, world_state, citizen_sns)

    def generate_ideology_authoritarian(self, country_name: str, target_country_state: CountryState, world_state: WorldState) -> str:
        return media.generate_ideology_authoritarian(self._generate_with_retry, self.logger, country_name, target_country_state, world_state)

    def generate_fragmentation_profile(self, target_country_name: str, sns_logs: List[Dict]) -> Tuple[str, str]:
        return media.generate_fragmentation_profile(self._generate_with_retry, self.logger, target_country_name, sns_logs)

    def generate_media_reports(self, world_state: WorldState, previous_actions: Dict[str, AgentAction], recent_summit_logs: List[str] = None) -> Tuple[List[str], Dict[str, float]]:
        return media.generate_media_reports(self._generate_with_retry, self.logger, self.sentiment_analyzer, world_state, previous_actions, recent_summit_logs)
