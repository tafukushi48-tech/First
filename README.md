# HAE論文自動収集・分類管理システム

Hereditary Angioedema (HAE) に関する学術論文を **PubMed** および **Europe PMC** から自動収集し、
Medical Affairs 活動に活用しやすい形で分類・蓄積するシステムです。

---

## 目的

HAE は希少疾患であり、エビデンスが各社の治験・観察研究・ガイドライン等に分散しています。
本システムは以下の課題を解決するために開発しました。

- **エビデンスランドスケープの継続的把握** — 週次で新着論文を自動収集し蓄積
- **競合品・新規治療の動向モニタリング** — 薬剤名・遺伝子名ベースの専用クエリで捕捉
- **MA活動への即時活用** — 5軸の自動分類とMA関連度スコアにより、文献の取捨選択を効率化
- **ペイヤー対応・価値訴求の根拠文献管理** — `why_it_matters_for_ma` 列に日本語の活用根拠を自動生成

### 収集対象疾患

| 対象 | 備考 |
|---|---|
| HAE type 1 / type 2 | C1-INH 欠乏（SERPING1 変異） |
| HAE with normal C1-INH (HAE-nC1INH) | FXII / PLG / ANGPT1 / KNG1 / MYOF / HS3ST6 変異を含む |
| Bradykinin 性浮腫（関連） | ACE 阻害薬誘発性 AE など |

---

## セットアップ

### 前提条件

- Python 3.11 以上
- PubMed (NCBI Entrez) アクセス用のメールアドレス（API キーは推奨、必須ではない）

### 1. リポジトリのクローンと依存ライブラリのインストール

```bash
git clone <repository-url>
cd First
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env` ファイルをプロジェクトルートに作成します（`.gitignore` に含まれているためコミットされません）。

```bash
# .env
NCBI_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NCBI_EMAIL=your_email@example.com
```

| 変数名 | 必須 | 説明 |
|---|---|---|
| `NCBI_API_KEY` | 推奨 | NCBI API キー。未設定でも動作するが、レート制限が 3 req/s に制限される。[無料取得](https://www.ncbi.nlm.nih.gov/account/) |
| `NCBI_EMAIL` | 推奨 | NCBI ポリシーで必須。未設定でも動作するが設定を推奨 |

### 3. データディレクトリの準備

初回実行前に出力先ディレクトリを作成します。

```bash
mkdir -p data/backups data/logs
```

---

## 実行方法

すべてのコマンドはプロジェクトルートで実行してください。
`PYTHONPATH=src` が必要です（`src/` 内のモジュール間インポートのため）。

### ドライラン（CSV に保存せず結果を確認）

実際の収集・分類をすべて行いますが、`papers_master.csv` への書き込みは行いません。
**初回動作確認や収集件数の事前確認に使用します。**

```bash
PYTHONPATH=src python -m src.main --dry-run
```

実行すると以下が標準出力に表示されます。

```
============================================================
 DRY-RUN レポート
============================================================
[取得件数]
  PubMed       : 312 件
  Europe PMC   : 198 件
  合計取得      : 510 件

[重複除去]
  DOI 重複       :  87 件除外
  PMID 重複      :  23 件除外
  タイトル重複候補:   4 件 (review_flag=True)
  → 新規候補     : 396 件

[分類済みサンプル (5件)]
------------------------------------------------------------
[1] Efficacy and safety of lanadelumab for long-term
    prophylaxis of hereditary angioedema...
    2024 | pubmed | HAE type 1/2 | long-term prophylaxis
    RCT | high | ★★★ (score=3)
    C1-INH欠乏型HAEの長期予防を対象としたRCTとして...
...
```

取得件数を絞ってドライランする場合：

```bash
PYTHONPATH=src python -m src.main --dry-run --max-results 20
```

### 通常実行（全クエリセット）

```bash
PYTHONPATH=src python -m src.main
```

新規論文が `data/papers_master.csv` に追記され、実行ログが `data/logs/` に保存されます。

### クエリセットを絞って実行

```bash
# 長期予防治療の新薬モニタリングのみ
PYTHONPATH=src python -m src.main --query ltp

# HAE-nC1INH と ガイドライン/レビュー を同時実行
PYTHONPATH=src python -m src.main --query nc1inh review

# 取得件数を制限（クエリ・ソースあたり上限）
PYTHONPATH=src python -m src.main --query general --max-results 100
```

### コマンドライン引数一覧

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--query` | `all` | 実行するクエリセット（複数指定可）。`all general nc1inh ltp review` から選択 |
| `--max-results` | `500` | 各クエリ・各ソースあたりの最大取得件数 |
| `--csv-path` | `data/papers_master.csv` | 出力先 CSV パス |
| `--dry-run` | `False` | CSV に保存せず、標準出力にレポートを表示する |

### クエリセット

| キー | 用途 | 主なキーワード |
|---|---|---|
| `general` | HAE 全般ベースライン | MeSH「hereditary angioedema」＋ SERPING1 / C1-INH deficiency。acquired AE を NOT 除外 |
| `nc1inh` | HAE with normal C1-INH 特化 | FXII / PLG / ANGPT1 / KNG1 / HS3ST6 / estrogen-dependent |
| `ltp` | 長期予防治療薬モニタリング | lanadelumab / garadacimab / berotralstat / donidalorsen 等の薬剤固有名詞 |
| `review` | ガイドライン・SR・メタ解析 | Review[pt] / Meta-Analysis[pt] / guideline / systematic review |

---

## CSV 出力仕様

`data/papers_master.csv` に UTF-8 (BOM なし) で出力されます。
カラム定義・順序は固定です（変更する場合は `CLAUDE.md` の R-01 手順を参照）。

### カラム定義（16列、順序固定）

| # | カラム名 | 型 | 説明 |
|---|---|---|---|
| 1 | `pmid` | 文字列 | PubMed ID（なければ空） |
| 2 | `doi` | 文字列 | DOI（なければ空） |
| 3 | `source` | 文字列 | 取得元: `pubmed` / `europepmc` |
| 4 | `title` | 文字列 | 論文タイトル |
| 5 | `abstract` | 文字列 | アブストラクト（なければ空） |
| 6 | `journal` | 文字列 | ジャーナル名 |
| 7 | `publication_date` | 文字列 | 出版日（`YYYY-MM-DD`。日不明は `YYYY-01-01`） |
| 8 | `first_author` | 文字列 | 筆頭著者姓名 |
| 9 | `authors` | 文字列 | 全著者（セミコロン区切り） |
| 10 | `disease_subtype` | 文字列 | 疾患サブタイプ（下表参照） |
| 11 | `treatment_area` | 文字列 | 治療領域（下表参照） |
| 12 | `publication_type` | 文字列 | 論文種別（下表参照） |
| 13 | `evidence_level` | 文字列 | エビデンスレベル: `high` / `medium` / `low` / `unknown` |
| 14 | `ma_relevance` | 文字列 | MA 関連度: `high` / `medium` / `low` |
| 15 | `why_it_matters_for_ma` | 文字列 | MA 活用根拠（日本語、100字以内） |
| 16 | `retrieved_at` | 文字列 | 収集日時（ISO 8601 UTC） |

### 分類値の定義

**disease_subtype**

| 値 | 定義 |
|---|---|
| `HAE-nC1INH` | HAE with normal C1-INH（FXII / PLG / ANGPT1 / KNG1 / MYOF / HS3ST6 変異、エストロゲン依存性） |
| `HAE type 1/2` | C1-INH 量的・機能的欠乏（SERPING1 変異） |
| `unspecified HAE` | サブタイプ不明または HAE 総論・bradykinin 性浮腫 |

**treatment_area**

| 値 | 定義 |
|---|---|
| `guidelines` | ガイドライン・エキスパートコンセンサス・治療アルゴリズム |
| `acute treatment` | 急性発作治療（icatibant, ecallantide, C1-INH IV 等） |
| `long-term prophylaxis` | 長期予防療法（lanadelumab, berotralstat, garadacimab 等）・遺伝子治療 |
| `diagnosis` | 診断・バイオマーカー・遺伝子検査 |
| `epidemiology` | 疫学・発症頻度・医療資源利用・自然歴 |
| `burden/QoL` | 疾患負荷・QoL・患者報告アウトカム・経済的影響 |
| `basic science` | 病態生理・分子メカニズム・前臨床研究 |
| `other` | 上記に該当しない |

**publication_type**

| 値 | エビデンスレベル | 定義 |
|---|---|---|
| `guideline/consensus` | high | 診療ガイドライン・コンセンサス文書 |
| `RCT` | high | ランダム化比較試験 |
| `OLE/extension` | medium | オープンラベル延長試験・長期安全性試験 |
| `RWE/observational` | medium | リアルワールドエビデンス・観察研究・レジストリ |
| `review` | medium（SR/メタ解析は high） | ナラティブレビュー・システマティックレビュー・メタ解析 |
| `letter/commentary` | low | レター・エディトリアル・コメンタリー |
| `case report` | low | 症例報告・症例集積 |
| `unknown` | unknown | 自動分類不可 |

### 重複除去ルール

1. `doi` が一致（正規化後）→ 重複と判定
2. `pmid` が一致 → 重複と判定
3. `doi` / `pmid` が両方空の場合 → タイトルを正規化（小文字・記号除去・空白圧縮）して照合。一致すれば重複、新規の場合は `review_flag=True` で保持

### データ品質ルール

- `title` が空のレコードは保存しない
- `pmid` と `doi` が両方空のレコードは保存しない
- `ma_relevance` が `high` / `medium` / `low` 以外のレコードは保存しない
- `papers_master.csv` への書き込みは **追記専用**（既存レコードの上書き・削除は `scripts/correct_record.py` 経由）

---

## GitHub Actions による自動実行

### スケジュール

`.github/workflows/literature_monitor.yml` により **毎週月曜 07:00 JST**（= 日曜 22:00 UTC）に自動実行されます。

### 実行フロー

```
① papers_master.csv をバックアップ (data/backups/papers_master_YYYYMMDD_HHMMSS.csv)
② 4クエリセット × PubMed + Europe PMC で論文を取得
③ 重複除去（DOI → PMID → タイトル正規化の優先順）
④ 5軸ルールベース分類 + MA活用根拠生成
⑤ バリデーション後に papers_master.csv へ追記
⑥ 差分があれば自動コミット & push
   例: "chore: 週次HAE論文収集 2026-04-14 (+38 行) [skip ci]"
⑦ 実行ログを data/logs/run_YYYYMMDD_HHMMSS.log に保存
```

### 事前準備：GitHub Secrets の登録

リポジトリの **Settings → Secrets and variables → Actions** で以下を登録します。

| Secret 名 | 内容 |
|---|---|
| `NCBI_API_KEY` | NCBI の API キー |
| `NCBI_EMAIL` | NCBI に登録したメールアドレス |

未登録でも実行されますが、PubMed の取得レートが制限されます。

### 手動実行

**Actions タブ → HAE Literature Monitor → Run workflow** から手動実行できます。
クエリセットを指定して実行することも可能です（省略時は全セット実行）。

### ログの確認

- CI 実行ログ: GitHub の **Actions タブ** で確認
- ローカル実行ログ: `data/logs/run_YYYYMMDD_HHMMSS.log`（`.gitignore` 済み）

---

## テスト

```bash
pytest
```

| テストファイル | 対象 | テスト数 |
|---|---|---|
| `tests/test_classify.py` | `classify_publication_type` / `classify_disease_subtype` | 22 |
| `tests/test_dedupe.py` | `normalize_title` / `normalize_doi` / `deduplicate` | 19 |

---

## ディレクトリ構成

```
.
├── .github/
│   └── workflows/
│       └── literature_monitor.yml  # 週次自動収集（月曜 07:00 JST）
├── data/
│   ├── papers_master.csv           # 蓄積データ（追記専用、Git 管理）
│   ├── backups/                    # 実行前自動バックアップ（.gitignore）
│   └── logs/                       # 実行ログ（.gitignore）
├── src/
│   ├── main.py                     # パイプライン本体・CLI エントリーポイント
│   ├── classify.py                 # 5軸分類ロジック + why_it_matters_for_ma 生成
│   ├── rules.py                    # 分類ルール定数（キーワード・正規表現）
│   ├── dedupe.py                   # 重複除去・タイトル正規化
│   ├── search_pubmed.py            # PubMed (NCBI Entrez API) 収集
│   └── search_europepmc.py        # Europe PMC REST API 収集
├── tests/
│   ├── test_classify.py
│   └── test_dedupe.py
├── CLAUDE.md                       # 設計ドキュメント・永続ルール（開発者向け）
├── pytest.ini
└── requirements.txt
```

---

## 今後の拡張案

### 収集範囲の拡充

- **ClinicalTrials.gov 連携** — HAE の進行中・完了試験を定期収集し、パイプライン文献と紐付け
- **Cochrane Library / EMBASE** — 現在 PubMed / Europe PMC に限定している収集源を拡張
- **プレプリントサーバー（medRxiv / bioRxiv）** — 査読前論文のモニタリング

### 分類精度の向上

- **LLM による分類（Claude API）** — `classify_paper()` のインターフェースを変えずにルールベースから差し替え可能な設計になっています。LLM に切り替えることで `why_it_matters_for_ma` の品質も向上できます
- **`treatment_area` の多ラベル分類** — 現状は単一ラベルですが、1論文が複数領域にまたがるケースに対応
- **薬剤名・試験名の辞書拡充** — `src/rules.py` の `DRUG_REFERENCE` を随時更新

### 出力・通知機能

- **Slack / Teams 通知** — 週次実行後に新着件数・注目論文を自動投稿
- **Excel / PowerPoint レポート生成** — Medical Affairs チーム向けのサマリーレポートを自動作成
- **ダッシュボード連携** — `papers_master.csv` を BIツール（Tableau / Power BI）に接続し、エビデンスランドスケープを可視化

### 運用の改善

- **手動レビュー UI** — `review_flag=True` のレコードを確認・修正するシンプルな Web UI
- **再分類スクリプト** — ルール更新後に既存レコードを一括再分類する `scripts/reclassify.py`
- **スキーマバージョン管理** — `classifier_version` カラムを CSV に追加し、分類ルールの変更履歴を追跡
