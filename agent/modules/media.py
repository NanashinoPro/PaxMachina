import json
import re
import random
from typing import List, Tuple, Dict, Any
from google.genai import types as genai_types
from models import WorldState, CountryState, AgentAction, GovernmentType
from logger import SimulationLogger

class GeminiSentimentAnalyzer:
    """Gemini API (gemini-2.0-flash-lite) を用いた感情分析器"""
    SENTIMENT_MODEL = "gemini-2.5-flash-lite"
    
    def __init__(self, client):
        self.client = client
    
    def analyze(self, text: str) -> list:
        try:
            prompt = (
                "以下のテキストの感情をスコアで評価してください。\n"
                "スコアは -1.0（非常にネガティブ）から +1.0（非常にポジティブ）の範囲で、"
                "小数点1桁の数値のみを返してください。複数文がある場合はカンマ区切りで返してください。\n"
                "例: 0.3 や -0.5,0.2 のように数値のみ返してください。説明は不要です。\n\n"
                f"テキスト: {text[:300]}"
            )
            response = self.client.models.generate_content(
                model=self.SENTIMENT_MODEL,
                contents=prompt
            )
            raw = response.text.strip()
            scores = []
            for part in raw.replace(" ", "").split(","):
                try:
                    score = float(part)
                    score = max(-1.0, min(1.0, score))
                    scores.append(score)
                except ValueError:
                    continue
            return scores if scores else [0.0]
        except Exception:
            return [0.0]

def generate_citizen_sns_posts(
    generate_func,
    logger: SimulationLogger,
    country_name: str, 
    country_state: CountryState, 
    world_state: WorldState, 
    count: int
) -> List[str]:
    """国民エージェントによるSNS投稿生成"""
    if count <= 0:
        return []
        
    recent_news = "\n".join([f"- {news}" for news in world_state.news_events[-3:]]) if world_state.news_events else "特になし"
    history_str = ""
    if country_state.stat_history:
        history_str = "- 過去のパラメーター推移:\n" + "\n".join([f"  T{s['turn']}: 経済力 {s['economy']}, 支持率 {s['approval_rating']}%" for s in country_state.stat_history]) + "\n"
    
    prompt = f"""あなたは{country_name}に住む一般の国民です。
現在の自国の状況は以下の通りです：
- 政治体制: {country_state.government_type.value}
- 経済状況: {country_state.economy:.1f}
- 政府支持率: {country_state.approval_rating:.1f}%
{history_str}- 最近の世界的ニュース:
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
        response_obj = generate_func(
            model="gemini-2.5-flash-lite", 
            contents=prompt,
            config=genai_types.GenerateContentConfig(response_mime_type="application/json"),
            category="sns"
        )
        response = response_obj.text.strip() if response_obj else "{}"
        
        json_text = response
        match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)
        if match:
            json_text = match.group(1)
        data = json.loads(json_text)
        logger.sys_log_detail(f"{country_name} Citizen SNS Posts", data)
        posts = data.get("posts", [])
        if isinstance(posts, list):
            return [str(p) for p in posts][:count]
        return []
    except Exception as e:
        logger.sys_log(f"[Citizen: {country_name}] SNS生成エラー: {e}", "ERROR")
        return [f"国民の声を取得できませんでした"] * count

def generate_breakthrough_name(
    generate_func,
    logger: SimulationLogger,
    country_name: str, 
    active_breakthroughs: List[Any], 
    current_year: int
) -> str:
    """技術革新名称生成"""
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
        response_obj = generate_func(
            model="gemini-2.5-flash-lite", 
            contents=prompt,
            category="breakthrough"
        )
        response = response_obj.text.strip()
        logger.sys_log(f"[Breakthrough] {country_name}で新技術誕生: {response}")
        return response
    except Exception as e:
        logger.sys_log(f"[Breakthrough: {country_name}] 生成エラー: {e}", "ERROR")
        return "次世代汎用人工知能 (AGI) の実用化"

def generate_ideology_democracy(
    generate_func,
    logger: SimulationLogger,
    country_name: str, 
    target_country_state: CountryState, 
    world_state: WorldState, 
    citizen_sns: List[str]
) -> str:
    sns_context = "なし"
    if citizen_sns:
        sns_context = "\n".join([f"- {post}" for post in citizen_sns])
        
    news_context = "直近のニュース:\nなし"
    if world_state.news_events:
        news_context = "直近のニュース:\n" + "\n".join([f"- {news}" for news in world_state.news_events[-5:]])
        
    history_text = ""
    if target_country_state.stat_history:
         history_text = "\n【過去のステータス推移】\n" + "\n".join([f" T{s['turn']}: 経済力 {s['economy']}, 軍事力 {s['military']}, 支持率 {s['approval_rating']}%" for s in target_country_state.stat_history]) + "\n"
         
    prompt = f"""あなたは{country_name}の新しい民主主義政権です。直前の選挙または政変により、前政権が倒れてあなたが選ばれました。

現在の経済: {target_country_state.economy:.1f}, 軍事力: {target_country_state.military:.1f}
前政権のイデオロギー: {target_country_state.ideology}
{history_text}
【新政権誕生直前の国民の生の声（SNS上の不満・要望）】
{sns_context}

{news_context}

指示:
これらの国民の生の声（不満・要望）を鋭く汲み取った上で、新政権が目指す「新たな国家目標・イデオロギー」を50文字程度で簡潔に宣言してください。前政権との違いがわかるようにしてください。必ず日本語で出力してください。"""
    
    try:
        response_obj = generate_func(
            model="gemini-2.5-flash-lite", 
            contents=prompt,
            category="ideology"
        )
        response = response_obj.text.strip()
        logger.sys_log(f"[Ideology Change] {country_name}(Democracy): {response}")
        return response
    except Exception as e:
        logger.sys_log(f"[Ideology Change: {country_name}] 生成エラー: {e}", "ERROR")
        return "前政権の腐敗を払拭し、国民の声に耳を傾ける透明な経済再建を目指す"

def generate_ideology_authoritarian(
    generate_func,
    logger: SimulationLogger,
    country_name: str, 
    target_country_state: CountryState, 
    world_state: WorldState
) -> str:
    news_context = "直近のニュース:\nなし"
    if world_state.news_events:
        news_context = "直近のニュース:\n" + "\n".join([f"- {news}" for news in world_state.news_events[-5:]])
        
    history_text = ""
    if target_country_state.stat_history:
         history_text = "\n【過去のステータス推移】\n" + "\n".join([f" T{s['turn']}: 経済力 {s['economy']}, 軍事力 {s['military']}, 支持率 {s['approval_rating']}%" for s in target_country_state.stat_history]) + "\n"
         
    prompt = f"""あなたは{country_name}の専制主義国家・独裁政権です。クーデターによる新政権樹立、または国家の次期5カ年計画の策定タイミングを迎えました。国民の世論に阿る必要はありません。

現在の経済: {target_country_state.economy:.1f}, 軍事力: {target_country_state.military:.1f}
これまでのイデオロギー: {target_country_state.ideology}
{history_text}
{news_context}

指示:
上記の現在の政治・経済・国際状況のみを踏まえ、力強く冷徹な「新たな国家目標・イデオロギー」を50文字程度で簡潔に宣言してください。他国への牽制や軍事的・経済的覇権の意志を織り込んでも構いません。必ず日本語で出力してください。"""
    
    try:
        response_obj = generate_func(
            model="gemini-2.5-flash-lite", 
            contents=prompt,
            category="ideology"
        )
        response = response_obj.text.strip()
        logger.sys_log(f"[Ideology Change] {country_name}(Authoritarian): {response}")
        return response
    except Exception as e:
        logger.sys_log(f"[Ideology Change: {country_name}] 生成エラー: {e}", "ERROR")
        return "強権的な指導力により国家を再建し、敵対勢力を排除して永遠の繁栄を確立する"

def generate_fragmentation_profile(
    generate_func,
    logger: SimulationLogger,
    target_country_name: str, 
    sns_logs: List[Dict]
) -> Tuple[str, str]:
    citizen_posts = [p['text'] for p in sns_logs if p['author'] == 'Citizen']
    recent_complaints = "\n".join(f"- {post}" for post in citizen_posts[-10:]) if citizen_posts else "政府に対する強い不満と独立への希求"
    
    prompt = f"""あなたは歴史シミュレーションのシナリオライターです。
現在、「{target_country_name}」という国家において、長年の圧政や不満の爆発によりクーデターが発生し、
独自の国名とイデオロギーを掲げる新しい独立国家（または新政府）が樹立されました。

【建国前の国民の悲痛な叫び（SNSの声）】
{recent_complaints}

指示:
上記の国民の声（不満の文脈や、どんな地域性・思想が隠れているか）を読み取り、
旧体制の「{target_country_name}」に反発する形で誕生した、新しい国家の「国名」と「新しいイデオロギー（国家目標）」を創造してください。
以下の堅格なJSONフォーマット（プレーンテキスト、マークダウンのコードブロックなし）で回答してください。

{{
  "new_country_name": "（例：新カリフォルニア共和国、華南自由連邦、ネオ・アメリカ、シベリア大公国 など、文脈に合った名前）",
  "new_ideology": "（50文字程度。例：旧体制の腐敗を打破し、地域に根ざした自由と真の民主主義、そして経済的自立を勝ち取る）"
}}"""

    try:
        response_obj = generate_func(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            category="ideology"
        )
        response_text = response_obj.text.strip()
        
        if response_text.startswith("```json"):
            response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
        response_text = response_text.strip()
        
        data = json.loads(response_text)
        new_name = data.get("new_country_name", f"新{target_country_name}")
        new_ideology = data.get("new_ideology", "旧体制を打破し、新たな理想国家を建設する")
        
        if logger:
            logger.sys_log(f"[Fragmentation] {target_country_name}から '{new_name}' が誕生。イデオロギー: {new_ideology}")
        return new_name, new_ideology
        
    except Exception as e:
        if logger:
            logger.sys_log(f"[Fragmentation: {target_country_name}] 新国家プロフィール生成エラー: {e}", "ERROR")
        return f"{target_country_name}自由国", "圧制を逃れ、自由と真の独立を確立する"

def generate_media_reports(
    generate_func,
    logger: SimulationLogger,
    sentiment_analyzer: GeminiSentimentAnalyzer,
    world_state: WorldState, 
    previous_actions: Dict[str, AgentAction], 
    recent_summit_logs: List[str] = None
) -> Tuple[List[str], Dict[str, float]]:
    """各国のメディアエージェントによるニュース記事生成と支持率への影響"""        
    if recent_summit_logs is None:
        recent_summit_logs = []
        
    reports = []
    media_modifiers = {}
    for country_name, country_state in world_state.countries.items():
        logger.sys_log(f"[Media: {country_name}] 記事生成中...")
        try:
            whistleblowing_scandal = ""
            
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
            
            history_text = ""
            if country_state.stat_history:
                history_text = "自国のパラメーター推移:\n" + "\n".join([f" T{s['turn']}: 経済力 {s['economy']}, 軍事力 {s['military']}, 支持率 {s['approval_rating']}%" for s in country_state.stat_history]) + "\n"
            
            prompt = (
                f"{role_desc}\n\n"
                f"自国の現状: 経済力={country_state.economy:.1f}, 軍事力={country_state.military:.1f}, 支持率={country_state.approval_rating:.1f}%\n"
                f"{history_text}"
                f"直近の政府の公開行動: {action_text}\n"
                f"世界の最新ニュース（他国の動向）: {world_state.news_events}\n\n"
                f"{summit_text}\n\n"
                f"{whistleblowing_scandal}"
                f"今回の状況を総括する、自国民に向けた象徴的なニュースを以下のJSON形式で出力してください。記事の見出しと本文は必ず日本語で作成してください。必ずJSONオブジェクトのみとしてください。\n"
                f"{{\n"
                f"  \"article\": \"ニュースの見出しと本文（100文字程度）\"\n"
                f"}}"
            )
            
            response_obj = generate_func(
                model="gemini-2.5-flash",
                contents=prompt,
                config=genai_types.GenerateContentConfig(response_mime_type="application/json"),
                category="media"
            )
            response = response_obj.text.strip() if response_obj else "{}"
            
            if response.startswith("```json"): response = response[7:]
            if response.endswith("```"): response = response[:-3]
            data = json.loads(response)
            
            article = data.get("article", "ニュース報道なし")
            
            scores = sentiment_analyzer.analyze(article)
            avg_score = sum(scores) / len(scores) if scores else 0.0
            modifier = max(-5.0, min(5.0, avg_score * 2.0))
            
            reports.append(f"🗞️ [{country_name}メディア] {article} (支持率影響: {modifier:+.1f}%)")
            
            media_modifiers[country_name] = modifier
            logger.sys_log_detail(f"{country_name} Media JSON", {"article": article, "local_sentiment_score": avg_score, "approval_modifier": modifier})
            
        except Exception as e:
            logger.sys_log(f"[Media: {country_name}] エラー: {e}", "ERROR")
            
    return reports, media_modifiers
