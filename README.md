# HAE論文自動収集・分類管理システム

Hereditary Angioedema (HAE) に関する学術論文を PubMed および Europe PMC から自動収集し、
Medical Affairs 活動に資する形で分類・蓄積するシステムです。

---

## 概要

- **収集対象**: HAE type 1/2、HAE-nC1INH、bradykinin性浮腫 関連論文
- **収集元**: PubMed (NCBI Entrez API) / Europe PMC REST API
- **分類軸**: 疾患サブタイプ / 治療領域 / 論文種別 / エビデンスレベル / MA関連度
- **出力**: `data/papers_master.csv`（追記専用、UTF-8）
- **自動実行**: GitHub Actions 毎週月曜 07:00 JST

---

## セットアップ

### 1. 依存ライブラリのインストール

```bash
pip install -r requirements.txt
```

### 2. 環境変数の設定

PubMed API キーを `.env` ファイルまたは環境変数で設定します（CLAUDE.md R-04）。

```bash
# .env ファイル（.gitignore 済み）
NCBI_API_KEY=your_api_key_here
NCBI_EMAIL=your_email@example.com
```

NCBI API キーは https://www.ncbi.nlm.nih.gov/account/ で無料取得できます。
未設定の場合も動作しますが、レート制限が 3 req/s に制限されます。

### 3. GitHub Secrets の登録（自動実行用）

リポジトリの **Settings → Secrets and variables → Actions** で以下を登録します。

| Secret 名 | 内容 |
|---|---|
| `NCBI_API_KEY` | NCBI の API キー |
| `NCBI_EMAIL` | NCBI に登録したメールアドレス |

---

## 実行方法

### 通常実行（全クエリセット）

```bash
PYTHONPATH=src python -m src.main
```

### クエリセットを絞って実行

```bash
# HAE全般のみ
PYTHONPATH=src python -m src.main --query general

# 複数指定
PYTHONPATH=src python -m src.main --query ltp nc1inh

# 取得件数を制限（テスト用）
PYTHONPATH=src python -m src.main --query general --max-results 50
```

### ドライラン（CSV に保存せず結果を確認）

```bash
PYTHONPATH=src python -m src.main --dry-run
```

実行すると取得件数・重複除去内訳・分類済みサンプル 5 件が表示されます。

---

## クエリセット

| キー | 用途 |
|---|---|
| `general` | HAE全般ベースライン（MeSH + フリーテキスト、acquired AE を NOT 除外） |
| `nc1inh` | HAE with normal C1-INH（FXII / PLG / ANGPT1 / KNG1 / HS3ST6 等） |
| `ltp` | 長期予防治療薬剤モニタリング（lanadelumab / garadacimab / berotralstat 等） |
| `review` | ガイドライン・メタ解析・システマティックレビュー |

---

## 出力スキーマ

`data/papers_master.csv` のカラム定義（順序固定、CLAUDE.md R-01）。

| カラム | 内容 |
|---|---|
| `pmid` | PubMed ID |
| `doi` | DOI |
| `source` | 取得元（pubmed / europepmc） |
| `title` | 論文タイトル |
| `abstract` | アブストラクト |
| `journal` | ジャーナル名 |
| `publication_date` | 出版日（YYYY-MM-DD） |
| `first_author` | 筆頭著者名 |
| `authors` | 著者リスト（セミコロン区切り） |
| `disease_subtype` | 疾患サブタイプ分類 |
| `treatment_area` | 治療領域分類 |
| `publication_type` | 論文種別 |
| `evidence_level` | エビデンスレベル（Oxford EBM 2011 準拠） |
| `ma_relevance` | MA関連度（high / medium / low） |
| `why_it_matters_for_ma` | MA関連度の根拠（日本語、100字以内） |
| `retrieved_at` | 収集日時（ISO 8601 UTC） |

---

## 自動実行（GitHub Actions）

`.github/workflows/literature_monitor.yml` により毎週月曜 07:00 JST に実行されます。

### 実行フロー

1. `papers_master.csv` をバックアップ（`data/backups/`）
2. 4クエリセットで PubMed + Europe PMC から論文を取得
3. 重複除去（DOI → PMID → タイトル正規化の優先順）
4. 5軸ルールベース分類
5. バリデーション後に `papers_master.csv` へ追記
6. 差分があればコミット & プッシュ（コミットメッセージ例: `chore: 週次HAE論文収集 2026-04-13 (+42 行) [skip ci]`）
7. 実行ログを `data/logs/run_YYYYMMDD_HHMMSS.log` に保存

### 手動実行

GitHub の **Actions タブ → HAE Literature Monitor → Run workflow** から手動実行できます。
クエリセットを絞って実行することも可能です。

### ログの確認

`data/logs/` に実行ごとのログが保存されます（`.gitignore` 済みのため Git 管理対象外）。
GitHub Actions の実行ログは Actions タブから確認できます。

---

## テスト

```bash
pytest
```

`tests/` 配下にユニットテストがあります。

| テストファイル | 対象 |
|---|---|
| `tests/test_classify.py` | 論文種別・疾患サブタイプ分類（22テスト） |
| `tests/test_dedupe.py` | タイトル正規化・DOI重複判定（19テスト） |

---

## ディレクトリ構成

```
.
├── .github/
│   └── workflows/
│       └── literature_monitor.yml  # 週次自動実行
├── data/
│   ├── papers_master.csv           # 蓄積データ（追記専用）
│   ├── backups/                    # 自動バックアップ（.gitignore）
│   └── logs/                       # 実行ログ（.gitignore）
├── src/
│   ├── main.py                     # パイプライン本体
│   ├── classify.py                 # 分類ロジック
│   ├── rules.py                    # 分類ルール定数
│   ├── dedupe.py                   # 重複除去
│   ├── search_pubmed.py            # PubMed 収集
│   └── search_europepmc.py        # Europe PMC 収集
├── tests/
│   ├── test_classify.py
│   └── test_dedupe.py
├── CLAUDE.md                       # 設計ドキュメント・永続ルール
├── pytest.ini
└── requirements.txt
```

---

## 注意事項

- `papers_master.csv` への書き込みは **追記専用**（既存レコードの上書き・削除は専用スクリプト経由）
- APIキー・認証情報はコードにハードコードしない（CLAUDE.md R-04）
- PubMed レート制限: APIキーあり 10 req/s、なし 3 req/s（CLAUDE.md R-05）
