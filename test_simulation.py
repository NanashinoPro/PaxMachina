import asyncio
from main import AIDiplomacyGame

async def main():
    game = AIDiplomacyGame()
    
    # 3ターンのシミュレーションを実行
    for turn in range(3):
        print(f"\n--- Turn {turn + 1} ---")
        await game.run_turn()
        
    print("\nSimulation Completed.")

if __name__ == "__main__":
    asyncio.run(main())
