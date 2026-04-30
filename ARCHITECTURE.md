# AI外交シミュレーション — アーキテクチャ仕様書

> **最終更新**: 2026-04-30  
> **対象ブランチ**: master / v1-2 / v1-3 / v2  
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
│       ├── constants.py      # 全定数（TURNS_PER_YEAR, 信用スプレッド等）
│       ├── diplomacy.py      # 外交・諜報処理
│       ├── domestic.py       # 内政・マクロ経済モデル
│       ├── economy.py        # 貿易・関税計算
│       ├── nuclear.py        # 核兵器システム(v1-3)
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
    national_debt: float                  # 国家債務(B$)
    government_budget: float              # 政府予算(ターン毎再計算, 利払い後の可処分額)
    press_freedom: float                  # 報道の自由度(0.0〜1.0)
    human_capital_index: float            # HCI（MYSからcompute_pwt_hci()で自動算出。CSVの値は無視）
    mean_years_schooling: float           # 平均就学年数
    # 投資配分（v1-3: 金額ベース(B$)。旧版は0.0〜1.0比率）
    invest_economy: float
    invest_military: float
    invest_welfare: float
    invest_education_science: float
    invest_intelligence: float
    # 核兵器(v1-3)
    nuclear_warheads: int                 # 保有核弾頭数
    nuclear_development_step: int         # 核開発段階(0:未着手〜4:保有国)
    nuclear_hosted_warheads: int          # 他国から配備された核弾頭数
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
| I-03 | `invest_economy` | 経済投資要求（金額B$） |
| I-04 | `invest_welfare` | 福祉投資要求（金額B$） |
| I-05 | `invest_education_science` | 教育・科学投資要求（金額B$） |
| I-06 | `target_press_freedom` | 報道の自由度（0.0〜1.0） |
| I-07 | `report_*`, `deception_reason` | 対外公表値偽装（null=真値公開） |
| I-08 | `dissolve_parliament` | 議会解散判断（民主主義のみ） |

#### Phase 1E: 予算配分（B-01）
- 各タスクエージェント（I-03〜05, M-01, M-02）から**金額(B$)ベース**の要求を受領
- B-01（Flash-lite）が歳入と要求を比較し、最終配分を決定
- 歳入不足時は赤字国債発行を判断（発行額も金額ベースで指定）
- 赤字国債 → `national_debt` に加算、金利計算に反映

#### Phase 1C: 軍事・諜報タスク
| タスクID | モデル | 出力フィールド |
|---------|-------|--------------|
| M-01 | Flash | `request_military`(B$)、`request_nuclear`(B$)、`nuclear_use_recommendation` |
| M-02 | Flash-lite | `request_intelligence`(B$) |
| M-03 | Flash | `war_commitment_ratios`（交戦中のみ） |
| M-04 | Flash-lite | `espionage_gather_intel`（対全相手国） |
| M-05 | Flash | `espionage_sabotage`（対全相手国） |

> **M-01の核使用提言**: `nuclear_use_recommendation`（"tactical:対象国名" or "strategic:対象国名" or null）
> M-01が提言した場合、`hidden_plans`に`[M-01核使用提言]`として保存され、次ターンのP-02で大統領に表示される。

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

#### Phase 2: 重大外交（P-02）
| タスクID | モデル | 内容 |
|---------|-------|------|
| P-02 | Flash | 宣戦/同盟提案/停戦/合併/降伏/☢️核使用/海峡封鎖（対全相手国） |

> **先制核攻撃**: P-02は交戦中でなくても`launch_tactical_nuclear`/`launch_strategic_nuclear`を発行可能。
> 先制攻撃の場合、エンジン側で自動的にWarState作成＋RelationType.AT_WARに更新される。

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

### 4-1. ターン時間軸パラメータ
```python
TURNS_PER_YEAR = 4  # 1ターン = 四半期（変更可能）
```
年間GDPをストック量として保持し、税収・利払い等のフロー量は `/TURNS_PER_YEAR` で四半期化する。

### 4-2. process_turn()の処理順序
1. **基礎予算の算出**: 税収(年間GDP×税率/TURNS_PER_YEAR) + 関税収入 - 利払い
2. 全国家の投資配分を正規化（金額ベースで歳入超過時は按分）
3. 経済成長計算（SNAモデル: Y = C + I + G + NX）
4. 軍事力更新（リチャードソン軍備競争モデル）
5. 諜報力更新
6. 支持率更新（税率・経済成長・福祉投資・HCIの関数）
7. HCI更新（教育投資・就学年数の関数）
8. 外交処理（制裁・貿易・援助・依存度更新）
9. 軍事衝突判定
10. 核兵器処理（開発進行・量産・使用・先制攻撃）
11. 諜報処理（収集成功/失敗・破壊工作）
12. 選挙・クーデター・反乱処理
13. 自然災害・技術革新イベント生成（乱数）
14. ニュースイベントリストに全結果を追記

### 4-3. 財政モデル（v1-3）

#### 税収（四半期化）
```python
tax_revenue_per_turn = (economy * tax_rate) / TURNS_PER_YEAR
```

#### 信用スプレッドモデル（Harvard研究準拠）
```python
# 定数（全て年率で定義）
DEBT_INTEREST_RATE_ANNUAL = 0.025    # 基本金利 2.5%/年
DEBT_SPREAD_THRESHOLD = 0.90         # 閾値: 債務GDP比90%
DEBT_SPREAD_SENSITIVITY = 0.006      # 感度: 10%pt超過で+60bp/年
DEBT_SPREAD_CAP_ANNUAL = 0.15        # 上限: 年率15%（ギリシャ危機級）

# 計算
debt_ratio = national_debt / GDP
if debt_ratio > 0.90:
    spread = min((debt_ratio - 0.90) * 0.006, 0.15)
    effective_rate = (0.025 + spread) / TURNS_PER_YEAR
else:
    effective_rate = 0.025 / TURNS_PER_YEAR

interest_payment = national_debt * effective_rate
government_budget = max(0, tax_revenue + tariff_revenue - interest_payment)
```

**学術的根拠**:
- Harvard研究 (Reinhart et al.): 先進国で債務GDP比10%pt増 → +6bp/年
- シミュレーション加速のため実証値の10倍の感度（+60bp/年）を使用
- 日本(GDP比260%超)で実効金利≈3.4%/年（現実の10年債利回り2.47%/年に近似）

#### 赤字国債モデル
- B-01が歳入不足と判断した場合、赤字国債を発行
- 発行額は`national_debt`に加算
- 次ターンから利払い対象に含まれる（動的金利モデル適用）

#### デフォルト処理
```python
if total_revenue < interest_payment:
    government_budget = 0.0
    national_debt += (interest_payment - total_revenue)  # 未払い利息の元本組み込み
```

### 4-4. 経済成長モデル（SNAベース: Y_q = C_q + I_q + G_q + NX_q, 四半期統一）
```
quarterly_gdp = GDP / TURNS_PER_YEAR
tax_q = GDP × 税率 / TURNS_PER_YEAR

C_q = (quarterly_gdp - tax_q) × (1 - 貯蓄率)     # ケインズ型消費関数（四半期）

# 利払いリーケージ修正: 税収から利払いに使われた分は債権者への所得移転
# その70%が国内民間投資に再投資される [Mankiw "Macroeconomics" Ch.3]
interest_leakage = max(0, tax_q - budget)
interest_reinvested = interest_leakage × 0.70  # INTEREST_REINVESTMENT_RATE

I_q = 民間貯蓄_q × 0.95 + interest_reinvested + 政府経済投資 × クラウドイン - 軍事投資 × クラウドアウト
G_q = 政府支出合計（予算 × 投資配分 × 政策実行力）  # 予算は四半期ベース（利払い後）
NX_q = 純輸出（重力モデルで計算、当ターンフロー）

新GDP = (C_q + I_q + G_q) × HCI乗数 × (1 + 内生的成長) × TURNS_PER_YEAR + NX_q × TURNS_PER_YEAR
```

GDP成長率フロア: 四半期あたり-5%（Álvarez-Pereira et al. 2022）

### 4-5. 軍事衝突モデル（リチャードソン軍備競争）
```
attack_power = military × commitment_ratio × (1 + tech_bonus)
defense_power = military × commitment_ratio × (1 + hci_bonus)
if attack_power > defense_power × 1.2:  占領進行
elif defense_power > attack_power × 1.2: 逆転占領
occupation_progress += delta  # 100%到達で征服
```

### 4-6. 核兵器システム（v1-3, src/engine/nuclear.py）

#### 核開発フロー
| Step | 名称 | 条件 |
|------|------|------|
| 0 | 未着手 | - |
| 1 | ウラン濃縮 | `request_nuclear > 0` で進行 |
| 2 | 核実験成功 | 累積投資閾値到達 |
| 3 | 実戦配備 | 累積投資閾値到達 |
| 4 | 核保有国 | 弾頭量産可能 |

#### 核弾頭量産
- Step4到達後、`request_nuclear`予算で量産
- **1四半期あたり最大50発**のキャップ
- 製造コストは `national_warhead_cost` で国別設定
- 製造コストは**政府予算(government_budget)から差し引き**

#### 核使用（戦術核・戦略核）
- **P-02（大統領）が最終決定**: `launch_tactical_nuclear` / `launch_strategic_nuclear`
- **交戦中でなくても使用可能（先制核攻撃）**
- 先制核攻撃時: 自動宣戦布告（WarState作成 + RelationType.AT_WAR）
- 戦術核先制: 奇襲効果（commitment=1.0 → 相手全軍が無防備）

#### M-01→P-02 核使用提言フロー
```
M-01: nuclear_use_recommendation → hidden_plansに[M-01核使用提言]を保存
  ↓ (1ターン遅延)
P-02: hidden_plansから提言を読み取り → 核使用の最終判断
```

### 4-7. エネルギー備蓄システム（v1-2以降, src/engine/energy.py）

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
- P-02の`declare_strait_blockade`/`resolve_strait_blockade`で制御
- 封鎖国はエネルギー収入が停止し、中東依存国に経済ペナルティが発生
- `data/energy_import_sources.json` で各国の輸入依存先を定義

### 4-8. 制裁ダメージモデル（v1-3.2, src/engine/economy.py）

#### 学術的根拠
- **Neuenkirch & Neumeier (2015, European J. Political Economy)**: UN制裁でGDP/C -2.3〜-3.5%pt/年
- **Gutmann, Neuenkirch & Neumeier (2021, J. Comparative Economics)**: 効果は最初の2年に集中
- **Hufbauer, Schott & Elliott (2007, "Economic Sanctions Reconsidered" 3rd Ed.)**: 発動国コスト平均-0.4%/年

#### 伝達チャネル
制裁はGDPを直接削るのではなく、SNAの各構成要素を個別に毀損する:
1. **貿易チャネル(NX)**: 重力モデル(`GRAVITY_SANCTION_DISTANCE_FACTOR=10.0`)で処理済み ✅
2. **投資チャネル(I)**: FDI撤退・政治リスクによる投資萎縮 → 残余ダメージとして適用
3. **金融チャネル(G)**: 資産凍結等による歳入減少 → 残余ダメージとして適用
4. **消費チャネル(C)**: インフレ・物資不足 → 貯蓄率上昇で間接的に表現

#### ダメージ計算（非貿易チャネル残余分）
```python
# 対象国: 1件あたり min(1.5%, 0.5 × imposer_GDP/target_GDP)
# 複数制裁は加算方式で集計後、累積キャップ2.0%/ターン（年-8%相当）を適用
SANCTION_TARGET_DAMAGE_PER_CASE = 0.5   # GDP比率係数
SANCTION_TARGET_MAX_PER_CASE = 1.5      # 1件上限（年-6%）
SANCTION_TARGET_MAX_CUMULATIVE = 2.0    # 累積上限（年-8%）

# 発動国: 1件あたり0.1%/ターン（年-0.4%）、合計最大0.5%/ターン
# ※ 貿易損失は重力モデルで処理済み。残余はサプライチェーン断絶・管理コスト
SANCTION_SENDER_COST_PER_CASE = 0.001   # 0.1%/件
SANCTION_SENDER_MAX_COST = 0.005        # 合計上限0.5%
```

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
| `v1-2` | エネルギーシナリオ | ホルムズ海峡封鎖・エネルギー備蓄枯渇 |
| `v1-3` | **核外交・財政改革** | 核兵器システム・金額ベース予算・信用スプレッド・赤字国債・先制核攻撃 |
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

### 9-5. 核弾頭量産の暴走（v1-3で解決済み）
核弾頭製造時に政府予算からコストが差し引かれていなかったため、無限量産が発生。
→ 製造コストの予算差し引き + 1四半期50発キャップを導入（v1-3 / 2026-04-28）

### 9-6. 税収の年間×4倍徴収バグ（v1-3で解決済み）
1ターン=四半期なのに、税収を`GDP × tax_rate`（年間分）で毎ターン徴収していた。
→ `(GDP × tax_rate) / TURNS_PER_YEAR` に修正（v1-3 / 2026-04-29）

### 9-7. 信用スプレッドの過剰設定（v1-3で解決済み）
旧モデル: 60%超で`(ratio-0.6)×5%/Q` → 日本で実効金利12.4%/Q（年率50%）。
→ Harvard研究に基づく年率ベースモデルに再設計。日本で≈3.4%/年に修正（v1-3 / 2026-04-29）

### 9-8. D-01/D-05 listエラー（未解決）
`'list' object has no attribute 'get'` — LLMが外交メッセージを辞書ではなくリストで返すことがある。
デフォルト値で継続するため致命的ではないが、外交メッセージが欠落する。

### 9-9. Turn 1 HCI乗数バグによる全国GDP -50%収縮（v1-3.1で解決済み）
CSVの `human_capital_index` 列に不正値（北朝鮮:0.01, 韓国:0.52, 中国:0.12, ロシア:0.05）が混入しており、
Turn 1のHCI乗数が `max(0.5, ratio)` = 0.5にクランプされ、C+I+G総需要が半減していた。
→ `main.py` の `initialize_world()` で `compute_pwt_hci(mean_years_schooling)` から自動算出するように修正（v1-3.1 / 2026-04-30）

### 9-10. 制裁ダメージの過大評価（v1-3.2で解決済み）
旧モデルでは制裁1件あたり最大10%/ターン（年-40%）のGDP直接乗算を行い、複数制裁が乗算方式で蓄積していた。
北朝鮮が韓国+アメリカから制裁を受けると実質-19%/ターン（年-76%）のオーバーシュート。
発動国コストも1件あたり-1%/ターン（年-4%）で乗算され、3件発動で-3%/ターン（年-12%）。
学術値（対象国: 年-3.5%、発動国: 年-0.4%）の8〜30倍の過大評価。
→ 対象国ダメージを加算→累積キャップ方式（最大2.0%/ターン）に変更。発動国コストを0.1%/件（最大0.5%/ターン）に引き下げ。
（v1-3.2 / 2026-04-30）

### 9-11. advance_time()内の財政ペナルティ二重課税（v1-3.2で解決済み）
`domestic.py`のコメントで「利払いで表現済み。直接GDPを削るペナルティは二重計上防止のため廃止」と明記されているにもかかわらず、
`core.py`の`advance_time()`に財政規律ペナルティ（`economy *= (1 - penalty/100)`）が残存していた。
国債がわずかでもある全国家が毎ターン末にGDPを直接削られていた。
→ 該当コードを削除（v1-3.2 / 2026-04-30）

---

## 10. 環境変数

```bash
GEMINI_API_KEY=<primary key>       # Proモデル・Flash使用
GEMINI_API_KEY_SUB=<secondary key> # Flash-lite・サブ処理用
```

`.env` ファイルをプロジェクトルートに配置して `python-dotenv` で読み込む。
