from typing import List
from models import WorldState, CountryState

def build_common_context(country_name: str, country_state: CountryState, world_state: WorldState, past_news: List[str] = None, role_name: str = "最高指導者（首脳）") -> str:
    """すべてのエージェント（大統領、各大臣）が共有する基本ステータスとニュースコンテキストを構築する"""
    
    my_info = (
        f"あなたは「{country_name}」の{role_name}です。\n"
        f"あなたの国の体制は '{country_state.government_type.value}'、現在のペルソナ・イデオロギーは '{country_state.ideology}' です。\n"
        f"---現在のステータス---\n"
        f"総人口(Population): {country_state.population:.1f}百万人\n"
        f"1人当たりGDP: {(country_state.economy / max(0.1, country_state.population)):.1f} (この数値が低下・停滞すると暴動リスクが激増します)\n"
        f"経済力(総GDP): {country_state.economy:.1f}\n"
        f"軍事力: {country_state.military:.1f}\n"
        f"諜報レベル: {country_state.intelligence_level:.1f}（高いほど諜報活動の成功率が向上し、敵の諜報を返り討ちやすくなる）\n"
        f"現在の税率: {country_state.tax_rate:.1%}\n"
        f"政府予算(税収 - 利払い): {country_state.government_budget:.1f}\n"
        f"直近の貿易収支(NX): {country_state.last_turn_nx:+.1f} (マイナスは赤字流出を意味)\n"
        f"国家債務(National Debt): {country_state.national_debt:.1f} (GDP比 {(country_state.national_debt / max(0.1, country_state.economy)):.1%}。高すぎると経済成長に深刻なペナルティ)\n"
        f"国民の支持率: {country_state.approval_rating:.1f}% (30%未満で危険)\n"
        f"報道の自由度: {country_state.press_freedom:.3f} (0.0-1.0。低いほど情報統制されるが不満が高まる)\n"
        f"教育・人的資本レベル: {country_state.education_level:.2f} (内生的成長理論に基づき、蓄積されるほどGDPを押し上げる能力が高まる)\n"
    )
    
    if country_state.turns_until_election is not None:
         my_info += f"次回の選挙まで残り: {country_state.turns_until_election}ターン (支持率が低いと落選します)\n"
    else:
         my_info += f"現在の反乱リスク: {country_state.rebellion_risk:.1f}% (支持率が低いと高まります)\n"
    
    if country_state.stat_history:
         my_info += "---過去のステータス推移（直近4ターン）---\n"
    
    carrying_capacity = max(10.0, country_state.area * 150.0)
    density_ratio = country_state.population / carrying_capacity
    gdp_per_capita = country_state.economy / max(0.1, country_state.population)
    
    my_info += f"現在の1人当たりGDP: {gdp_per_capita:.2f} (⚠️ 0.8未満は絶対的貧困となり、年間5%以上の急落とともに暴動による致命的な支持率低下を招きます)\n"
    my_info += f"現在の人口密度（環境収容力に対する割合）: {density_ratio*100:.1f}%\n"
    if density_ratio > 0.8:
        my_info += "【⚠️人口過密警告】人口が環境収容力（国土の限界）に近づいており、インフラ逼迫による支持率低下（過密ペナルティ）のリスクが高まっています。福祉カットや経済・教育投資を通じた（少子化の罠の促進）による間接的な人口抑制を検討してください。\n"
    my_info += "\n"     
    for s in country_state.stat_history:
        my_info += f" T{s['turn']}: 経済力 {s['economy']}, 軍事力 {s['military']}, 支持率 {s['approval_rating']}%\n"
    
    if country_state.dependency_ratio:
        deps_str = ", ".join([f"{k}: {v*100:.1f}%" for k, v in country_state.dependency_ratio.items()])
        my_info += f"現在の対外経済依存度（60%超過で国家主権喪失・属国化）: {deps_str}\n"

    if country_state.suzerain:
        my_info += f"\n【🚨緊急警告🚨】あなたの国は現在 {country_state.suzerain} の「属国（傀儡）」に成り下がっています。\n"
        my_info += "独自の外交権はシステムによって実質的に凍結されており、いかなる外交・軍事アクションも宗主国の意向により無効化されます。現状では内政に専念し、機が熟すか宗主国が滅亡するのを待つ以外に道はありません。\n\n"

    if country_state.private_messages:
        my_info += "---🚨【他国からの極秘通信】🚨---\n"
        for pmsg in country_state.private_messages:
            my_info += f"{pmsg}\n"
        my_info += "（※これらは第三国には一切見えない非公開情報です）\n\n"

    # 保留中の援助申請（翌ターン承認制）
    pending_aids_for_me = [p for p in world_state.pending_aid_proposals if p.target == country_name]
    if pending_aids_for_me:
        my_info += "---💰【保留中の援助申請（要承認）】💰---\n"
        my_info += "以下の国から援助の申し出があります。diplomatic_policiesの該当国に対して `aid_acceptance_ratio`（0.0〜1.0）を設定し、受入率を決定してください。\n"
        my_info += "（デフォルト1.0=全額受入。0.0=全拒否。0.3=3割のみ受入等。依存度の上昇や戦略的リスクを考慮して判断してください）\n"
        for p in pending_aids_for_me:
            my_info += f"  - {p.donor}: 経済援助 {p.amount_economy:.1f}, 軍事援助 {p.amount_military:.1f}\n"
        my_info += "\n"

    my_info += f"あなたの脳内（非公開の計画など）には次のような情報があります: '{country_state.hidden_plans}'\n\n"
    
    my_info += "---🗄️【国家情報局(RAG) 過去の重要記録アクセス機能】🗄️---\n"
    my_info += "あなたは関数呼び出し(Function Calling)により `search_historical_events(query)` ツールを使用可能です。\n"
    my_info += "【重要】現在の意思決定において、過去の事件の詳細、他国との過去の密約、特定の技術革新の履歴など、文脈上不足している重要な情報がある場合は、**推論を決定する前に必ずこのツールを呼び出して情報を検索してください。**\n\n"
    
    active_trades = world_state.active_trades if hasattr(world_state, 'active_trades') else []
    my_trades = []
    for t in active_trades:
        if t.country_a == country_name:
            my_trades.append(t.country_b)
        elif t.country_b == country_name:
            my_trades.append(t.country_a)
    
    if my_trades:
        my_info += f"---締結中の貿易協定---\n貿易相手国: {', '.join(my_trades)} (相互に経済効率化ボーナスが発生し、経済構造の差に応じて貿易収支が発生します)\n\n"

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
        
    other_info = "---世界の状況---\n"
    other_info += f"現在は {world_state.year}年 第{world_state.quarter}四半期 です。\n"
    
    if len(world_state.countries) <= 1:
        other_info += "\n【重要】他国はすべて滅亡または自国に併合され、世界はあなたの国によって完全に統一されました。\n"
        other_info += "新たな仮想敵を設定する必要はありません。以後は世界の安定と繁栄、自国民の幸福度向上に注力した内政戦略を構築してください。\n\n"
    else:
        for p_name, p_state in world_state.countries.items():
            if p_name == country_name: continue
            
            from models import RelationType
            rel = world_state.relations.get(country_name, {}).get(p_name, RelationType.NEUTRAL)
            rel_str = rel.value if hasattr(rel, 'value') else str(rel)
            
            war_info = ""
            for w in world_state.active_wars:
                if (w.aggressor == country_name and w.defender == p_name) or (w.aggressor == p_name and w.defender == country_name):
                    war_info = f" [!交戦中!] 占領進捗率: {w.target_occupation_progress:.1f}%"
            
            suzerain_info = f", 宗主国={p_state.suzerain}" if getattr(p_state, 'suzerain', None) else ""
            
            other_info += (
                f"- {p_name} ({p_state.government_type.value}): "
                f"経済力={p_state.economy:.1f}, "
                f"軍事力={p_state.military:.1f}, "
                f"諜報力={p_state.intelligence_level:.1f}, "
                f"関係={rel_str}{war_info}{suzerain_info}\n"
            )
        
    news_info = ""
    if past_news:
        news_info = "---直近1年(4四半期)の世界のニュース---\n"
        for i, turn_news in enumerate(past_news):
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
        
    return my_info + other_info + news_info
