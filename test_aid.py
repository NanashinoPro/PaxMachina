import uuid
import os
import asyncio
from typing import Dict
from models import WorldState, CountryState, GovernmentType, AgentAction, DomesticAction, DiplomaticAction
from engine import WorldEngine
from logger import SimulationLogger

async def run_aid_test():
    # ログディレクトリの準備
    log_dir = f"TEST_AID_UUID"
    os.makedirs(f"{log_dir}/system", exist_ok=True)
    os.makedirs(f"{log_dir}/simulations", exist_ok=True)
    os.makedirs(f"{log_dir}/agents", exist_ok=True)

    logger = SimulationLogger("TEST_AID_UUID")
    
    # 世界状態のモック作成
    world = WorldState(
        turn=1,
        year=2026,
        quarter=1,
        countries={
            "USA": CountryState(
                name="USA",
                government_type=GovernmentType.DEMOCRACY,
                ideology="自由と民主主義の防衛",
                population=330.0,
                initial_population=330.0,
                economy=25000.0,
                military=1000.0,
                approval_rating=50.0,
                press_freedom=0.8,
                tax_rate=0.20
            ),
            "SmallNation": CountryState(
                name="SmallNation",
                government_type=GovernmentType.AUTHORITARIAN,
                ideology="独裁と軍事",
                population=10.0,
                initial_population=10.0,
                economy=100.0, # 非常に小さい経済規模
                military=10.0,
                approval_rating=80.0,
                press_freedom=0.1,
                tax_rate=0.30
            )
        }
    )
    
    engine = WorldEngine(initial_state=world)
    
    print("=== TURN 1 ===")
    logger.display_country_status(world)
    
    # ターン1: USAからSmallNationへ莫大な援助
    print("\n[USAからの莫大な援助によるオランダ病発症テスト]")
    actions = {
        "USA": AgentAction(
            thought_process="SmallNationを金で買い属国にする。",
            sns_posts=["援助を実施！"],
            update_hidden_plans="",
            domestic_policy=DomesticAction(
                tax_rate=0.20, target_press_freedom=0.8,
                invest_economy=0.4, invest_military=0.2, invest_welfare=0.2, invest_education_science=0.1, invest_intelligence=0.1, reason="Test",
                reasoning_for_military_investment="Test"
            ),
            diplomatic_policies=[
                DiplomaticAction(
                    target_country="SmallNation",
                    aid_amount_economy=100.0,
                    aid_amount_military=10.0,
                    reason="属国化・オランダ病テスト"
                )
            ]
        ),
        "SmallNation": AgentAction(
            thought_process="もらえるものはもらう",
            sns_posts=[],
            update_hidden_plans="",
            domestic_policy=DomesticAction(
                tax_rate=0.30, target_press_freedom=0.1,
                invest_economy=0.25, invest_military=0.25, invest_welfare=0.25, invest_education_science=0.125, invest_intelligence=0.125, reason="Test",
                reasoning_for_military_investment="Test"
            ),
            diplomatic_policies=[]
        )
    }
    
    world = engine.process_turn(actions)
    world.turn += 1
    
    logger.display_country_status(world)
    for l in engine.sys_logs_this_turn:
        print(l)
        
    print("\n=== TURN 2 ===")
    print("[USAからの追加援助での属国化・外交無効化テスト]")
    # ターン2: 適量を追加して依存度を上げ、属国化。および独自の外交を試みる。
    actions_t2 = {
        "USA": AgentAction(
            thought_process="徐々に依存度を高める。",
            sns_posts=[],
            update_hidden_plans="",
            domestic_policy=DomesticAction(
                tax_rate=0.20, target_press_freedom=0.8,
                invest_economy=0.4, invest_military=0.2, invest_welfare=0.2, invest_education_science=0.1, invest_intelligence=0.1, reason="Test",
                reasoning_for_military_investment="Test"
            ),
            diplomatic_policies=[
                DiplomaticAction(
                    target_country="SmallNation",
                    aid_amount_economy=100.0, # さらに依存度を上げる
                    reason="属国化テスト"
                )
            ]
        ),
        "SmallNation": AgentAction(
            thought_process="内政のみ",
            sns_posts=[],
            update_hidden_plans="",
            domestic_policy=DomesticAction(
                tax_rate=0.30, target_press_freedom=0.1,
                invest_economy=0.5, invest_military=0.5, invest_welfare=0.0, invest_education_science=0.0, invest_intelligence=0.0, reason="Test",
                reasoning_for_military_investment="Test"
            ),
            diplomatic_policies=[
                DiplomaticAction(
                    target_country="USA",
                    message="文句を言う",
                    reason="独自の外交を試みる"
                )
            ]
        )
    }
    
    world = engine.process_turn(actions_t2)
    world.turn += 1
    logger.display_country_status(world)
    for l in engine.sys_logs_this_turn:
        print(l)
    print("\nSmallNationの依存度:", world.countries["SmallNation"].dependency_ratio.get("USA"))
    print("SmallNationの宗主国:", getattr(world.countries["SmallNation"], "suzerain", None))
    print("SmallNationの外交アクション（USAへのメッセージ等）はクリアされたか:", len(actions_t2["SmallNation"].diplomatic_policies) == 0)
    
if __name__ == "__main__":
    asyncio.run(run_aid_test())
