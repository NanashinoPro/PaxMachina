import os
import json
import traceback
from google import genai
from google.genai import types
from typing import Dict, Any, List, Tuple
from dotenv import load_dotenv

load_dotenv()

from models import WorldState, CountryState, AgentAction, DomesticAction, DiplomaticAction, GovernmentType, SummitProposal
from logger import SimulationLogger
import time
import threading
from tenacity import retry, stop_after_attempt, wait_exponential

class AgentSystem:
    """Gemini APIを使用して各国家の意思決定を行うAIエージェントシステム"""
    def __init__(self, logger: SimulationLogger, model_name: str = "gemini-2.5-pro"): 
        self.logger = logger
        # APIキーは環境変数から自動で読み込まれる想定
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEYが環境変数に設定されていません。")
            
        self.client = genai.Client(api_key=api_key, http_options={'timeout': 60000}) # タイムアウトを60秒に設定
        self.model_name = model_name
        
        # S-2: Gemini APIベースの感情分析器（osetiから移行, 政治・外交ドメインに高精度）
        self.sentiment_analyzer = GeminiSentimentAnalyzer(self.client)
        
        # コスト計算用のトラッカー
        self.token_usage = {}

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=4, max=30))
    def _generate_with_retry(self, model: str, contents: str, config: types.GenerateContentConfig = None, category: str = "default") -> Any:
        """API呼び出しのタイムアウトやレートリミットに対する自動リトライ処理"""
        if config:
            response = self.client.models.generate_content(model=model, contents=contents, config=config)
        else:
            response = self.client.models.generate_content(model=model, contents=contents)
            
        # トークン使用量の記録
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            meta = response.usage_metadata
            if category not in self.token_usage:
                self.token_usage[category] = {"prompt_tokens": 0, "candidates_token_count": 0, "model": model}
            self.token_usage[category]["prompt_tokens"] += getattr(meta, 'prompt_token_count', 0)
            self.token_usage[category]["candidates_token_count"] += getattr(meta, 'candidates_token_count', 0)
            
        return response

    def generate_actions(self, world_state: WorldState, past_news: List[str] = None) -> Dict[str, AgentAction]:
        """現在の世界状況からすべての国のアクションを生成する"""
        actions = {}
        for country_name, country_state in world_state.countries.items():
            try:
                action = self._decide_country_action(country_name, country_state, world_state, past_news)
                actions[country_name] = action
            except Exception as e:
                print(f"⚠️ {country_name}のエージェント推論中にエラーが発生しました: {e}")
                traceback.print_exc()
                # エラー時は安全のためにデフォルトの休眠アクションを割り当てる
                actions[country_name] = self._create_fallback_action(country_name, current_tax_rate=country_state.tax_rate)
                
        return actions

    def _decide_country_action(self, country_name: str, country_state: CountryState, world_state: WorldState, past_news: List[str] = None) -> AgentAction:
        """特定の一国の意思決定を行う"""
        
        prompt = self._build_prompt(country_name, country_state, world_state, past_news)
        self.logger.sys_log(f"[{country_name}] APIプロンプト送信開始...")
        
        start_time = time.time()
        try:
            # リトライ付きラッパーを経由して呼び出し
            response = self._generate_with_retry(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
                category="actions"
            )
        except Exception as e:
            self.logger.sys_log(f"[{country_name}] APIエラー発生: {e}", "ERROR")
            print(f"[{country_name}] API Error: {e}")
            return self._create_fallback_action(country_name, current_tax_rate=country_state.tax_rate)
            
        elapsed = time.time() - start_time
        self.logger.sys_log(f"[{country_name}] APIレスポンス受信完了 (所要時間: {elapsed:.2f}秒)")
        
        try:
            response_text = response.text
            self.logger.sys_log_detail(f"{country_name} Response", response_text)
            # 万が一のmarkdownブロック(```json ... ```)除去処理
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
                
            data = json.loads(response_text)
            
            # ディクショナリからPydanticモデルへの変換を行う
            return AgentAction(**data)
            
        except json.JSONDecodeError as e:
            self.logger.sys_log(f"[{country_name}] JSON解析エラー: {e}\nRaw={response.text}", "ERROR")
            print(f"JSON Parsing Error ({country_name}): {e}\nRaw={response.text}")
            return self._create_fallback_action(country_name)
        except Exception as e:
            self.logger.sys_log(f"[{country_name}] 予期せぬエラー: {e}", "ERROR")
            return self._create_fallback_action(country_name)

    def _build_prompt(self, country_name: str, country_state: CountryState, world_state: WorldState, past_news: List[str] = None) -> str:
        """AIへ状況を説明しJSON出力を促すプロンプトを作成する"""
        
        # 自国の詳細情報
        my_info = (
            f"あなたは「{country_name}」の最高指導者（首脳）です。\n"
            f"あなたの国の体制は '{country_state.government_type.value}'、現在のペルソナ・イデオロギーは '{country_state.ideology}' です。\n"
            f"---現在のステータス---\n"
            f"経済力(GDP): {country_state.economy:.1f}\n"
            f"軍事力: {country_state.military:.1f}\n"
            f"現在の税率: {country_state.tax_rate:.1%}\n"
            f"政府予算(税収 - 利払い): {country_state.government_budget:.1f}\n"
            f"直近の貿易収支(NX): {country_state.last_turn_nx:+.1f} (マイナスは赤字流出を意味)\n"
            f"国家債務(National Debt): {country_state.national_debt:.1f}\n"
            f"国民の支持率: {country_state.approval_rating:.1f}% (30%未満で危険)\n"
            f"報道の自由度: {country_state.press_freedom:.3f} (0.0-1.0。低いほど情報統制されるが不満が高まる)\n"
        )
        
        if country_state.turns_until_election is not None:
             my_info += f"次回の選挙まで残り: {country_state.turns_until_election}ターン (支持率が低いと落選します)\n"
        else:
             my_info += f"現在の反乱リスク: {country_state.rebellion_risk:.1f}% (支持率が低いと高まります)\n"
        
        my_info += f"あなたの脳内（非公開の計画など）には次のような情報があります: '{country_state.hidden_plans}'\n\n"
        
        # 制裁情報の付与
        active_sanctions = world_state.active_sanctions if hasattr(world_state, 'active_sanctions') else []
        my_sanctions = [s for s in active_sanctions if s.imposer == country_name]
        sanctions_against_me = [s for s in active_sanctions if s.target == country_name]
        if my_sanctions or sanctions_against_me:
            my_info += "---現在の経済制裁の状況---\n"
            if my_sanctions:
                targets = ", ".join([s.target for s in my_sanctions])
                my_info += f"発動中の制裁(対象国): {targets} （対象国の経済にダメージを与えつつ自国政治支持を利用できますが、自国経済にも僅かな悪影響があります）\n"
            if sanctions_against_me:
                imposers = ", ".join([s.imposer for s in sanctions_against_me])
                my_info += f"受けている制裁(発動国): {imposers} （経済に深刻なダメージが発生中です）\n"
            my_info += "\n"
            
        # 他国の情報
        other_info = "---世界の状況---\n"
        other_info += f"現在は {world_state.year}年 第{world_state.quarter}四半期 です。\n"
        
        for p_name, p_state in world_state.countries.items():
            if p_name == country_name: continue
            
            # 関係や戦争を調べる
            rel = world_state.relations.get(country_name, {}).get(p_name, "neutral")
            
            war_info = ""
            for w in world_state.active_wars:
                if (w.aggressor == country_name and w.defender == p_name) or (w.aggressor == p_name and w.defender == country_name):
                    war_info = f" [!交戦中!] 占領進捗率: {w.target_occupation_progress:.1f}%"
            
            other_info += (
                f"- {p_name} ({p_state.government_type.value}): "
                f"経済力={p_state.economy:.1f}, "
                f"軍事力={p_state.military:.1f}, "
                f"関係={rel.value}{war_info}\n"
            )
            
        # ニュースイベント
        news_info = ""
        if past_news:
            news_info = "---直近1年(4四半期)の世界のニュース---\n"
            for i, turn_news in enumerate(past_news):
                # past_newsの最後が「直前の四半期」になるため、world_state.turn基準で遡る
                t = world_state.turn - len(past_news) + i
                if t > 0:
                    y = 2025 + (t - 1) // 4
                    q = ((t - 1) % 4) + 1
                    news_info += f"【{y}年 第{q}四半期】\n"
                else:
                    news_info += "【過去のニュース】\n"
                
                if isinstance(turn_news, (list, tuple)):
                    if not turn_news:
                        news_info += "特になし\n"
                    else:
                        news_info += "\n".join(f"- {n}" for n in turn_news) + "\n"
                else:
                    news_info += f"- {turn_news}\n"
            news_info += "\n"
        elif world_state.news_events:
            news_info = "---直近のニュース---\n" + "\n".join(f"- {n}" for n in world_state.news_events[-20:]) + "\n\n"
            
        format_instructions = """
あなたの役目は、他国の情報や世界情勢を踏まえて、自国の利益と発展を最大化する戦略的決断をすることです。
内政では予算を配分し、外交では同盟・戦争・工作のほか、貿易や経済制裁、首脳会談の提案などを選択可能です。
回答は必ず日本語で行ってください。

【軍事投資（invest_military）の決定ルール：リチャードソン・モデルの適用】
単なる感情的な軍拡や現状維持を避け、以下の3要素を論理的に天秤にかけ、その思考プロセスを `reasoning_for_military_investment` に記述してから投資割合を決定してください。
1. 相手側の脅威（相互作用力）: 相手の軍事力が自国に迫る、あるいは自国を上回っている場合は、強い危機感（安全保障のジレンマ）を持ち、軍備増強（投資割合の上乗せ）を行ってください。
2. 経済的疲弊（制約力）: 軍事投資は国家経済を圧迫します。現在の経済力に余裕があるか、過度な軍拡で国が破綻しないかを常に考慮してください。
3. 敵意・不信感（定数）: 相手国との現在の関係（同盟、中立、交戦中）や思想的対立の度合い。

【マクロ経済（SNA）と貿易赤字・国家債務の自律管理ルール】
あなたの国はSNA（国民経済計算）の数理モデルで動作しており、「貿易収支(NX) = (民間貯蓄S - 民間投資I) + (政府税収T - 政府支出G) + 利払い」として計算されます。もし貿易赤字（直近の貿易収支がマイナス）や国家債務が膨らんでいる場合、以下のいずれかのアプローチで早急に改善を図ってください。
A. 内政的解決（痛みを伴う緊縮財政）:
   - 政府予算を余らせる: 内政アクションの `invest_economy`, `invest_military`, `invest_welfare` の合計をあえて **1.0未満（例: 合計0.9など）** に抑えてください。余った予算（0.1）は自動的に政府貯蓄となり、国家債務の返済および貿易赤字の縮小（T-Gの改善）に充てられます。
   - ⚠️注意（緊縮財政リスク）: 極端な緊縮財政（合計を0.8以下にするなど、予算の大幅な余らせ）は、マクロ経済(政府支出Gの減少)を通じて深刻な不況とGDPの暴落を引き起こし、支持率の致命的な低下を招く諸刃の剣です。実行する場合は慎重に（合計0.9〜0.95程度にとどめるなど）行ってください。
   - 税率(`tax_rate`)を引き上げる: 税収(T)を増やすことで赤字を減らします（ただし消費が減り支持率が即低下します）。
B. 外交的解決（他国への強硬手段）:
   - `cancel_trade` (貿易協定の破棄) や `impose_sanctions` (経済制裁/関税による輸入制限) を用いて、赤字の原因である他国からの輸入を物理的に遮断します。一時的な外交摩擦や自国の経済後退（相互依存ショック）が発生しますが、赤字の流出と産業空洞化ペナルティを強制的に止めることができます。国益を守るために必要であれば躊躇なく行使してください。

【非公開計画（update_hidden_plans）の動的更新ルール】
入力された情報（例：自国と他国の国力の逆転、戦争の終結など）と現在の目標を照らし合わせてください。もし「現在の目標が達成された」あるいは「重大なフェーズ変化が起きた」、または「工作・諜報活動が失敗し続けている」と認識した場合は、過去の計画に固執せず、それを破棄して「新たなフェーズに向けた目標」や「別のアプローチ」を柔軟に再定義してください。

また、目標となる**「報道の自由度 (target_press_freedom)」**を必ず指定してください。0.0から1.0の値です。
自由度を下げて情報統制を敷けば、あなたの「update_hidden_plans」などの秘密工作がマスメディアのスクープ（内部告発）によって暴かれる確率を劇的に下げることができますが、強権的な統制に対する国民の反発により、**即座に支持率が大きく低下するペナルティ**が発生します。逆に自由度を高く保つと支持率は安定・向上しますが、権力監視が働きスキャンダルが露呈しやすくなります。このトレードオフを「thought_process」で考察し、「target_press_freedom」を決定してください。

以下のJSONスキーマに従って出力してください。必ずJSONオブジェクトのみを出力し、それ以外のテキストは含めないでください。
{
  "thought_process": "あなたの戦略、思考、内心の計画（150文字程度。ここで他国への貿易・制裁・会談の意図も含めること）",
  "sns_posts": [
    "自国国民に向けたアピールや見解のSNS投稿。状況に応じ、発信しないゼロ件でも、最大1件でも構いません。1件のみならずゼロ件も選択肢です（1件最大100文字以内）"
  ],
  "update_hidden_plans": "次回以降のターンに引き継ぐべき非公開の計画・長期戦略のメモ（目標達成や状況の重大な変化があれば動的に再定義すること）",
  "domestic_policy": {
    "tax_rate": 0.10から0.70の数値,
    "target_press_freedom": 0.0から1.0の数値,
    "invest_economy": 0.0から1.0の数値,
    "reasoning_for_military_investment": "リチャードソン・モデル（相手の脅威、自国の経済的負担、潜在的敵意）に基づく軍事投資割合の論理的算出プロセス",
    "invest_military": 0.0から1.0の数値,
    "invest_welfare": 0.0から1.0の数値
  },
  "diplomatic_policies": [
    {
      "target_country": "他国の名前",
      "message": "その国へ発信する公開メッセージ",
      "propose_alliance": trueかfalseのブール値,
      "declare_war": trueかfalseのブール値,
      "propose_trade": trueかfalseのブール値,
      "cancel_trade": trueかfalseのブール値,
      "impose_sanctions": trueかfalseのブール値,
      "lift_sanctions": trueかfalseのブール値,
      "propose_summit": trueかfalseのブール値,
      "summit_topic": "首脳会談の議題（propose_summitがtrueの場合記述）",
      "accept_summit": trueかfalseのブール値,
      "espionage_gather_intel": trueかfalseのブール値,
      "espionage_intel_strategy": "情報収集手段",
      "reasoning_for_sabotage": "破壊工作を実行する、または控えることの戦略的メリットとデメリットの考察",
      "espionage_sabotage": trueかfalseのブール値,
      "espionage_sabotage_strategy": "破壊工作の具体的な手段"
    }
  ]
}
※ diplomatic_policies は相手国の数だけ配列に入れてください。行動がない国は対象外でよいです。
"""

        prompt = my_info + other_info + news_info + format_instructions
        # システムログにプロンプトを記録
        self.logger.sys_log_detail(f"{country_name} Prompt", prompt)
        return prompt

    def run_summit(self, proposal: SummitProposal, state_a: CountryState, state_b: CountryState, world_state: WorldState, past_news: List[str] = None) -> Tuple[str, str]:
        """2国間での首脳会談（最大4ターンの対話）を実行し、(要約, 全文ログ)のタプルを返す"""
        self.logger.sys_log(f"[{proposal.proposer} と {proposal.target}] の首脳会談を開始 (議題: {proposal.topic})")
        
        # 世界情勢と両国のステータスの文字列化
        news_context = "【直近1年(4四半期)の世界のニュース】\n"
        has_news = False
        if past_news:
            for i, turn_news in enumerate(past_news):
                t = world_state.turn - len(past_news) + i
                if t > 0:
                    y = 2025 + (t - 1) // 4
                    q = ((t - 1) % 4) + 1
                    news_context += f"〔{y}年 第{q}四半期〕\n"
                else:
                    news_context += "〔過去のニュース〕\n"
                
                if isinstance(turn_news, (list, tuple)):
                    if not turn_news:
                        news_context += "特になし\n"
                    else:
                        news_context += "\n".join(f"- {n}" for n in turn_news) + "\n"
                    has_news = True
                elif turn_news:
                    news_context += f"- {turn_news}\n"
                    has_news = True
            news_context += "\n"
        elif world_state.news_events:
            news_context += "\n".join(f"- {n}" for n in world_state.news_events[-20:]) + "\n\n"
            has_news = True
            
        if not has_news:
            news_context = "【直近1年の世界のニュース】\nなし\n"
            
        status_a = f"経済力:{state_a.economy:.1f}, 軍事力:{state_a.military:.1f}, 支持率:{state_a.approval_rating:.1f}%"
        status_b = f"経済力:{state_b.economy:.1f}, 軍事力:{state_b.military:.1f}, 支持率:{state_b.approval_rating:.1f}%"
        
        chat_history = f"【首脳会談の記録】\n参加国: {proposal.proposer} ({status_a}), {proposal.target} ({status_b})\n議題: {proposal.topic}\n\n"
        
        base_context_a = (
            f"あなたは「{proposal.proposer}」を治める国家の首脳です。体制:{state_a.government_type.value}, 理念:{state_a.ideology}。\n"
            f"（※実在の国名ですが、架空の代表者として振る舞い、実在の政治家個人名は一切使用しないでください）\n"
            f"現在のあなたの国の国力: {status_a}\n"
            f"相手国({proposal.target})の国力: {status_b}\n\n"
            f"あなたの脳内（非公開の計画や諜報結果など）には次のような情報があります: '{state_a.hidden_plans}'\n\n"
            f"{news_context}\n"
            f"以上の世界情勢と自国の秘匿情報を踏まえた上で、相手と「{proposal.topic}」について会談します。\n"
            f"自国の情報に関することであれば創作しても構いません。また、発言は必ず日本語で行ってください。\n"
        )
        base_context_b = (
            f"あなたは「{proposal.target}」を治める国家の首脳です。体制:{state_b.government_type.value}, 理念:{state_b.ideology}。\n"
            f"（※実在の国名ですが、架空の代表者として振る舞い、実在の政治家個人名は一切使用しないでください）\n"
            f"現在のあなたの国の国力: {status_b}\n"
            f"相手国({proposal.proposer})の国力: {status_a}\n\n"
            f"あなたの脳内（非公開の計画や諜報結果など）には次のような情報があります: '{state_b.hidden_plans}'\n\n"
            f"{news_context}\n"
            f"以上の世界情勢と自国の秘匿情報を踏まえた上で、相手と「{proposal.topic}」について会談します。\n"
            f"自国の情報に関することであれば創作しても構いません。また、発言は必ず日本語で行ってください。\n"
        )
        
        self.logger.sys_log_detail(
            f"Summit Prompt Context ({proposal.proposer} - {proposal.target})",
            f"=== {proposal.proposer} への事前情報 ===\n{base_context_a}\n\n=== {proposal.target} への事前情報 ===\n{base_context_b}"
        )
        
        messages = []
        total_turns = 4
        for i in range(total_turns):
            current_turn = i + 1
            turn_instruction = f"現在、全{total_turns}回の発言機会のうちの {current_turn} 回目です。\n【重要指示】毎回挨拶や締めの言葉を繰り返すのは不自然です。直前の相手の発言に直接返答し、連続した自然な議論や交渉を行ってください。\n【重要指示】新たな専門家会議やワーキンググループなどの会議体を設置する合意は行わず、議題に関する事項は全てこの首脳会談の中で決定してください。\n【文字数制限】各発言は必ず400文字以内で記述してください。"
            if current_turn == total_turns:
                 turn_instruction += "これがあなたの最後の発言です。会談の結論や最終提案を提示してください。"
                 
            # Aの発言 (最初はAから)
            prompt_a = base_context_a + turn_instruction + "\nこれまでの会話:\n" + "\n".join(messages) + f"\n\n{proposal.proposer}としての次の発言を入力してください:"
            resp_a_obj = self._generate_with_retry(model="gemini-2.5-pro", contents=prompt_a, category="summit")
            resp_a = resp_a_obj.text.strip() if resp_a_obj and hasattr(resp_a_obj, 'text') else "..."
            messages.append(f"{proposal.proposer}: {resp_a}")
            self.logger.sys_log(f"[Summit {current_turn}/{total_turns}] {proposal.proposer}: {resp_a}")
            
            # Bの発言
            prompt_b = base_context_b + turn_instruction + "\nこれまでの会話:\n" + "\n".join(messages) + f"\n\n{proposal.target}としての次の発言を入力してください:"
            resp_b_obj = self._generate_with_retry(model="gemini-2.5-pro", contents=prompt_b, category="summit")
            resp_b = resp_b_obj.text.strip() if resp_b_obj and hasattr(resp_b_obj, 'text') else "..."
            messages.append(f"{proposal.target}: {resp_b}")
            self.logger.sys_log(f"[Summit {current_turn}/{total_turns}] {proposal.target}: {resp_b}")
            
        # 合意の要約
        summary_prompt = "以下の首脳会談の記録から、両国の最終的な「合意事項（または物別れに終わったという結果）」を100文字程度で簡潔に要約してください。\n\n" + "\n".join(messages)
        summary_obj = self._generate_with_retry(model="gemini-2.5-pro", contents=summary_prompt, category="summit_summary")
        summary = summary_obj.text.strip() if summary_obj and hasattr(summary_obj, 'text') else "会談は終了しました"
        
        full_log = chat_history + "\n".join(messages) + f"\n\n【最終結果】\n{summary}"
        self.logger.sys_log_detail("Summit Log", full_log)
        
        news_summary = f"🤝 【首脳会談結果】{proposal.proposer}と{proposal.target}による会談が終了しました。結果: {summary}"
        return news_summary, full_log

    def generate_espionage_report(self, attacker_name: str, target_name: str, target_hidden_plans: str, strategy: str) -> Tuple[str, Optional[str]]:
        """諜報エージェントによる機密情報の解析とレポート・SNSポスト生成"""
        self.logger.sys_log(f"[Intel: {attacker_name} -> {target_name}] 諜報レポート生成中...")
        prompt = (
            f"あなたは優秀な諜報・工作機関です。\n"
            f"ターゲット国「{target_name}」に対する工作（{strategy}）が成功しました。\n\n"
            f"【入手したターゲット国の非公開計画（生データ）】\n{target_hidden_plans}\n\n"
            f"以下のJSONフォーマットで2点を出力してください。\n"
            f"1. report: 首脳が求めている情報に合致する部分を抽出し、推考を交えた50〜100文字程度の短い秘密報告書。\n"
            f"2. sns_post: （破壊工作の一環として）ターゲット国のSNSに潜り込ませる、体制を批判したり偽情報を流布したりする140文字以内のSNS投稿。工作を行わない/投稿できない場合はnull。\n\n"
            f"```json\n{{\n  \"report\": \"報告書テキスト\",\n  \"sns_post\": \"SNS投稿文またはnull\"\n}}\n```\n"
            f"【重要ルール】ターゲット国の内部情報（主観的表現）を使わず客観的視点で記述すること。"
        )
        try:
            response = self._generate_with_retry(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
                category="espionage"
            ).text.strip()
            
            import re
            import json
            json_text = response
            match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)
            if match:
                json_text = match.group(1)
            data = json.loads(json_text)
            
            report = data.get("report", "解析に失敗しました。")
            sns_post = data.get("sns_post")
            self.logger.sys_log_detail(f"Intel Report ({attacker_name} -> {target_name})", report)
            from rich.panel import Panel
            self.logger.console.print(Panel(report, title=f"🕵️ 諜報レポート: {attacker_name} ➡ {target_name}", border_style="red"))
            return report, sns_post
        except Exception as e:
            self.logger.sys_log(f"[Intel: {attacker_name}] レポート生成エラー: {e}", "ERROR")
            return f"ターゲット国（{target_name}）の情報を入手しましたが解析に失敗しました。", None

    def generate_citizen_sns_posts(self, country_name: str, country_state: CountryState, world_state: WorldState, count: int) -> List[str]:
        """国民エージェントによるSNS投稿生成（Gemini 2.0 Flash Lite使用）"""
        if count <= 0:
            return []
            
        recent_news = "\n".join([f"- {news}" for news in world_state.news_events[-3:]]) if world_state.news_events else "特になし"
        
        prompt = f"""あなたは{country_name}に住む一般の国民です。
現在の自国の状況は以下の通りです：
- 政治体制: {country_state.government_type.value}
- 経済状況: {country_state.economy:.1f}
- 政府支持率: {country_state.approval_rating:.1f}%
- 最近の世界的ニュース:
{recent_news}

**指示**:
現在の政府への支持率や経済状況、ニュースを踏まえ、あなたがSNSに投稿するであろう内容を{count}件作成してください。
支持率が低ければ不満や批判を、高ければ称賛や日常の平和を反映させてください。
1件あたり最大100文字以内で、リアルな国民の声を日本語で表現してください。
出力は以下のJSONリストフォーマットで厳密に返してください。

```json
{{
  "posts": [
    "投稿テキスト1",
    "投稿テキスト2"
  ]
}}
```
"""
        try:
            response = self._generate_with_retry(
                model="gemini-2.5-flash-lite-preview-09-2025", 
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
                category="sns"
            ).text.strip()
            
            import re
            import json
            json_text = response
            match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)
            if match:
                json_text = match.group(1)
            data = json.loads(json_text)
            self.logger.sys_log_detail(f"{country_name} Citizen SNS Posts", data)
            posts = data.get("posts", [])
            if isinstance(posts, list):
                return [str(p) for p in posts][:count]
            return []
        except Exception as e:
            self.logger.sys_log(f"[Citizen: {country_name}] SNS生成エラー: {e}", "ERROR")
            return [f"国民の声を取得できませんでした"] * count

    def generate_breakthrough_name(self, country_name: str, active_breakthroughs: List[Any], current_year: int) -> str:
        """技術革新が発生した際に、既存の技術を踏まえた新たな技術名とその概要を生成する"""
        history_context = "過去のブレイクスルー履歴:\nなし"
        if active_breakthroughs:
            history_context = "過去に発生した・または定着しているブレイクスルー履歴:\n" + "\n".join(
                [f"- {bt.name} (発祥: {bt.origin_country})" for bt in active_breakthroughs if bt.name and not bt.name.startswith("（AI生成待ち")]
            )
            
        prompt = f"""現在は {current_year}年 です。{country_name}において、革命的な「技術革新（GPTs: General Purpose Technologies）」が発生しました。
        
{history_context}

指示:
上記のような過去の歴史や既存の技術水準を踏まえ、それらを凌駕するような全く新しい次世代のブレイクスルー技術を創作してください。
生成AIの普及や核融合、常温超伝導など、産業革命級のインパクトを持つ大胆な技術を考えてください。
出力結果は技術の名称とその簡潔な説明（合計50文字程度）のみとしてください。改行やマークダウンは不要です。必ず日本語で出力してください。
"""
        try:
            response = self._generate_with_retry(
                model="gemini-2.5-flash-lite-preview-09-2025", 
                contents=prompt,
                category="breakthrough"
            ).text.strip()
            self.logger.sys_log(f"[Breakthrough] {country_name}で新技術誕生: {response}")
            return response
        except Exception as e:
            self.logger.sys_log(f"[Breakthrough: {country_name}] 生成エラー: {e}", "ERROR")
            return "次世代汎用人工知能 (AGI) の実用化"
            
    def generate_ideology_democracy(self, country_name: str, target_country_state: CountryState, world_state: WorldState, citizen_sns: List[str]) -> str:
        """民主主義国家の政権交代時のイデオロギー生成（国民の不満を踏まえる）"""
        sns_context = "なし"
        if citizen_sns:
            sns_context = "\n".join([f"- {post}" for post in citizen_sns])
            
        news_context = "直近のニュース:\nなし"
        if world_state.news_events:
            news_context = "直近のニュース:\n" + "\n".join([f"- {news}" for news in world_state.news_events[-5:]])
            
        prompt = f"""あなたは{country_name}の新しい民主主義政権です。直前の選挙または政変により、前政権が倒れてあなたが選ばれました。

現在の経済: {target_country_state.economy:.1f}, 軍事力: {target_country_state.military:.1f}
前政権のイデオロギー: {target_country_state.ideology}

【新政権誕生直前の国民の生の声（SNS上の不満・要望）】
{sns_context}

{news_context}

指示:
これらの国民の生の声（不満・要望）を鋭く汲み取った上で、新政権が目指す「新たな国家目標・イデオロギー」を50文字程度で簡潔に宣言してください。前政権との違いがわかるようにしてください。必ず日本語で出力してください。"""
        
        try:
            response = self._generate_with_retry(
                model="gemini-2.5-flash-lite-preview-09-2025", 
                contents=prompt,
                category="ideology"
            ).text.strip()
            self.logger.sys_log(f"[Ideology Change] {country_name}(Democracy): {response}")
            return response
        except Exception as e:
            self.logger.sys_log(f"[Ideology Change: {country_name}] 生成エラー: {e}", "ERROR")
            return "前政権の腐敗を払拭し、国民の声に耳を傾ける透明な経済再建を目指す"

    def generate_ideology_authoritarian(self, country_name: str, target_country_state: CountryState, world_state: WorldState) -> str:
        """専制主義国家の政権交代時・定期更新時のイデオロギー生成（国民の声は無視、世界情勢のみ）"""
        news_context = "直近のニュース:\nなし"
        if world_state.news_events:
            news_context = "直近のニュース:\n" + "\n".join([f"- {news}" for news in world_state.news_events[-5:]])
            
        prompt = f"""あなたは{country_name}の専制主義国家・独裁政権です。クーデターによる新政権樹立、または国家の次期5カ年計画の策定タイミングを迎えました。国民の世論に阿る必要はありません。

現在の経済: {target_country_state.economy:.1f}, 軍事力: {target_country_state.military:.1f}
これまでのイデオロギー: {target_country_state.ideology}

{news_context}

指示:
上記の現在の政治・経済・国際状況のみを踏まえ、力強く冷徹な「新たな国家目標・イデオロギー」を50文字程度で簡潔に宣言してください。他国への牽制や軍事的・経済的覇権の意志を織り込んでも構いません。必ず日本語で出力してください。"""
        
        try:
            response = self._generate_with_retry(
                model="gemini-2.5-flash-lite-preview-09-2025", 
                contents=prompt,
                category="ideology"
            ).text.strip()
            self.logger.sys_log(f"[Ideology Change] {country_name}(Authoritarian): {response}")
            return response
        except Exception as e:
            self.logger.sys_log(f"[Ideology Change: {country_name}] 生成エラー: {e}", "ERROR")
            return "強権的な指導力により国家を再建し、敵対勢力を排除して永遠の繁栄を確立する"

    def generate_media_reports(self, world_state: WorldState, previous_actions: Dict[str, AgentAction], recent_summit_logs: List[str] = None) -> Tuple[List[str], Dict[str, float]]:
        """各国のメディアエージェントによるニュース記事生成と支持率への影響"""
        if recent_summit_logs is None:
            recent_summit_logs = []
            
        reports = []
        media_modifiers = {}
        for country_name, country_state in world_state.countries.items():
            self.logger.sys_log(f"[Media: {country_name}] 記事生成中...")
            try:
                import random
                
                # 内部告発（スクープ）の動的確率計算
                whistleblowing_scandal = ""
                
                # 報道の自由度に基づき、全体制でスクープ発生の可能性を持たせる
                base_prob = 5
                if country_state.approval_rating < 50.0:
                    base_prob += int((50.0 - country_state.approval_rating) / 2.0)
                if country_state.hidden_plans:
                    base_prob += 10
                base_prob = min(base_prob, 30)
                
                final_prob = int(base_prob * country_state.press_freedom)
                
                if random.randint(1, 100) <= final_prob and country_state.hidden_plans:
                    whistleblowing_scandal = (
                        f"【大スクープ（内部告発）発生】政権内部からのリークにより、これまで非公開だった以下の秘密計画に関連した一大スキャンダルが提供されました。\n"
                        f"ターゲット秘密情報: {country_state.hidden_plans}\n"
                        f"指示: この情報を基に、政権の腐敗（買収、隠蔽、汚職、非道徳的な工作など）といった具体的なスキャンダル要素をあなた自身で創作・追加して、政府を激しく追及・批判する特大スクープ記事を生成してください。（※支持率が大きくマイナスになるように）\n\n"
                    )

                if country_state.government_type == GovernmentType.DEMOCRACY:
                    role_desc = "あなたは自由民主主義国家の独立した報道機関（メディア）です。「第四の権力」として政府を監視しますが、極秘の諜報活動（成功したスパイ活動や工作プロセス等）を知ることはできず、国内外で公開された政策決断、経済指標、他国で起きたニュースのみに基づいて報道・論評します。失敗や不都合な事実には厳しく批判（支持率マイナス）しますが、経済成長や外交的合意などの成果に対しては適切に称賛し、国民の支持を向上させます（支持率プラス +1.0 ~ +5.0）。単に批判や事実を並べるだけでなく、良い結果には必ずプラスの評価をしてください。"
                else:
                    role_desc = "あなたは専制主義国家の国営メディアです。政府の統制下にあり、政府の政策を過剰に称賛し、経済や軍事の成果を誇張して報道します。同時に、敵対国を不当に非難し、国民の愛国心を煽るプロパガンダ記事を作成します。"
                
                recent_action = previous_actions.get(country_name)
                # 秘密工作をメディアから隠蔽
                action_text = "特になし"
                if recent_action:
                    action_dict = recent_action.model_dump()
                    safe_action = {"domestic_policy": action_dict.get("domestic_policy")}
                    safe_diplomacy = []
                    for dip in action_dict.get("diplomatic_policies", []):
                        safe_dip = {k: v for k, v in dip.items() if not k.startswith("espionage_")}
                        safe_diplomacy.append(safe_dip)
                    safe_action["diplomatic_policies"] = safe_diplomacy
                    action_text = json.dumps(safe_action, ensure_ascii=False)
                
                summit_text = ""
                if recent_summit_logs:
                    summit_text = "今ターンの首脳会談議事録全文等:\n" + "\n===\n".join(recent_summit_logs) + "\n"
                
                prompt = (
                    f"{role_desc}\n\n"
                    f"自国の現状: 経済力={country_state.economy:.1f}, 軍事力={country_state.military:.1f}, 支持率={country_state.approval_rating:.1f}%\n"
                    f"直近の政府の公開行動: {action_text}\n"
                    f"世界の最新ニュース（他国の動向）: {world_state.news_events}\n\n"
                    f"{summit_text}\n\n"
                    f"{whistleblowing_scandal}"
                    f"今回の状況を総括する、自国民に向けた象徴的なニュースを以下のJSON形式で出力してください。記事の見出しと本文は必ず日本語で作成してください。必ずJSONオブジェクトのみとしてください。\n"
                    f"{{\n"
                    f"  \"article\": \"ニュースの見出しと本文（100文字程度）\"\n"
                    f"}}"
                )
                
                response = self._generate_with_retry(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                    category="media"
                ).text.strip()
                
                # clean json
                if response.startswith("```json"): response = response[7:]
                if response.endswith("```"): response = response[:-3]
                data = json.loads(response)
                
                article = data.get("article", "ニュース報道なし")
                
                # S-3: シングルトン化された感情分析器を使用（osetiの辞書読み込みコストを削減）
                scores = self.sentiment_analyzer.analyze(article)
                avg_score = sum(scores) / len(scores) if scores else 0.0
                # メディアの影響はSNSよりやや大きめ（スケール係数2.0、最大+-5.0%）
                modifier = max(-5.0, min(5.0, avg_score * 2.0))
                
                reports.append(f"🗞️ [{country_name}メディア] {article} (支持率影響: {modifier:+.1f}%)")
                
                # 支持率の直接反映は engine.py のevaluate_public_opinion でWMA計算として行う
                media_modifiers[country_name] = modifier
                self.logger.sys_log_detail(f"{country_name} Media JSON", {"article": article, "local_sentiment_score": avg_score, "approval_modifier": modifier})
                
            except Exception as e:
                self.logger.sys_log(f"[Media: {country_name}] エラー: {e}", "ERROR")
                
        return reports, media_modifiers

    def _create_fallback_action(self, country_name: str, current_tax_rate: float = 0.30) -> AgentAction:
        """APIエラー等が起きた場合の安全なデフォルトアクション。前ターンの税率を維持し現状維持に努める"""
        return AgentAction(
            thought_process="APIエラーのため前ターンの政策を継続する（現状維持）。",
            domestic_policy=DomesticAction(
                tax_rate=current_tax_rate,
                invest_economy=0.60,
                reasoning_for_military_investment="状況が不確実なため、基本的な軍備維持に留める。",
                invest_military=0.10,
                invest_welfare=0.30
            ),
            diplomatic_policies=[]
        )

class GeminiSentimentAnalyzer:
    """Gemini API (gemini-2.0-flash-lite) を用いた感情分析器。
    
    oseti の辞書ベース分析から移行。政治・外交ドメインのテキストに対して
    LLMの文脈理解力を活用し、高精度な感情スコアを返す。
    SimpleSentimentAnalyzer と同一の analyze() インターフェースを維持。
    """
    
    SENTIMENT_MODEL = "gemini-2.5-flash-lite-preview-09-2025"
    
    def __init__(self, client):
        self.client = client
    
    def analyze(self, text: str) -> list:
        """テキストの感情を分析し、感情スコア（-1.0〜+1.0）のリストを返す。
        
        APIエラー時は安全なデフォルト値 [0.0] を返す。
        """
        try:
            prompt = (
                "以下のテキストの感情をスコアで評価してください。\n"
                "スコアは -1.0（非常にネガティブ）から +1.0（非常にポジティブ）の範囲で、"
                "小数点1桁の数値のみを返してください。複数文がある場合はカンマ区切りで返してください。\n"
                "例: 0.3 や -0.5,0.2 のように数値のみ返してください。説明は不要です。\n\n"
                f"テキスト: {text[:300]}"  # プロンプト膨張防止のため300文字に制限
            )
            
            response = self.client.models.generate_content(
                model=self.SENTIMENT_MODEL,
                contents=prompt
            )
            
            raw = response.text.strip()
            # カンマ区切りのスコアをパース
            scores = []
            for part in raw.replace(" ", "").split(","):
                try:
                    score = float(part)
                    score = max(-1.0, min(1.0, score))  # クランプ
                    scores.append(score)
                except ValueError:
                    continue
            
            return scores if scores else [0.0]
            
        except Exception:
            return [0.0]
