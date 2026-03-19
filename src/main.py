import time
import json
import os
import random
from models import WorldState, CountryState, GovernmentType, RelationType, TradeState, SanctionState, WarState
from engine import WorldEngine
from agent import AgentSystem
from logger import SimulationLogger
import summarizer
import notifier
from db_manager import DBManager

def initialize_world() -> WorldState:
    """初期の歴史的状況をCSV(initial_stats.csv, initial_relations.csv)から読み込んでWorldStateを返す"""
    import csv
    countries = {}
    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "initial_stats.csv")
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"]
            government_type = GovernmentType(row["government_type"])
            
            # 数値型への変換
            countries[name] = CountryState(
                name=name,
                government_type=government_type,
                ideology=row["ideology"],
                economy=float(row["economy"]),
                military=float(row["military"]),
                intelligence_level=float(row["intelligence_level"]),
                area=float(row["area"]),
                approval_rating=float(row["approval_rating"]),
                turns_until_election=int(row["turns_until_election"]) if row["turns_until_election"] else None,
                rebellion_risk=float(row["rebellion_risk"]) if row["rebellion_risk"] else 0.0,
                press_freedom=float(row["press_freedom"]),
                education_level=float(row["education_level"]),
                initial_education_level=float(row["education_level"]),
                population=float(row["population"]),
                initial_population=float(row["population"]),
                hidden_plans=""
            )

    # 関係性の初期化（全組み合わせをデフォルトNEUTRALに）
    relations = {}
    country_names = list(countries.keys())
    for i, name_a in enumerate(country_names):
        relations[name_a] = {}
        for j, name_b in enumerate(country_names):
            if i != j:
                relations[name_a][name_b] = RelationType.NEUTRAL

    # initial_relations.csv から初期の国家間関係を読み込む
    active_trades = []
    active_wars = []
    active_sanctions = []
    relations_csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "initial_relations.csv")
    
    if os.path.exists(relations_csv_path):
        with open(relations_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ca = row["country_a"].strip()
                cb = row["country_b"].strip()
                
                # 両国が initial_stats.csv に存在するか検証
                if ca not in countries or cb not in countries:
                    print(f"⚠️ initial_relations.csv: 不明な国名をスキップ ({ca}, {cb})")
                    continue
                
                # 関係タイプの設定（双方向）
                rel = RelationType(row["relation_type"].strip())
                relations[ca][cb] = rel
                relations[cb][ca] = rel
                
                # 貿易協定
                if row["trade"].strip().lower() == "true":
                    active_trades.append(TradeState(country_a=ca, country_b=cb))
                
                # 経済制裁（方向あり）
                if row["sanctions_a_to_b"].strip().lower() == "true":
                    active_sanctions.append(SanctionState(imposer=ca, target=cb))
                if row["sanctions_b_to_a"].strip().lower() == "true":
                    active_sanctions.append(SanctionState(imposer=cb, target=ca))
                
                # 戦争状態
                war_aggressor = row.get("war_aggressor", "").strip()
                if war_aggressor and rel == RelationType.AT_WAR:
                    defender = cb if war_aggressor == ca else ca
                    active_wars.append(WarState(aggressor=war_aggressor, defender=defender))
        
        print(f"📋 initial_relations.csv を読み込みました: 貿易{len(active_trades)}件, 制裁{len(active_sanctions)}件, 戦争{len(active_wars)}件")
    else:
        print("⚠️ initial_relations.csv が見つかりません。全関係をNEUTRALで初期化します。")

    # ニュースイベントの初期化（初期関係に基づく）
    initial_news = ["世界のリーダーたちが行動を開始しています。"]
    for war in active_wars:
        initial_news.append(f"⚔️ {war.aggressor}と{war.defender}の間で軍事衝突が発生しています。")
    for trade in active_trades:
        initial_news.append(f"🤝 {trade.country_a}と{trade.country_b}は貿易協定を締結しています。")
    for sanction in active_sanctions:
        initial_news.append(f"⛔ {sanction.imposer}が{sanction.target}に経済制裁を発動中です。")

    world = WorldState(
        turn=1,
        year=2025,
        quarter=1,
        countries=countries,
        relations=relations,
        active_wars=active_wars,
        active_trades=active_trades,
        active_sanctions=active_sanctions,
        news_events=initial_news
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
        current_seed = args.seed
        print(f"🔒 乱数シード固定: {current_seed}")
    else:
        current_seed = random.randint(0, 2**32 - 1)
        print(f"🔒 乱数シード（自動生成）: {current_seed}")
    random.seed(current_seed)
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
        logger.sys_log(f"[Reproducibility] 乱数シード: {current_seed}")
    else:
        # システム初期化
        world_state = initialize_world()
        logger = SimulationLogger()
        logger.sys_log(f"[Reproducibility] 乱数シード: {current_seed}")

    db_manager = DBManager(collection_name=f"diplomacy_events_{logger.session_id}")

    try:
        agent_system = AgentSystem(logger=logger, db_manager=db_manager)
    except ValueError as e:
        print(f"初期化エラー: {e}")
        print("実行前に `export GEMINI_API_KEY=あなたのキー` を設定してください。")
        return

    # S-2: AgentSystemのGemini感情分析器をエンジンに注入
    engine = WorldEngine(initial_state=world_state, analyzer=agent_system.sentiment_analyzer, db_manager=db_manager)

    if args.resume:
        # 復元されたstataは前ターンの終了時（時間進行前）のものなので、ここで時間を進めて次ターンを開始する
        engine.advance_time()
        print(f"--- 🌍 AI外交シミュレーション (Turn {world_state.turn} から再開) ---")
    else:
        print("--- 🌍 AI外交シミュレーション ---")

    # シミュレーションループ
    MAX_TURNS = args.turns
    past_news_queue = []

    # ideologyが空の国家に初期ideologyを生成（CSV空欄→首脳エージェントが自律記述）
    empty_ideology_countries = [
        (name, state) for name, state in world_state.countries.items()
        if not state.ideology or not state.ideology.strip()
    ]
    if empty_ideology_countries:
        print(f"\n🔄 {len(empty_ideology_countries)}つの国家にイデオロギー（国家目標）を生成中...")
        for country_name, country_state in empty_ideology_countries:
            try:
                if country_state.government_type == GovernmentType.DEMOCRACY:
                    new_ideology = agent_system.generate_ideology_democracy(
                        country_name, country_state, world_state, []
                    )
                else:
                    new_ideology = agent_system.generate_ideology_authoritarian(
                        country_name, country_state, world_state
                    )
                country_state.ideology = new_ideology
                logger.sys_log(f"[{country_name}] 初期イデオロギーを生成: {new_ideology}")
                print(f"  ✅ {country_name}: {new_ideology[:60]}...")
            except Exception as e:
                # フォールバック: デフォルトのideologyを設定
                fallback = "国家の安定と繁栄を追求する" if country_state.government_type == GovernmentType.DEMOCRACY else "国家体制の維持と発展を推進する"
                country_state.ideology = fallback
                logger.sys_log(f"[{country_name}] イデオロギー生成失敗、フォールバック使用: {e}", "WARNING")
                print(f"  ⚠️ {country_name}: フォールバック使用 ({fallback})")
        print()
    
    for _ in range(MAX_TURNS):
        # 1. ターン開始時のシステム内政判定（選挙・クーデター）
        engine.process_pre_turn()
        
        # 2. 国家ステータス
        logger.display_turn_header(world_state)
        logger.display_section_header("1. 国家ステータス")
        logger.display_country_status(world_state)
        
        # 3. ニュース・イベントログ (前期の結果 + 今期開始時の事象)
        logger.display_section_header("2. ニュース・イベントログ")
        logger.display_world_events(world_state)
        
        # 4. イデオロギーの再作成（新政権の発足など）
        affected_countries = set(getattr(engine, 'pending_rebellions', []) + getattr(engine, 'pending_elections', []))
        if affected_countries or any(name == "中国" and world_state.turn % 20 == 0 for name in world_state.countries.keys()):
            logger.display_section_header("2.5 イデオロギーの再作成")
            ideology_updates = []
            for country_name, country_state in world_state.countries.items():
                is_china_periodic = (country_name == "中国" and world_state.turn % 20 == 0)
                if country_name in affected_countries or is_china_periodic:
                    try:
                        if country_state.government_type == GovernmentType.DEMOCRACY:
                            print(f"🗳️ {country_name}の新しいイデオロギー策定に向けて世論を調査中...")
                            sns_posts = agent_system.generate_citizen_sns_posts(country_name, country_state, world_state, 5)
                            new_ideology = agent_system.generate_ideology_democracy(country_name, country_state, world_state, sns_posts)
                        else:
                            new_ideology = agent_system.generate_ideology_authoritarian(country_name, country_state, world_state)
                            
                        country_state.ideology = new_ideology
                        reason = "新政権" if country_name in affected_countries else "定期的な国家目標見直し"
                        msg = f"🔄 {country_name}が{reason}により新たな国家目標を発表しました: 「{new_ideology[:50]}...」"
                        world_state.news_events.append(msg)
                        ideology_updates.append(msg)
                        logger.sys_log(f"[{country_name}] 新しいイデオロギーを設定: {new_ideology}")
                    except Exception as e:
                        logger.sys_log(f"[{country_name}] イデオロギーの生成に失敗しました: {e}", "ERROR")
            
            if ideology_updates:
                logger.display_category_events(ideology_updates, "イデオロギー再構築", style="bold blue", icon="🔄")
        
        # 5. 各AIエージェントによる行動の決定（API呼び出し）
        print("\n⏳ 首脳AIが状況を分析し、行動を決定しています...")
        actions = agent_system.generate_actions(world_state, past_news=past_news_queue)
        
        # 6. 各国の意思決定
        logger.display_section_header("3. 各国の意思決定")
        for country_name, action in actions.items():
            logger.display_agent_thoughts(country_name, action)

        # 7. エンジンによる世界の更新（判定フェーズ）
        world_state = engine.process_turn(actions)
        
        # 8 & 9. 災害・技術革新、経済制裁などの抽出
        disaster_tech_events = [e for e in world_state.news_events if any(k in e for k in ["💡", "🚨", "技術"])]
        sanctions_trade_events = [e for e in world_state.news_events if any(k in e for k in ["⛔", "✅", "🚢", "🤝", "貿易", "制裁"])]
        
        logger.display_section_header("4. 災害・技術革新の発生")
        if disaster_tech_events:
            logger.display_category_events(disaster_tech_events, "災害・技術イベント", style="bold red", icon="🆘")
        else:
            print("目立った災害や技術革新は発生しませんでした。")

        logger.display_section_header("5. 経済制裁等")
        if sanctions_trade_events:
            logger.display_category_events(sanctions_trade_events, "経済・通商動向", style="bold yellow", icon="💰")
        else:
            print("新たな制裁や貿易の変化は検出されませんでした。")

        # 3.1. エンジン内での計算結果のログ出力
        for log_msg in engine.sys_logs_this_turn:
            logger.sys_log(log_msg)
        engine.sys_logs_this_turn.clear()
        
        # （イデオロギー再作成はループの前半に移動済み）

        # 7. 諜報機関のレポート作成
        logger.display_section_header("7. 諜報機関のレポート作成")
        if hasattr(engine, 'pending_intel_requests') and engine.pending_intel_requests:
            print("🕵️ 諜報機関が機密情報を解析し、レポートを作成しています...")
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
                
                # コンソール表示
                logger.display_category_events([report], f"🕵️ {attacker_name} 諜報レポート (対象: {target_name})", style="bold magenta", icon="🕵️")
                
                # アタッカー側の脳内に機密報告を追記
                ca = world_state.countries.get(attacker_name)
                ct = world_state.countries.get(target_name)
                if ca and ct:
                    ca.hidden_plans += f" [機密報告: ターゲット国「{target_name}」について: {report}]"
                    leaked_msg = f"ターン{max(1, world_state.turn - 1)}: {attacker_name}に『{report}』相当の情報が漏洩した"
                    ct.leaked_intel.append(leaked_msg)
                    ct.hidden_plans += f" [機密情報: {report} ※この機密情報はシステム側からランダムに入力されるものです。]"
        else:
            print("特筆すべき諜報レポートはありません。")
                    
        # 5.5 技術革新の名称生成
        for bt in world_state.active_breakthroughs:
            if bt.name.startswith("（AI生成待ち"):
                print(f"💡 {bt.origin_country}で発生した新技術の詳細を分析中...")
                new_name = agent_system.generate_breakthrough_name(bt.origin_country, world_state.active_breakthroughs, world_state.year)
                bt.name = new_name
                news_text = f"💡 【技術革新】{bt.origin_country}において、歴史的な技術革新「{new_name}」が誕生しました！"
                world_state.news_events.append(news_text)
                logger.sys_log(news_text)

        # 8. 首脳会談の要約
        logger.display_section_header("8. 首脳会談の要約")
        recent_summit_logs = []
        if engine.summits_to_run_this_turn:
            print("\n🤝 首脳会談が開催されています...")
            for proposal in engine.summits_to_run_this_turn:
                ca = world_state.countries.get(proposal.proposer)
                cb = world_state.countries.get(proposal.target)
                if ca and cb:
                    # 国家がまだ存在しているか再確認 (engine.process_turnで敗北した可能性)
                    if proposal.proposer not in world_state.countries or proposal.target not in world_state.countries:
                        continue
                    summit_news_result, full_summit_log = agent_system.run_summit(proposal, ca, cb, world_state, past_news=past_news_queue)
                    
                    is_private_summit = getattr(proposal, 'is_private', False)
                    if summit_news_result:
                        world_state.news_events.append(summit_news_result)
                        logger.display_category_events([summit_news_result], f"首脳会談: {proposal.proposer} & {proposal.target}", style="bold cyan", icon="🤝")
                    else:
                        logger.sys_log(f"[非公開会談完了] {proposal.proposer} & {proposal.target}")
                        
                    if not is_private_summit:
                        recent_summit_logs.append(full_summit_log)
                        
                    world_state.summit_logs.append({
                        "turn": world_state.turn,
                        "participants": [proposal.proposer, proposal.target],
                        "topic": proposal.topic,
                        "log": full_summit_log,
                        "is_private": is_private_summit
                    })
        else:
            print("今期、首脳会談は行われませんでした。")
                    
        # 9. ニュースの表示
        logger.display_section_header("9. ニュースの表示")
        print("🗞️ 各国メディアがニュースを分析中...")
        media_reports, media_modifiers = agent_system.generate_media_reports(world_state, actions, recent_summit_logs)
        world_state.news_events.extend(media_reports)
        logger.display_world_events(world_state, title="📰 本日のハイライト・メディア報道")

        # 10. SNSタイムライン
        logger.display_section_header("10. SNSタイムライン")
        print("📱 各国のSNSタイムラインを生成しています...")
        sns_timelines = {country: [] for country in world_state.countries.keys()}
        
        # 首脳の投稿
        for country, action in actions.items():
            if country not in world_state.countries:
                continue # 敗北国はSNSを投稿しない
            if hasattr(action, 'sns_posts') and action.sns_posts:
                for post in action.sns_posts:
                    if post.strip():
                        sns_timelines[country].append({"author": "Leader", "text": post})
                        
        # 破壊工作
        if hasattr(engine, 'pending_sabotage_requests') and engine.pending_sabotage_requests:
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
                    
        # 一般国民
        for country, state in world_state.countries.items():
            if country not in sns_timelines:
                continue
            current_posts = len(sns_timelines[country])
            needed = 5 - current_posts
            if needed > 0:
                citizen_posts = agent_system.generate_citizen_sns_posts(country, state, world_state, needed)
                for p in citizen_posts:
                    if p and p.strip():
                         sns_timelines[country].append({"author": "Citizen", "text": p})
                         
        # 分裂ロジック等のためにエンジンのステートに現ターンのSNSログを保存
        engine.turn_sns_logs = sns_timelines.copy()

        engine.evaluate_public_opinion(sns_timelines, media_modifiers)
        logger.display_sns_timeline(sns_timelines)
        
        # SNS評価後のエンジンログを出力
        for log_msg in engine.sys_logs_this_turn:
            logger.sys_log(log_msg)
        engine.sys_logs_this_turn.clear()

        # ログの保存 (敗北国のアクションを除去した上で保存)
        safe_actions = {c: a for c, a in actions.items() if c in world_state.countries}
        logger.save_turn_log(world_state, safe_actions)
        
        # 10. ターン履歴の保存と時間進行
        past_news_queue.append(world_state.news_events.copy())
        if len(past_news_queue) > 4:
            past_news_queue.pop(0)
            
        engine.advance_time()
        
        # ターン進行のウェイト
        print("\n" + "="*50 + "\n")
        time.sleep(3)

    print("🏁 指定ターン数のシミュレーションが終了しました。")
    print(f"シミュレーションログは {logger.sim_log_dir}/ に保存されています。")
    print(f"システムログは {logger.sys_log_dir}/ に保存されています。")
    
    # 最後にシミュレーションの要約を自動生成 (コスト計算に含めるため先に実行)
    try:
        if hasattr(logger, 'sim_log_file'):
            summary_info = summarizer.generate_summary(logger.sim_log_file, force=True)
            if summary_info and "usage" in summary_info:
                agent_system.token_usage["サマリー生成"] = {
                    "model": "gemini-2.5-flash",
                    "prompt_tokens": summary_info["usage"]["prompt_tokens"],
                    "candidates_token_count": summary_info["usage"]["candidates_token_count"]
                }
    except Exception as e:
        print(f"Failed to auto-generate summary: {e}")

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

    # シミュレーション完了通知
    notifier.send_notification(
        "🌍 AI外交シミュレーション完了",
        f"全 {MAX_TURNS} ターンのシミュレーションが正常に終了しました。"
    )

if __name__ == "__main__":
    main()
