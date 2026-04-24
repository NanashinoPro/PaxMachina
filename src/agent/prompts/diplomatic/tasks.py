from typing import Dict, List
from models import WorldState, CountryState, PresidentPolicy
from agent.prompts.base import build_common_context
from agent.prompts.diplomatic import build_policy_section

# 全外交タスクで共通の他国リスト生成
def _other_countries(world_state: WorldState, country_name: str) -> List[str]:
    return [n for n in world_state.countries if n != country_name]


def build_message_prompt(country_name, country_state: CountryState, world_state: WorldState,
                         policy: PresidentPolicy, analyst_reports: Dict = None, past_news=None) -> str:
    """D-01: 外交メッセージ送信（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="外交担当官（メッセージ）")
    others = _other_countries(world_state, country_name)
    return ctx + build_policy_section(policy) + f"""
他国: {', '.join(others)}
メッセージを送るべき国があれば、公開または非公開メッセージを作成してください。
不要なら空リストを返してください。

JSONのみ出力:
{{"messages": [{{"target_country": "国名", "message": "メッセージ内容", "is_private": false, "reason": "理由（30文字以内）"}}]}}
"""


def build_trade_prompt(country_name, country_state: CountryState, world_state: WorldState,
                       policy: PresidentPolicy, past_news=None) -> str:
    """D-02: 貿易協定の提案・破棄（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="外交担当官（貿易）")
    trade_partners = [t.country_b if t.country_a == country_name else t.country_a for t in world_state.active_trades
                      if t.country_a == country_name or t.country_b == country_name]
    others = _other_countries(world_state, country_name)
    return ctx + build_policy_section(policy) + f"""
現在の貿易相手国: {', '.join(trade_partners) or 'なし'}
全国: {', '.join(others)}

貿易協定を新規提案（propose_trade=true）または破棄（cancel_trade=true）する国があれば指定してください。

JSONのみ出力:
{{"trade_actions": [{{"target_country": "国名", "propose_trade": false, "cancel_trade": false, "reason": "理由（30文字以内）"}}]}}
"""


def build_sanctions_prompt(country_name, country_state: CountryState, world_state: WorldState,
                           policy: PresidentPolicy, past_news=None) -> str:
    """D-03: 経済制裁の発動・解除（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="外交担当官（制裁）")
    active_out = [s.target for s in world_state.active_sanctions if s.imposer == country_name]
    active_in  = [s.imposer for s in world_state.active_sanctions if s.target == country_name]
    others = _other_countries(world_state, country_name)
    return ctx + build_policy_section(policy) + f"""
自国が制裁中: {', '.join(active_out) or 'なし'}
自国が制裁受中: {', '.join(active_in) or 'なし'}
対象候補: {', '.join(others)}

制裁を発動（impose_sanctions=true）または解除（lift_sanctions=true）する国があれば指定してください。

JSONのみ出力:
{{"sanction_actions": [{{"target_country": "国名", "impose_sanctions": false, "lift_sanctions": false, "reason": "理由（30文字以内）"}}]}}
"""


def build_summit_prompt(country_name, country_state: CountryState, world_state: WorldState,
                        policy: PresidentPolicy, past_news=None) -> str:
    """D-04: 首脳会談の提案・受諾（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="外交担当官（首脳会談）")
    pending_in = [s.proposer for s in world_state.pending_summits
                  if s.target == country_name and not s.participants]
    others = _other_countries(world_state, country_name)
    return ctx + build_policy_section(policy) + f"""
受諾待ちの会談提案（前ターン受信）: {', '.join(pending_in) or 'なし'}
対象候補: {', '.join(others)}

2国間首脳会談の提案・受諾を決定してください。

JSONのみ出力:
{{"summit_actions": [{{"target_country": "国名", "propose_summit": false, "accept_summit": false, "summit_topic": null, "reason": "理由（30文字以内）"}}]}}
"""


def build_multilateral_summit_prompt(country_name, country_state: CountryState, world_state: WorldState,
                                     policy: PresidentPolicy, past_news=None) -> str:
    """D-05: 多国間首脳会談の提案（flash）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="外交担当官（多国間会談）")
    others = _other_countries(world_state, country_name)
    pending_multi = [s for s in world_state.pending_summits
                     if s.participants and country_name in s.participants and s.proposer != country_name]
    pending_str = ", ".join(f"{s.proposer}提案({s.topic})" for s in pending_multi) or "なし"
    return ctx + build_policy_section(policy) + f"""
受諾待ちの多国間会談: {pending_str}
招待可能国: {', '.join(others)}

多国間首脳会談の提案（propose_multilateral_summit=true）または受諾（accept_summit=true）を決定してください。
不要なら空リストを返してください。

JSONのみ出力:
{{"multilateral_actions": [{{"target_country": "ホスト国名（受諾時）or自国（提案時）", "propose_multilateral_summit": false, "accept_summit": false, "summit_participants": [], "summit_topic": null, "reason": "理由（30文字以内）"}}]}}
"""


def build_aid_donor_prompt(country_name, country_state: CountryState, world_state: WorldState,
                           policy: PresidentPolicy, past_news=None) -> str:
    """D-06: 対外援助の設定（送り手）（flash）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="外交担当官（援助送付）")
    aid_out = [c for c in world_state.recurring_aid_contracts if c.donor == country_name]
    aid_str = "\n".join(f"  - {c.target}: 経済{c.amount_economy:.1f}/T, 軍事{c.amount_military:.1f}/T" for c in aid_out) or "（なし）"
    others = _other_countries(world_state, country_name)
    return ctx + build_policy_section(policy) + f"""
【現在の援助契約（サブスク制・毎ターン自動継続）】
{aid_str}

援助先候補: {', '.join(others)}
【注意】変更不要なら出力しないこと（0.0のまま = 変更なし）。停止はaid_cancel=true。
⚠️ 累積援助比率60%超で相手が属国化リスク / 1ターンGDP20%超でオランダ病。

JSONのみ出力（変更・停止する国のみ）:
{{"aid_actions": [{{"target_country": "国名", "aid_amount_economy": 0.0, "aid_amount_military": 0.0, "aid_cancel": false, "reason": "理由（30文字以内）"}}]}}
"""


def build_aid_acceptance_prompt(country_name, country_state: CountryState, world_state: WorldState,
                                policy: PresidentPolicy, past_news=None) -> str:
    """D-07: 援助受入率の設定（受け手）（flash-lite）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="外交担当官（援助受入）")
    aid_in = [c for c in world_state.recurring_aid_contracts if c.target == country_name]
    if not aid_in:
        return ""  # 援助を受けていない場合はスキップ
    aid_str = "\n".join(f"  - {c.donor}: 経済{c.amount_economy:.1f}/T, 軍事{c.amount_military:.1f}/T" for c in aid_in)
    dep_str = ", ".join(f"{k}:{v*100:.1f}%" for k, v in country_state.dependency_ratio.items()) or "なし"
    return ctx + build_policy_section(policy) + f"""
【受けている援助契約】
{aid_str}
【現在の対外依存度】{dep_str}（60%超で属国化リスク）

援助の受入率（0.0=拒否〜1.0=全額受入）を国ごとに設定してください。
依存度が高まっている国は受入率を下げることを検討してください。

JSONのみ出力:
{{"acceptance_actions": [{{"target_country": "援助元国名", "aid_acceptance_ratio": 1.0, "reason": "理由（30文字以内）"}}]}}
"""


def build_power_vacuum_prompt(country_name, country_state: CountryState, world_state: WorldState,
                              policy: PresidentPolicy, past_news=None) -> str:
    """D-08: パワーバキューム・影響力介入入札（flash）"""
    ctx = build_common_context(country_name, country_state, world_state, past_news, role_name="外交担当官（勢力圏介入）")
    auctions = list(world_state.pending_vacuum_auctions) + list(world_state.pending_influence_auctions)
    if not auctions:
        return ""  # オークションがない場合はスキップ
    auction_str = ""
    for a in auctions:
        new_c = a.get("new_country") or a.get("target_country", "")
        old_c = a.get("old_country", "")
        c_state = world_state.countries.get(new_c)
        if c_state:
            auction_str += f"  - {new_c}（旧:{old_c}）: 軍事{c_state.military:.1f}, 経済{c_state.economy:.1f}\n"
    return ctx + build_policy_section(policy) + f"""
【介入可能なオークション】
{auction_str}
vacuum_bid(0〜自国軍事力)を設定。0=介入しない。高いほど吸収/影響力拡大の確率↑。

JSONのみ出力:
{{"vacuum_actions": [{{"target_country": "国名", "vacuum_bid": 0.0, "reason": "理由（30文字以内）"}}]}}
"""
