# AI Diplomacy Simulation

## 1. 概要 (Abstract)

本プロジェクトは、大規模言語モデル（LLM）を国家元首や政府の意思決定中枢（エージェント）として見立て、多国間における外交・内政・戦争・諜報活動をシミュレーションするためのマルチエージェント型エージェントベースモデル（ABM: Agent-Based Model）です。

従来の固定的なルールベースやミニマックス法に基づくゲームAIとは異なり、高い自然言語推論能力と世界知識を持つLLM（各種推論には`gemini-2.5-pro`、メディアやSNS生成には`gemini-2.5-flash`や`flash-lite`等）が各国のペルソナ（イデオロギー、政治体制、経済・軍事力）を与えられ、毎ターンの複雑な戦略を自律的に思索・決定します。本システムは、生成AIのゲーム理論的挙動や「仮想的な国際関係学」を観察・分析するためのテストベッドとして機能します。

## 2. 前提条件 (Prerequisites)

- **Python 3.11+**（3.13 推奨）
- **Google Gemini API キー** — [Google AI Studio](https://aistudio.google.com/apikey) から取得してください

## 3. セットアップ (Setup)

```bash
# 1. リポジトリをクローン
git clone https://github.com/Nanashino_AI/ai_diplomacy.git
cd ai_diplomacy

# 2. Python 仮想環境を作成・有効化
python3 -m venv .venv
source .venv/bin/activate

# 3. 依存関係をインストール
pip install -r requirements.txt

# 4. 環境変数を設定
cp .env.example .env
# .env ファイルを編集し、GEMINI_API_KEY にあなたのAPIキーを入力してください
```

## 4. システムアーキテクチャ・数理モデル詳細

本シミュレーションを構成する各エージェントの役割（首脳・国民SNS・メディア・諜報機関等）や、支持率の計算、戦争・貿易・諜報被害・災害イベントの数理的な状態遷移モデル（ODDプロトコル準拠）についての詳細な解説は、以下のドキュメントを参照してください。

👉 [**ARCHITECTURE.md (システム設計と数理モデル詳細)**](./docs/ARCHITECTURE.md)
👉 [**あーきてくちゃ.md (子供向け解説)**](./docs/あーきてくちゃ.md)

## 5. ログ・追跡システム (Logging & Telemetry)

全てのターンにおけるシミュレーションデータは `logs/simulations/` に JSON Lines (JSONL) 形式で完全に追記・保存されます。
これには公開情報のステータスだけでなく、AIが非公開で行っていた「思考プロセス（Thought Process）」や背後関係の全履歴が含まれます。
システム側のAPI通信エラーやレイテンシの記録は `logs/system/` 以下の `.log` ファイルとして物理的に分離され保存されます。
また、シミュレーション終了時には `summarizer.py` が自動実行され、ログ全体から各国の初期戦略や途中の変更、主要な出来事を分析・要約したファイル（`.summary.json`）が生成されます。

> **📦 過去のシミュレーションログ**: 実際に実行されたシミュレーションの全ログデータは、リポジトリサイズ軽量化のため [GitHub Releases](../../releases) ページからダウンロードできます。

## 6. Web UI による可視化と対話的分析 (Visualization & Interactive Analysis)

本システムには軽量なPython（Flask）ベースのローカルWebサーバーが含まれています。
```bash
python src/web_ui.py
```
を実行し `http://localhost:8081` にアクセスすることで、過去のすべてのセッションの時系列推移、各国の裏側の狙い（諜報・政策）、ニュースイベントの発生状況、そして**市民や首脳、工作員によるアイコン付きのSNSタイムライン**を直感的なフロントエンド（Chart.js / Vanilla JS）から分析・閲覧可能です。

さらに、**LLMを活用したチャット分析インターフェース（RAG拡張）**を内蔵しており、特定のシミュレーションログ履歴（JSONL）をコンテキストとして直接読み込ませた上で、「ターン〇〇でアメリカが中国に制裁を発動した背景の推考」や「この世界における各国の軍拡競争の要因分析」などをLLMと対話しながら深掘り調査することが可能です。

## 7. 変更可能なパラメータ一覧 (Configurable Parameters)

ユーザーがシミュレーションの挙動を調整するために変更可能なパラメータの一覧です。

### 7.1 環境変数 (`.env`)

| パラメータ名 | 説明 |
|---|---|
| `GEMINI_API_KEY` | **[必須]** Google Gemini APIキー |
| `DISCORD_WEBHOOK_URL` | [任意] シミュレーション完了時のDiscord通知用Webhook URL |

### 7.2 コマンドライン引数

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `--turns` | int | `40` | シミュレーションの実行ターン数 |
| `--resume` | str | なし | 再開するシミュレーションログファイル（`.jsonl`）のパス |
| `--seed` | int | ランダム | 乱数シード（再現性のために設定推奨） |

### 7.3 初期国家設定 (`data/initial_stats.csv`)

各行が1つの国家を定義します。国家の追加・削除もこのファイルで行います。

| カラム名 | 型 | 説明 |
|---|---|---|
| `name` | str | 国名 |
| `government_type` | str | 政治体制（`democracy` / `authoritarian`） |
| `ideology` | str | 国家理念・戦略目標（空欄の場合、AIが自動生成） |
| `economy` | float | 初期GDP（経済力） |
| `military` | float | 初期軍事力 |
| `intelligence_level` | float | 初期諜報レベル |
| `area` | float | 領土面積（km²） |
| `approval_rating` | float | 初期支持率（0-100） |
| `turns_until_election` | int | 【民主主義のみ】次回選挙までのターン数（空欄で無効） |
| `rebellion_risk` | float | 【専制主義のみ】初期反乱リスク（空欄で0） |
| `press_freedom` | float | 報道の自由度（0.0-1.0） |
| `education_level` | float | 教育・人的資本レベル |
| `population` | float | 総人口（百万人単位） |

### 7.4 初期国家間関係 (`data/initial_relations.csv`)

各行が2国間の初期関係を定義します。未定義のペアは自動的に `neutral` になります。

| カラム名 | 型 | 説明 |
|---|---|---|
| `country_a` | str | 国名A |
| `country_b` | str | 国名B |
| `relation_type` | str | 関係タイプ（`alliance` / `neutral` / `at_war`） |
| `trade` | bool | 貿易協定の有無（`true` / `false`） |
| `sanctions_a_to_b` | bool | A→Bへの経済制裁の有無 |
| `sanctions_b_to_a` | bool | B→Aへの経済制裁の有無 |
| `war_aggressor` | str | 戦争状態の場合の攻撃側国名（空欄で非戦争） |

#### 停戦・講和メカニズム

戦争状態（`at_war`）の2国間では、以下の戦争終結メカニズムが利用可能です：

| メカニズム | トリガー | 処理 |
|---|---|---|
| **停戦提案** | 片方が`propose_ceasefire`→翌ターン相手が`accept_ceasefire` | 講和会談へ移行 |
| **降伏勧告** | 攻撃側が`demand_surrender`→防衛側が`accept_surrender` | 無条件降伏として講和会談へ移行 |
| **講和会談** | 停戦/降伏成立後に自動実行 | 占領率に基づく領土・人口移転、賠償金計算、関係リセット |

### 7.5 エンジン定数 (`src/engine/constants.py`)

シミュレーションの数理モデルを制御する定数です。変更には数理モデルの理解が必要です。

#### 政治・支持率

| 定数名 | デフォルト | 説明 |
|---|---|---|
| `DEMOCRACY_WARN_APPROVAL` | `40.0` | 民主主義国の支持率警告閾値 |
| `CRITICAL_APPROVAL` | `15.0` | 支持率の危機的閾値 |
| `WMA_HISTORY_WEIGHT` | `0.8` | 加重移動平均の履歴重み |
| `WMA_BASE_VALUE` | `50.0` | 加重移動平均の基準値 |
| `TAX_APPROVAL_PENALTY_MULTIPLIER` | `200.0` | 増税1%あたりの支持率低下係数 |
| `TAX_REDUCTION_APPROVAL_BONUS_MULTIPLIER` | `100.0` | 減税1%あたりの支持率上昇係数 |
| `MAX_TAX_CHANGE_PER_TURN` | `0.10` | 1ターンの税率変動上限（±10%） |
| `DEMOCRACY_MIN_EXECUTION_POWER` | `0.4` | 民主主義の最低政策実行力 |

#### 経済モデル

| 定数名 | デフォルト | 説明 |
|---|---|---|
| `BASE_ECONOMIC_GROWTH_RATE` | `0.006` | 基礎経済成長率（四半期あたり） |
| `BASE_INVESTMENT_RATE` | `0.14` | 基礎的な民間投資性向 |
| `GOVERNMENT_CROWD_IN_MULTIPLIER` | `0.05` | 経済予算による民間投資誘発乗数 |
| `GOVERNMENT_CROWD_OUT_MULTIPLIER` | `0.15` | 軍事予算による民間投資抑制乗数 |
| `DEBT_REPAYMENT_CROWD_IN_MULTIPLIER` | `0.8` | 債務返済の民間市場還流乗数 |
| `DEBT_TO_GDP_PENALTY_THRESHOLD` | `1.0` | 債務対GDP比ペナルティ発生閾値（100%） |
| `DEBT_INTEREST_RATE` | `0.01` | 国家債務の利払い金利 |
| `MILITARY_CROWDING_OUT_RATE` | `0.002` | 軍事費によるクラウディングアウト率 |

#### 軍事・戦争モデル

| 定数名 | デフォルト | 説明 |
|---|---|---|
| `BASE_MILITARY_GROWTH_RATE` | `0.015` | 基礎軍事成長率 |
| `BASE_MILITARY_MAINTENANCE_ALPHA` | `0.03` | 軍事力の基礎維持費率 |
| `MAX_MILITARY_FATIGUE_ALPHA` | `0.20` | 戦時疲弊による最大減衰率 |
| `DEFENDER_ADVANTAGE_MULTIPLIER` | `1.2` | 防衛側の戦闘力ボーナス倍率 |

#### 貿易モデル

| 定数名 | デフォルト | 説明 |
|---|---|---|
| `DEMOCRACY_BASE_SAVING_RATE` | `0.25` | 民主主義国の基礎貯蓄率 |
| `AUTHORITARIAN_BASE_SAVING_RATE` | `0.30` | 専制主義国の基礎貯蓄率 |
| `TRADE_GRAVITY_FRICTION_ALLIANCE` | `1.0` | 同盟国間の貿易摩擦係数 |
| `TRADE_GRAVITY_FRICTION_NEUTRAL` | `2.0` | 中立国間の貿易摩擦係数 |

#### 諜報・教育・科学

| 定数名 | デフォルト | 説明 |
|---|---|---|
| `INTEL_GROWTH_RATE` | `0.02` | 諜報投資の成長率 |
| `INTEL_MAINTENANCE_ALPHA` | `0.05` | 諜報網の自然減衰率 |
| `EDUCATION_GROWTH_RATE` | `0.05` | 教育投資による人的資本の蓄積速度 |
| `EDUCATION_MAINTENANCE_ALPHA` | `0.015` | 人的資本の自然減衰率 |
| `ENDOGENOUS_GROWTH_ALPHA` | `0.05` | 教育がGDP成長率に与える内生的成長ボーナス係数 |

#### 災害イベント

| 定数名 | デフォルト | 説明 |
|---|---|---|
| `GLOBAL_DISASTERS` | リスト | 世界規模の災害定義（名称, 発生確率, 最小被害%, 最大被害%）|
| `NATIONAL_DISASTERS` | リスト | 国家規模の災害定義（名称, 発生確率, 最小被害%, 最大被害%）|

#### 反乱・クーデター

| 定数名 | デフォルト | 説明 |
|---|---|---|
| `FRAGMENTATION_BASE_INSTABILITY_MULTIPLIER` | `0.2` | 分裂時の基礎不安定度乗数 |
| `FRAGMENTATION_SIZE_FACTOR_MULTIPLIER` | `0.05` | 分裂時の国家規模影響乗数 |
| `FRAGMENTATION_TRADE_FACTOR_MULTIPLIER` | `5.0` | 分裂時の貿易依存度影響乗数 |
| `COUP_BUDGET_RATIO_MIN` | `0.20` | クーデター後の緊急予算リセット比率（最小） |
| `COUP_BUDGET_RATIO_MAX` | `0.30` | クーデター後の緊急予算リセット比率（最大） |

## 8. 実行方法 (Usage)

シミュレーションを実行するには以下のコマンドを使用します。

### 新規シミュレーションの開始
新規にシミュレーションを開始する場合は、以下のように実行します。
```bash
python src/main.py --turns 40
```
`--turns` オプションでシミュレーションを実行するターン数を指定できます（デフォルトは40ターン）。

### 既存のシミュレーションの再開（レジューム機能）
エラーによる停止や中断したシミュレーションを特定のターンから実行したい場合は、`--resume` オプションを用いてログファイル（JSONL）を指定することで、その続きからシミュレーションを再開できます。
システムログおよびシミュレーションログは、新規ファイルを作成するのではなく、既存の該当ログファイルにそのまま追記されます。

```bash
python src/main.py --resume logs/simulations/sim_YYYYMMDD_HHMMSS.jsonl --turns 10
```

## 9. ライセンス (License)

本プロジェクトは [MIT License](./LICENSE) の下で公開されています。
