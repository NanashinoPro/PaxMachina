import time
import json
import os
import random
from models import WorldState, CountryState, GovernmentType, RelationType, TradeState, SanctionState, WarState, PendingAidProposal, RecurringAid
from engine import WorldEngine
from agent import AgentSystem
from logger import SimulationLogger
import summarizer
import notifier
from db_manager import DBManager

def _safe_float(value: str, default: float) -> float:
    """CSVから読み込んだ文字列を安全に float に変換する。空文字列や非数値はデフォルト値を返す。"""
    if not value or not value.strip():
        return default
    try:
        return float(value.strip())
    except (ValueError, TypeError):
        return default

def initialize_world(data_dir: str = None) -> WorldState:
    """初期の歴史的状況をCSV(initial_stats.csv, initial_relations.csv)から読み込んでWorldStateを返す"""
    import csv
    base_data_dir = data_dir if data_dir else os.path.join(os.path.dirname(__file__), "..", "data")
    countries = {}
    csv_path = os.path.join(base_data_dir, "initial_stats.csv")
    
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
                human_capital_index=float(row["human_capital_index"]),
                initial_human_capital_index=float(row["human_capital_index"]),
                mean_years_schooling=float(row["mean_years_schooling"]),
                population=float(row["population"]),
                initial_population=float(row["population"]),
                capital_lat=float(row.get("capital_lat", 0.0) or 0.0),
                capital_lon=float(row.get("capital_lon", 0.0) or 0.0),
                has_dissolution_power=row.get("has_dissolution_power", "").strip().lower() == "true",
                hidden_plans="",
                # 初期国家はシミュレーション開始時点で既に長年の政権が存在する
                # クールダウン(4ターン)を大きく超える20ターン相当の政権期間を設定
                # [学術的根拠] Polity IV: 既存政権の安定性は過去の継続期間に依存する
                regime_duration=20,
                # v1-2: エネルギー初期値（CSVから読み込む）
                energy_self_sufficiency=_safe_float(row.get("energy_self_sufficiency"), 0.13),
                energy_reserve_target_turns=_safe_float(row.get("energy_reserve_target_turns"), 1.0),
                energy_reserve_turns=_safe_float(row.get("energy_reserve_target_turns"), 1.0),  # 初期備蓄は目標値でスタート
                # v1-3: 核兵器パラメータ（CSVから読み込む）
                nuclear_warheads=int(_safe_float(row.get("nuclear_warheads"), 0)),
                nuclear_dev_step=int(_safe_float(row.get("nuclear_dev_step"), 0)),
                has_second_strike=row.get("has_second_strike", "").strip().lower() == "true",
                nuclear_host_provider=row.get("nuclear_host_provider", "").strip() or None,
                nuclear_hosted_warheads=int(_safe_float(row.get("nuclear_hosted_warheads"), 0)),
            )
            # 専制主義国家は初期から支持率を対外偽装する
            # CSVの approval_rating は政府の「公表値（偽装値）」であり、真の民意は不明
            # → 真値を50.0（不明のためニュートラル）に設定し、公表値はCSVの値を使用
            if government_type == GovernmentType.AUTHORITARIAN:
                public_approval = float(row["approval_rating"])   # CSVの値 = 公表値
                countries[name].approval_rating = 50.0            # 真値 = 不明なので50%
                countries[name].reported_approval_rating = public_approval  # 公表値（偽装）



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
    initial_aid_proposals = []
    initial_aid_entries = []
    relations_csv_path = os.path.join(base_data_dir, "initial_relations.csv")
    
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
                    tariff_a = float(row.get("tariff_a_to_b", 0.05) or 0.05)
                    tariff_b = float(row.get("tariff_b_to_a", 0.05) or 0.05)
                    active_trades.append(TradeState(
                        country_a=ca, country_b=cb,
                        tariff_a_to_b=tariff_a, tariff_b_to_a=tariff_b
                    ))
                
                # 経済制裁（方向あり）
                if row["sanctions_a_to_b"].strip().lower() == "true":
                    active_sanctions.append(SanctionState(imposer=ca, target=cb))
                if row["sanctions_b_to_a"].strip().lower() == "true":
                    active_sanctions.append(SanctionState(imposer=cb, target=ca))
                
                # 戦争状態
                war_aggressor = row.get("war_aggressor", "").strip()
                if war_aggressor and rel == RelationType.AT_WAR:
                    defender = cb if war_aggressor == ca else ca
                    # 初期侵攻比率と初期占領進捗率の読み込み
                    agg_commit = float(row.get("aggressor_commitment_ratio", 0.50) or 0.50)
                    def_commit = float(row.get("defender_commitment_ratio", 0.80) or 0.80)
                    init_progress = float(row.get("initial_occupation_progress", 0.0) or 0.0)
                    active_wars.append(WarState(
                        aggressor=war_aggressor, defender=defender,
                        aggressor_commitment_ratio=agg_commit,
                        defender_commitment_ratio=def_commit,
                        target_occupation_progress=init_progress
                    ))
                
                # 初期援助の読み込み（「すでに流れている援助」として即時反映 + 次ターン分もPendingとして登録）
                aid_eco_a = float(row.get("initial_aid_economy_a_to_b", 0.0) or 0.0)
                aid_mil_a = float(row.get("initial_aid_military_a_to_b", 0.0) or 0.0)
                aid_eco_b = float(row.get("initial_aid_economy_b_to_a", 0.0) or 0.0)
                aid_mil_b = float(row.get("initial_aid_military_b_to_a", 0.0) or 0.0)
                
                if aid_eco_a > 0 or aid_mil_a > 0:
                    initial_aid_entries.append({"donor": ca, "target": cb, "eco": aid_eco_a, "mil": aid_mil_a})
                if aid_eco_b > 0 or aid_mil_b > 0:
                    initial_aid_entries.append({"donor": cb, "target": ca, "eco": aid_eco_b, "mil": aid_mil_b})
        
        print(f"📋 initial_relations.csv を読み込みました: 貿易{len(active_trades)}件, 制裁{len(active_sanctions)}件, 戦争{len(active_wars)}件, 初期援助{len(initial_aid_entries)}件")
    else:
        print("⚠️ initial_relations.csv が見つかりません。全関係をNEUTRALで初期化します。")

    # 初期援助の即時適用（Turn 1開始時にすでに援助が流れている状態を再現）
    initial_recurring_aids = []
    for aid in initial_aid_entries:
        donor_state = countries.get(aid["donor"])
        target_state = countries.get(aid["target"])
        if donor_state and target_state:
            # ① 即時反映: target国のmilitary/economyに直接加算
            target_state.military += aid["mil"]
            target_state.economy += aid["eco"]
            print(f"  💰 初期援助即時反映: {aid['donor']}→{aid['target']} (経済+{aid['eco']:.1f}, 軍事+{aid['mil']:.1f})")
            # ② サブスク契約として登録（以降は毎ターン自動継続）
            initial_recurring_aids.append(RecurringAid(
                donor=aid["donor"], target=aid["target"],
                amount_economy=aid["eco"], amount_military=aid["mil"]
            ))

    # ニュースイベントの初期化（初期関係に基づく）
    initial_news = ["世界のリーダーたちが行動を開始しています。"]
    for war in active_wars:
        initial_news.append(f"⚔️ {war.aggressor}と{war.defender}の間で軍事衝突が発生しています。")
    for trade in active_trades:
        initial_news.append(f"🤝 {trade.country_a}と{trade.country_b}は貿易協定を締結しています。")
    for sanction in active_sanctions:
        initial_news.append(f"⛔ {sanction.imposer}が{sanction.target}に経済制裁を発動中です。")
    for aid in initial_aid_entries:
        initial_news.append(f"💰 {aid['donor']}は{aid['target']}に対して継続的な援助を実施中です（経済{aid['eco']:.1f}B, 軍事{aid['mil']:.1f}B/四半期）。")

    world = WorldState(
        turn=1,
        year=2026,
        quarter=1,
        countries=countries,
        relations=relations,
        active_wars=active_wars,
        active_trades=active_trades,
        active_sanctions=active_sanctions,
        news_events=initial_news,
        recurring_aid_contracts=initial_recurring_aids
    )

    # ==========================================================
    # 初期ホルムズ海峡封鎖（2026年Q1: イランが開戦と同時に封鎖宣言）
    # ==========================================================
    world.active_strait_blockades.append("ホルムズ海峡")
    world.strait_blockade_owners["ホルムズ海峡"] = "イラン"
    # 産油国の輸出を停止（サウジ・イランは輸出ルートが遮断される）
    for _blocked in ["サウジアラビア", "イラン"]:
        if _blocked in world.countries:
            world.countries[_blocked].energy_export_blocked = True
    initial_news.append(
        "🚨【ホルムズ海峡封鎖】イランが開戦と同時にホルムズ海峡の封鎖を宣言。"
        "中東産油国からのエネルギー輸入が遮断されました。"
        "日本・フィリピンなど輸入依存国に深刻な影響が及ぶ見通しです。"
    )

    return world

def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI Diplomacy Simulation")
    parser.add_argument("--turns", type=int, default=40, help="Number of turns to run")
    parser.add_argument("--resume", type=str, help="Path to a simulation log file (.jsonl) to resume from", default=None)
    parser.add_argument("--resume-turn", type=int, help="指定ターンの状態から再開する（--resumeと併用必須）", default=None, dest="resume_turn")
    parser.add_argument("--seed", type=int, default=None, help="乱数シード（再現性のために設定推奨）")
    parser.add_argument("--data-dir", type=str, default=None, dest="data_dir",
                        help="カスタムデータディレクトリ（例: data/test でtest_stats.csv/test_relations.csvを使用）")
    args = parser.parse_args()
    
    # バリデーション: --resume-turn は --resume と併用必須
    if args.resume_turn is not None and args.resume is None:
        print("エラー: --resume-turn は --resume と併用してください。")
        print("使用例: python src/main.py --resume logs/simulations/sim_XXXXXX.jsonl --resume-turn 18 --turns 3")
        return
    
    # --- 再現性のための乱数シード設定 ---
    if args.seed is not None:
        current_seed = args.seed
        print(f"🔒 乱数シード固定: {current_seed}")
    else:
        current_seed = random.randint(0, 2**32 - 1)
        print(f"🔒 乱数シード（自動生成）: {current_seed}")
    random.seed(current_seed)
    # past_news_queue を事前に宣言（resume時に復元する可能性があるため）
    past_news_queue_restored = None
    
    if args.resume:
        if not os.path.exists(args.resume):
            print(f"エラー: 指定されたログファイルが見つかりません: {args.resume}")
            return
            
        with open(args.resume, "r", encoding="utf-8") as f:
            lines = f.readlines()
            if not lines:
                print("エラー: ログファイルが空です。")
                return
            
            if args.resume_turn is not None:
                # --- 指定ターンからの再開 ---
                target_data = None
                all_turn_data = []
                available_turns = []
                for line in lines:
                    data = json.loads(line)
                    all_turn_data.append(data)
                    available_turns.append(data["turn"])
                    if data["turn"] == args.resume_turn:
                        target_data = data
                
                if target_data is None:
                    print(f"エラー: ターン {args.resume_turn} がログファイルに見つかりません。")
                    print(f"利用可能なターン: {available_turns}")
                    return
                
                world_state = WorldState.model_validate(target_data["world_state"])
                
                # past_news_queue の復元（直近4ターン分）
                past_news_queue_restored = []
                for data in all_turn_data:
                    if data["turn"] <= args.resume_turn and data["turn"] > args.resume_turn - 4:
                        past_news_queue_restored.append(
                            data["world_state"].get("news_events", [])
                        )
                
                print(f"📂 ターン {args.resume_turn} の状態を復元しました。")
            else:
                # --- 従来動作: 最終ターンから再開 ---
                last_line = lines[-1]
                last_turn_data = json.loads(last_line)
                world_state = WorldState.model_validate(last_turn_data["world_state"])
            
        if args.resume_turn is not None:
            # resume-turn: 新しいセッションで新しいファイルに保存
            logger = SimulationLogger()
            logger.sys_log(f"[Reproducibility] 乱数シード: {current_seed}")
            logger.sys_log(f"[Resume] ターン {args.resume_turn} の状態から再開 (元ファイル: {args.resume})")
            
            # 元ファイルから指定ターンまでのデータを新しいJONLファイルにコピー
            with open(args.resume, "r", encoding="utf-8") as src:
                with open(logger.sim_log_file, "w", encoding="utf-8") as dst:
                    copied = 0
                    for line in src:
                        data = json.loads(line)
                        if data["turn"] <= args.resume_turn:
                            dst.write(line)
                            copied += 1
                    dst.flush()
                    os.fsync(dst.fileno())
            print(f"📋 元ファイルからターン 1〜{args.resume_turn} のデータ（{copied}行）を新しいログにコピーしました。")
        else:
            # 従来の --resume: 同じセッションに追記
            filename = os.path.basename(args.resume)
            if filename.startswith("sim_") and filename.endswith(".jsonl"):
                session_id = filename[4:-6]
            else:
                session_id = None
            logger = SimulationLogger(session_id=session_id)
            logger.sys_log(f"[Reproducibility] 乱数シード: {current_seed}")
    else:
        # システム初期化
        data_dir = os.path.join(os.path.dirname(__file__), "..", args.data_dir) if args.data_dir else None
        world_state = initialize_world(data_dir=data_dir)
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
    # past_news_queue の初期化（resume時に復元されている場合はそれを使用）
    past_news_queue = past_news_queue_restored if past_news_queue_restored is not None else []

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
        
        # ターン開始前の各国データをスナップショット保存（サマリー差分計算用）
        _country_snapshot = {
            name: {
                "economy":            c.economy,
                "military":           c.military,
                "approval_rating":    c.approval_rating,
                "intelligence_level": c.intelligence_level,
                "energy_reserve":     getattr(c, 'energy_reserve', None),
            }
            for name, c in world_state.countries.items()
        }

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
        # Agent呼出し前に政府予算を事前計算（process_turn内でも再計算されるが、
        # Agentプロンプトに正しい予算値を渡すために必要）
        DEBT_INTEREST_RATE = 0.01
        for country_name, country in world_state.countries.items():
            tax_revenue = country.economy * country.tax_rate
            interest_payment = country.national_debt * DEBT_INTEREST_RATE
            total_revenue = tax_revenue + country.tariff_revenue
            country.government_budget = max(0.0, total_revenue - interest_payment)

        n_countries = len(world_state.countries)
        logger.console.print(f"\n[bold yellow]⏳ {n_countries}カ国の首脳AIが戦略を立案中... しばらくお待ちください[/bold yellow]\n")
        actions, all_analyst_reports, all_task_logs = agent_system.generate_actions(world_state, past_news=past_news_queue)
        logger.console.print(f"[bold green]✅ 全国家の行動決定が完了しました[/bold green]\n")
        
        # 6. 各国の意思決定
        logger.display_section_header("3. 各国の意思決定")
        for country_name, action in actions.items():
            logger.display_agent_thoughts(country_name, action)

        # 7. エンジンによる世界の更新（判定フェーズ）
        world_state = engine.process_turn(actions)

        # v1-2: タスクエージェント制の海峡封鎖決定を処理（v1-2ブランチ固有、masterでは何もしない）
        if hasattr(engine, '_process_strait_blockade_actions'):
            engine._process_strait_blockade_actions(actions)
        
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
                is_private_summit = getattr(proposal, 'is_private', False)
                
                # 多国間会談の判定
                if proposal.participants and len(proposal.participants) >= 2:
                    # 多国間首脳会談
                    participant_states = {p: world_state.countries[p] for p in proposal.accepted_participants if p in world_state.countries}
                    if len(participant_states) < 2:
                        continue
                    
                    summit_news_result, full_summit_log = agent_system.run_multilateral_summit(proposal, participant_states, world_state, past_news=past_news_queue)
                    
                    participant_names = ", ".join(participant_states.keys())
                    if summit_news_result:
                        world_state.news_events.append(summit_news_result)
                        logger.display_category_events([summit_news_result], f"多国間首脳会談: {participant_names}", style="bold cyan", icon="🌐")
                    else:
                        logger.sys_log(f"[非公開多国間会談完了] {participant_names}")
                    
                    if not is_private_summit:
                        recent_summit_logs.append(full_summit_log)
                    
                    world_state.summit_logs.append({
                        "turn": world_state.turn,
                        "participants": list(participant_states.keys()),
                        "topic": proposal.topic,
                        "log": full_summit_log,
                        "is_private": is_private_summit
                    })
                else:
                    # 2国間首脳会談（既存ロジック）
                    ca = world_state.countries.get(proposal.proposer)
                    cb = world_state.countries.get(proposal.target)
                    if ca and cb:
                        if proposal.proposer not in world_state.countries or proposal.target not in world_state.countries:
                            continue
                        summit_news_result, full_summit_log = agent_system.run_summit(proposal, ca, cb, world_state, past_news=past_news_queue)
                        
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
                    
        # 9. メディア報道のみ表示（外交イベントはセクション5で表示済み）
        logger.display_section_header("9. メディア報道")
        logger.console.print("[dim]🗞️ 各国メディアがニュースを分析中...[/dim]")
        media_reports, media_modifiers = agent_system.generate_media_reports(world_state, actions, recent_summit_logs)
        world_state.news_events.extend(media_reports)
        # メディア報告のみ（🗞️ で始まる行）を抽出して表示
        media_only = [e for e in media_reports if e.strip().startswith("🗞️")]
        if media_only:
            logger.display_category_events(media_only, "📰 各国メディア報道", style="bold white", icon="🗞️")
        else:
            logger.console.print("[dim]今期、メディア報告はありません。[/dim]")

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
        logger.save_turn_log(world_state, safe_actions, analyst_reports=all_analyst_reports, task_logs=all_task_logs)
        
        # 10. ターン履歴の保存と時間進行
        past_news_queue.append(world_state.news_events.copy())
        if len(past_news_queue) > 4:
            past_news_queue.pop(0)
            
        engine.advance_time()
        
        # ターンサマリー（変化量テーブル）
        logger.display_section_header("📊 ターンサマリー")
        logger.display_turn_summary(_country_snapshot, world_state)

        logger.console.print("\n" + "═" * 70 + "\n")
        time.sleep(3)

    print("🏁 指定ターン数のシミュレーションが終了しました。")
    # 最後にシミュレーションの要約を自動生成 (コスト計算に含めるため先に実行)　-> サマリーは別途作成するためスキップ
    # try:
    #     if hasattr(logger, 'sim_log_file'):
    #         summary_info = summarizer.generate_summary(logger.sim_log_file, force=True)
    #         if summary_info and "usage" in summary_info:
    #             agent_system.token_usage["サマリー生成"] = {
    #                 "model": "gemini-2.5-flash",
    #                 "prompt_tokens": summary_info["usage"]["prompt_tokens"],
    #                 "candidates_token_count": summary_info["usage"]["candidates_token_count"],
    #                 "thoughts_token_count": summary_info["usage"].get("thoughts_token_count", 0)
    #             }
    # except Exception as e:
    #     print(f"Failed to auto-generate summary: {e}")

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
        t_tokens = usage.get("thoughts_token_count", 0)
        
        # 単価 (100万トークンあたり)
        # 思考トークン単価 (Gemini 2.5系: Promptと同額)
        if "gemini-3.1-pro" in model.lower():
            p_price, c_price, t_price = 2.00, 12.00, 2.00
        elif "gemini-2.5-pro" in model.lower():
            p_price, c_price, t_price = 1.25, 10.00, 1.25
        elif "gemini-2.5-flash-lite" in model.lower():
            p_price, c_price, t_price = 0.10, 0.40, 0.10
        elif "gemini-2.5-flash" in model.lower():
            p_price, c_price, t_price = 0.30, 2.50, 0.30
        else: # 分からないモデルのフォールバック (flash扱い)
            p_price, c_price, t_price = 0.30, 2.50, 0.30
            
        cat_cost = (p_tokens / 1_000_000 * p_price) + (c_tokens / 1_000_000 * c_price) + (t_tokens / 1_000_000 * t_price)
        total_cost += cat_cost
        
        if t_tokens > 0:
            report_line = f"- [{category}] {model}: Prompt {p_tokens} ({p_price}$/M), Output {c_tokens} ({c_price}$/M), Thinking {t_tokens} ({t_price}$/M) -> ${cat_cost:.4f}"
        else:
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
