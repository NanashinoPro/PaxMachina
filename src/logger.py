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
    
    def __init__(self, log_dir: str = None, session_id: str = None):
        self.console = Console()
        if log_dir is None:
            log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
        self.base_log_dir = log_dir
        self.sim_log_dir = f"{log_dir}/simulations"
        self.sys_log_dir = f"{log_dir}/system"
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        
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
        table.add_column("HCI", justify="right", style="purple")
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
            
            # 支持率表示: 偽装中なら「公表値\n（真値）」で明示
            if c.reported_approval_rating is not None:
                approval_display = (
                    f"[bold yellow]{c.reported_approval_rating:.1f}%[/bold yellow]\n"
                    f"[dim](真:{c.approval_rating:.1f}%)[/dim]"
                )
            else:
                approval_display = f"{c.approval_rating:.1f}%"

            table.add_row(
                name,
                "🗳️ 民主" if c.government_type == "democracy" else "👑 専制",
                f"{c.population:.1f}",
                f"{(c.economy / max(0.1, c.population)):.1f}",
                f"{c.economy:.1f}",
                f"{c.military:.1f}",
                f"{c.human_capital_index:.2f}",
                f"{c.intelligence_level:.1f}",
                approval_display,
                ideology_text
            )
            
        self.console.print(table)
        
    def display_agent_thoughts(self, country_name: str, action: AgentAction):
        """(非公開)エージェントの思考ログを表示（コンパクト版）"""
        text = Text()

        # 思考（先頭120文字のみ）
        thought = action.thought_process or ""
        thought_preview = (thought[:120] + "…") if len(thought) > 120 else thought
        text.append("💭 ", style="bold magenta")
        text.append(f"{thought_preview}\n", style="dim white")

        # 内政（1行）
        dpol = action.domestic_policy
        new_tax_rate = dpol.tax_rate
        if new_tax_rate >= 1.0:
            new_tax_rate /= 100.0
        text.append("🏛 ", style="bold green")
        text.append(
            f"税{new_tax_rate:.0%} | "
            f"経{dpol.invest_economy:.0%} 軍{dpol.invest_military:.0%} "
            f"福{dpol.invest_welfare:.0%} 教{dpol.invest_education_science:.0%} 諜{dpol.invest_intelligence:.0%}\n"
        )

        # 外交（対象国のみリスト）
        if action.diplomatic_policies:
            targets = []
            for dip in action.diplomatic_policies:
                aid_econ = getattr(dip, 'aid_amount_economy', 0.0) or 0.0
                aid_mil  = getattr(dip, 'aid_amount_military', 0.0) or 0.0
                tag = f"[援助 経:{aid_econ:.0f}/軍:{aid_mil:.0f}]" if (aid_econ > 0 or aid_mil > 0) else ""
                targets.append(f"{dip.target_country}{tag}")
            text.append("🌐 ", style="bold blue")
            text.append(", ".join(targets) + "\n")

        # SNS（1件・60文字）
        if action.sns_posts:
            post = (action.sns_posts[0] or "").strip()
            post_preview = (post[:60] + "…") if len(post) > 60 else post
            if post_preview:
                text.append("📢 ", style="bold cyan")
                text.append(f'"{post_preview}"\n', style="italic")

        self.console.print(Panel(
            text,
            title=f"[bold magenta]🧠 {country_name}[/]",
            border_style="magenta",
            padding=(0, 1),
        ))

    def display_turn_summary(self, world_before: dict, world_after: "WorldState"):
        """ターン終了時に各国の変化量をサマリーテーブルで表示"""
        from rich.table import Table as RTable
        table = RTable(title="📊 ターンサマリー（変化量）", show_lines=False, box=None)
        table.add_column("国",   style="cyan",   no_wrap=True)
        table.add_column("経済力", justify="right")
        table.add_column("軍事力", justify="right")
        table.add_column("支持率", justify="right")
        table.add_column("諜報力", justify="right")
        table.add_column("エネルギー備蓄", justify="right")

        for name, c in world_after.countries.items():
            before = world_before.get(name, {})

            def delta_str(current: float, prev: float, unit: str = "") -> str:
                diff = current - prev
                color = "green" if diff > 0 else ("red" if diff < 0 else "dim")
                sign = "+" if diff >= 0 else ""
                return f"[{color}]{current:.1f}({sign}{diff:.1f}{unit})[/{color}]"

            reserve = getattr(c, 'energy_reserve', None)
            target  = getattr(c, 'energy_reserve_target_turns', None)
            reserve_str = "—"
            if reserve is not None:
                prev_r = before.get('energy_reserve', reserve)
                diff_r = reserve - prev_r
                color  = "green" if diff_r >= 0 else "red"
                sign   = "+" if diff_r >= 0 else ""
                tgt    = f"/{target:.1f}T" if target else ""
                reserve_str = f"[{color}]{reserve:.1f}{tgt}({sign}{diff_r:.1f})[/{color}]"

            table.add_row(
                name,
                delta_str(c.economy,            before.get('economy',            c.economy)),
                delta_str(c.military,           before.get('military',           c.military)),
                delta_str(c.approval_rating,    before.get('approval_rating',    c.approval_rating), "%"),
                delta_str(c.intelligence_level, before.get('intelligence_level', c.intelligence_level)),
                reserve_str,
            )
        self.console.print(table)
        self.console.print()



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

    def save_turn_log(self, world: WorldState, actions: dict, analyst_reports: dict = None, task_logs: dict = None):
        """ターン終了時の全状態と行動履歴をJSONファイルに追記保存"""
        filename = self.sim_log_file

        # task_logs: {国名: {タスク名: raw_LLM_response}} をJSONパース済みに変換
        parsed_task_logs = {}
        for country, tasks in (task_logs or {}).items():
            parsed_task_logs[country] = {}
            for task_role, raw_text in tasks.items():
                try:
                    parsed_task_logs[country][task_role] = json.loads(raw_text)
                except (json.JSONDecodeError, TypeError):
                    # JSONでなければ文字列のまま保存
                    parsed_task_logs[country][task_role] = raw_text

        log_entry = {
            "turn": world.turn,
            "year": world.year,
            "quarter": world.quarter,
            "world_state": world.model_dump(),
            "actions": {k: v.model_dump() for k, v in actions.items()},
            "analyst_reports": analyst_reports or {},
            "task_logs": parsed_task_logs,
        }

        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

