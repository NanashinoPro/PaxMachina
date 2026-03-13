import os
import json
import traceback
import time
from typing import Dict, Any, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from google.genai import types
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

from models import WorldState, CountryState, AgentAction, DomesticAction
from logger import SimulationLogger

from agent.prompts.foreign import build_foreign_minister_prompt
from agent.prompts.defense import build_defense_minister_prompt
from agent.prompts.economic import build_economic_minister_prompt
from agent.prompts.president import build_president_prompt

from agent.modules.media import GeminiSentimentAnalyzer
from agent.modules import summit, media, intelligence

load_dotenv()

class AgentSystem:
    """Gemini APIを使用して各国家の意思決定を行うAIエージェントシステム（外務・防衛・経済の大臣と大統領の4エージェント制）"""
    
    def __init__(self, logger: SimulationLogger, model_name: str = "gemini-2.5-pro", db_manager=None): 
        self.logger = logger
        self.db_manager = db_manager
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEYが環境変数に設定されていません。")
            
        self.client = genai.Client(api_key=api_key, http_options={'timeout': 60000})
        self.model_name = model_name
        self.sentiment_analyzer = GeminiSentimentAnalyzer(self.client)
        self.token_usage = {}

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=4, max=30))
    def _generate_with_retry(self, model: str, contents: str, config: types.GenerateContentConfig = None, category: str = "default") -> Any:
        if config:
            response = self.client.models.generate_content(model=model, contents=contents, config=config)
        else:
            response = self.client.models.generate_content(model=model, contents=contents)
            
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            meta = response.usage_metadata
            if category not in self.token_usage:
                self.token_usage[category] = {"prompt_tokens": 0, "candidates_token_count": 0, "model": model}
            self.token_usage[category]["prompt_tokens"] += getattr(meta, 'prompt_token_count', 0)
            self.token_usage[category]["candidates_token_count"] += getattr(meta, 'candidates_token_count', 0)
            
        return response

    def _create_search_tool(self, country_name: str):
        db_manager = getattr(self, "db_manager", None)
        
        def search_historical_events(query: str) -> str:
            """過去の重要な外交、内政、諜報に関する出来事の記録やニュースをデータベースから検索します。"""
            if not db_manager:
                return "データベースが利用できません。"
            self.logger.sys_log(f"[{country_name}] Tool Call: 過去の記録を検索中... (クエリ: '{query}')")
            try:
                results = db_manager.search_events(searcher_country=country_name, query=query, limit=3)
                if not results:
                    return "該当する記録は見つかりませんでした。"
                
                res_str = "---検索結果---\n"
                for r in results:
                    t = r.get("turn", "?")
                    cnt = r.get("content", "")
                    res_str += f"[Turn {t}] {cnt}\n"
                return res_str
            except Exception as e:
                return f"検索中にエラーが発生しました: {e}"
        return search_historical_events if db_manager else None

    def _execute_agent(self, country_name: str, role: str, prompt: str, category: str) -> str:
        """エージェントの推論を実行し、必要に応じて検索ツールを呼び出す"""
        start_time = time.time()
        self.logger.sys_log(f"[{country_name}:{role}] API推論開始...")
        
        search_tool = self._create_search_tool(country_name)
        tools = [search_tool] if search_tool else None

        try:
            response = self._generate_with_retry(
                model=self.model_name,
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
                            model=self.model_name,
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

    def generate_actions(self, world_state: WorldState, past_news: List[str] = None) -> Dict[str, AgentAction]:
        actions = {}
        for country_name, country_state in world_state.countries.items():
            try:
                action = self._decide_country_action(country_name, country_state, world_state, past_news)
                actions[country_name] = action
            except Exception as e:
                self.logger.sys_log(f"⚠️ {country_name}の推論中にエラーが発生しました: {e}", "ERROR")
                traceback.print_exc()
                actions[country_name] = self._create_fallback_action(country_name, current_tax_rate=country_state.tax_rate)
                
        return actions

    def _decide_country_action(self, country_name: str, country_state: CountryState, world_state: WorldState, past_news: List[str] = None) -> AgentAction:
        """閣僚エージェントと大統領エージェントを用いた2段階の意思決定を行う"""
        
        # フェーズ1: 3大臣によるプロポーザルの並行生成
        foreign_prompt = build_foreign_minister_prompt(country_name, country_state, world_state, past_news)
        defense_prompt = build_defense_minister_prompt(country_name, country_state, world_state, past_news)
        economic_prompt = build_economic_minister_prompt(country_name, country_state, world_state, past_news)

        proposals = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_role = {
                executor.submit(self._execute_agent, country_name, "外務大臣", foreign_prompt, "actions_foreign"): "foreign",
                executor.submit(self._execute_agent, country_name, "防衛大臣", defense_prompt, "actions_defense"): "defense",
                executor.submit(self._execute_agent, country_name, "経済内務大臣", economic_prompt, "actions_economic"): "economic"
            }
            
            for future in as_completed(future_to_role):
                role = future_to_role[future]
                try:
                    result = future.result()
                    proposals[role] = result
                    self.logger.sys_log_detail(f"{country_name} Minister Proposal ({role})", result)
                except Exception as exc:
                    self.logger.sys_log(f"[{country_name}:{role}] 並列推論中に例外発生: {exc}", "ERROR")
                    proposals[role] = "{}"

        # フェーズ2: 大統領による最終決定
        president_prompt = build_president_prompt(
            country_name, 
            country_state, 
            world_state, 
            foreign_proposal=proposals.get('foreign', '{}'),
            defense_proposal=proposals.get('defense', '{}'),
            economic_proposal=proposals.get('economic', '{}'),
            past_news=past_news
        )

        final_decision_text = self._execute_agent(country_name, "大統領", president_prompt, "actions_president")
        
        self.logger.sys_log_detail(f"{country_name} President Decision", final_decision_text)
        
        # JSON解析とAgentActionモデルへのマッピング
        try:
            data = json.loads(final_decision_text)
            return AgentAction(**data)
        except json.JSONDecodeError as e:
            self.logger.sys_log(f"[{country_name}:大統領] JSON解析エラー: {e}\nRaw={final_decision_text}", "ERROR")
            return self._create_fallback_action(country_name)
        except Exception as e:
            self.logger.sys_log(f"[{country_name}:大統領] 予期せぬエラー: {e}", "ERROR")
            return self._create_fallback_action(country_name)

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
        return summit.run_summit(self._generate_with_retry, self.logger, proposal, state_a, state_b, world_state, past_news)

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
