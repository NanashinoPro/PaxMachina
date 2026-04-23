from typing import List, Optional
from models import WorldState, CountryState, RelationType


def build_analyst_prompt(
    country_name: str,
    country_state: CountryState,
    world_state: WorldState,
    target_country_name: str,
    past_news: List = None,
    use_real_stats: bool = False,
) -> str:
    """統合型分析官のプロンプトを構築する。
    
    対象国1国に対して、外交・軍事・経済の3観点から包括的な分析レポートを生成する。
    このレポートは外務大臣・防衛大臣・財務大臣の3者に共有される。
    use_real_stats=True の場合、諜報成功により真値が取得されており、偽装値との比較を含む。
    """

    target_state = world_state.countries.get(target_country_name)
    if not target_state:
        return ""
    
    # ---- 自国の基本情報（簡潔版）----
    my_info = (
        f"あなたは「{country_name}」の情報分析官です。\n"
        f"自国の体制: {country_state.government_type.value}\n"
        f"自国の経済力(GDP): {country_state.economy:.1f}, 軍事力: {country_state.military:.1f}, "
        f"諜報レベル: {country_state.intelligence_level:.1f}\n"
        f"国民の支持率: {country_state.approval_rating:.1f}%\n"
        f"直近の貿易収支(NX): {country_state.last_turn_nx:+.1f}\n"
        f"国家債務(GDP比): {(country_state.national_debt / max(0.1, country_state.economy)):.1%}\n\n"
    )
    
    # ---- 対象国の詳細情報 ----
    rel = world_state.relations.get(country_name, {}).get(target_country_name, RelationType.NEUTRAL)
    rel_str = rel.value if hasattr(rel, 'value') else str(rel)
    
    # 戦争情報
    war_info = ""
    for w in world_state.active_wars:
        if (w.aggressor == country_name and w.defender == target_country_name) or \
           (w.aggressor == target_country_name and w.defender == country_name):
            if w.aggressor == country_name:
                role = "攻撃側"
                my_commit = w.aggressor_commitment_ratio
                enemy_commit = w.defender_commitment_ratio
            else:
                role = "防衛側"
                my_commit = w.defender_commitment_ratio
                enemy_commit = w.aggressor_commitment_ratio
            war_info = (
                f"\n⚠️ 【交戦中({role})】占領進捗率: {w.target_occupation_progress:.1f}%"
                f" | 自国投入率: {my_commit:.0%}, 敵国投入率: {enemy_commit:.0%}\n"
            )
    
    # 貿易関係
    trade_info = ""
    for t in world_state.active_trades:
        if t.country_a == country_name and t.country_b == target_country_name:
            trade_info = f"貿易協定: 締結中 (自国関税={t.tariff_a_to_b:.1%}, 対象国関税={t.tariff_b_to_a:.1%})"
        elif t.country_b == country_name and t.country_a == target_country_name:
            trade_info = f"貿易協定: 締結中 (自国関税={t.tariff_b_to_a:.1%}, 対象国関税={t.tariff_a_to_b:.1%})"
    if not trade_info:
        trade_info = "貿易協定: なし"
    
    # 制裁関係
    sanction_info = ""
    for s in world_state.active_sanctions:
        if s.imposer == country_name and s.target == target_country_name:
            sanction_info += f"自国→対象国への経済制裁: 発動中\n"
        elif s.imposer == target_country_name and s.target == country_name:
            sanction_info += f"対象国→自国への経済制裁: 発動中\n"
    
    # 属国関係
    suzerain_info = ""
    if getattr(target_state, 'suzerain', None):
        suzerain_info = f"宗主国: {target_state.suzerain}\n"
    if getattr(country_state, 'suzerain', None) == target_country_name:
        suzerain_info += f"⚠️ 自国は{target_country_name}の属国です\n"
    
    # 依存度
    dependency_info = ""
    if country_state.dependency_ratio and target_country_name in country_state.dependency_ratio:
        dep = country_state.dependency_ratio[target_country_name]
        dependency_info = f"自国の対{target_country_name}経済依存度: {dep*100:.1f}%\n"
    if target_state.dependency_ratio and country_name in target_state.dependency_ratio:
        dep = target_state.dependency_ratio[country_name]
        dependency_info += f"{target_country_name}の対自国経済依存度: {dep*100:.1f}%\n"
    
    # 保留中の援助
    pending_aid_info = ""
    for p in world_state.pending_aid_proposals:
        if p.donor == target_country_name and p.target == country_name:
            pending_aid_info += f"保留中の援助: {target_country_name}→自国 (経済{p.amount_economy:.1f}, 軍事{p.amount_military:.1f})\n"
        elif p.donor == country_name and p.target == target_country_name:
            pending_aid_info += f"保留中の援助: 自国→{target_country_name} (経済{p.amount_economy:.1f}, 軍事{p.amount_military:.1f})\n"
    
    # 情報偽装: 諜報成功(use_real_stats=True)なら真値、失敗なら偽装値を使用
    real_gdppc   = target_state.economy / max(0.1, target_state.population)
    disp_econ    = target_state.reported_economy           if (target_state.reported_economy           is not None and not use_real_stats) else target_state.economy
    disp_mil     = target_state.reported_military          if (target_state.reported_military          is not None and not use_real_stats) else target_state.military
    disp_intel   = target_state.reported_intelligence_level if (target_state.reported_intelligence_level is not None and not use_real_stats) else target_state.intelligence_level
    disp_approval= target_state.reported_approval_rating   if (target_state.reported_approval_rating   is not None and not use_real_stats) else target_state.approval_rating
    disp_gdppc   = target_state.reported_gdp_per_capita    if (target_state.reported_gdp_per_capita    is not None and not use_real_stats) else real_gdppc

    # 諜報成功時: 偽装が存在するフィールドを全て比較した機密ヘッダーを生成
    deception_intel_header = ""
    if use_real_stats:
        deception_details = []
        _checks = [
            ("経済力",        target_state.reported_economy,            target_state.economy,            ""),
            ("軍事力",        target_state.reported_military,           target_state.military,           ""),
            ("支持率",        target_state.reported_approval_rating,    target_state.approval_rating,    "%"),
            ("諜報力",        target_state.reported_intelligence_level, target_state.intelligence_level, ""),
            ("1人当たりGDP", target_state.reported_gdp_per_capita,     real_gdppc,                      ""),
        ]
        for label, rep_val, true_val, unit in _checks:
            if rep_val is not None:
                dev = abs(rep_val - true_val) / max(1.0, abs(true_val)) * 100.0
                deception_details.append(f"{label}: 公式={rep_val:.1f}{unit} / 実際={true_val:.1f}{unit} (乖離={dev:.1f}%)")
        if deception_details:
            deception_intel_header = (
                f"\n⚠️【機密情報：諜報成功】対象国「{target_country_name}」の公式発表値に偽装が発見されました！\n"
                + "\n".join(deception_details) + "\n"
                + "以下の数値は真値を反映しています。この情報は自国のみが知る極秘情報です。大臣には必ず共有してください。\n"
            )
        else:
            deception_intel_header = (
                f"\n✅【諜報成功（偽装なし確認）】対象国「{target_country_name}」の公式発表値に偽装の証拠は発見されませんでした。\n"
            )

    target_info = (
        f"---分析対象国: {target_country_name} の詳細情報---\n"
        f"{deception_intel_header}"
        f"政治体制: {target_state.government_type.value}\n"
        f"イデオロギー: {target_state.ideology}\n"
        f"経済力(GDP): {disp_econ:.1f}\n"
        f"1人当たりGDP: {disp_gdppc:.1f}\n"
        f"軍事力: {disp_mil:.1f}\n"
        f"諜報レベル: {disp_intel:.1f}\n"
        f"人口: {target_state.population:.1f}百万人\n"
        f"支持率: {disp_approval:.1f}%\n"
        f"国家債務(GDP比): {(target_state.national_debt / max(0.1, target_state.economy)):.1%}\n"
        f"二国間関係: {rel_str}\n"
        f"{trade_info}\n"
        f"{sanction_info}"
        f"{suzerain_info}"
        f"{dependency_info}"
        f"{pending_aid_info}"
        f"{war_info}\n"
    )
    
    # ステータス推移
    if target_state.stat_history:
        target_info += "---対象国のステータス推移（直近4ターン）---\n"
        for s in target_state.stat_history:
            target_info += f" T{s['turn']}: 経済力 {s['economy']}, 軍事力 {s['military']}, 支持率 {s['approval_rating']}%\n"
        target_info += "\n"
    
    # ---- 他国との関係コンテキスト（三角関係の把握用）----
    third_party_info = ""
    for other_name, other_state in world_state.countries.items():
        if other_name == country_name or other_name == target_country_name:
            continue
        rel_target_other = world_state.relations.get(target_country_name, {}).get(other_name, RelationType.NEUTRAL)
        rel_self_other = world_state.relations.get(country_name, {}).get(other_name, RelationType.NEUTRAL)
        third_party_info += (
            f"  - {other_name}: 対象国との関係={rel_target_other.value}, 自国との関係={rel_self_other.value}\n"
        )
    
    if third_party_info:
        target_info += f"---第三国との関係（三角関係の分析用）---\n{third_party_info}\n"
    
    # ---- ニュース情報（対象国関連のみフィルタ）----
    news_info = ""
    if past_news:
        filtered_lines = []
        for turn_news in past_news:
            if isinstance(turn_news, (list, tuple)):
                for n in turn_news:
                    if target_country_name in n or country_name in n:
                        filtered_lines.append(n)
            elif isinstance(turn_news, str):
                if target_country_name in turn_news or country_name in turn_news:
                    filtered_lines.append(turn_news)
        if filtered_lines:
            news_info = "---関連する直近のニュース---\n"
            for n in filtered_lines[-10:]:  # 最新10件に制限
                news_info += f"- {n}\n"
            news_info += "\n"
    
    # ---- DB検索ツールの利用ガイド ----
    rag_guide = (
        "---🗄️【国家情報局(RAG) 過去の重要記録アクセス】🗄️---\n"
        "あなたは `search_historical_events(query)` ツールを使用可能です。\n"
        f"対象国「{target_country_name}」に関する過去の密約、外交事件、軍事衝突、経済制裁の履歴など、\n"
        "分析に必要な情報が不足している場合は、**必ずこのツールで検索してから結論を出してください。**\n\n"
    )
    
    # ---- 分析指示 ----
    instructions = f"""---分析指示---
あなたは「{country_name}」の情報分析官として、対象国「{target_country_name}」に関する包括的な分析レポートを作成してください。
このレポートは外務大臣・防衛大臣・財務大臣の3名に通達されます。
回答は必ず日本語でお願いします。

以下の3つの観点から分析し、**プレーンテキスト形式**で報告してください（JSONは不要）。

【1. 外交分析】
- 二国間関係の現状評価（友好的/中立/敵対的）
- 外交上の機会（同盟・貿易・首脳会談の可能性）
- 外交上のリスク（関係悪化・戦争の可能性・制裁リスク）
- 自国の国益を最大化するための外交戦略の提言

【2. 軍事・安全保障分析】
- 軍事バランスの評価（軍事力の比較、脅威度）
- 諜報活動の状況と推奨事項（情報収集・破壊工作の提案）
- 交戦中の場合：戦況評価と投入比率の推奨
- 同盟関係が軍事バランスに与える影響

【3. 経済・通商分析】
- 二国間の貿易関係の評価
- 関税率の適正水準の提言（高すぎ/低すぎの判断）
- 経済制裁の効果と推奨事項
- 対外援助の戦略的価値の評価

※各セクション100〜200文字程度で簡潔にまとめてください。合計500〜600文字程度を目安としてください。
"""
    
    return my_info + target_info + news_info + rag_guide + instructions
