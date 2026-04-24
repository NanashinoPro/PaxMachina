from models import PresidentPolicy
from agent.prompts.domestic import build_policy_section

def _build_policy_section(policy: PresidentPolicy) -> str:
    return build_policy_section(policy)
