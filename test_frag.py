import asyncio
from models import WorldState, CountryState, GovernmentType
from engine import WorldEngine
from agent import AgentSystem
from logger import SimulationLogger

async def main():
    print("Testing Fragmentation...")
    
    world = WorldState(turn=1, year=2025, countries={})
    
    # テスト用国家（民主主義で支持率0%）
    usa = CountryState(
        name="アメリカ",
        economy=100.0,
        military=50.0,
        approval_rating=0.0, # すぐにクーデター
        government_type=GovernmentType.DEMOCRACY,
        ideology="自由競争",
        press_freedom=1.0,
        target_country=None,
        area=1000.0
    )
    
    # もう一つのテスト用国家（専制主義で反乱リスクMax）
    chn = CountryState(
        name="中国",
        economy=100.0,
        military=50.0,
        approval_rating=0.0,
        government_type=GovernmentType.AUTHORITARIAN,
        ideology="共同富裕",
        press_freedom=0.2,
        target_country=None,
        area=1000.0
    )
    chn.rebellion_risk = 150.0 # 確実に反乱
    
    world.countries = {"アメリカ": usa, "中国": chn}
    
    logger = SimulationLogger("TEST_UUID")
    agent_system = AgentSystem(logger=logger)
    engine = WorldEngine(initial_state=world, analyzer=None)
    
    # 疑似SNSログ（分裂プロフィール生成用）
    engine.turn_sns_logs = {
        "アメリカ": [{"author": "Citizen", "text": "ワシントンの腐敗はもう耐えられない。カリフォルニアは独立すべきだ！"},
                  {"author": "Citizen", "text": "増税ばかりで生活が苦しい。中央政府から主権を取り戻そう。"}],
        "中国": [{"author": "Citizen", "text": "独裁政治に反対！南方地域はもっと自由な経済と政治を求める！"}]
    }

    # クーデター/分裂判定のキック
    print("\n--- Processing Pre-Turn ---")
    engine.process_pre_turn()
    
    # 結果の確認
    print("\n--- State After Breakdown ---")
    for name, c in engine.state.countries.items():
        print(f"[{name}] GDP:{c.economy:.1f}, Military:{c.military:.1f}, Gov:{c.government_type.value}, Area:{c.area:.1f}")
        print(f"  Ideology: {c.ideology}")

if __name__ == "__main__":
    asyncio.run(main())
