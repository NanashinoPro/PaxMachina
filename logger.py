import os
import json
from datetime import datetime
from typing import Any
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

from models import WorldState, AgentAction

class SimulationLogger:
    """シミュレーションのログ保存と表示を担当するクラス"""
    
    def __init__(self, log_dir: str = "logs", session_id: str = None):
        self.console = Console()
        self.base_log_dir = log_dir
        self.sim_log_dir = f"{log_dir}/simulations"
        self.sys_log_dir = f"{log_dir}/system"
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        import os
        
        for d in [self.sim_log_dir, self.sys_log_dir]:
            if not os.path.exists(d):
                os.makedirs(d)
                
        # ログファイルの設定
        self.sys_log_file = f"{self.sys_log_dir}/system_{self.session_id}.log"
        self.sim_log_file = f"{self.sim_log_dir}/sim_{self.session_id}.jsonl"
        
        if session_id is None:
            self.sys_log("=== シミュレーションシステム起動 ===")
        else:
            self.sys_log(f"=== シミュレーションシステム再開 (Session: {self.session_id}) ===")

    def sys_log(self, message: str, level: str = "INFO"):
        """システムログをリアルタイムでファイルに出力する"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}\n"
        # ファイルへ即時書き込み
        with open(self.sys_log_file, "a", encoding="utf-8") as f:
            f.write(log_line)
            f.flush()
            os.fsync(f.fileno())
        
        # エラー時はコンソールにも表示
        if level in ["ERROR", "WARNING"]:
            self.console.print(f"[bold red]システムエラー: {message}[/bold red]")

    def sys_log_detail(self, category: str, data: Any):
        """システムログに詳細データ（プロンプトや計算結果など）を追記する"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if isinstance(data, str):
                details = data
            elif hasattr(data, "model_dump"):
                details = json.dumps(data.model_dump(), ensure_ascii=False, indent=2)
            else:
                details = json.dumps(data, ensure_ascii=False, indent=2)
                
            log_line = f"[{timestamp}] [{category}]\n{details}\n{'-'*50}\n"
            with open(self.sys_log_file, "a", encoding="utf-8") as f:
                f.write(log_line)
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            self.sys_log(f"ログ詳細の書き込みに失敗: {e}", "ERROR")
            
    def display_turn_header(self, world: WorldState):
        """ターンの開始ヘッダーを表示"""
        title = f"🌍 Turn {world.turn} ({world.year}年 Q{world.quarter})"
        self.console.print(Panel(f"[bold cyan]{title}[/bold cyan]", expand=False))

    def display_country_status(self, world: WorldState):
        """現在の各国のステータスを表形式で表示"""
        table = Table(title="国家ステータス")
        
        table.add_column("国", justify="left", style="cyan", no_wrap=True)
        table.add_column("体制", style="magenta")
        table.add_column("人口(M)", justify="right", style="cyan")
        table.add_column("1人当GDP", justify="right", style="green")
        table.add_column("経済力", justify="right", style="green")
        table.add_column("軍事力", justify="right", style="red")
        table.add_column("教育・科学", justify="right", style="purple")
        table.add_column("諜報力", justify="right", style="blue")
        table.add_column("支持率", justify="right", style="yellow")
        table.add_column("イデオロギー/状態", style="white")

        for name, c in world.countries.items():
            ideology_text = c.ideology
            if len(ideology_text) > 30:
                ideology_text = ideology_text[:28] + "..."
                
            status_extras = []
            if getattr(c, 'suzerain', None):
                status_extras.append(f"🛡️ {c.suzerain}の属国")
            if c.government_type == "democracy" and c.turns_until_election:
                status_extras.append(f"選挙迄:{c.turns_until_election}T")
            if c.government_type == "authoritarian":
                status_extras.append(f"反乱R:{c.rebellion_risk:.1f}%")
                
            extra_str = " | ".join(status_extras)
            if extra_str:
                 ideology_text += f"\n[{extra_str}]"
            
            table.add_row(
                name,
                "🗳️ 民主" if c.government_type == "democracy" else "👑 専制",
                f"{c.population:.1f}",
                f"{(c.economy / max(0.1, c.population)):.1f}",
                f"{c.economy:.1f}",
                f"{c.military:.1f}",
                f"{c.education_level:.1f}",
                f"{c.intelligence_level:.1f}",
                f"{c.approval_rating:.1f}%",
                ideology_text
            )
            
        self.console.print(table)
        
    def display_agent_thoughts(self, country_name: str, action: AgentAction):
        """(非公開)エージェントの思考ログを表示"""
        
        text = Text()
        text.append(f"思考: ", style="bold magenta")
        text.append(f"{action.thought_process}\n")
        
        text.append(f"内政: ", style="bold green")
        dpol = action.domestic_policy
        # 首脳AIが 15.0(%) のように整数で返してきた場合の補正ロジック
        new_tax_rate = action.domestic_policy.tax_rate
        if new_tax_rate >= 1.0:
            new_tax_rate /= 100.0
        text.append(f"税率 {new_tax_rate:.1%} | 経済 {dpol.invest_economy:.0%} | 軍事 {dpol.invest_military:.0%} | 福祉 {dpol.invest_welfare:.0%} | 教育・科学 {dpol.invest_education_science:.0%} | 諜報 {dpol.invest_intelligence:.0%}\n")
        text.append(f"内政理由: ", style="bold yellow")
        text.append(f"{dpol.reason}\n")
        
        if action.diplomatic_policies:
            text.append(f"外交: ", style="bold blue")
            for dip in action.diplomatic_policies:
                aid_str = ""
                aid_econ = getattr(dip, 'aid_amount_economy', 0.0)
                aid_mil = getattr(dip, 'aid_amount_military', 0.0)
                if aid_econ > 0 or aid_mil > 0:
                    aid_str = f" [援助 経:{aid_econ:.1f}/軍:{aid_mil:.1f}]"
                text.append(f"\n  → {dip.target_country}{aid_str}: {dip.reason}")
            text.append("\n")

        if action.update_hidden_plans:
            text.append(f"秘匿計画: ", style="bold red")
            text.append(f"{action.update_hidden_plans}\n")
            
        if action.sns_posts:
            text.append(f"SNS投稿: ", style="bold cyan")
            for post in action.sns_posts:
                text.append(f"\n  \"{post}\"")
            text.append("\n")
        
        self.console.print(Panel(text, title=f"🧠 {country_name} 首脳の脳内", border_style="magenta"))

    def display_world_events(self, world: WorldState, title: str = "📰 ニュース・イベントログ"):
        """世界で起こったニュース(公開イベント)を表示"""
        if not world.news_events:
            self.console.print(f"[dim]{title}: 目立ったイベントは発生しませんでした。[/dim]")
            return
            
        text = Text()
        for event in world.news_events:
            if "【開戦】" in event or "🔥" in event:
                text.append(f"{event}\n", style="bold red")
            elif "🕵️‍♂️" in event or "🚨" in event:
                text.append(f"{event}\n", style="bold yellow")
            elif "🤝" in event:
                text.append(f"{event}\n", style="bold cyan")
            elif "【政権交代】" in event or "【革命" in event:
                text.append(f"{event}\n", style="bold magenta reverse")
            else:
                text.append(f"{event}\n")
                
        self.console.print(Panel(text, title=title, border_style="yellow"))

    def display_section_header(self, title: str, style: str = "bold white on blue"):
        """セクションの区切りヘッダーを表示"""
        self.console.print(f"\n[{style}] {title} [/]\n")

    def display_category_events(self, events: list, title: str, style: str = "yellow", icon: str = "📢"):
        """特定カテゴリのイベントをパネル表示"""
        if not events:
            return
        
        text = Text()
        for e in events:
            text.append(f"{e}\n")
        
        self.console.print(Panel(text, title=f"{icon} {title}", border_style=style))

    def display_sns_timeline(self, sns_timelines: dict):
        """SNS風にタイムラインを表示する"""
        from rich.panel import Panel
        from rich.text import Text
        for country, posts in sns_timelines.items():
            if not posts: continue
            text = Text()
            for post in posts:
                author = post.get("author", "Citizen")
                author_color = "cyan" if author == "Citizen" else ("magenta" if author == "Leader" else "red")
                author_tag = "🧑‍💻 国民" if author == "Citizen" else ("👑 トップ" if author == "Leader" else "🕵️ 工作員")
                text.append(f"{author_tag}: ", style=f"bold {author_color}")
                text.append(f"{post.get('text', '')}\n", style="white")
                
            self.console.print(Panel(text, title=f"📱 {country} SNS Timeline", border_style="cyan"))

    def save_turn_log(self, world: WorldState, actions: dict):
        """ターン終了時の全状態と行動履歴をJSONファイルに追記保存"""
        filename = self.sim_log_file
        
        log_entry = {
            "turn": world.turn,
            "year": world.year,
            "quarter": world.quarter,
            "world_state": world.model_dump(),
            "actions": {k: v.model_dump() for k, v in actions.items()}
        }
        
        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
