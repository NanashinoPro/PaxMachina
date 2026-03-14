from typing import Dict, List, Any
from models import GovernmentType

from .constants import WMA_HISTORY_WEIGHT, WMA_BASE_WEIGHT, WMA_BASE_VALUE

class PublicOpinionMixin:
    def evaluate_public_opinion(self, timelines: Dict[str, List[Dict[str, str]]], media_modifiers: Dict[str, float]):
        """
        全国のSNSタイムライン（投稿リスト）およびメディア影響を受け取り、
        加重移動平均（WMA）モデルを用いて最終的な支持率を計算・適用する。
        timelines: { "国名": [ {"author": "Citizen/Leader/Espionage", "text": "投稿内容"} ] }
        """
        for country_name, posts in timelines.items():
            country = self.state.countries[country_name]
            sns_history = []
            total_sns_modifier = 0.0
            censored_count = 0
            
            for post_item in posts:
                author = post_item["author"]
                text = post_item["text"]
                
                scores = self.analyzer.analyze(text)
                avg_score = sum(scores) / len(scores) if scores else 0.0
                
                # スコアを-2.0〜+2.0程度にスケール。マイルドにするため0.8倍
                post_modifier = avg_score * 1.6 
                
                is_censored = False
                if country.government_type == GovernmentType.AUTHORITARIAN:
                    # 首脳の投稿は検閲しない
                    if author != "Leader":
                        # 専制主義はネガティブな発言を検閲
                        if post_modifier < -0.3:
                            is_censored = True
                            
                            # 検閲による反発（バックラッシュ）モデル導入
                            # [学術的背景]
                            # 1. 心理的リアクタンス理論 (ストライサンド効果): 情報を隠蔽する行為そのものが、元の情報以上の反発を生む。
                            # 2. 情報の非対称性とベイジアン更新: 隠された情報は「最悪の事態」と推論され、実際の不満以上に政権打撃となる。
                            # 実装として、検閲された不満（マイナス値）の2倍をペナルティとして加算する。
                            post_modifier = post_modifier * 2.0 
                            
                            # 国民の投稿が検閲された場合のみフラストレーションが蓄積
                            if author == "Citizen":
                                censored_count += 1
                
                # 各投稿の感情スコアをシステムログに出力
                censor_tag = " [検閲]" if is_censored else ""
                self.sys_logs_this_turn.append(f"[{country_name} SNS] {author}: score={avg_score:+.2f} modifier={post_modifier:+.2f}{censor_tag} | {text[:50]}")
                
                # Leader投稿は支持率に影響させない（自己操作防止）
                # 検閲時はペナルティ(`post_modifier`)として作用するため、`is_censored`判定に関わらず合算する
                if author != "Leader":
                    total_sns_modifier += post_modifier
                    
                sns_history.append({
                    "author": author,
                    "post": text,
                    "score": avg_score,
                    "censored": is_censored
                })
                
            # 支持率への影響をマイルドに制限（最大+-3.0%）
            total_sns_modifier = max(-3.0, min(3.0, total_sns_modifier))
                
            # ログ保存
            if country_name not in self.state.sns_logs:
                self.state.sns_logs[country_name] = []
            self.state.sns_logs[country_name].append({
                "turn": self.state.turn,
                "posts": sns_history,
                "total_modifier": total_sns_modifier,
                "censored_count": censored_count
            })
            
            # --- WMA (Weighted Moving Average) による支持率計算 ---
            dom = self.turn_domestic_factors.get(country_name, {})
            gdp_growth = dom.get("gdp_growth_rate", 0.0)
            welfare_bonus = dom.get("welfare_bonus", 0.0)
            trade_bonus = dom.get("trade_support_bonus", 0.0)
            media_mod = media_modifiers.get(country_name, 0.0)
            
            # WMA Calculation: 
            # Current = Base 50% * 0.2 + Previous * 0.8 + Dynamic Bonuses
            old_approval = country.approval_rating
            base_trend = (old_approval * WMA_HISTORY_WEIGHT) + (WMA_BASE_VALUE * WMA_BASE_WEIGHT)
            
            # 政治疲労 (Political Fatigue) による支持率の自然減衰
            # [学術的背景] 政権の長期化に伴い、国民の「飽き」や「未解決な不満」が蓄積し、
            # 初期の熱狂（ハネムーン期間）が失われる現象をモデリング。
            # 指数1.2は、現実の民主国家における支持率下落トレンドへのキャリブレーションを意図し、
            # ターンの経過とともに非線形に下落圧力が強まる設計。
            # 例: 20ターンで約-1.5%、40ターンで約-3.5%の強力なペナルティとなる。
            duration_factor = (country.regime_duration / 10.0) ** 1.2            
            # 従来： -0.5 - ((old_approval - 50.0) * 0.01 if old_approval > 50.0 else 0)
            # 変更： 基本的に-0.5をベースとし、長期政権ほど追加デバフ。支持率が高いほどさらに減衰ペースが上がる。
            approval_factor = ((old_approval - 50.0) * 0.03 if old_approval > 50.0 else 0)
            fatigue_decay = -0.5 - duration_factor - approval_factor
            
            import math
            # Apply dynamic factors with carefully tuned weights
            if gdp_growth >= 0:
                # [学術的背景] 限界効用逓減の法則
                # 一定以上の経済成長による支持率上昇は徐々に頭打ち（非線形）になる。
                # 例: +5%成長で+2.5ボーナス、+20%成長でも+4.0程度に抑える。
                if gdp_growth <= 5.0:
                    growth_modifier = gdp_growth * 0.5
                else:
                    growth_modifier = 2.5 + math.log10(gdp_growth - 4.0) * 1.5
            else:
                growth_modifier = gdp_growth * 0.5
                
            if gdp_growth < -5.0:
                # 深刻な不況（5%以上のマイナス成長）には非線形なペナルティを課すが、
                # クーデター等の直後に発生する無限死亡ループを防ぐため、1ターンのペナルティ上限を設ける
                # 不満の非対称性 (Grievance Asymmetry) により、マイナス局面はプラス局面より強い影響力を持つ
                penalty = (abs(gdp_growth) - 5.0) ** 1.5
                growth_modifier -= min(30.0, penalty)
                
            new_approval = (
                base_trend 
                + fatigue_decay              # Natural political fatigue decay
                + growth_modifier            # Dynamic GDP growth/collapse modifier
                + (media_mod * 1.0)          # max +-5.0
                + (total_sns_modifier * 0.5) # max +-1.5
                + welfare_bonus              # based on log curve approx -2.0 to +2.5
                + trade_bonus                # from trade benefits or deficit penalties
            )
            
            country.approval_rating = max(0.0, min(100.0, new_approval))
            
            # 検閲による反乱リスクの増加
            if censored_count > 0:
                country.rebellion_risk += censored_count * 1.5
                self.sys_logs_this_turn.append(f"[{country.name} SNS] 一般国民の投稿が{censored_count}件検閲され、反乱リスクが上昇")

            self.sys_logs_this_turn.append(
                f"[{country.name} 支持率更新] {old_approval:.1f}% -> {country.approval_rating:.1f}% "
                f"(内訳: 政治疲労{fatigue_decay:.1f}, GDP成長{growth_modifier:+.1f}, 福祉{welfare_bonus:+.1f}, 貿易恩恵{trade_bonus:+.1f}, メディア{media_mod:+.1f}, SNS世論{total_sns_modifier*0.5:+.1f})"
            )
