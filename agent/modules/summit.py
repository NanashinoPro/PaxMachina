import types
import time
import json
from typing import List, Tuple, Any, Dict, Optional
from google.genai import types as genai_types
from models import WorldState, CountryState, SummitProposal
from logger import SimulationLogger

def run_summit(
    generate_func,
    logger: SimulationLogger,
    proposal: SummitProposal, 
    state_a: CountryState, 
    state_b: CountryState, 
    world_state: WorldState, 
    past_news: List[str] = None
) -> Tuple[str, str]:
    """2国間での首脳会談（最大4ターンの対話）を実行し、(要約, 全文ログ)のタプルを返す"""
    logger.sys_log(f"[{proposal.proposer} と {proposal.target}] の首脳会談を開始 (議題: {proposal.topic})")
    
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
    
    is_private_str = "【⚠️警告: この会談は極秘の非公開会談であり、協議内容は第三国には一切漏洩しません。率直な意見交換が可能です】\n\n" if getattr(proposal, 'is_private', False) else ""
    
    base_context_a = (
        f"あなたは「{proposal.proposer}」を治める国家の首脳です。体制:{state_a.government_type.value}, 理念:{state_a.ideology}。\n"
        f"（※実在の国名ですが、架空の代表者として振る舞い、実在の政治家個人名は一切使用しないでください）\n"
        f"現在のあなたの国の国力: {status_a}\n"
        f"相手国({proposal.target})の国力: {status_b}\n\n"
        f"あなたの脳内（非公開の計画や諜報結果など）には次のような情報があります: '{state_a.hidden_plans}'\n\n"
        f"{is_private_str}"
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
        f"{is_private_str}"
        f"{news_context}\n"
        f"以上の世界情勢と自国の秘匿情報を踏まえた上で、相手と「{proposal.topic}」について会談します。\n"
        f"自国の情報に関することであれば創作しても構いません。また、発言は必ず日本語で行ってください。\n"
    )
    
    logger.sys_log_detail(
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
        try:
            resp_a_obj = generate_func(model="gemini-2.5-pro", contents=prompt_a, category="summit")
            resp_a = resp_a_obj.text.strip() if resp_a_obj and hasattr(resp_a_obj, 'text') else "..."
        except Exception as e:
            logger.sys_log(f"[{proposal.proposer}] APIエラー(Summit): {e}", "ERROR")
            resp_a = "通信障害により発言できませんでした。"
        messages.append(f"【{proposal.proposer}首脳】: {resp_a}")
        logger.sys_log(f"[Summit {current_turn}/{total_turns}] {proposal.proposer}: {resp_a}")
        
        # Bの発言
        prompt_b = base_context_b + turn_instruction + "\nこれまでの会話:\n" + "\n".join(messages) + f"\n\n{proposal.target}としての次の発言を入力してください:"
        try:
            resp_b_obj = generate_func(model="gemini-2.5-pro", contents=prompt_b, category="summit")
            resp_b = resp_b_obj.text.strip() if resp_b_obj and hasattr(resp_b_obj, 'text') else "..."
        except Exception as e:
            logger.sys_log(f"[{proposal.target}] APIエラー(Summit): {e}", "ERROR")
            resp_b = "通信障害により発言できませんでした。"
        messages.append(f"【{proposal.target}首脳】: {resp_b}")
        logger.sys_log(f"[Summit {current_turn}/{total_turns}] {proposal.target}: {resp_b}")
        
    # 合意の要約
    summary_prompt = "以下の首脳会談の記録から、両国の最終的な「合意事項（または物別れに終わったという結果）」を100文字程度で簡潔に要約してください。\n\n" + "\n".join(messages)
    try:
        summary_obj = generate_func(model="gemini-2.5-pro", contents=summary_prompt, category="summit_summary")
        summary = summary_obj.text.strip() if summary_obj and hasattr(summary_obj, 'text') else "会談は終了しました"
    except Exception as e:
        logger.sys_log(f"[Summit Summary] APIエラー: {e}", "ERROR")
        summary = "APIエラーにより会談結果の要約に失敗しました。"
    
    full_log = chat_history + "\n".join(messages) + f"\n\n【最終結果】\n{summary}"
    logger.sys_log_detail("Summit Log", full_log)
    
    if getattr(proposal, 'is_private', False):
        news_summary = None
    else:
        news_summary = f"🤝 【首脳会談結果】{proposal.proposer}と{proposal.target}による会談が終了しました。結果: {summary}"
        
    return news_summary, full_log
