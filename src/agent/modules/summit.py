import types
import time
import json
from typing import List, Tuple, Any, Dict, Optional, Callable
from google.genai import types as genai_types
from models import WorldState, CountryState, SummitProposal
from logger import SimulationLogger

SUMMIT_MODEL = "gemini-2.5-flash"

def _generate_with_tool(generate_func, logger: SimulationLogger, model: str, prompt: str, category: str, 
                        search_tool=None, country_name: str = "Summit") -> str:
    """DB検索ツール付きでLLMを呼び出し、ツール呼び出しがあればフォローアップする"""
    tools = [search_tool] if search_tool else None
    config = genai_types.GenerateContentConfig(tools=tools, temperature=0.4) if tools else None
    
    response = generate_func(model=model, contents=prompt, config=config, category=category)
    
    # ツール呼び出しの処理（core.py _execute_agent と同等）
    if search_tool and getattr(response, 'function_calls', None):
        for function_call in response.function_calls:
            if function_call.name == "search_historical_events":
                args = function_call.args if isinstance(function_call.args, dict) else dict(function_call.args)
                query = args.get("query", "")
                tool_result = search_tool(query)
                
                follow_up_prompt = prompt + f"\n\nエージェントツールからの検索結果 '{query}':\n{tool_result}\n\nこれらを踏まえ、発言を行ってください。"
                response = generate_func(model=model, contents=follow_up_prompt, category=category)
                break
    
    return response.text.strip() if response and hasattr(response, 'text') else "..."

def run_summit(
    generate_func,
    logger: SimulationLogger,
    db_manager,
    proposal: SummitProposal, 
    state_a: CountryState, 
    state_b: CountryState, 
    world_state: WorldState, 
    past_news: List[str] = None,
    search_tool_a: Callable = None,
    search_tool_b: Callable = None
) -> Tuple[str, str]:
    """2国間での首脳会談（最大4ターンの対話）を実行し、(要約, 全文ログ)のタプルを返す"""
    logger.sys_log(f"[{proposal.proposer} と {proposal.target}] の首脳会談を開始 (議題: {proposal.topic}, モデル: {SUMMIT_MODEL})")
    
    # 両国の関連する直近イベント（DB検索）
    news_context = f"【両国間({proposal.proposer}と{proposal.target})に関連する直近1年(4四半期)の出来事】\n"
    has_news = False
    
    if db_manager:
        limit_turns = 4
        min_turn = max(1, world_state.turn - limit_turns + 1)
        recent_events = db_manager.get_recent_events_between_countries(
            proposal.proposer, proposal.target, world_state.turn, limit_turns=limit_turns
        )
        
        # システムログに検索プロセスを記録
        log_header = f"[Summit DB Search] クエリ: '{proposal.proposer}' & '{proposal.target}' の関連イベント (Turns {min_turn}-{world_state.turn}) -> {len(recent_events)}件抽出"
        logger.sys_log(log_header)
        
        if recent_events:
            log_detail = ""
            for ev in recent_events:
                t = ev.get('turn', '?')
                c = ev.get('content', '')
                et = ev.get('event_type', '?')
                log_detail += f"[Turn {t}] [{et}] {c}\n"
                
                # プロンプト用コンテキストへの追加
                y = 2025 + (t - 1) // 4 if isinstance(t, int) else "?"
                q = ((t - 1) % 4) + 1 if isinstance(t, int) else "?"
                news_context += f"〔{y}年 第{q}四半期 (Turn {t})〕\n- {c}\n"
            
            logger.sys_log_detail("Summit DB Search Result Details", log_detail)
            news_context += "\n"
            has_news = True
            
    # DBが利用できない、またはイベントが見つからない場合のフォールバック（旧実装）
    if not has_news:
        news_context = "【直近1年の世界のニュース】\n"
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
            news_context = "【両国間に関する直近1年の重要な出来事】\n特になし\n"
        
    status_a = f"経済力:{state_a.economy:.1f}, 軍事力:{state_a.military:.1f}, 支持率:{state_a.approval_rating:.1f}%"
    status_b = f"経済力:{state_b.economy:.1f}, 軍事力:{state_b.military:.1f}, 支持率:{state_b.approval_rating:.1f}%"
    
    chat_history = f"【首脳会談の記録】\n参加国: {proposal.proposer} ({status_a}), {proposal.target} ({status_b})\n議題: {proposal.topic}\n\n"
    
    is_private_str = "【⚠️警告: この会談は極秘の非公開会談であり、協議内容は第三国には一切漏洩しません。率直な意見交換が可能です】\n\n" if getattr(proposal, 'is_private', False) else ""
    
    tool_instruction = "\n【ツール】必要に応じて、search_historical_events ツールを使用して過去の外交・内政・諜報に関する記録を検索できます。\n" if (search_tool_a or search_tool_b) else ""
    
    base_context_a = (
        f"あなたは「{proposal.proposer}」を治める国家の首脳です。体制:{state_a.government_type.value}, 理念:{state_a.ideology}。\n"
        f"（※実在の国名ですが、架空の代表者として振る舞い、実在の政治家個人名は一切使用しないでください）\n"
        f"現在のあなたの国の国力: {status_a}\n"
        f"相手国({proposal.target})の国力: {status_b}\n\n"
        f"あなたの脳内（非公開の計画や諜報結果など）には次のような情報があります: '{state_a.hidden_plans}'\n\n"
        f"{is_private_str}"
        f"{news_context}\n"
        f"{tool_instruction}"
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
        f"{tool_instruction}"
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
            resp_a = _generate_with_tool(generate_func, logger, SUMMIT_MODEL, prompt_a, "summit", search_tool_a, proposal.proposer)
        except Exception as e:
            logger.sys_log(f"[{proposal.proposer}] APIエラー(Summit): {e}", "ERROR")
            resp_a = "通信障害により発言できませんでした。"
        messages.append(f"【{proposal.proposer}首脳】: {resp_a}")
        logger.sys_log(f"[Summit {current_turn}/{total_turns}] {proposal.proposer}: {resp_a}")
        
        # Bの発言
        prompt_b = base_context_b + turn_instruction + "\nこれまでの会話:\n" + "\n".join(messages) + f"\n\n{proposal.target}としての次の発言を入力してください:"
        try:
            resp_b = _generate_with_tool(generate_func, logger, SUMMIT_MODEL, prompt_b, "summit", search_tool_b, proposal.target)
        except Exception as e:
            logger.sys_log(f"[{proposal.target}] APIエラー(Summit): {e}", "ERROR")
            resp_b = "通信障害により発言できませんでした。"
        messages.append(f"【{proposal.target}首脳】: {resp_b}")
        logger.sys_log(f"[Summit {current_turn}/{total_turns}] {proposal.target}: {resp_b}")
        
    # 合意の要約
    summary_prompt = "以下の首脳会談の記録から、両国の最終的な「合意事項（または物別れに終わったという結果）」を100文字程度で簡潔に要約してください。\n\n" + "\n".join(messages)
    try:
        summary_obj = generate_func(model=SUMMIT_MODEL, contents=summary_prompt, category="summit_summary")
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


def run_multilateral_summit(
    generate_func,
    logger: SimulationLogger,
    db_manager,
    proposal: SummitProposal,
    country_states: Dict[str, Any],
    world_state: WorldState,
    past_news: List[str] = None,
    search_tools: Dict[str, Callable] = None
) -> Tuple[str, str]:
    """多国間首脳会談（ラウンドロビン方式）を実行し、(要約, 全文ログ)のタプルを返す"""
    participants = proposal.accepted_participants if proposal.accepted_participants else proposal.participants
    if proposal.proposer not in participants:
        participants = [proposal.proposer] + participants
    
    # 存在しない国を除外
    participants = [p for p in participants if p in country_states]
    
    if len(participants) < 2:
        logger.sys_log(f"[多国間会談] 参加国が2国未満のため中止 (参加国: {participants})", "WARNING")
        return None, ""
    
    participant_names = ", ".join(participants)
    logger.sys_log(f"[多国間首脳会談] 開催: {participant_names} (議題: {proposal.topic}, モデル: {SUMMIT_MODEL})")
    
    # 各国の状態情報を構築
    status_map = {}
    for p in participants:
        cs = country_states[p]
        status_map[p] = f"経済力:{cs.economy:.1f}, 軍事力:{cs.military:.1f}, 支持率:{cs.approval_rating:.1f}%"
    
    # DB検索による関連イベントの収集（全参加国間）
    news_context = f"【参加国間（{participant_names}）に関連する直近1年(4四半期)の出来事】\n"
    has_news = False
    
    if db_manager:
        limit_turns = 4
        all_events = []
        # 全参加国ペアの組み合わせからイベントを収集
        for i, p1 in enumerate(participants):
            for p2 in participants[i+1:]:
                events = db_manager.get_recent_events_between_countries(
                    p1, p2, world_state.turn, limit_turns=limit_turns
                )
                all_events.extend(events)
        
        # 重複排除（content基準）
        seen_contents = set()
        unique_events = []
        for ev in all_events:
            c = ev.get('content', '')
            if c not in seen_contents:
                seen_contents.add(c)
                unique_events.append(ev)
        
        if unique_events:
            for ev in unique_events:
                t = ev.get('turn', '?')
                c = ev.get('content', '')
                y = 2025 + (t - 1) // 4 if isinstance(t, int) else "?"
                q = ((t - 1) % 4) + 1 if isinstance(t, int) else "?"
                news_context += f"〔{y}年 第{q}四半期 (Turn {t})〕\n- {c}\n"
            news_context += "\n"
            has_news = True
            logger.sys_log(f"[Multilateral Summit DB Search] {len(unique_events)}件のイベントを抽出")
    
    if not has_news:
        news_context = "【参加国間に関する直近1年の重要な出来事】\n特になし\n"
    
    is_private_str = "【⚠️警告: この会談は極秘の非公開会談であり、協議内容は参加国以外には一切漏洩しません。率直な意見交換が可能です】\n\n" if getattr(proposal, 'is_private', False) else ""
    
    # 各参加国のベースコンテキストを構築
    base_contexts = {}
    for p in participants:
        cs = country_states[p]
        others_status = "\n".join(f"  - {o}: {status_map[o]}" for o in participants if o != p)
        
        tool_instruction = ""
        if search_tools and search_tools.get(p):
            tool_instruction = "\n【ツール】必要に応じて、search_historical_events ツールを使用して過去の外交・内政・諜報に関する記録を検索できます。\n"
        
        base_contexts[p] = (
            f"あなたは「{p}」を治める国家の首脳です。体制:{cs.government_type.value}, 理念:{cs.ideology}。\n"
            f"（※実在の国名ですが、架空の代表者として振る舞い、実在の政治家個人名は一切使用しないでください）\n"
            f"現在のあなたの国の国力: {status_map[p]}\n"
            f"他の参加国の国力:\n{others_status}\n\n"
            f"あなたの脳内（非公開の計画や諜報結果など）には次のような情報があります: '{cs.hidden_plans}'\n\n"
            f"{is_private_str}"
            f"{news_context}\n"
            f"{tool_instruction}"
            f"以上の世界情勢と自国の秘匿情報を踏まえた上で、参加国と「{proposal.topic}」について多国間会談を行います。\n"
            f"自国の情報に関することであれば創作しても構いません。また、発言は必ず日本語で行ってください。\n"
        )
    
    # ラウンドロビン式で会談実行（4ラウンド × 全参加国）
    chat_history = f"【多国間首脳会談の記録】\n参加国: {participant_names}\n議題: {proposal.topic}\n\n"
    messages = []
    total_rounds = 4
    
    for round_num in range(total_rounds):
        current_round = round_num + 1
        for speaker in participants:
            turn_instruction = (
                f"現在、全{total_rounds}ラウンドのうちの第{current_round}ラウンドです。参加国は{len(participants)}カ国です。\n"
                f"【重要指示】毎回挨拶や締めの言葉を繰り返すのは不自然です。直前の発言に直接返答し、連続した自然な議論や交渉を行ってください。\n"
                f"【重要指示】新たな専門家会議やワーキンググループなどの会議体を設置する合意は行わず、議題に関する事項は全てこの会談の中で決定してください。\n"
                f"【文字数制限】各発言は必ず400文字以内で記述してください。"
            )
            if current_round == total_rounds and speaker == participants[-1]:
                turn_instruction += "これが会談の最後の発言です。会談の結論や最終提案を提示してください。"
            
            prompt = (
                base_contexts[speaker] + turn_instruction + 
                "\nこれまでの会話:\n" + "\n".join(messages) + 
                f"\n\n{speaker}としての次の発言を入力してください:"
            )
            
            search_tool = search_tools.get(speaker) if search_tools else None
            try:
                resp = _generate_with_tool(generate_func, logger, SUMMIT_MODEL, prompt, "summit", search_tool, speaker)
            except Exception as e:
                logger.sys_log(f"[{speaker}] APIエラー(Multilateral Summit): {e}", "ERROR")
                resp = "通信障害により発言できませんでした。"
            
            messages.append(f"【{speaker}首脳】: {resp}")
            logger.sys_log(f"[Multilateral Summit R{current_round}] {speaker}: {resp}")
    
    # 合意の要約
    summary_prompt = (
        f"以下の多国間首脳会談（参加国: {participant_names}）の記録から、"
        f"参加国の最終的な「合意事項（または物別れに終わったという結果）」を150文字程度で簡潔に要約してください。\n\n"
        + "\n".join(messages)
    )
    try:
        summary_obj = generate_func(model=SUMMIT_MODEL, contents=summary_prompt, category="summit_summary")
        summary = summary_obj.text.strip() if summary_obj and hasattr(summary_obj, 'text') else "会談は終了しました"
    except Exception as e:
        logger.sys_log(f"[Multilateral Summit Summary] APIエラー: {e}", "ERROR")
        summary = "APIエラーにより会談結果の要約に失敗しました。"
    
    full_log = chat_history + "\n".join(messages) + f"\n\n【最終結果】\n{summary}"
    logger.sys_log_detail("Multilateral Summit Log", full_log)
    
    if getattr(proposal, 'is_private', False):
        news_summary = None
    else:
        news_summary = f"🤝 【多国間首脳会談結果】{participant_names}による多国間会談が終了しました。結果: {summary}"
    
    return news_summary, full_log
