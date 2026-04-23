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

from models import WorldState, CountryState, AgentAction, DomesticAction
from logger import SimulationLogger

from agent.prompts.analyst import build_analyst_prompt
from agent.prompts.foreign import build_foreign_minister_prompt
from agent.prompts.defense import build_defense_minister_prompt
from agent.prompts.economic import build_economic_minister_prompt
from agent.prompts.finance import build_finance_minister_prompt
from agent.prompts.president import build_president_prompt

from agent.modules.media import GeminiSentimentAnalyzer
from agent.modules import summit, media, intelligence

load_dotenv()

class AgentSystem:
    """Gemini APIを使用して各国家の意思決定を行うAIエージェントシステム（外務・防衛・経済・財務の大臣と大統領の5エージェント制）"""
    
    def __init__(self, logger: SimulationLogger = None, model_name: str = "gemini-2.5-pro", db_manager=None): 
        self.logger = logger
        self.db_manager = db_manager
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            # loggerがNone（ダミーインスタンス）の場合はAPI未設定でもクラッシュしない
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
        
        # サブAPIキーのクライアント初期化（フォールバック用）
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
        
        # Ollamaクライアントの初期化
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
        """内部用: 指定されたclientでAPI呼び出しを行う（tenacityリトライ付き）"""
        # Mistral Small (Ollama) への自動ルーティング
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
        """メインキーでAPI呼び出しを試行し、全リトライ失敗時にサブキーへフォールバック"""
        try:
            return self._generate_with_retry_internal(self.client, model, contents, config, category)
        except Exception as main_error:
            if self.client_sub is None:
                raise  # サブキーなしの場合はそのままエラーを伝播
            
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
                raise  # サブキーでも失敗した場合はサブ側のエラーを伝播

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
                config=types.GenerateContentConfig(
                    tools=tools,
                    temperature=0.4
                ),
                category=category
            )
            
            # ツール呼び出しの処理
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
            return response_text.strip()

        except Exception as e:
            self.logger.sys_log(f"[{country_name}:{role}] APIエラー発生: {e}", "ERROR")
            return "{}"

    def generate_actions(
        self, world_state: WorldState, past_news: List[str] = None
    ) -> Tuple[Dict[str, AgentAction], Dict[str, Dict[str, str]]]:
        """全国家の行動を生成し、(actions, all_analyst_reports) のタプルで返す"""
        actions: Dict[str, AgentAction] = {}
        all_analyst_reports: Dict[str, Dict[str, str]] = {}
        for country_name, country_state in world_state.countries.items():
            try:
                action, analyst_reports = self._decide_country_action(
                    country_name, country_state, world_state, past_news
                )
                actions[country_name] = action
                all_analyst_reports[country_name] = analyst_reports
            except Exception as e:
                self.logger.sys_log(f"⚠️ {country_name}の推論中にエラーが発生しました: {e}", "ERROR")
                traceback.print_exc()
                actions[country_name] = self._create_fallback_action(
                    country_name, current_tax_rate=country_state.tax_rate
                )
                all_analyst_reports[country_name] = {}

        return actions, all_analyst_reports

    @staticmethod
    def _extract_thought_process(proposal_text: str, role: str) -> str:
        """大臣JSONからthought_processを抽出して大統領向け提言テキストを生成"""
        try:
            data = json.loads(proposal_text)
            thought = data.get("thought_process", "").strip()
            return f"【{role}の思考・提言】\n{thought}" if thought else f"（{role}の提言なし）"
        except Exception:
            return f"（{role}のJSON解析失敗）"

    def _decide_country_action(
        self, country_name: str, country_state: CountryState,
        world_state: WorldState, past_news: List[str] = None
    ) -> Tuple[AgentAction, Dict[str, str]]:
        """分析官→閣僚→大統領の3段階の意思決定を行い、(AgentAction, analyst_reports) で返す"""
        
        # フェーズ0: 分析官による各国分析 (gemini-2.5-flash-lite)
        analyst_reports = {}
        other_countries = [name for name in world_state.countries.keys() if name != country_name]
        
        if other_countries:
            self.logger.sys_log(f"[{country_name}] フェーズ0: 分析官による各国分析を開始 ({len(other_countries)}カ国)")
            for target_name in other_countries:
                try:
                    target_state = world_state.countries.get(target_name)

                    # ===== 確率的諜報判定 =====
                    # 自国諜報力 / (自国 + 相手国諜報力) の確率で真値取得に成功
                    # 偽装がない国に対しては判定を行わない（処理コスト節約）
                    import random
                    has_deception = target_state is not None and any([
                        target_state.reported_economy            is not None,
                        target_state.reported_military           is not None,
                        target_state.reported_approval_rating    is not None,
                        target_state.reported_intelligence_level is not None,
                        target_state.reported_gdp_per_capita     is not None,
                    ])
                    use_real_stats = False
                    if has_deception and target_state is not None:
                        my_intel     = max(1.0, country_state.intelligence_level)
                        enemy_intel  = max(1.0, target_state.intelligence_level)
                        success_prob = my_intel / (my_intel + enemy_intel)
                        roll = random.random()
                        use_real_stats = (roll < success_prob)
                        result_str = "✅ 諜報成功（真値取得）" if use_real_stats else "❌ 諜報失敗（偽装値のまま）"
                        self.logger.sys_log(
                            f"[{country_name}→{target_name} 諜報判定] "
                            f"自国:{my_intel:.1f} / 相手:{enemy_intel:.1f} "
                            f"成功確率:{success_prob:.1%} | roll:{roll:.3f} → {result_str}"
                        )
                    # ===========================

                    analyst_prompt = build_analyst_prompt(
                        country_name, country_state, world_state,
                        target_name, past_news,
                        use_real_stats=use_real_stats
                    )
                    report = self._execute_agent(
                        country_name, f"分析官(対{target_name})",
                        analyst_prompt, "analyst",
                        override_model="gemini-2.5-flash-lite"
                    )
                    analyst_reports[target_name] = report
                    self.logger.sys_log_detail(f"{country_name} Analyst Report (vs {target_name})", report)
                except Exception as exc:
                    self.logger.sys_log(f"[{country_name}:分析官(対{target_name})] 推論中に例外発生: {exc}", "ERROR")
                    analyst_reports[target_name] = "分析データなし（エラー）"
            
            self.logger.sys_log(f"[{country_name}] フェーズ0完了: {len(analyst_reports)}カ国の分析レポートを取得")
        
        # フェーズ1: 4大臣によるプロポーザルの逐次生成
        # 外務・防衛大臣には分析官レポートを渡す（財務大臣は不要）
        ar = analyst_reports if analyst_reports else None
        foreign_prompt  = build_foreign_minister_prompt(country_name, country_state, world_state, past_news, analyst_reports=ar)
        defense_prompt  = build_defense_minister_prompt(country_name, country_state, world_state, past_news, analyst_reports=ar)
        economic_prompt = build_economic_minister_prompt(country_name, country_state, world_state, past_news)
        finance_prompt  = build_finance_minister_prompt(country_name, country_state, world_state, past_news, analyst_reports=None)

        proposals = {}
        minister_tasks = [
            ("外務大臣", foreign_prompt, "actions_foreign", "foreign"),
            ("防衛大臣", defense_prompt, "actions_defense", "defense"),
            ("経済内務大臣", economic_prompt, "actions_economic", "economic"),
            ("財務大臣", finance_prompt, "actions_finance", "finance"),
        ]
        for role_name, prompt, category, key in minister_tasks:
            try:
                result = self._execute_agent(country_name, role_name, prompt, category, "gemini-2.5-flash")
                proposals[key] = result
                self.logger.sys_log_detail(f"{country_name} Minister Proposal ({key})", result)
            except Exception as exc:
                self.logger.sys_log(f"[{country_name}:{role_name}] 推論中に例外発生: {exc}", "ERROR")
                proposals[key] = "{}"

        # フェーズ2: 大統領による最終決定 (gemini-2.5-pro)
        # 大臣提案のfull JSONは system.log に記録済み。大統領には thought_process のみ渡す。
        minister_summaries = {
            "外務大臣": self._extract_thought_process(proposals.get('foreign',  '{}'), "外務大臣"),
            "防衛大臣": self._extract_thought_process(proposals.get('defense',  '{}'), "防衛大臣"),
            "経済大臣": self._extract_thought_process(proposals.get('economic', '{}'), "経済大臣"),
            "財務大臣": self._extract_thought_process(proposals.get('finance',  '{}'), "財務大臣"),
        }
        president_prompt = build_president_prompt(
            country_name,
            country_state,
            world_state,
            minister_summaries=minister_summaries,
            past_news=past_news
        )

        final_decision_text = self._execute_agent(country_name, "大統領", president_prompt, "actions_president")
        self.logger.sys_log_detail(f"{country_name} President Decision", final_decision_text)

        # JSON解析とAgentActionモデルへのマッピング
        try:
            data = json.loads(final_decision_text)
            return AgentAction(**data), analyst_reports
        except json.JSONDecodeError as e:
            self.logger.sys_log(f"[{country_name}:大統領] JSON解析エラー: {e}\nRaw={final_decision_text}", "ERROR")
            return self._create_fallback_action(country_name), analyst_reports
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:大統領] 予期せぬエラー: {e}", "ERROR")
            return self._create_fallback_action(country_name), analyst_reports

    def _create_fallback_action(self, country_name: str, current_tax_rate: float = 0.30) -> AgentAction:
        return AgentAction(
            thought_process="APIエラーのため前ターンの政策を継続する（現状維持）。",
            domestic_policy=DomesticAction(
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

    # Delegation methods for modules
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
