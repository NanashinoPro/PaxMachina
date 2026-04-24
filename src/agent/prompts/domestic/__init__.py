"""施政方針セクションの共通ビルダー"""
from models import PresidentPolicy

def build_policy_section(policy: PresidentPolicy) -> str:
    lines = "\n".join(f"・{d}" for d in policy.directives)
    return f"\n【🏛️ 大統領施政方針（{policy.stance}）】\n{lines}\n\nあなたの担当タスクはこの方針に沿って決定してください。\n"
