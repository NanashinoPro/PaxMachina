from models import PresidentPolicy
from agent.prompts.domestic import build_policy_section as _bps

def build_policy_section(policy: PresidentPolicy) -> str:
    return _bps(policy)
