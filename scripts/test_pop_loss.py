import os
import random
import logging
from models import WorldState, CountryState, GovernmentType, WarState
from engine import WorldEngine

def run_test():
    world_state = WorldState(
        turn=1,
        year=2025,
        quarter=1,
        countries={
            "TestLand A": CountryState(
                name="TestLand A", government_type=GovernmentType.DEMOCRACY, ideology="Test",
                economy=1000.0, military=100.0, intelligence_level=10.0, area=100.0,
                approval_rating=50.0, population=100.0, initial_population=100.0,
                education_level=100.0, initial_education_level=100.0, press_freedom=1.0, hidden_plans=""
            ),
            "TestLand B": CountryState(
                name="TestLand B", government_type=GovernmentType.AUTHORITARIAN, ideology="Test",
                economy=1000.0, military=100.0, intelligence_level=10.0, area=100.0,
                approval_rating=50.0, population=100.0, initial_population=100.0,
                education_level=100.0, initial_education_level=100.0, press_freedom=0.2, hidden_plans=""
            )
        },
        relations={"TestLand A": {"TestLand B": "neutral"}, "TestLand B": {"TestLand A": "neutral"}},
        active_wars=[], active_trades=[], news_events=[]
    )

    class DummyDB:
        def log_events(self, turn_number, year, quarter, events): pass
        def add_event(self, *args, **kwargs): pass
    
    # We will need the DummyLogger to capture events
    class DummyLogger:
        def sys_log(self, text, *args, **kwargs):
            # print(f"SYS_LOG: {text}")
            pass
            
    engine = WorldEngine(initial_state=world_state, analyzer=None, db_manager=DummyDB())
    # Mock log_event for capturing
    captured_logs = []
    original_log_event = engine.log_event
    def mock_log_event(msg, involved_countries):
        captured_logs.append(msg)
        original_log_event(msg, involved_countries)
    engine.log_event = mock_log_event

    print("=== WAR CASUALTY TEST ===")
    world_state.active_wars.append(WarState(id="1", aggressor="TestLand A", defender="TestLand B", turn_started=1, target_occupation_progress=0.0))
    engine._process_wars()

    pop_a = world_state.countries["TestLand A"].population
    pop_b = world_state.countries["TestLand B"].population
    print(f"Post-War Pop A: {pop_a:.4f}M (Expected < 100.0)")
    print(f"Post-War Pop B: {pop_b:.4f}M (Expected < 100.0 - B lost more since defending)")
    
    for l in captured_logs:
        if "民間人犠牲" in l:
            print("LOGGED WAR:", l)
    
    captured_logs.clear()

    print("\n=== DISASTER CASUALTY TEST ===")
    # Patch random to force a disaster
    original_random = random.random
    engine.state.turn = 2
    random.random = lambda: 0.00000001  # Guaranteed disaster
    engine._process_random_events()
    random.random = original_random
    
    pop_a_after = world_state.countries["TestLand A"].population
    pop_b_after = world_state.countries["TestLand B"].population
    print(f"Post-Disaster Pop A: {pop_a_after:.4f}M (Expected < {pop_a:.4f})")
    print(f"Post-Disaster Pop B: {pop_b_after:.4f}M (Expected < {pop_b:.4f})")
    
    for l in captured_logs:
        if "厄災発生" in l or "国家災害発生" in l:
            print("LOGGED DISASTER:", l)

if __name__ == "__main__":
    run_test()
