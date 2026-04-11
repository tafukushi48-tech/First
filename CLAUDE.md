# CLAUDE.md — HAE論文自動収集・分類管理プロジェクト

このファイルはClaude Codeがこのリポジトリで作業する際に参照する永続ルール集です。
コードを変更・追加する前に必ずこのファイルを読み直してください。

---

## プロジェクト目的

Hereditary Angioedema (HAE) に関する学術論文を PubMed および Europe PMC から
自動収集し、Medical Affairs 活動に資する形で分類・蓄積・管理するシステムを構築する。

### 対象疾患

- **HAE type 1** — C1-INH 量的欠乏（SERPING1 変異）
- **HAE type 2** — C1-INH 機能的欠乏（SERPING1 変異）
- **HAE with normal C1-INH (HAE-nC1-INH)** — FXII, PLG, ANGPT1, KNG1, MYOF, HS3ST6 変異を含む
- 上記に加え、bradykinin-mediated angioedema 全般を補助的に収集対象とする

### 主な利用者・用途

Medical Affairs チームによる：
- エビデンスランドスケープの把握
- 競合品・新規治療の動向モニタリング
- パイヤー対応・価値訴求の根拠文献管理
- 社内ナレッジベースへの蓄積

---

## 永続ルール

以下のルールはいかなる実装においても例外なく遵守すること。

### R-01 スキーマ不変の原則
`papers_master.csv` のカラム定義（名前・順序・型）は `src/storage/csv_store.py` の
`SCHEMA` 定数で一元管理する。カラムの追加・削除・改名は必ず SCHEMA を先に変更し、
移行スクリプトを用意してからコードに反映する。

### R-02 追記専用の原則
`papers_master.csv` への書き込みは **append-only** とする。既存レコードの上書き・
削除は専用の補正スクリプト（`scripts/correct_record.py`）経由でのみ行う。
パイプライン本体から既存行を削除する処理を書いてはならない。

### R-03 バックアップ必須の原則
パイプライン実行開始時、`papers_master.csv` を `data/backups/papers_master_YYYYMMDD_HHMMSS.csv`
へ自動コピーしてから処理を開始する。バックアップを省略する実装は認めない。

### R-04 APIキー外部管理の原則
PubMed (NCBI) の API キーおよびその他のクレデンシャルは環境変数または `.env` ファイルで
管理し、コードにハードコードしない。`.env` は `.gitignore` に含める。
環境変数名: `NCBI_API_KEY`, `NCBI_EMAIL`

### R-05 レート制限遵守の原則
- PubMed: API キーあり 10 req/s、なし 3 req/s を上限とする
- Europe PMC: 10 req/s を上限とする
- すべての外部APIコールはリトライ付きラッパー（`src/utils/http.py`）を通すこと

### R-06 MA relevance 必須の原則
すべての論文レコードは `ma_relevance_score`（0–3 の整数）および
`ma_relevance_reason`（理由文字列）を必ず持つ。
未分類のまま CSV に保存してはならない（デフォルト値 0 は許容）。

### R-07 文字コードの原則
すべての CSV ファイルは **UTF-8 (BOM なし)** で保存する。
pandas の読み書きには常に `encoding="utf-8"` を明示する。

### R-08 ログ必須の原則
パイプライン実行ごとに `data/logs/run_YYYYMMDD_HHMMSS.log` を生成し、
以下を記録する：取得件数、重複除去件数、新規追加件数、エラー件数、実行時間。

---

## 分類定義

分類ルールの実体は `config/classifiers.yaml` に記述し、コードから参照する。
以下はその仕様定義であり、yamlの内容と常に一致させること。

### 1. disease_subtype（疾患サブタイプ）

| 値 | 定義 |
|---|---|
| `HAE_type1_2` | HAE type 1 または type 2（C1-INH 欠乏、SERPING1 変異） |
| `HAE_nC1INH` | HAE with normal C1-INH（FXII, PLG, ANGPT1, KNG1, MYOF, HS3ST6） |
| `HAE_general` | サブタイプ不明または HAE 総論 |
| `bradykinin_AE` | Bradykinin 性浮腫（ACE阻害薬誘発など、HAEと関連性あり） |
| `other_AE` | その他の血管性浮腫（histamine性など、比較対照目的） |
| `unclassified` | 自動分類不可（手動レビュー要） |

### 2. treatment_area（治療領域）

| 値 | 定義 |
|---|---|
| `acute_treatment` | 急性発作治療（icatibant, C1-INH concentrate, ecallantide 等） |
| `short_term_prophylaxis` | 短期予防（処置前投与等） |
| `long_term_prophylaxis` | 長期予防（lanadelumab, berotralstat, C1-INH SC 等） |
| `gene_therapy` | 遺伝子治療・RNA 療法（garadacimab, donidalorsen 等も含む新規MOA） |
| `diagnosis_biomarker` | 診断・バイオマーカー研究 |
| `epidemiology_burden` | 疫学・疾病負荷 |
| `quality_of_life` | QoL・患者報告アウトカム |
| `pathophysiology` | 病態生理・基礎研究 |
| `guideline_review` | ガイドライン・総説 |
| `other` | 上記に該当しない |

### 3. publication_type（論文種別）

| 値 | Oxford EBM 参考 |
|---|---|
| `RCT` | ランダム化比較試験 |
| `meta_analysis` | メタ解析・システマティックレビュー |
| `observational` | コホート・症例対照・横断研究 |
| `case_report` | 症例報告・症例集積 |
| `review` | narrative review |
| `guideline` | 診療ガイドライン・コンセンサス文書 |
| `editorial_letter` | 編集・レター・コメンタリー |
| `basic_research` | 基礎・in vitro / in vivo 研究 |
| `other` | 上記に該当しない |

### 4. evidence_level（エビデンスレベル）

Oxford Centre for Evidence-Based Medicine 2011 に準拠。

| 値 | 定義 |
|---|---|
| `1a` | SR of RCTs |
| `1b` | Individual RCT |
| `2a` | SR of cohort studies |
| `2b` | Individual cohort study / low-quality RCT |
| `3a` | SR of case-control studies |
| `3b` | Individual case-control study |
| `4` | Case series / poor cohort or case-control |
| `5` | Expert opinion / basic research |
| `unclassified` | 自動判定不可 |

publication_type から evidence_level へのデフォルトマッピングを
`classifiers.yaml` に定義し、classifier.py で参照する。

### 5. ma_relevance_score（Medical Affairs 関連度）

| スコア | 基準 |
|---|---|
| `3` | 直接的に MA 活動に使用できる（RCT 結果、ガイドライン、comparative effectiveness） |
| `2` | 間接的に有用（疫学データ、QoL、real-world evidence） |
| `1` | 参考資料として保持（基礎研究、editorial 等） |
| `0` | MA 関連性が低い（デフォルト。要レビュー） |

`ma_relevance_reason` には自動分類の根拠を 100 字以内の日本語で記録する。

---

## データスキーマ

`papers_master.csv` の全カラムを以下に定義する。順序は変更しない。

```
pmid                  # PubMed ID（文字列、なければ空）
doi                   # DOI（文字列、なければ空）
title                 # 論文タイトル（UTF-8）
abstract              # アブストラクト（UTF-8、なければ空）
authors               # 著者リスト（セミコロン区切り）
journal               # ジャーナル名
pub_year              # 出版年（整数）
pub_date              # 出版日（YYYY-MM-DD、不明は YYYY-01-01）
source                # 取得元（"pubmed" / "europepmc" / "manual"）
disease_subtype       # 分類1
treatment_area        # 分類2
publication_type      # 分類3
evidence_level        # 分類4
ma_relevance_score    # 分類5（整数 0–3）
ma_relevance_reason   # MA関連度の根拠（日本語、100字以内）
classifier_version    # 分類ルールのバージョン（semver文字列）
collected_at          # 収集日時（ISO 8601 UTC）
review_flag           # 手動レビュー要否（True/False）
notes                 # 自由記述（手動補記用）
```

---

## コーディング方針

### 言語・バージョン
- Python 3.11 以上を前提とする
- 型ヒントを積極的に使用する（`from __future__ import annotations` を各ファイル先頭に）

### コメント・ドキュメント
- モジュール・クラス・関数の docstring は **日本語**で記述する
- コード識別子（変数名・関数名・クラス名）は **英語**（snake_case / PascalCase）
- 複雑なロジックには日本語インラインコメントを付ける

### 依存ライブラリ
- HTTP 通信: `requests` + `tenacity`（リトライ）
- データ処理: `pandas`
- PubMed: `biopython` の `Entrez` モジュール
- 設定読み込み: `PyYAML`
- ロギング: 標準ライブラリ `logging`（外部ライブラリ不使用）
- テスト: `pytest`

### 設計原則
- 収集・重複除去・分類・保存の各層は独立したモジュールとし、相互依存を避ける
- `pipeline.py` 以外からは `csv_store.py` の書き込み関数を呼ばない
- 分類ロジックは最初はルールベース（正規表現 + キーワードマッチ）で実装する
  - ML/LLM への移行は `classifier.py` のインターフェースを変えずに差し替え可能な設計にする
- 外部APIの呼び出しは必ずモック可能な設計にし、テスト時はネットワーク不要にする

### エラー処理
- 個別論文の取得・分類エラーはスキップしてログに記録し、パイプライン全体を止めない
- CSV 書き込み失敗は致命的エラーとして即時停止する
- 未知の分類値は `unclassified` にフォールバックし、`review_flag = True` を立てる

---

## データ品質ルール

### 必須チェック（保存前に validate して弾く）
- `title` が空のレコードは保存しない
- `pmid` と `doi` が両方空のレコードは保存しない
- `pub_year` が 1900 未満または現在年超のレコードは警告ログを出す
- `ma_relevance_score` が 0–3 の整数以外は保存しない

### 重複判定ルール（優先順位順）
1. `pmid` が一致 → 重複
2. `doi` が一致（大文字小文字・前後スペース正規化後）→ 重複
3. 両方空の場合: `title` を正規化（小文字・記号除去）して一致確認 → 重複候補として `review_flag = True` で保存

### 手動レビュー対象
以下の条件に1つでも該当するレコードは `review_flag = True` を立てる：
- `disease_subtype = "unclassified"`
- `evidence_level = "unclassified"`
- `ma_relevance_score = 0`
- タイトル重複候補（PMIDもDOIも空）

---

## 変更時の注意点

### スキーマ変更時
1. このファイルの「データスキーマ」セクションを先に更新する
2. `src/storage/csv_store.py` の `SCHEMA` 定数を更新する
3. 既存の `papers_master.csv` を移行するスクリプト `scripts/migrate_schema_vX_to_vY.py` を作成する
4. `classifier_version` をインクリメントする
5. テストのフィクスチャデータも更新する

### 分類ルール変更時
1. このファイルの「分類定義」セクションを先に更新する
2. `config/classifiers.yaml` を更新する
3. `classifier_version` をインクリメントする（semver: バグ修正→patch, ルール追加→minor, 体系変更→major）
4. 既存レコードへの再分類が必要な場合は `scripts/reclassify.py` を作成・実行する

### 新しいデータソース追加時
- `src/collectors/` に新モジュールを追加し、既存のPubMed/Europe PMCと同じ出力スキーマに正規化する
- `source` カラムの有効値をこのファイルに追記する
- `pipeline.py` への組み込みは最小限の変更で済む設計を維持する

### 週次自動実行の設定変更時
- `scripts/run_weekly.sh` と GitHub Actions の `.github/workflows/weekly_collect.yml` は必ず同期させる
- 実行スケジュールを変更する場合は、重複実行防止ロジック（lock ファイル）の動作を確認する

---

*このファイルはプロジェクトの設計ドキュメントを兼ねる。実装が進むにつれて随時更新すること。*
*最終更新: 2026-04-11*
