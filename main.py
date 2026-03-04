import time
import json
import os
import random
from models import WorldState, CountryState, GovernmentType, RelationType, TradeState
from engine import WorldEngine
from agent import AgentSystem
from logger import SimulationLogger
import summarizer
import notifier

def initialize_world() -> WorldState:
    """初期の歴史的状況を設定したWorldStateを返す"""
    world = WorldState(
        turn=1,
        year=2025,
        quarter=1,
        countries={
            "アメリカ": CountryState(
                name="アメリカ",
                government_type=GovernmentType.DEMOCRACY,
                ideology="自由民主主義体制の維持、同盟国との連携による覇権維持、経済的優位の確保",
                economy=25000.0,
                military=850.0,
                area=9833517.0,
                approval_rating=55.0,
                turns_until_election=16, 
                rebellion_risk=0.0,
                press_freedom=0.6549, 
                hidden_plans=""
            ),
            "中国": CountryState(
                name="中国",
                government_type=GovernmentType.AUTHORITARIAN,
                ideology="国家主導による急速な経済・軍事の発展、既存の世界秩序の変更と覇権の奪取",
                economy=18000.0,
                military=306.0,
                area=9596960.0,
                approval_rating=70.0,
                rebellion_risk=5.0,
                press_freedom=0.2241, 
                hidden_plans=""
            )
        },
        relations={
            "アメリカ": {"中国": RelationType.NEUTRAL},
            "中国": {"アメリカ": RelationType.NEUTRAL}
        },
        active_wars=[],
        active_trades=[TradeState(country_a="アメリカ", country_b="中国")],
        news_events=["世界のリーダーたちが行動を開始しています。"]
    )
    return world

def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI Diplomacy Simulation")
    parser.add_argument("--turns", type=int, default=40, help="Number of turns to run")
    parser.add_argument("--resume", type=str, help="Path to a simulation log file (.jsonl) to resume from", default=None)
    parser.add_argument("--seed", type=int, default=None, help="乱数シード（再現性のために設定推奨）")
    args = parser.parse_args()
    
    # --- 再現性のための乱数シード設定 ---
    if args.seed is not None:
        random.seed(args.seed)
        print(f"🔒 乱数シード固定: {args.seed}")
    else:
        seed = random.randint(0, 2**32 - 1)
        random.seed(seed)
        print(f"🔒 乱数シード（自動生成）: {seed}")
    
    if args.resume:
        if not os.path.exists(args.resume):
            print(f"エラー: 指定されたログファイルが見つかりません: {args.resume}")
            return
            
        with open(args.resume, "r", encoding="utf-8") as f:
            lines = f.readlines()
            if not lines:
                print("エラー: ログファイルが空です。")
                return
            last_line = lines[-1]
            last_turn_data = json.loads(last_line)
            world_state = WorldState.model_validate(last_turn_data["world_state"])
            
        # ファイル名から session_id を抽出 (例: sim_20260301_192846.jsonl)
        filename = os.path.basename(args.resume)
        if filename.startswith("sim_") and filename.endswith(".jsonl"):
            session_id = filename[4:-6]
        else:
            session_id = None
            
        logger = SimulationLogger(session_id=session_id)
        logger.sys_log(f"[Reproducibility] 乱数シード: {args.seed if args.seed is not None else 'auto'}")
        print(f"--- 🌍 AI外交シミュレーション (Turn {world_state.turn} から再開) ---")
    else:
        # システム初期化
        world_state = initialize_world()
        logger = SimulationLogger()
        logger.sys_log(f"[Reproducibility] 乱数シード: {args.seed if args.seed is not None else 'auto'}")
        print("--- 🌍 AI外交シミュレーション ---")

    try:
        agent_system = AgentSystem(logger=logger)
    except ValueError as e:
        print(f"初期化エラー: {e}")
        print("実行前に `export GEMINI_API_KEY=あなたのキー` を設定してください。")
        return

    # S-2: AgentSystemのGemini感情分析器をエンジンに注入
    engine = WorldEngine(initial_state=world_state, analyzer=agent_system.sentiment_analyzer)

    # シミュレーションループ
    MAX_TURNS = args.turns
    past_news_queue = []
    
    for _ in range(MAX_TURNS):
        # 1. ターンの開始表示
        logger.display_turn_header(world_state)
        logger.display_country_status(world_state)
        logger.display_world_events(world_state)
        
        # 2. 各AIエージェントによる行動の決定（API呼び出し）
        print("\n⏳ 首脳AIが状況を分析し、行動を決定しています...")
        actions = agent_system.generate_actions(world_state, past_news=past_news_queue)
        
        # 思考プロセスの表示（CLI上では分かりやすさのため表示）
        print("\n--- 🧠 各国の意思決定 ---")
        for country_name, action in actions.items():
            logger.display_agent_thoughts(country_name, action)

        # 3. エンジンによる世界の更新（判定フェーズ：内政・外交・諜報・戦争の成否を算出）
        world_state = engine.process_turn(actions)
        
        # 3.1. エンジン内での計算結果のログ出力
        for log_msg in engine.sys_logs_this_turn:
            logger.sys_log(log_msg)
        engine.sys_logs_this_turn.clear()
        
        # 4. 諜報（情報収集）成功時の機密レポート生成と被害国への漏洩記録
        if hasattr(engine, 'pending_intel_requests') and engine.pending_intel_requests:
            print("\n🕵️ 諜報機関が機密情報を解析し、レポートを作成しています...")
            for req in engine.pending_intel_requests:
                attacker_name = req["attacker"]
                target_name = req["target"]
                
                # Intel Agentを呼び出し
                report, _ = agent_system.generate_espionage_report(
                    attacker_name=attacker_name,
                    target_name=target_name,
                    target_hidden_plans=req["target_hidden_plans"],
                    strategy=req["strategy"]
                )
                
                # アタッカー側の脳内に機密報告を追記
                ca = world_state.countries.get(attacker_name)
                ct = world_state.countries.get(target_name)
                if ca and ct:
                    ca.hidden_plans += f" [機密報告: ターゲット国「{target_name}」について: {report}]"
                    # 被害国（ターゲット国）側に「何が漏洩したか」の履歴を残す（裏ステータスとして保管）
                    leaked_msg = f"ターン{max(1, world_state.turn - 1)}: {attacker_name}に『{report}』相当の情報が漏洩した"
                    ct.leaked_intel.append(leaked_msg)
                    logger.sys_log(f"[Hidden] {target_name} の漏洩履歴(leaked_intel)に追記されました: {leaked_msg}")
                    # 被害国（ターゲット国）のプロンプトにも自国の機密情報として即時追記し、世界のズレを防ぎつつメタ推測を禁止する
                    ct.hidden_plans += f" [機密情報: {report} ※この機密情報はシステム側からランダムに入力されるものです。]"

        # 5. 政権交代やクーデターが発生した場合の新しいイデオロギーの設定、定期的更新（中国）
        # pending_rebellions, pending_elections のリストにある国を処理
        affected_countries = set(getattr(engine, 'pending_rebellions', []) + getattr(engine, 'pending_elections', []))
        
        for country_name, country_state in world_state.countries.items():
            # 中国の20ターン（5年）ごとの定期レビュー
            is_china_periodic = (country_name == "中国" and world_state.turn % 20 == 0)
            
            if country_name in affected_countries or is_china_periodic:
                try:
                    if country_state.government_type == GovernmentType.DEMOCRACY:
                        # 民主的な体制の場合は直前の国民感情（SNS模擬投稿）を取得してイデオロギー生成に反映
                        print(f"🗳️ {country_name}の新しいイデオロギー策定に向けて世論を調査中...")
                        sns_posts = agent_system.generate_citizen_sns_posts(country_name, country_state, world_state, 5)
                        new_ideology = agent_system.generate_ideology_democracy(country_name, country_state, world_state, sns_posts)
                    else:
                        # 専制主義体制の場合は状況のみで生成
                        new_ideology = agent_system.generate_ideology_authoritarian(country_name, country_state, world_state)
                        
                    country_state.ideology = new_ideology
                    reason = "新政権" if country_name in affected_countries else "定期的な国家目標見直し"
                    world_state.news_events.append(f"🔄 {country_name}が{reason}により新たな国家目標を発表しました: 「{new_ideology[:30]}...」")
                    logger.sys_log(f"[{country_name}] 新しいイデオロギーを設定: {new_ideology}")
                except Exception as e:
                    logger.sys_log(f"[{country_name}] イデオロギーの生成に失敗しました: {e}", "ERROR")
                    
        # 5.5 技術革新の名称生成（待ち状態のものを処理）
        for bt in world_state.active_breakthroughs:
            if bt.name.startswith("（AI生成待ち"):
                print(f"💡 {bt.origin_country}で発生した新技術の詳細を分析中...")
                new_name = agent_system.generate_breakthrough_name(bt.origin_country, world_state.active_breakthroughs, world_state.year)
                bt.name = new_name
                news_text = f"💡 【技術革新】{bt.origin_country}において、歴史的な技術革新「{new_name}」が誕生しました！"
                world_state.news_events.append(news_text)
                logger.sys_log(news_text)

        # 6. 首脳会談の実行（受諾されたものがあれば）
        recent_summit_logs = []
        if engine.summits_to_run_this_turn:
            print("\n🤝 首脳会談が開催されています...")
            for proposal in engine.summits_to_run_this_turn:
                ca = world_state.countries.get(proposal.proposer)
                cb = world_state.countries.get(proposal.target)
                if ca and cb:
                    summit_news_result, full_summit_log = agent_system.run_summit(proposal, ca, cb, world_state, past_news=past_news_queue)
                    world_state.news_events.append(summit_news_result)
                    recent_summit_logs.append(full_summit_log)
                    world_state.summit_logs.append({
                        "turn": world_state.turn,
                        "participants": [proposal.proposer, proposal.target],
                        "topic": proposal.topic,
                        "log": full_summit_log
                    })
                    
        # 7. メディアエージェントによる報道と支持率への影響（ローカル感情分析）
        print("🗞️ 各国メディアがニュースを生成中...")
        media_reports, media_modifiers = agent_system.generate_media_reports(world_state, actions, recent_summit_logs)
        world_state.news_events.extend(media_reports)

        # 8. SNSタイムラインの構築・評価（最後に配置：メディア報道を踏まえた国民の反応）
        print("\n📱 各国のSNSタイムラインを生成しています...")
        sns_timelines = {country: [] for country in world_state.countries.keys()}
        
        # 首脳の投稿
        for country, action in actions.items():
            if hasattr(action, 'sns_posts') and action.sns_posts:
                for post in action.sns_posts:
                    if post.strip():
                        sns_timelines[country].append({"author": "Leader", "text": post})
                        
        # 破壊工作による敵国偽情報投稿
        if hasattr(engine, 'pending_sabotage_requests') and engine.pending_sabotage_requests:
            print("🕵️ 敵国の破壊工作部隊がSNSへの偽情報工作を行っています...")
            for req in engine.pending_sabotage_requests:
                attacker = req["attacker"]
                target = req["target"]
                _, sns_post = agent_system.generate_espionage_report(
                    attacker_name=attacker,
                    target_name=target,
                    target_hidden_plans=req["target_hidden_plans"],
                    strategy=req["strategy"]
                )
                if sns_post and sns_post.strip() and target in sns_timelines:
                    sns_timelines[target].append({"author": "Espionage", "text": sns_post})
                    
        # 一般国民の投稿
        for country, state in world_state.countries.items():
            current_posts = len(sns_timelines[country])
            needed = 5 - current_posts
            if needed > 0:
                citizen_posts = agent_system.generate_citizen_sns_posts(country, state, world_state, needed)
                for p in citizen_posts:
                    if p and p.strip():
                         sns_timelines[country].append({"author": "Citizen", "text": p})
                         
        # エンジンに渡して評価・支持率適用 (WMA)
        engine.evaluate_public_opinion(sns_timelines, media_modifiers)
        
        # コンソールログにSNSの声をわかりやすく出力
        if hasattr(logger, 'display_sns_timeline'):
            logger.display_sns_timeline(sns_timelines)
        
        # SNS評価後のエンジンログを出力
        for log_msg in engine.sys_logs_this_turn:
            logger.sys_log(log_msg)
        engine.sys_logs_this_turn.clear()

        # 9. ログの保存（全ての処理が完了した後の最終状態を保存）
        logger.save_turn_log(world_state, actions)
        
        # 10. ターン履歴の保存と時間進行
        past_news_queue.append(world_state.news_events.copy())
        if len(past_news_queue) > 4:
            past_news_queue.pop(0)
            
        engine.advance_time()
        
        # ターン進行のウェイト
        print("\n" + "="*50 + "\n")
        time.sleep(3) # APIのレートリミット対策も兼ねる

    print("🏁 指定ターン数のシミュレーションが終了しました。")
    print(f"シミュレーションログは {logger.sim_log_dir}/ に保存されています。")
    print(f"システムログは {logger.sys_log_dir}/ に保存されています。")
    
    # コスト計算と出力
    print("\n" + "="*50)
    print("💰 APIトークン使用量と推定コスト")
    print("="*50)
    total_cost = 0.0
    cost_log_lines = ["\n💰 API Cost Report:"]
    for category, usage in agent_system.token_usage.items():
        model = usage["model"]
        p_tokens = usage["prompt_tokens"]
        c_tokens = usage["candidates_token_count"]
        
        # 単価 (100万トークンあたり)
        if "gemini-3.1-pro" in model.lower():
            p_price, c_price = 2.00, 12.00
        elif "gemini-2.5-pro" in model.lower():
            p_price, c_price = 1.25, 10.00
        elif "gemini-2.5-flash-lite" in model.lower():
            p_price, c_price = 0.10, 0.40
        elif "gemini-2.5-flash" in model.lower():
            p_price, c_price = 0.30, 2.50
        else: # 分からないモデルのフォールバック (flash扱い)
            p_price, c_price = 0.30, 2.50
            
        cat_cost = (p_tokens / 1_000_000 * p_price) + (c_tokens / 1_000_000 * c_price)
        total_cost += cat_cost
        
        report_line = f"- [{category}] {model}: Prompt {p_tokens} ({p_price}$/M), Output {c_tokens} ({c_price}$/M) -> ${cat_cost:.4f}"
        print(report_line)
        cost_log_lines.append(report_line)
        
    total_line = f"▶ Total Estimated Cost: ${total_cost:.4f}"
    print("-" * 50)
    print(total_line)
    print("=" * 50 + "\n")
    cost_log_lines.append(total_line)
    
    # システムログに追記
    for line in cost_log_lines:
        logger.sys_log(line)
    
    # 最後にシミュレーションの要約を自動生成
    try:
        if hasattr(logger, 'sim_log_file'):
            summarizer.generate_summary(logger.sim_log_file)
    except Exception as e:
        print(f"Failed to auto-generate summary: {e}")

    # シミュレーション完了通知
    notifier.send_notification(
        "🌍 AI外交シミュレーション完了",
        f"全 {MAX_TURNS} ターンのシミュレーションが正常に終了しました。"
    )

if __name__ == "__main__":
    main()
