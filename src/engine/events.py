import random
import uuid
from scipy.stats import skewnorm
from models import CountryState, GovernmentType, WarState, DisasterEvent, BreakthroughState, TradeState
from .constants import (
    GLOBAL_DISASTERS, NATIONAL_DISASTERS, EARTH_LAND_AREA,
    FRAGMENTATION_BASE_INSTABILITY_MULTIPLIER, FRAGMENTATION_SIZE_FACTOR_MULTIPLIER, FRAGMENTATION_TRADE_FACTOR_MULTIPLIER,
    FRAGMENTATION_INSTABILITY_THRESHOLD, FRAGMENTATION_COOLDOWN_TURNS,
    COUP_BUDGET_RATIO_MIN, COUP_BUDGET_RATIO_MAX
)

class EventsMixin:
    def process_pre_turn(self):
        """
        AIエージェントの意思決定前に、システムが自動で発生させるイベント（政権交代など）を処理する
        """
        self.events_this_turn = []
        self.sys_logs_this_turn = []
        self.pending_rebellions = []
        self.pending_elections = []
        
        # 反乱と選挙の進行（Alesina-Spolaore分裂判定もここに含まれる）
        # 分裂で新しい国が self.state.countries に追加されるため、list() でコピーして回す
        for name, country in list(self.state.countries.items()):
            # 【新設】クールダウン期間: 新政権発足後4ターン（1年）は分裂・クーデター免除
            # [学術的根拠] Polity IV regime durability coding: 政権の安定性は最低で1年の観測期間を要する
            if country.regime_duration <= FRAGMENTATION_COOLDOWN_TURNS:
                self.sys_logs_this_turn.append(f"[{name} クールダウン] regime_duration={country.regime_duration} <= {FRAGMENTATION_COOLDOWN_TURNS}。分裂・クーデター判定をスキップ。")
                continue
            
            # 支持率低下による反乱リスク
            if country.approval_rating < 30.0:
                country.rebellion_risk += 5.0
                self.log_event(f"⚠️ {name}の国内で政府への抗議運動が激化しています。(支持率{country.approval_rating:.1f}%)", involved_countries=[name])
            else:
                country.rebellion_risk = max(0.0, country.rebellion_risk - 2.0)
                
            # 体制別 イベント
            if country.government_type == GovernmentType.DEMOCRACY:
                # 民主主義の動的クーデター確率 (Alesina-Spolaore統合)
                if country.approval_rating <= 30.0:
                    # 30%で0、0%で100%になるクーデター確率
                    coup_prob = max(0.0, (30.0 - country.approval_rating) / 30.0 * 100.0)
                    if random.uniform(0.0, 100.0) < coup_prob:
                        self.log_event(f"⚠️ {name}で【政府機能麻痺】激しい暴動により民主政権が崩壊しました！(支持率{country.approval_rating:.1f}%)", involved_countries=[name, "global"])
                        self._handle_rebellion(name, country)
                        if name in self.state.countries and self.state.countries[name].turns_until_election is not None:
                            self.state.countries[name].turns_until_election = 16 # 米国の場合4年(16ターン)リセット
                        continue
                    
                if country.turns_until_election is not None:
                    country.turns_until_election -= 1
                    if country.turns_until_election <= 0:
                        self._handle_election(name, country)
                        if name in self.state.countries:
                            self.state.countries[name].turns_until_election = 16 # 米国の場合4年(16ターン)リセット
                        
            elif country.government_type == GovernmentType.AUTHORITARIAN:
                # 専制主義での反乱判定
                if country.rebellion_risk > random.uniform(20.0, 100.0):
                    self._handle_rebellion(name, country)
                    if name in self.state.countries:
                        self.state.countries[name].rebellion_risk = 0.0
                    
        # プレターンイベントでリストを上書き（前ターンのログをここでクリア）
        self.state.news_events = self.events_this_turn.copy()

    def _process_random_events(self):
        """災害イベントおよび技術革新の発生を処理する"""
        # 技術革新の進行更新
        for bt in self.state.active_breakthroughs:
            if not bt.spread_globally:
                bt.turns_active += 1
                if bt.turns_active >= 4:
                    bt.spread_globally = True
                    self.log_event(f"💡 【技術波及】{bt.origin_country}発の技術革新「{bt.name}」が世界中に普及し、世界経済の底上げに寄与し始めました。", involved_countries=[bt.origin_country, "global"])
        
        # ------------- 災害 -------------
        # 1. 世界規模災害
        
        for name, prob, min_dmg, max_dmg in GLOBAL_DISASTERS:
            if random.random() < prob:
                # 歪正規分布を用いてダメージを決定。a=4は正の歪み（低い値が多く、稀に高い値）
                # scale = レンジ幅の15%: min_dmg付近に集中し、max_dmgに到達する確率を著しく低く抑える
                # max_dmg/min_dmgでハードキャップ: 定数で定義した最大値は絶対に超えない
                a = 4
                scale = (max_dmg - min_dmg) * 0.15
                damage = skewnorm.rvs(a, loc=min_dmg, scale=scale)
                damage = min(max_dmg, max(min_dmg, damage))
                new_event = DisasterEvent(turn=self.state.turn, name=name, damage_percent=damage)
                self.state.disaster_history.append(new_event)
                
                # 人口減少処理を追加 (被害比例型)
                total_pop_loss = 0.0
                for c in self.state.countries.values():
                    pop_loss = c.population * (damage / 100.0) * 0.05 # 経済被害率の5%相当が犠牲に
                    c.population = max(0.1, c.population - pop_loss)
                    total_pop_loss += pop_loss
                
                self.log_event(f"🚨 【世界規模の厄災発生】{name}が発生！世界全体で推定 -{damage:.1f}% の経済ダメージと、約 {total_pop_loss:.1f}M（百万人）の犠牲者による大混乱が起きています。", involved_countries=["global"])
                break # 一度に複数起きる確率は無視する（処理軽減）
                
        # 2. 国規模災害
        
        for country_name in list(self.state.countries.keys()):
            country = self.state.countries[country_name]
            for name, prob, min_dmg, max_dmg in NATIONAL_DISASTERS:
                actual_prob = prob
                if "火山噴火" in name or "大噴火" in name:
                    area_ratio = country.area / EARTH_LAND_AREA
                    actual_prob = prob * area_ratio
                    
                if random.random() < actual_prob:
                    # 歪正規分布を用いてダメージを決定。a=4は正の歪み（低い値が多く、稀に高い値）
                    # scale = レンジ幅の15%: min_dmg付近に集中し、max_dmgに到達する確率を著しく低く抑える
                    # max_dmg/min_dmgでハードキャップ: 定数で定義した最大値は絶対に超えない
                    a = 4
                    scale = (max_dmg - min_dmg) * 0.15
                    damage = skewnorm.rvs(a, loc=min_dmg, scale=scale)
                    damage = min(max_dmg, max(min_dmg, damage))
                    new_event = DisasterEvent(turn=self.state.turn, country=country_name, name=name, damage_percent=damage)
                    self.state.disaster_history.append(new_event)
                    
                    # 人口減少処理 (被害比例型)
                    pop_loss = country.population * (damage / 100.0) * 0.1 # 国家災害は局所的な分、比率を高め(10%)に
                    country.population = max(0.1, country.population - pop_loss)
                    
                    self.log_event(f"🌪️ 【国家災害発生】{country_name}で{name}が直撃し、-{damage:.1f}% に相当する経済ダメージと約 {pop_loss:.2f}M 人の犠牲者を出しました！", involved_countries=[country_name, "global"])
                    break # 同一国内で複数同時被災は無視
                    
        # ------------- 技術革新 -------------
        # 技術革新は各国 2.0%の確率で発生。ただし進行中は同国で連続発生しづらくする
        for country_name in list(self.state.countries.keys()):
            if any(bt.origin_country == country_name and not bt.spread_globally for bt in self.state.active_breakthroughs):
                continue # すでに独占的な技術革新中
                
            if random.random() < 0.020:
                new_bt = BreakthroughState(
                    origin_country=country_name, 
                    name=f"（AI生成待ちの技術革新 - T{self.state.turn}）", 
                    turns_active=0, 
                    spread_globally=False
                )
                self.state.active_breakthroughs.append(new_bt)
                self.sys_logs_this_turn.append(f"[{country_name}] 技術革新フラグが立ちました")

    def _handle_election(self, country_name: str, country: CountryState):
        """
        民主主義国家の大統領選挙の論理を処理する
        """
        roll = random.uniform(0.0, 100.0)
        self.log_event(f"🗳️ {country_name}で国家元首の総選挙が実施されました。(現在の与党支持率: {country.approval_rating:.1f}%)", involved_countries=[country_name])
        
        if roll <= country.approval_rating:
            # 再選
            self.log_event(f"✅ 【選挙結果】{country_name}の現政権が過半数の信任を得て再選を果たしました！", involved_countries=[country_name])
            self.sys_logs_this_turn.append(f"[{country_name} 選挙] 乱数 {roll:.1f} <= 支持率 {country.approval_rating:.1f} により再選")
        else:
            # 敗北（政権交代）
            self.log_event(f"🔄 【政権交代】{country_name}の選挙で現政権が敗北し、新たな指導者が選出されました。", involved_countries=[country_name])
            self.sys_logs_this_turn.append(f"[{country_name} 選挙] 乱数 {roll:.1f} > 支持率 {country.approval_rating:.1f} により落選")
            
            # 敗北時の新政権の支持率: 100 - 旧支持率/2 にリセット
            new_approval = max(0.0, min(100.0, 100.0 - country.approval_rating / 2.0))
            country.approval_rating = new_approval
            self.sys_logs_this_turn.append(f"[{country_name} 新政権] 新たなハネムーン期間として支持率が {new_approval:.1f}% にリセットされました。")
            country.regime_duration = 0  # 選挙での政権交代によりリセット

    def _handle_rebellion(self, country_name: str, country: CountryState):
        """国家崩壊（クーデター・革命）の処理。Alesina-Spolaoreモデルに基づく分裂判定を含む"""
        
        # --- 1. 分裂(Fragmentation)の判定 ---
        
        # 基礎不安定性 (どれだけマイナスまで支持率が振り切れていたか等の不満度。0-100程度)
        base_instability = max(0.0, 30.0 - country.approval_rating) + min(100.0, country.rebellion_risk)
        
        # 【新設】不安定性しきい値ゲート: base_instability < 40 の場合、分裂判定をスキップ
        # [学術的根拠] Goldstone et al. (2010) Political Instability Task Force:
        # 国家崩壊は単一要因ではなく、複数の不安定要因が同時に蓄積した場合にのみ発生する
        if base_instability < FRAGMENTATION_INSTABILITY_THRESHOLD:
            self.sys_logs_this_turn.append(
                f"[{country_name} 分裂判定スキップ] base_instability={base_instability:.1f} < "
                f"閾値{FRAGMENTATION_INSTABILITY_THRESHOLD}。通常のクーデターに進行。"
            )
        else:
            # 面積（国土規模）による多様性/異質性コスト（Alesina-Spolaore: サイズによる分裂圧力）
            # ※ここでは面積の絶対値をベースに係数をかける（最大+30%程度）
            size_factor = min(30.0, country.area * FRAGMENTATION_SIZE_FACTOR_MULTIPLIER)
            
            # 自由貿易の恩恵（Alesina-Spolaore: 貿易網が発達しているほど小国が生き返りやすいため分裂圧力増）
            # 対象国が結んでいる貿易協定の数をカウント
            trade_count = sum(1 for t in self.state.active_trades if t.country_a == country_name or t.country_b == country_name)
            trade_factor = trade_count * FRAGMENTATION_TRADE_FACTOR_MULTIPLIER
            
            # 分裂確率 P_frag
            p_frag = min(100.0, (base_instability * FRAGMENTATION_BASE_INSTABILITY_MULTIPLIER) + size_factor + trade_factor)
            
            # 民主主義の場合は武力弾圧を行わないため相対的に分裂のハードルが低い(平和的独立)
            if country.government_type == GovernmentType.DEMOCRACY:
                p_frag += 10.0
            else: # 専制主義は流血を辞さず抑え込むため分裂発生率はやや低い
                p_frag -= 10.0
                
            p_frag = max(0.0, min(100.0, p_frag))
            
            is_fragmentation = random.uniform(0.0, 100.0) < p_frag
            
            if is_fragmentation:
                self._execute_fragmentation(country_name, country, base_instability)
                return

        # --- 2. 通常のクーデター（政権交代のみ） ---
        self.log_event(f"🔄 【政権交代】{country_name}にてクーデターが成功し、新政府が樹立されました！", involved_countries=[country_name, "global"])
        
        # 【Option C】クーデター後の経済の立て直し（基本GDPのリセット＝悪循環の底打ち）
        # 旧政権の負債や非効率さをリセットし、新たなベースラインを設定する。
        # クーデターまでの経済ダメージは維持するが、そこからの再出発を保障する。
        # （ここではGDP自体を底上げするのではなく、経済成長ペナルティをリセットする意味合いで、
        #   政府予算の強制補充や税率の一時的適正化を行う）
        country.economy = max(10.0, country.economy * 0.9) # 内戦による経済ダメージ（10%減）
        country.military = max(0.5, country.economy * 0.1)  # 軍事力をGDPの10%にリセット
        coup_budget_ratio = random.uniform(COUP_BUDGET_RATIO_MIN, COUP_BUDGET_RATIO_MAX)
        country.government_budget = country.economy * coup_budget_ratio # 緊急予算の確保（クーデター後の税収低下を反映）
        country.tax_rate = 0.3 # 標準税率へ一旦リセット
        
        # 政府支持率の反転 (100% - 旧支持率) 
        # 低い支持率で倒れた政府の交代劇であるほど、初期の熱狂（ハネムーン期間）が高くなる
        country.approval_rating = max(50.0, 100.0 - country.approval_rating)
        country.rebellion_risk = 0.0
        country.regime_duration = 0 # クーデター成立によりリセット
        
        # 専制・独裁は民主化するかどうかの分岐
        if country.government_type == GovernmentType.AUTHORITARIAN:
            if random.random() < 0.3: # 30%で民主化
                country.government_type = GovernmentType.DEMOCRACY
                country.turns_until_election = 16
                self.log_event(f"🕊️ {country_name}は民主化宣言を行いました！新政権は初の自由選挙に向けた準備を進めています。", involved_countries=[country_name, "global"])
            else:
                self.log_event(f"🛡️ {country_name}では新たな軍事政権が実権を握り、引き続き強権的な統治が続きます。", involved_countries=[country_name, "global"])
        else:
            # 民主主義が崩壊した場合、軍事政権化する可能性
            if random.random() < 0.4:
                country.government_type = GovernmentType.AUTHORITARIAN
                country.turns_until_election = None
                self.log_event(f"⚔️ {country_name}の混乱に乗じて軍部が蜂起！民主政権は崩壊し、専制主義国家への道を歩み始めました。", involved_countries=[country_name, "global"])
            else:
                self.log_event(f"🗳️ {country_name}で臨時政府が樹立され、早期の総選挙が約束されました。", involved_countries=[country_name])
                country.turns_until_election = 4
        
        # イデオロギーの刷新（非同期処理のため、メインループの「AIプロンプト」フェーズでAgentが思考する。
        # ここではフラグだけを立て、ログは出さない。プロンプトへの渡し方はagent.py側の責任とする）
        country.ideology = f"[新政権樹立フェーズ] 旧政権({country.ideology})を打倒した新政府の指針を策定中"
        
        # 秘密計画の破棄とターゲットのリセット
        country.hidden_plans = "政権交代により過去の計画はすべて白紙撤回された。新たな国家戦略を立案せよ。"

        # 案C: クーデター時の「死のループ」を防ぐため、旧政権の負の遺産・基準となるペナルティをリセット
        country.national_debt = 0.0
        country.trade_deficit_counter = 0
        country.last_turn_nx = 0.0
        country.rebellion_risk = 0.0
        country.intelligence_level = 0.0  # 諜報組織も崩壊・リセット
        
        # 【新設】影響力介入オークションの登録
        # [学術的根拠] Morgenthau (1948): 政変によるパワー・バキュームは周辺大国の介入を誘発する。
        # 歴史的実例: ウクライナ政変(2014)→ロシアのクリミア介入、エジプト政変(2013)→サウジ/UAE介入
        # 分裂版と異なり、領土併合ではなく「依存度の上昇」（影響力圏への取り込み）が結果となる。
        self.state.pending_influence_auctions.append({
            "target_country": country_name,
            "trigger": "coup",
            "target_economy": country.economy,  # 経済力が防衛ベット（GDPが高い国ほど外部介入に強い）
        })
        self.sys_logs_this_turn.append(
            f"[影響力介入オークション登録] {country_name}で政変発生。"
            f"GDP={country.economy:.1f}で外部介入に抵抗。各国のベットを待機中。"
        )
        
        self.pending_rebellions.append(country_name)

    def _execute_fragmentation(self, old_name: str, old_country: CountryState, base_instability: float):
        """国家分裂の実行ロジック。最大100%の転覆(乗っ取り)を含む"""
        
        # 1. 離脱(奪取)されるリソース割合の決定
        # 不満度(base_instability: 0~200程度) が高いほど、丸ごとひっくり返る可能性大
        # 通常は20-40%、最悪のクーデターなら70-100%
        mean_split_ratio = min(95.0, 20.0 + (base_instability * 0.4))
        split_ratio = max(10.0, min(100.0, random.gauss(mean_split_ratio, 10.0))) / 100.0
        
        is_overthrow = split_ratio > 0.85 # 85%以上持っていかれたら事実上の国家転覆（旧体制が辺境に追いやられる）
        
        if is_overthrow:
            self.log_event(f"🧨 【国家転覆】度重なる失政と圧政への怒りが爆発！{old_name}におけるクーデターは全土規模の革命へと発展し、国家がひっくり返りました！(国土奪取率: {split_ratio:.1%})", involved_countries=[old_name, "global"])
        else:
            self.log_event(f"💥 【国家分裂】{old_name}にて分離独立運動が激化！政府のコントロールを外れ、一部地域が独立を宣言しました！(離脱率: {split_ratio:.1%})", involved_countries=[old_name, "global"])
            
        # 2. Agentによる新国家名とイデオロギーの生成
        from agent import AgentSystem # ここで動的インポート
        dummy_agent = AgentSystem(None) # 生成用のダミーインスタンス
        
        # ログから市民の不満を探す
        sns_logs = self.turn_sns_logs.get(old_name, [])
        new_name, new_ideology = dummy_agent.generate_fragmentation_profile(old_name, sns_logs)
        
        # （重要）名前の重複チェック
        if new_name == old_name or new_name in self.state.countries:
            new_name = f"新{old_name}共和国"
            
        # 3. リソースの分割
        new_economy = max(1.0, old_country.economy * split_ratio)
        new_military = max(0.5, old_country.military * split_ratio)
        new_area = max(1.0, old_country.area * split_ratio)
        new_debt = old_country.national_debt * split_ratio
        new_population = max(0.1, old_country.population * split_ratio)
        
        # 人的インフラ（教育）の引き継ぎ（無減衰で100%引き継ぎ）
        new_hci = old_country.human_capital_index
        new_initial_hci = old_country.initial_human_capital_index
        new_mys = old_country.mean_years_schooling
        # 組織インフラ（諜報）の分割
        new_intelligence = max(0.0, old_country.intelligence_level * split_ratio)
        
        old_country.economy = max(1.0, old_country.economy - new_economy)
        old_country.military = max(0.5, old_country.military - new_military)
        old_country.area = max(1.0, old_country.area - new_area)
        old_country.national_debt = max(0.0, old_country.national_debt - new_debt)
        old_country.population = max(0.1, old_country.population - new_population)
        old_country.intelligence_level = max(0.0, old_country.intelligence_level - new_intelligence)
        
        if is_overthrow:
             # 事実上の乗っ取りなので新国家が旧体制の借金を帳消し（デフォルト）にすることが多い
             new_debt *= 0.2
             
        # 政体の反転/決定
        new_gov_type = GovernmentType.DEMOCRACY if old_country.government_type == GovernmentType.AUTHORITARIAN else GovernmentType.AUTHORITARIAN
        if random.random() < 0.2: # 20%で偶然同じ政体になる（内ゲバ）
            new_gov_type = old_country.government_type

        # 4. 新国家オブジェクトの生成
        new_country = CountryState(
            name=new_name,
            economy=new_economy,
            military=new_military,
            approval_rating=80.0, # 独立初期の熱狂
            government_type=new_gov_type,
            ideology=new_ideology,
            press_freedom=0.8 if new_gov_type == GovernmentType.DEMOCRACY else 0.2,
            target_country=old_name, # 当面は旧国を強く意識
            area=new_area,
            population=new_population,
            initial_population=new_population,
            human_capital_index=new_hci,
            initial_human_capital_index=max(1.0, new_initial_hci), # 0割りを防ぐ
            mean_years_schooling=new_mys,
            intelligence_level=new_intelligence
        )
        new_country.national_debt = new_debt
        if new_gov_type == GovernmentType.DEMOCRACY:
            new_country.turns_until_election = 16
            
        # 世界に追加
        self.state.countries[new_name] = new_country
        
        # 【新設】パワー・バキューム・オークションを登録 (Tullock CSF方式)
        # [学術的根拠] Tullock (1980), Hirshleifer (1989): コンテスト成功関数。
        # 分裂で誕生した新国家に対し、各大国がベットする軍事介入オークションを開催。
        # 新国家は自国の全軍事力で独立を防衛する。
        self.state.pending_vacuum_auctions.append({
            "new_country": new_name,
            "old_country": old_name,
            "new_military": new_country.military,
        })
        self.sys_logs_this_turn.append(
            f"[パワー・バキューム] {new_name}(旧:{old_name}) が誕生。"
            f"軍事力{new_country.military:.1f}で独立防衛。各国のベットを待機中。"
        )
        
        # 5. 外交関係（平和的独立か、内戦か）
        if old_country.government_type == GovernmentType.DEMOCRACY:
            # Velvet Divorce（平和的独立）
            self.log_event(f"🤝 民主的な手続き（住民投票等）により、{new_name}の独立が平和裏に承認されました。旧体制との間に武力衝突はありません。", involved_countries=[old_name, new_name, "global"])
            old_country.approval_rating = max(30.0, old_country.approval_rating) # やや落ち着く
        else:
            # Secessionist War（内戦突入）
            self.log_event(f"⚔️ 【独立戦争勃発】{old_name}の独裁体制は独立を許さず、直ちに{new_name}に対する武力鎮圧を開始！凄惨な内戦に突入しました！", involved_countries=[old_name, new_name, "global"])
            war = WarState(
                aggressor=old_name,
                defender=new_name,
                target_occupation_progress=0.0,
                aggressor_commitment_ratio=0.80,  # 武力鎮圧のため高め
                defender_commitment_ratio=0.90     # 独立防衛のため全力投入
            )
            self.state.active_wars.append(war)

        # 6. 貿易協定の引き継ぎ (Fidrmuc & Fidrmuc 2003: 分裂後も貿易はゼロにならない)
        # 旧母国が持っていた貿易協定を新国家にも適用
        old_trades = [t for t in self.state.active_trades if t.country_a == old_name or t.country_b == old_name]
        inherited_partners = []
        for t in old_trades:
            partner = t.country_b if t.country_a == old_name else t.country_a
            if partner != new_name:  # 自分自身との貿易は除外
                self.state.active_trades.append(TradeState(country_a=new_name, country_b=partner))
                inherited_partners.append(partner)

        # 平和的離別の場合は旧母国との貿易協定も付与
        if old_country.government_type == GovernmentType.DEMOCRACY:
            self.state.active_trades.append(TradeState(country_a=old_name, country_b=new_name))
            inherited_partners.append(old_name)

        if inherited_partners:
            self.log_event(
                f"📊 【残留貿易】{new_name}は{', '.join(inherited_partners)}との暫定的な貿易関係を引き継ぎました",
                involved_countries=[new_name] + inherited_partners
            )
            
        # もし100%乗っ取られて旧政権のリソースが微小（1.0未満）になった場合、事実上の滅亡処理
        if old_country.economy <= 1.5 or old_country.military <= 1.0:
             self._handle_defeat(old_name, new_name)
             self.log_event(f"☠️ 【旧体制消滅】リソースのほぼ全てを掌握した{new_name}により、旧体制({old_name})は完全に歴史から抹消されました。", involved_countries=[old_name, new_name, "global"])
