# AI外交シミュレーション — アーキテクチャ仕様書

> **最終更新**: 2026-04-25  
> **対象ブランチ**: master / v1-2 / v2  
> **このドキュメントだけで本システムを再実装できることを目標とする。**

---

## 1. システム概要

複数のAI国家エージェントが毎ターン、外交・軍事・内政・経済の意思決定を行い、世界情勢が動的に変化するターン制地政学シミュレーション。

### 実行環境
| 項目 | 値 |
|------|---|
| Python | 3.13 (`/opt/homebrew/bin/python3.13`) |
| 仮想環境 | `.venv/` (プロジェクトルート直下) |
| LLM | Google Gemini API（`GEMINI_API_KEY` / `GEMINI_API_KEY_SUB`） |
| モデル用途 | Pro: 大統領方針策定 / Flash: 軍事・外交タスク / Flash-lite: 内政軽量タスク |

### ディレクトリ構成
```
00ai_diplomacy/
├── src/
│   ├── main.py               # エントリポイント・ターンループ
│   ├── models.py             # Pydanticデータモデル全定義
│   ├── logger.py             # コンソール表示・JSONL永続化
│   ├── db_manager.py         # ベクターDB（履歴検索）
│   ├── agent/
│   │   ├── core.py           # AgentSystem: 全タスク実行オーケストレーター
│   │   └── prompts/          # タスク別プロンプトビルダー
│   │       ├── base.py               # build_common_context（共通コンテキスト）
│   │       ├── president_policy.py   # P-01: 大統領施政方針
│   │       ├── major_diplomacy.py    # B-01: 重大外交（宣戦・同盟・停戦）
│   │       ├── budget_normalize.py   # 予算正規化エージェント
│   │       ├── analyst.py            # アナリストレポート生成
│   │       ├── domestic/
│   │       │   ├── tax_rate.py       # I-01: 税率
│   │       │   ├── tariff.py         # I-02: 関税
│   │       │   ├── invest.py         # I-03〜05: 経済/福祉/教育投資
│   │       │   └── governance.py     # I-06〜08: 報道統制/情報偽装/議会
│   │       ├── military/
│   │       │   └── tasks.py          # M-01〜05: 軍事/諜報投資・前線・工作
│   │       └── diplomatic/
│   │           └── tasks.py          # D-01〜08: 外交全タスク
│   └── engine/
│       ├── core.py           # SimulationEngine: 世界ルール適用
│       ├── diplomacy.py      # 外交・諜報処理
│       ├── economy.py        # 経済計算
│       └── energy.py         # エネルギー備蓄・ホルムズ海峡(v1-2)
├── data/
│   ├── initial_stats.csv     # 本番用初期国家データ
│   ├── initial_relations.csv # 本番用初期外交関係
│   ├── energy_import_sources.json  # エネルギー輸入依存(v1-2)
│   └── test/
│       ├── initial_stats.csv     # テスト用(2カ国)
│       └── initial_relations.csv
└── logs/
    └── system/
        ├── system_*.log      # システムログ（全LLM応答含む）
        └── sim_*.jsonl       # シミュレーションデータ（ターン別）
```

---

## 2. データモデル（src/models.py）

### 2-1. CountryState（国家状態）
```python
class CountryState(BaseModel):
    # 基本
    name: str
    government_type: GovernmentType       # "democracy" | "authoritarian"
    ideology: str                         # 自然言語での国家目標
    economy: float                        # 経済力（GDP相当）
    military: float                       # 軍事力
    intelligence_level: float             # 諜報レベル
    population: float                     # 人口(百万人)
    area: float                           # 面積(km²)
    approval_rating: float                # 支持率(%)
    tax_rate: float                       # 税率(0.0〜1.0)
    tariff_rate: Dict[str, float]         # 国別関税率
    national_debt: float                  # 国家債務
    government_budget: float              # 政府予算(ターン毎再計算)
    press_freedom: float                  # 報道の自由度(0.0〜1.0)
    human_capital_index: float            # HCI
    mean_years_schooling: float           # 平均就学年数
    # 投資配分（0.0〜1.0、合計≦1.0が理想）
    invest_economy: float
    invest_military: float
    invest_welfare: float
    invest_education_science: float
    invest_intelligence: float
    # 対外公表値（情報偽装用、Noneなら真値を公開）
    reported_economy: Optional[float]
    reported_military: Optional[float]
    reported_approval_rating: Optional[float]
    reported_intelligence_level: Optional[float]
    reported_gdp_per_capita: Optional[float]
    # 内政イベント
    turns_until_election: Optional[int]
    has_dissolution_power: bool
    rebellion_risk: float
    # 秘匿計画（他国非公開）
    hidden_plans: str
    # 援助依存度
    dependency_ratio: Dict[str, float]
    # エネルギー（v1-2のみ）
    energy_reserve: Optional[float]       # 備蓄（ターン換算）
    energy_reserve_target_turns: Optional[float]
```

### 2-2. WorldState
```python
class WorldState(BaseModel):
    turn: int
    year: int
    quarter: int
    countries: Dict[str, CountryState]
    relations: Dict[str, Dict[str, str]]  # relations[A][B] = "ally"|"neutral"|"hostile"
    active_wars: List[War]
    recurring_aid_contracts: List[AidContract]
    pending_vacuum_auctions: List[dict]
    pending_influence_auctions: List[dict]
    news_events: List[str]                # 当ターンのイベント文字列一覧
    strait_blockade_active: bool          # ホルムズ海峡封鎖状態(v1-2)
    strait_blockade_initiator: Optional[str]
```

### 2-3. AgentAction（エージェントの行動出力）
```python
class AgentAction(BaseModel):
    thought_process: str                  # 思考プロセス（非公開）
    domestic_policy: DomesticAction
    diplomatic_policies: List[DiplomaticAction]
    military_actions: MilitaryAction
    update_hidden_plans: str
    sns_posts: List[str]
```

### 2-4. DomesticAction
```python
class DomesticAction(BaseModel):
    tax_rate: float                       # 0.10〜0.70
    tariff_rate: Dict[str, float]         # 国別関税率
    invest_economy: float
    invest_military: float
    invest_welfare: float
    invest_education_science: float
    invest_intelligence: float
    target_press_freedom: float           # 0.0〜1.0
    report_economy: Optional[float]       # Noneなら真値公開
    report_military: Optional[float]
    report_approval_rating: Optional[float]
    report_intelligence_level: Optional[float]
    report_gdp_per_capita: Optional[float]
    deception_reason: str                 # or "" でNone対策必須
    dissolve_parliament: bool
    reason: str
```

### 2-5. MilitaryAction
```python
class MilitaryAction(BaseModel):
    invest_military: float
    invest_intelligence: float
    reasoning_for_military_investment: str  # or "" でNone対策必須
    war_commitment_ratios: Dict[str, float]
    espionage_gather_intel: bool
    espionage_intel_strategy: Optional[str]
    espionage_sabotage: bool
    espionage_sabotage_strategy: Optional[str]
    reasoning_for_sabotage: str
```

---

## 3. エージェントアーキテクチャ（src/agent/core.py）

### 3-1. タスクエージェント構成

各国毎に以下のタスクを順次実行し、1つのAgentActionを構築する。

#### Phase 0: 大統領施政方針
| タスクID | モデル | 出力型 | ファイル |
|---------|-------|--------|---------|
| P-01 | Pro | PresidentPolicy | `president_policy.py` |

**PresidentPolicy**:
```python
class PresidentPolicy(BaseModel):
    stance: str           # 拡張型/防御型/外交優先型/経済優先型/強権維持型/危機対応型
    directives: List[str] # タスクエージェントへの具体的指示3〜5項目
    hidden_plans: str     # 非公開戦略メモ
    sns_posts: List[str]  # 国民向けSNS
```

#### Phase 1A: 分析官レポート
| タスクID | モデル | 内容 |
|---------|-------|------|
| A-01 | Flash | 軍事バランス・外交リスク分析（対全相手国） |

#### Phase 1B: 内政タスク（flash-lite）
| タスクID | 出力フィールド | 内容 |
|---------|--------------|------|
| I-01 | `tax_rate` | 税率決定（0.10〜0.70、変動上限±10%pt） |
| I-02 | `tariff_rate` | 国別関税率（0.0〜1.0） |
| I-03 | `invest_economy` | 経済投資配分（0.0〜1.0） |
| I-04 | `invest_welfare` | 福祉投資配分 |
| I-05 | `invest_education_science` | 教育・科学投資配分 |
| I-06 | `target_press_freedom` | 報道の自由度（0.0〜1.0） |
| I-07 | `report_*`, `deception_reason` | 対外公表値偽装（null=真値公開） |
| I-08 | `dissolve_parliament` | 議会解散判断（民主主義のみ） |

#### Phase 1B: 予算正規化
- 全投資配分（I-03〜05 + M-01 + M-02）の合計が1.0超の場合、Pro/Flashで按分正規化

#### Phase 1C: 軍事・諜報タスク
| タスクID | モデル | 出力フィールド |
|---------|-------|--------------|
| M-01 | Flash | `invest_military`、`reasoning_for_military_investment` |
| M-02 | Flash-lite | `invest_intelligence` |
| M-03 | Flash | `war_commitment_ratios`（交戦中のみ） |
| M-04 | Flash-lite | `espionage_gather_intel`（対全相手国） |
| M-05 | Flash | `espionage_sabotage`（対全相手国） |

#### Phase 1D: 外交タスク
| タスクID | モデル | 内容 |
|---------|-------|------|
| D-01 | Flash-lite | 外交メッセージ（公開/非公開） |
| D-02 | Flash-lite | 貿易協定の提案/破棄 |
| D-03 | Flash | 経済制裁の発動/解除 |
| D-04 | Flash | 首脳会談の提案/受諾 |
| D-05 | Flash | 多国間協議の提案/受諾 |
| D-06 | Flash | 対外援助の設定（サブスク制） |
| D-07 | Flash-lite | 援助受入率の設定（0.0=拒否〜1.0=全額） |
| D-08 | Flash | パワーバキューム入札 |

#### Phase 2: 重大外交（B-01）
| タスクID | モデル | 内容 |
|---------|-------|------|
| B-01 | Pro | 宣戦/同盟提案/停戦/合併/降伏（対全相手国） |

### 3-2. プロンプト設計原則

> **重要**: プロンプトの出力例（JSONサンプル）に**具体的な数値を書いてはならない**。LLMはサンプル値をそのままコピーする傾向があり、全国家が同一の値を返す問題が発生する。

```python
# ❌ 悪い例（全国家が0.30を返す）
{"tax_rate": 0.30, "reason": "理由"}

# ✅ 良い例（LLMが文脈から判断する）
{"tax_rate": ???, "reason": "理由"}
```

数値が必要な文脈情報は**プロンプト本文のデータとして**渡し、JSONサンプルには `???` プレースホルダーを使う。

### 3-3. タスクログ収集
- `AgentSystem._execute_agent()` は全タスクのLLM生JSONレスポンスを `_task_log_buffer` に蓄積
- `generate_actions()` は `(actions, analyst_reports, all_task_logs)` の3タプルを返す
- `all_task_logs` は `{国名: {タスクID: 生レスポンスdict}}` の構造

---

## 4. シミュレーションエンジン（src/engine/）

### 4-1. process_turn()の処理順序
1. 全国家の投資配分を正規化（合計が1.0超の場合）
2. 税収・関税収入から国家予算を計算（債務利子 1%/ターン差引）
3. 経済成長計算（HCI乗数・投資効果・隣国交易）
4. 軍事力更新（invest_military × budget × growth_factor）
5. 諜報力更新
6. 支持率更新（税率・経済成長・福祉投資・HCIの関数）
7. HCI更新（教育投資・就学年数の関数）
8. 外交処理（制裁・貿易・援助・依存度更新）
9. 軍事衝突判定（リチャードソンモデル）
10. 諜報処理（収集成功/失敗・破壊工作）
11. 選挙・クーデター・反乱処理
12. 自然災害・技術革新イベント生成（乱数）
13. ニュースイベントリストに全結果を追記

### 4-2. 経済モデル
```
GDP成長率 = base_rate + invest_economy × budget_multiplier + hci_bonus + trade_bonus - tax_drag
政府予算  = economy × tax_rate + tariff_revenue - national_debt × 0.01
```

### 4-3. 軍事衝突モデル（リチャードソン軍備競争）
```
attack_power = military × commitment_ratio × (1 + tech_bonus)
defense_power = military × commitment_ratio × (1 + hci_bonus)
if attack_power > defense_power × 1.2:  占領進行
elif defense_power > attack_power × 1.2: 逆転占領
occupation_progress += delta  # 100%到達で征服
```

### 4-4. エネルギー備蓄システム（v1-2のみ, src/engine/energy.py）

#### 備蓄計算
```
毎ターン消費 = 1.0 ターン分
輸入によるゲイン = Σ(輸入依存度[供給国] × 供給量)
ホルムズ封鎖中: 中東依存国は gain = 0（代替ルート分のみ）
energy_reserve = max(0, energy_reserve - 1.0 + gain)
```

#### 備蓄枯渇ペナルティ
| 備蓄残量 | ペナルティ |
|---------|---------|
| ≤ 0 | 経済力 ×0.85、軍事力 ×0.90/ターン |
| 0〜1T | 軽微なGDP減少 |

#### ホルムズ海峡封鎖
- `world_state.strait_blockade_active = True` で発動
- タスクエージェントM-03の特殊ターゲット `__STRAIT_BLOCKADE__` で制御
- 封鎖国はエネルギー収入が停止し、中東依存国に経済ペナルティが発生
- `data/energy_import_sources.json` で各国の輸入依存先を定義

---

## 5. ロギングシステム（src/logger.py）

### 5-1. コンソール出力（Rich）

| セクション | 内容 |
|-----------|------|
| 1. 国家ステータス | 全国家の主要指標テーブル |
| 2. ニュース・イベントログ | 前ターンのイベント一覧 |
| 3. 各国の意思決定 | 🧠パネル（思考120文字・内政1行・外交リスト・SNS1件） |
| 4. 災害・技術革新 | 該当イベントのみ抽出表示 |
| 5. 外交・制裁イベント | 外交イベントのみ抽出 |
| 6. 首脳会談 | 会談内容（非公開フラグ対応） |
| 7. 軍事衝突 | 戦争状況テーブル |
| 8. 諜報活動 | 成功/失敗結果 |
| 9. メディア報道 | AI生成メディアレポート（🗞️マークのみ） |
| 10. SNSタイムライン | 首脳/市民/工作のSNS投稿 |
| 📊 ターンサマリー | 各国の変化量テーブル（差分カラー表示） |

### 5-2. コンソール表示ルール
- **首脳の脳内パネル（🧠）はコンパクト化**
  - 思考：先頭120文字のみ
  - 内政：`税30% | 経35% 軍15% 福25% 教5% 諜10%` の1行形式
  - 秘匿計画は**表示しない**（思考と重複）
  - SNS：1件・60文字
- **セクション9はメディア報道のみ**（外交イベントはセクション5で完結）

### 5-3. JSONL永続化スキーマ（logs/system/sim_*.jsonl）
```json
{
  "turn": 1,
  "timestamp": "2026-04-24T21:40:00",
  "world_state": { ... },
  "actions": { "日本": { ... }, ... },
  "analyst_reports": { "日本": { "中国": "レポート文" } },
  "task_logs": {
    "日本": {
      "P-01": { "stance": "経済優先型", "directives": [...] },
      "I-01": { "tax_rate": 0.28, "reason": "..." },
      ...
    }
  }
}
```

### 5-4. システムログ（logs/system/system_*.log）
- 全LLMレスポンス（生テキスト）を含む
- タスクごとに `[INFO] [国名:タスクID] API推論開始...` / `レスポンス受信完了 (所要時間: X.XXs)` を記録
- エラー時は `[ERROR]` レベルで記録

---

## 6. メインループ（src/main.py）

```python
for _ in range(MAX_TURNS):
    # スナップショット保存（ターンサマリー用）
    _country_snapshot = {name: {...} for name, c in world_state.countries.items()}
    
    engine.process_pre_turn()          # 選挙・クーデター先行判定
    logger.display_turn_header()
    logger.display_country_status()
    logger.display_world_events()      # 前ターン結果
    
    # AI行動決定（全タスク実行）
    actions, analyst_reports, task_logs = agent_system.generate_actions(world_state)
    
    # 首脳の意思決定表示
    for country, action in actions.items():
        logger.display_agent_thoughts(country, action)
    
    world_state = engine.process_turn(actions)   # 世界更新
    engine._process_strait_blockade_actions(actions)  # 封鎖処理(v1-2)
    
    # セクション4〜10の表示...
    
    media_reports, media_modifiers = agent_system.generate_media_reports(...)
    engine.evaluate_public_opinion(sns_timelines, media_modifiers)
    
    logger.save_turn_log(world_state, actions, analyst_reports, task_logs)
    
    # ターンサマリー
    logger.display_turn_summary(_country_snapshot, world_state)
    
    engine.advance_time()   # quarter/year進行
    time.sleep(3)
```

---

## 7. 起動コマンド

```bash
# 通常実行
.venv/bin/python ./src/main.py --turns 5

# テストデータで実行
.venv/bin/python ./src/main.py --turns 1 --data-dir data/test

# ログから再開
.venv/bin/python ./src/main.py --resume logs/system/sim_YYYYMMDD_HHMMSS.jsonl --turns 3

# 乱数シード固定
.venv/bin/python ./src/main.py --turns 5 --seed 42
```

---

## 8. ブランチ戦略

| ブランチ | 用途 | 固有機能 |
|---------|------|---------|
| `master` | 本番安定版 | 基本シミュレーション |
| `v1-2` (v1-2：海峡封鎖＋エネルギー枯渇シナリオ) | エネルギーシナリオ | ホルムズ海峡封鎖・エネルギー備蓄枯渇 |
| `v2` | 実験的タスクエージェント制 | v1-2ベースに高度な意思決定ロジック |

---

## 9. 既知のバグ・注意事項

### 9-1. LLMのnull返却問題
`deception_reason` と `reasoning_for_military_investment` はLLMが `null` を返すことがある。
**必ず `or ""` でフォールバックすること**:
```python
deception_reason = raw.get("deception_reason") or ""
reasoning_for_military_investment = raw.get("reasoning_for_military_investment") or ""
```

### 9-2. 税率・投資率の固定値問題（解決済み）
プロンプトの出力例JSONに具体的数値を書くとLLMがコピーし、全国家が同じ値を返す。
→ `???` プレースホルダーに変更済み（v1-2.13 / 2026-04-25）

### 9-3. promptファイル消失問題（解決済み）
`src/agent/prompts/domestic/`, `military/`, `diplomatic/` 配下のファイルがGit未追跡状態で消失し、`__pycache__` のみで動作していた。
→ Git履歴から復元済み（v1-2.11 / 2026-04-25）

### 9-4. tax_rateの単位補正
LLMが `0.30`（小数）ではなく `30.0`（パーセント値）を返すことがある。
```python
if new_tax_rate >= 1.0:
    new_tax_rate /= 100.0
```
この補正は `core.py` と `logger.py` の両方で実施。

---

## 10. 環境変数

```bash
GEMINI_API_KEY=<primary key>       # Proモデル・Flash使用
GEMINI_API_KEY_SUB=<secondary key> # Flash-lite・サブ処理用
```

`.env` ファイルをプロジェクトルートに配置して `python-dotenv` で読み込む。
