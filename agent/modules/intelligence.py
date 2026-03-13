import json
import re
from typing import Tuple, Optional
from google.genai import types as genai_types
from logger import SimulationLogger

def generate_espionage_report(
    generate_func,
    logger: SimulationLogger,
    attacker_name: str, 
    target_name: str, 
    target_hidden_plans: str, 
    strategy: str
) -> Tuple[str, Optional[str]]:
    """諜報エージェントによる機密情報の解析とレポート・SNSポスト生成"""
    logger.sys_log(f"[Intel: {attacker_name} -> {target_name}] 諜報レポート生成中...")
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
        response_obj = generate_func(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(response_mime_type="application/json"),
            category="espionage"
        )
        response = response_obj.text.strip() if response_obj and hasattr(response_obj, 'text') else "{}"
        
        json_text = response
        match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)
        if match:
            json_text = match.group(1)
        data = json.loads(json_text)
        
        report = data.get("report", "解析に失敗しました。")
        sns_post = data.get("sns_post")
        logger.sys_log_detail(f"Intel Report ({attacker_name} -> {target_name})", report)
        return report, sns_post
    except Exception as e:
        logger.sys_log(f"[Intel: {attacker_name}] レポート生成エラー: {e}", "ERROR")
        return f"ターゲット国（{target_name}）の情報を入手しましたが解析に失敗しました。", None
