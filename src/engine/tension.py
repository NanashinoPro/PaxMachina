"""
緊張度メカニクス (Tension Mechanics)
学術的根拠: Mueller (1970) Rally Effect, Schultz (2001) Audience Cost, Fearon (1994)

威嚇する側のオーディエンスコスト + 威嚇される側のRally効果/恐怖を統合的に計算
"""

import random
from typing import Dict, List, Tuple

from models import (
    WorldState, CountryState, GovernmentType,
    MilitaryDeploymentOrder
)


# ---------------------------------------------------------
# 緊張度スコアの計算
# ---------------------------------------------------------

# 配備ウェイト定数
ARMY_TENSION_WEIGHTS = {
    "intimidation": 3.0,
    "offensive": 2.0,
    "defensive": 0.5,
}

NAVAL_TENSION_WEIGHTS = {
    "show_of_force": 5.0,
    "blockade": 8.0,
    "naval_engagement": 6.0,
    "amphibious_support": 4.0,
    "shore_bombardment": 7.0,
    "patrol": 0.3,
}

AIR_TENSION_WEIGHTS = {
    "recon_flight": 2.0,
    "strategic_bombing": 10.0,
    "air_superiority": 1.0,
    "ground_support": 1.5,
}


def calc_tension_score(deployments: List[MilitaryDeploymentOrder], target_country: str) -> float:
    """
    特定の国に対する軍事的緊張度スコアを計算
    
    Args:
        deployments: ある国の全配備命令リスト
        target_country: 緊張度を計算する対象国名
    
    Returns:
        緊張度スコア (0.0〜)
    """
    tension = 0.0
    for d in deployments:
        t_country = d.target_country if hasattr(d, 'target_country') else d.get('target_country', '')
        if t_country != target_country:
            continue
        
        d_type = d.type.value if hasattr(d.type, 'value') else str(d.type) if hasattr(d, 'type') else d.get('type', '')
        
        if d_type == "army":
            posture = d.posture.value if hasattr(d, 'posture') and d.posture and hasattr(d.posture, 'value') else (d.get('posture', 'defensive') if isinstance(d, dict) else 'defensive')
            divisions = d.divisions if hasattr(d, 'divisions') else d.get('divisions', 0)
            tension += divisions * ARMY_TENSION_WEIGHTS.get(posture, 0.5)
            
        elif d_type == "navy":
            mission = d.naval_mission.value if hasattr(d, 'naval_mission') and d.naval_mission and hasattr(d.naval_mission, 'value') else (d.get('naval_mission', 'patrol') if isinstance(d, dict) else 'patrol')
            fleets = d.fleets if hasattr(d, 'fleets') else d.get('fleets', 0)
            tension += fleets * NAVAL_TENSION_WEIGHTS.get(mission, 0.3)
            
        elif d_type == "air":
            mission = d.air_mission.value if hasattr(d, 'air_mission') and d.air_mission and hasattr(d.air_mission, 'value') else (d.get('air_mission', 'air_superiority') if isinstance(d, dict) else 'air_superiority')
            squadrons = d.squadrons if hasattr(d, 'squadrons') else d.get('squadrons', 0)
            tension += squadrons * AIR_TENSION_WEIGHTS.get(mission, 1.0)
    
    return tension


def get_tension_level(tension_score: float) -> str:
    """緊張度スコアからレベルを返す"""
    if tension_score >= 50:
        return "extreme"
    elif tension_score >= 30:
        return "high"
    elif tension_score >= 10:
        return "medium"
    return "low"


# ---------------------------------------------------------
# 緊張度の効果適用
# ---------------------------------------------------------

def apply_tension_effects(
    world_state: WorldState,
    sys_logs: List[str],
    events: List[str]
) -> List[str]:
    """
    全国間の緊張度効果を適用する。
    
    - 威嚇される側: Rally効果（中緊張）→ 不安（高緊張）→ 恐怖（極高緊張）
    - 威嚇する側: オーディエンスコスト（民主主義国家のみ）
    - 偶発衝突: 極高緊張時に5%の確率で自動発生
    
    Returns:
        生成されたニュースイベントのリスト
    """
    news_events = []
    
    # 全国ペアの緊張度を計算
    tension_map: Dict[Tuple[str, str], float] = {}  # (威嚇する側, される側) → スコア
    
    for threatener_name, threatener in world_state.countries.items():
        for target_name in world_state.countries:
            if threatener_name == target_name:
                continue
            
            deployments = threatener.military_deployment.deployments
            if not deployments:
                continue
            
            score = calc_tension_score(deployments, target_name)
            if score > 0:
                tension_map[(threatener_name, target_name)] = score
    
    # 効果の適用
    for (threatener_name, target_name), tension in tension_map.items():
        threatener = world_state.countries.get(threatener_name)
        target = world_state.countries.get(target_name)
        
        if not threatener or not target:
            continue
        
        level = get_tension_level(tension)
        
        if level == "low":
            continue
        
        # ----- 威嚇される側の効果 (Mueller 1970 Rally Effect) -----
        if level == "medium":
            # Rally効果: +1〜+3% 支持率上昇
            rally_bonus = min(3.0, tension * 0.15)
            target.approval_rating = min(100.0, target.approval_rating + rally_bonus)
            sys_logs.append(
                f"[緊張度:中] {target_name}: Rally効果 +{rally_bonus:.1f}% "
                f"(Mueller 1970, 威嚇元:{threatener_name}, 緊張度:{tension:.1f})"
            )
            
        elif level == "high":
            # Rally減衰 → 不安: -1%/ターン
            target.approval_rating = max(0.0, target.approval_rating - 1.0)
            sys_logs.append(
                f"[緊張度:高] {target_name}: Rally効果減衰、国民不安 -1.0% "
                f"(威嚇元:{threatener_name}, 緊張度:{tension:.1f})"
            )
            news_events.append(
                f"⚠️ {threatener_name}の軍事的プレゼンスにより{target_name}で不安が広がっています。"
            )
            
        elif level == "extreme":
            # 恐怖: -3%/ターン
            target.approval_rating = max(0.0, target.approval_rating - 3.0)
            sys_logs.append(
                f"[緊張度:極高] {target_name}: 国民恐怖 -3.0% "
                f"(威嚇元:{threatener_name}, 緊張度:{tension:.1f})"
            )
            news_events.append(
                f"🔴 {threatener_name}の大規模な軍事展開により{target_name}で深刻な安全保障上の危機が発生！"
            )
            
            # 偶発衝突リスク (5%)
            if random.random() < 0.05:
                # 偶発的な軍事衝突 → 戦争を自動開始
                # ただし、既に交戦中の場合はスキップ
                already_at_war = any(
                    (w.aggressor == threatener_name and w.defender == target_name) or
                    (w.aggressor == target_name and w.defender == threatener_name)
                    for w in world_state.active_wars
                )
                if not already_at_war:
                    from models import WarState
                    world_state.active_wars.append(WarState(
                        aggressor=threatener_name,
                        defender=target_name,
                        aggressor_commitment_ratio=0.3,
                        defender_commitment_ratio=0.5
                    ))
                    news_events.append(
                        f"💥 【偶発衝突】{threatener_name}と{target_name}の軍事的緊張が限界を超え、"
                        f"偶発的な武力衝突が発生！戦争に突入しました！"
                    )
                    sys_logs.append(
                        f"[偶発衝突] {threatener_name} → {target_name}: "
                        f"緊張度{tension:.1f}による5%リスクが発動。戦争自動開始"
                    )
        
        # ----- 威嚇する側の効果 (Schultz 2001 / Fearon 1994 Audience Cost) -----
        if level in ("high", "extreme"):
            # 民主主義国家の場合: オーディエンスコスト
            if threatener.government_type == GovernmentType.DEMOCRACY:
                # 威嚇を維持し続けると「口だけか」と疑われ -0.5%/ターン
                aud_cost = 0.5 if level == "high" else 1.0
                threatener.approval_rating = max(0.0, threatener.approval_rating - aud_cost)
                sys_logs.append(
                    f"[オーディエンスコスト] {threatener_name}(民主主義): "
                    f"威嚇維持ペナルティ -{aud_cost:.1f}% "
                    f"(Schultz 2001, 対{target_name}, 緊張度:{tension:.1f})"
                )
            else:
                # 権威主義国家: 軽微な影響のみ (-0.1%)
                threatener.approval_rating = max(0.0, threatener.approval_rating - 0.1)
                sys_logs.append(
                    f"[オーディエンスコスト:軽微] {threatener_name}(権威主義): "
                    f"-0.1% (対{target_name}, 緊張度:{tension:.1f})"
                )
    
    return news_events


# ---------------------------------------------------------
# プロンプト注入用の緊張情報生成
# ---------------------------------------------------------

def build_tension_info_for_target(world_state: WorldState, country_name: str) -> str:
    """
    威嚇される側のプロンプトに注入する緊張情報を生成
    """
    lines = []
    
    for threatener_name, threatener in world_state.countries.items():
        if threatener_name == country_name:
            continue
        
        deployments = threatener.military_deployment.deployments
        if not deployments:
            continue
        
        score = calc_tension_score(deployments, country_name)
        if score < 1.0:
            continue
        
        level = get_tension_level(score)
        level_ja = {"low": "低", "medium": "中", "high": "高", "extreme": "極高"}.get(level, "低")
        
        lines.append(f"▼ {threatener_name} → あなたの国: 緊張度 {score:.1f} ({level_ja}レベル)")
        
        for d in deployments:
            t_country = d.target_country if hasattr(d, 'target_country') else d.get('target_country', '')
            if t_country != country_name:
                continue
            d_type = d.type.value if hasattr(d.type, 'value') else str(d.type)
            if d_type == "army":
                posture = d.posture.value if d.posture and hasattr(d.posture, 'value') else 'defensive'
                lines.append(f"  └ 陸軍{d.divisions}師団が{posture}態勢で配備中")
            elif d_type == "navy":
                mission = d.naval_mission.value if d.naval_mission and hasattr(d.naval_mission, 'value') else 'patrol'
                lines.append(f"  └ 海軍{d.fleets}艦隊が{mission}態勢")
            elif d_type == "air":
                mission = d.air_mission.value if d.air_mission and hasattr(d.air_mission, 'value') else 'air_superiority'
                lines.append(f"  └ 空軍{d.squadrons}飛行隊が{mission}を実施中")
    
    if not lines:
        return ""
    
    header = "---⚠️【軍事的緊張情報】⚠️---\n"
    header += "以下の国があなたの国に対して軍事的圧力を行使しています：\n\n"
    
    footer = "\n\n【緊張度の効果（あなたの国への影響）】\n"
    footer += "- 緊張度 0-10 (低): 影響なし。\n"
    footer += "- 緊張度 10-30 (中): Rally効果で支持率+1〜+3%/ターン上昇。\n"
    footer += "- 緊張度 30-50 (高): 国民不安で支持率-1%/ターン低下。軍備増強を検討してください。\n"
    footer += "- 緊張度 50+ (極高): 支持率-3%/ターン。偶発衝突5%リスクあり。\n"
    
    return header + "\n".join(lines) + footer


def build_tension_info_for_threatener(world_state: WorldState, country_name: str) -> str:
    """
    威嚇する側のプロンプトに注入するオーディエンスコスト情報を生成
    """
    country = world_state.countries.get(country_name)
    if not country:
        return ""
    
    deployments = country.military_deployment.deployments
    if not deployments:
        return ""
    
    lines = []
    for target_name in world_state.countries:
        if target_name == country_name:
            continue
        
        score = calc_tension_score(deployments, target_name)
        if score < 10.0:
            continue
        
        level = get_tension_level(score)
        level_ja = {"low": "低", "medium": "中", "high": "高", "extreme": "極高"}.get(level, "低")
        
        lines.append(f"▼ あなたの国 → {target_name}: 緊張度 {score:.1f} ({level_ja}レベル)")
        
        # 配備概要
        details = []
        for d in deployments:
            t = d.target_country if hasattr(d, 'target_country') else d.get('target_country', '')
            if t != target_name:
                continue
            d_type = d.type.value if hasattr(d.type, 'value') else str(d.type)
            if d_type == "army":
                posture = d.posture.value if d.posture and hasattr(d.posture, 'value') else 'defensive'
                details.append(f"陸軍{d.divisions}師団({posture})")
            elif d_type == "navy":
                mission = d.naval_mission.value if d.naval_mission and hasattr(d.naval_mission, 'value') else 'patrol'
                details.append(f"海軍{d.fleets}艦隊({mission})")
            elif d_type == "air":
                mission = d.air_mission.value if d.air_mission and hasattr(d.air_mission, 'value') else 'air_superiority'
                details.append(f"空軍{d.squadrons}飛行隊({mission})")
        if details:
            lines.append(f"  └ 配備中: {', '.join(details)}")
    
    if not lines:
        return ""
    
    header = "---📊【あなたの軍事プレゼンスによる緊張度レポート】📊---\n"
    header += "以下の国に対するあなたの軍事配備が緊張を引き起こしています：\n\n"
    
    # オーディエンスコスト警告
    is_democracy = country.government_type == GovernmentType.DEMOCRACY
    if is_democracy:
        footer = "\n\n【オーディエンスコスト警告（Schultz 2001; Fearon 1994）】\n"
        footer += "⚠️ あなたは民主主義国家です。軍事的威嚇のリスク：\n"
        footer += "- 威嚇を維持して何もしない場合: 支持率 -0.5%/ターン\n"
        footer += "- 威嚇を解除（後退）した場合: 蓄積した緊張度の10%分の支持率が低下\n"
        footer += "- エスカレート（宣戦布告等）した場合: コストなし。ただし戦争コストを負う\n"
    else:
        footer = "\n\n※ 権威主義国家のため、オーディエンスコストは軽微です。\n"
    
    return header + "\n".join(lines) + footer
