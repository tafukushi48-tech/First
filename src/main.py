"""
HAE論文自動収集パイプライン — メインエントリーポイント。

実行フロー:
  1. papers_master.csv をバックアップ
  2. PubMed + Europe PMC から論文を取得
  3. 重複除去 (既存 CSV + バッチ内)
  4. 5軸ルールベース分類
  5. バリデーション
  6. papers_master.csv へ追記
  7. 実行ログ保存

使い方:
  python src/main.py [--max-results N] [--dry-run]

CLAUDE.md R-01〜R-08 準拠。
"""
from __future__ import annotations

import argparse
import datetime
import logging
import os
import shutil
import sys
import time
from typing import Optional

import pandas as pd

# 同ディレクトリからのインポート (python src/main.py で実行した場合に解決される)
import classify
import dedupe
import search_europepmc
import search_pubmed

# ---------------------------------------------------------------------------
# スキーマ定義 (CLAUDE.md R-01)
# 将来 src/storage/csv_store.py に移管する想定。順序を変更しないこと。
# ---------------------------------------------------------------------------
SCHEMA: list[str] = [
    "pmid",
    "doi",
    "title",
    "abstract",
    "authors",
    "journal",
    "pub_year",
    "pub_date",
    "source",
    "disease_subtype",
    "treatment_area",
    "publication_type",
    "evidence_level",
    "ma_relevance_score",
    "ma_relevance_reason",
    "classifier_version",
    "collected_at",
    "review_flag",
    "notes",
]

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR     = os.path.join(_PROJECT_ROOT, "data")
_CSV_PATH     = os.path.join(_DATA_DIR, "papers_master.csv")
_BACKUP_DIR   = os.path.join(_DATA_DIR, "backups")
_LOG_DIR      = os.path.join(_DATA_DIR, "logs")

# ---------------------------------------------------------------------------
# HAE 検索クエリ定数
# ---------------------------------------------------------------------------
# 4つのクエリセットで用途別に収集範囲を制御する。
# CLAUDE.md 対象疾患: HAE type1/2, HAE-nC1-INH, bradykinin-mediated angioedema
#
# クエリキー:
#   "general"  — HAE全般ベースライン (acquired AE / allergic AE を NOT 除外)
#   "nc1inh"   — HAE with normal C1-INH (FXII/PLG/ANGPT1/KNG1/HS3ST6 等)
#   "ltp"      — 長期予防治療薬剤モニタリング (lanadelumab, garadacimab 等)
#   "review"   — ガイドライン・メタ解析・システマティックレビュー

# ── PubMed クエリ ──────────────────────────────────────────────────────────

# 1. HAE全般
# MeSH + フリーテキスト併用。"HAE" は angioedema との AND で多義性を抑制。
# NOT 節で後天性 (acquired) ・アレルギー性 AE のノイズを除去。
PUBMED_QUERY_HAE_GENERAL = (
    '('
    '"hereditary angioedema"[MeSH Terms] OR '
    '"hereditary angioedema"[Title/Abstract] OR '
    '"C1 inhibitor deficiency"[Title/Abstract] OR '
    '"C1-INH deficiency"[Title/Abstract] OR '
    '"C1 esterase inhibitor deficiency"[Title/Abstract] OR '
    '"SERPING1"[Title/Abstract] OR '
    '("HAE"[Title/Abstract] AND "angioedema"[Title/Abstract]) OR '
    '"bradykinin-mediated angioedema"[Title/Abstract]'
    ') NOT ('
    '"acquired angioedema"[Title/Abstract] OR '
    '"acquired C1 inhibitor deficiency"[Title/Abstract] OR '
    '"allergic angioedema"[Title/Abstract]'
    ')'
)

# 2. HAE with normal C1-INH (HAE-nC1INH)
# 原因遺伝子 (FXII/PLG/ANGPT1/KNG1/HS3ST6) を angioedema と AND して特異性を確保。
PUBMED_QUERY_HAE_NC1INH = (
    '('
    '(("hereditary angioedema"[Title/Abstract] OR "HAE"[Title/Abstract]) '
    'AND ("normal C1 inhibitor"[Title/Abstract] OR "normal C1-INH"[Title/Abstract])) OR '
    '"HAE-nC1INH"[Title/Abstract] OR '
    '"HAE with normal C1"[Title/Abstract] OR '
    '(("factor XII"[Title/Abstract] OR "FXII"[Title/Abstract] OR "F12"[Title/Abstract]) '
    'AND ("hereditary angioedema"[Title/Abstract] OR "angioedema"[Title/Abstract])) OR '
    '("plasminogen"[Title/Abstract] AND "angioedema"[Title/Abstract] '
    'AND ("mutation"[Title/Abstract] OR "variant"[Title/Abstract])) OR '
    '("ANGPT1"[Title/Abstract] AND "angioedema"[Title/Abstract]) OR '
    '("KNG1"[Title/Abstract] AND "angioedema"[Title/Abstract]) OR '
    '("HS3ST6"[Title/Abstract] AND "angioedema"[Title/Abstract]) OR '
    '("estrogen"[Title/Abstract] AND "hereditary angioedema"[Title/Abstract])'
    ')'
)

# 3. 長期予防治療 (LTP)
# 薬剤固有名詞 (lanadelumab 等) は HAE 特異的なので単独で可。
# danazol/stanozolol は他疾患でも使われるため HAE コンテキストが必須。
PUBMED_QUERY_LTP = (
    '('
    '"lanadelumab"[Title/Abstract] OR "Takhzyro"[Title/Abstract] OR '
    '"berotralstat"[Title/Abstract] OR "Orladeyo"[Title/Abstract] OR '
    '"Haegarda"[Title/Abstract] OR '
    '"garadacimab"[Title/Abstract] OR "CSL312"[Title/Abstract] OR '
    '"donidalorsen"[Title/Abstract] OR "KVD824"[Title/Abstract] OR '
    '("long-term prophylaxis"[Title/Abstract] '
    'AND ("hereditary angioedema"[Title/Abstract] OR "HAE"[Title/Abstract])) OR '
    '(("danazol"[Title/Abstract] OR "stanozolol"[Title/Abstract]) '
    'AND ("hereditary angioedema"[Title/Abstract] OR "HAE"[Title/Abstract]))'
    ')'
)

# 4. ガイドライン・総説・メタ解析
# PubMed publication type タグ ([pt]) で確実に捕捉。
# タイトルキーワードで [pt] 未付与の consensus 文書もカバー。
PUBMED_QUERY_REVIEW_GUIDELINE = (
    '('
    '"hereditary angioedema"[MeSH Terms] OR '
    '"hereditary angioedema"[Title/Abstract] OR '
    '("HAE"[Title/Abstract] AND "angioedema"[Title/Abstract])'
    ') AND ('
    'Review[pt] OR Meta-Analysis[pt] OR "Systematic Review"[pt] OR '
    'Practice Guideline[pt] OR Guideline[pt] OR '
    '"consensus"[Title/Abstract] OR '
    '"guideline"[Title/Abstract] OR '
    '"systematic review"[Title/Abstract] OR '
    '"meta-analysis"[Title/Abstract] OR '
    '"narrative review"[Title/Abstract]'
    ')'
)

# ── Europe PMC クエリ (Lucene 構文) ────────────────────────────────────────

# 1. HAE全般
EUROPEPMC_QUERY_HAE_GENERAL = (
    '('
    '"hereditary angioedema" OR '
    '"C1 inhibitor deficiency" OR '
    '"C1-INH deficiency" OR '
    '"C1 esterase inhibitor deficiency" OR '
    '"SERPING1" OR '
    '("HAE" AND "angioedema") OR '
    '"bradykinin-mediated angioedema"'
    ') NOT ('
    '"acquired angioedema" OR '
    '"acquired C1 inhibitor deficiency" OR '
    '"allergic angioedema"'
    ')'
)

# 2. HAE with normal C1-INH
EUROPEPMC_QUERY_HAE_NC1INH = (
    '('
    '("hereditary angioedema" AND "normal C1 inhibitor") OR '
    '("hereditary angioedema" AND "normal C1-INH") OR '
    '"HAE-nC1INH" OR '
    '"HAE with normal C1" OR '
    '(("factor XII" OR "FXII") AND "angioedema") OR '
    '("plasminogen" AND "angioedema" AND ("mutation" OR "variant")) OR '
    '("ANGPT1" AND "angioedema") OR '
    '("KNG1" AND "angioedema") OR '
    '("HS3ST6" AND "angioedema") OR '
    '("estrogen" AND "hereditary angioedema")'
    ')'
)

# 3. 長期予防治療 (LTP)
EUROPEPMC_QUERY_LTP = (
    '('
    '"lanadelumab" OR "Takhzyro" OR '
    '"berotralstat" OR "Orladeyo" OR '
    '"Haegarda" OR '
    '"garadacimab" OR "CSL312" OR '
    '"donidalorsen" OR "KVD824" OR '
    '("long-term prophylaxis" AND ("hereditary angioedema" OR "HAE")) OR '
    '(("danazol" OR "stanozolol") AND ("hereditary angioedema" OR "HAE"))'
    ')'
)

# 4. ガイドライン・総説・メタ解析
EUROPEPMC_QUERY_REVIEW_GUIDELINE = (
    '('
    '"hereditary angioedema" OR '
    '("HAE" AND "angioedema")'
    ') AND ('
    '"consensus" OR "guideline" OR '
    '"systematic review" OR "meta-analysis" OR '
    '"narrative review" OR '
    'PUB_TYPE:review OR PUB_TYPE:"practice-guideline"'
    ')'
)

# ── クエリセット辞書 ────────────────────────────────────────────────────────
# キー → (PubMed クエリ, Europe PMC クエリ, 説明)
QUERY_SETS: dict[str, tuple[str, str, str]] = {
    "general": (
        PUBMED_QUERY_HAE_GENERAL,
        EUROPEPMC_QUERY_HAE_GENERAL,
        "HAE全般ベースライン",
    ),
    "nc1inh": (
        PUBMED_QUERY_HAE_NC1INH,
        EUROPEPMC_QUERY_HAE_NC1INH,
        "HAE with normal C1-INH (HAE-nC1INH)",
    ),
    "ltp": (
        PUBMED_QUERY_LTP,
        EUROPEPMC_QUERY_LTP,
        "長期予防治療薬剤モニタリング (LTP)",
    ),
    "review": (
        PUBMED_QUERY_REVIEW_GUIDELINE,
        EUROPEPMC_QUERY_REVIEW_GUIDELINE,
        "ガイドライン・メタ解析・システマティックレビュー",
    ),
}


# ---------------------------------------------------------------------------
# ロギング設定 (CLAUDE.md R-08)
# ---------------------------------------------------------------------------

def setup_logging(log_dir: str, run_ts: str) -> logging.Logger:
    """
    ファイルと標準出力の両方にログを出力するよう設定する。

    Args:
        log_dir: ログファイルを保存するディレクトリ
        run_ts:  実行タイムスタンプ文字列 (YYYYMMDD_HHMMSS)

    Returns:
        設定済みの root ロガー
    """
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"run_{run_ts}.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%Y-%m-%dT%H:%M:%S")

    # ファイルハンドラ (DEBUG 以上)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root_logger.addHandler(fh)

    # 標準出力ハンドラ (INFO 以上)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root_logger.addHandler(ch)

    return root_logger


# ---------------------------------------------------------------------------
# CSV バックアップ (CLAUDE.md R-03)
# ---------------------------------------------------------------------------

def backup_csv(csv_path: str, backup_dir: str, run_ts: str) -> Optional[str]:
    """
    papers_master.csv をタイムスタンプ付きでバックアップする。

    ファイルが存在しない場合 (初回実行) はスキップして None を返す。
    """
    if not os.path.exists(csv_path):
        logging.getLogger(__name__).info("バックアップ対象なし (初回実行): %s", csv_path)
        return None

    os.makedirs(backup_dir, exist_ok=True)
    dest = os.path.join(backup_dir, f"papers_master_{run_ts}.csv")
    try:
        shutil.copy2(csv_path, dest)
        logging.getLogger(__name__).info("バックアップ完了: %s", dest)
        return dest
    except OSError as e:
        # バックアップ失敗は致命的エラーとして扱う (R-03)
        logging.getLogger(__name__).critical("バックアップ失敗 — パイプラインを中断します: %s", e)
        raise


# ---------------------------------------------------------------------------
# レコード バリデーション (CLAUDE.md データ品質ルール)
# ---------------------------------------------------------------------------

def validate_record(record: dict) -> tuple[bool, str]:
    """
    保存前のデータ品質チェックを行う。

    Returns:
        (ok: bool, reason: str) — ok=False の場合は保存しない
    """
    logger = logging.getLogger(__name__)

    if not str(record.get("title", "")).strip():
        return False, "title が空"

    pmid = str(record.get("pmid", "")).strip()
    doi  = str(record.get("doi", "")).strip()
    if not pmid and not doi:
        return False, "pmid と doi が両方空"

    try:
        ma_score = int(record.get("ma_relevance_score", -1))
    except (ValueError, TypeError):
        return False, f"ma_relevance_score が不正: {record.get('ma_relevance_score')}"
    if not (0 <= ma_score <= 3):
        return False, f"ma_relevance_score が範囲外: {ma_score}"

    # pub_year の範囲チェック (弾かずに警告のみ)
    try:
        pub_year = int(record.get("pub_year", 0) or 0)
        current_year = datetime.datetime.utcnow().year
        if pub_year and (pub_year < 1900 or pub_year > current_year):
            logger.warning("pub_year が範囲外: %d (title: %s)", pub_year,
                           str(record.get("title", ""))[:50])
    except (ValueError, TypeError):
        pass

    return True, ""


# ---------------------------------------------------------------------------
# CSV 追記保存 (CLAUDE.md R-01, R-02, R-07)
# ---------------------------------------------------------------------------

def append_to_csv(records: list[dict], csv_path: str) -> int:
    """
    バリデーション済みレコードを papers_master.csv へ追記する。

    - SCHEMA に定義された列順で書き込む
    - ファイルが存在しない場合はヘッダー付きで新規作成する
    - 既存ファイルへは append-only で追記する (既存行は変更しない)
    - CSV は UTF-8 (BOM なし) で保存する

    Args:
        records:  保存するレコードのリスト
        csv_path: 書き込み先の CSV パス

    Returns:
        実際に保存した件数

    Raises:
        IOError: ファイル書き込みに失敗した場合 (致命的エラー)
    """
    logger = logging.getLogger(__name__)
    if not records:
        logger.info("保存対象レコードなし")
        return 0

    # バリデーション
    valid_records: list[dict] = []
    skip_count = 0
    for rec in records:
        ok, reason = validate_record(rec)
        if ok:
            valid_records.append(rec)
        else:
            skip_count += 1
            logger.warning("バリデーション失敗でスキップ: %s | title: %s",
                           reason, str(rec.get("title", ""))[:60])

    if skip_count:
        logger.info("バリデーション失敗: %d件スキップ", skip_count)

    if not valid_records:
        return 0

    # DataFrame 化 (SCHEMA の列順に揃える)
    df_new = pd.DataFrame(valid_records)
    for col in SCHEMA:
        if col not in df_new.columns:
            df_new[col] = ""
    df_new = df_new[SCHEMA]

    # 型の正規化
    df_new["pub_year"]          = pd.to_numeric(df_new["pub_year"], errors="coerce").fillna(0).astype(int)
    df_new["ma_relevance_score"] = pd.to_numeric(df_new["ma_relevance_score"], errors="coerce").fillna(0).astype(int)
    df_new["review_flag"]       = df_new["review_flag"].astype(bool)

    # 追記 (ファイル存在有無でヘッダー制御)
    file_exists = os.path.exists(csv_path)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    try:
        df_new.to_csv(
            csv_path,
            mode="a",
            header=not file_exists,
            index=False,
            encoding="utf-8",
        )
    except OSError as e:
        logger.critical("CSV 書き込み失敗 — パイプラインを中断します: %s", e)
        raise IOError(f"CSV 書き込み失敗: {e}") from e

    logger.info("CSV 追記完了: %d件 → %s", len(valid_records), csv_path)
    return len(valid_records)


# ---------------------------------------------------------------------------
# 収集レコードの正規化
# ---------------------------------------------------------------------------

def _normalize_raw_record(rec: dict) -> dict:
    """
    各コレクターが返すフィールド名をスキーマ列名に統一する。

    search_pubmed.search() は publication_date を返すが、SCHEMA では
    pub_date / pub_year の2列に分かれているため、ここで変換する。
    search_europepmc.search() が同じフィールド名で返す場合も同様に処理する。

    Args:
        rec: コレクターが返した生レコード dict

    Returns:
        pub_date / pub_year を持つ正規化済み dict (元 dict は変更しない)
    """
    if "publication_date" not in rec:
        return rec

    pub_date = rec.get("publication_date") or ""
    try:
        pub_year = int(pub_date[:4]) if pub_date else 0
    except (ValueError, TypeError):
        pub_year = 0

    normalized = {k: v for k, v in rec.items() if k != "publication_date"}
    normalized["pub_date"] = pub_date
    normalized["pub_year"] = pub_year
    return normalized


# ---------------------------------------------------------------------------
# パイプライン本体
# ---------------------------------------------------------------------------

def run_pipeline(
    query_keys:  list[str] | None = None,
    csv_path:    str  = _CSV_PATH,
    max_results: int  = 500,
    dry_run:     bool = False,
) -> dict:
    """
    論文収集パイプラインを実行する。

    Args:
        query_keys:  実行するクエリセットのキーリスト。
                     None の場合は QUERY_SETS の全キーを実行する。
                     有効なキー: "general", "nc1inh", "ltp", "review"
        csv_path:    出力 CSV パス
        max_results: 各クエリ・各ソースあたりの最大取得件数
        dry_run:     True の場合は CSV に書き込まずログのみ出力

    Returns:
        実行統計 dict (fetched_pubmed, fetched_europepmc, after_dedupe, saved, errors)
    """
    logger = logging.getLogger(__name__)
    run_start = time.time()

    if query_keys is None:
        query_keys = list(QUERY_SETS.keys())

    stats: dict[str, int] = {
        "fetched_pubmed":    0,
        "fetched_europepmc": 0,
        "after_dedupe":      0,
        "saved":             0,
        "errors":            0,
    }

    # --- Step 1: 既存 CSV のキーを読み込む ---
    logger.info("=== Step 1: 既存データ読み込み ===")
    existing_dois, existing_pmids, existing_titles = dedupe.load_existing_keys(csv_path)

    # --- Step 2 & 3: 各クエリセットで PubMed + Europe PMC を取得 ---
    raw_records: list[dict] = []

    for key in query_keys:
        pubmed_q, epmc_q, description = QUERY_SETS[key]
        logger.info("=== クエリセット [%s]: %s ===", key, description)

        # PubMed
        try:
            pubmed_records = search_pubmed.search(pubmed_q, retmax=max_results)
            stats["fetched_pubmed"] += len(pubmed_records)
            raw_records.extend(pubmed_records)
            logger.info("  PubMed: %d件取得", len(pubmed_records))
        except Exception as e:
            logger.error("  PubMed [%s] 検索エラー: %s", key, e)
            stats["errors"] += 1

        # Europe PMC
        try:
            epmc_records = search_europepmc.search(epmc_q, page_size=max_results)
            stats["fetched_europepmc"] += len(epmc_records)
            raw_records.extend(epmc_records)
            logger.info("  Europe PMC: %d件取得", len(epmc_records))
        except Exception as e:
            logger.error("  Europe PMC [%s] 検索エラー: %s", key, e)
            stats["errors"] += 1

    all_records = [_normalize_raw_record(r) for r in raw_records]
    logger.info(
        "取得合計: %d件 (PubMed: %d, Europe PMC: %d) — クエリセット: %s",
        len(all_records), stats["fetched_pubmed"], stats["fetched_europepmc"],
        ", ".join(query_keys),
    )

    if not all_records:
        logger.warning("取得レコードが 0件です。パイプラインを終了します")
        return stats

    # --- Step 4: 重複除去 ---
    logger.info("=== Step 4: 重複除去 ===")
    unique_records, dedupe_stats = dedupe.deduplicate(
        all_records, existing_dois, existing_pmids, existing_titles
    )
    stats["after_dedupe"] = len(unique_records)

    if not unique_records:
        logger.info("新規レコードなし。パイプラインを終了します")
        return stats

    # --- Step 5: 分類 ---
    logger.info("=== Step 5: 5軸分類 ===")
    now_utc = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    classified: list[dict] = []
    for rec in unique_records:
        try:
            rec_classified = classify.classify_paper(rec)
            # 収集日時を設定
            rec_classified["collected_at"] = now_utc
            rec_classified.setdefault("notes", "")
            classified.append(rec_classified)
        except Exception as e:
            stats["errors"] += 1
            logger.warning("分類エラー (スキップ) — title: %s — %s",
                           str(rec.get("title", ""))[:60], e)

    logger.info("分類完了: %d件", len(classified))

    # --- Step 6: 保存 ---
    logger.info("=== Step 6: CSV 追記 ===")
    if dry_run:
        logger.info("[DRY-RUN] 保存はスキップします (%d件対象)", len(classified))
        stats["saved"] = 0
    else:
        try:
            stats["saved"] = append_to_csv(classified, csv_path)
        except IOError as e:
            logger.critical("CSV 保存失敗: %s", e)
            raise

    elapsed = time.time() - run_start
    logger.info(
        "=== パイプライン完了 (%.1f秒) ===\n"
        "  PubMed取得:    %d件\n"
        "  EuropePMC取得: %d件\n"
        "  重複除去後:    %d件\n"
        "  保存:          %d件\n"
        "  エラー:        %d件",
        elapsed,
        stats["fetched_pubmed"],
        stats["fetched_europepmc"],
        stats["after_dedupe"],
        stats["saved"],
        stats["errors"],
    )
    return stats


# ---------------------------------------------------------------------------
# CLI エントリーポイント
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする。"""
    valid_query_keys = list(QUERY_SETS.keys())  # ["general", "nc1inh", "ltp", "review"]

    p = argparse.ArgumentParser(
        description="HAE関連論文を PubMed / Europe PMC から自動収集して CSV に蓄積する"
    )
    p.add_argument(
        "--max-results", type=int, default=500,
        help="各クエリ・各ソースあたりの最大取得件数 (デフォルト: 500)",
    )
    p.add_argument(
        "--csv-path", type=str, default=_CSV_PATH,
        help=f"出力先 CSV パス (デフォルト: {_CSV_PATH})",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="CSV に書き込まずログ出力のみ行うテストモード",
    )
    p.add_argument(
        "--query",
        nargs="+",
        choices=["all"] + valid_query_keys,
        default=["all"],
        metavar="QUERY_KEY",
        help=(
            "実行するクエリセット (複数指定可)。"
            f"選択肢: all (全セット), {', '.join(valid_query_keys)}。"
            "デフォルト: all"
        ),
    )
    return p.parse_args()


def main() -> None:
    """パイプラインのメイン関数。"""
    args = _parse_args()

    run_ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    setup_logging(_LOG_DIR, run_ts)
    logger = logging.getLogger(__name__)

    # --query の "all" を全キーに展開する
    if "all" in args.query:
        query_keys = list(QUERY_SETS.keys())
    else:
        # 重複排除しつつ QUERY_SETS の順序を維持する
        seen: set[str] = set()
        query_keys = [k for k in args.query if not (k in seen or seen.add(k))]  # type: ignore[func-returns-value]

    logger.info(
        "HAE論文収集パイプライン開始 (実行ID: %s) — クエリ: %s",
        run_ts, ", ".join(query_keys),
    )
    if args.dry_run:
        logger.info("[DRY-RUN モード] CSV への書き込みはスキップされます")

    # バックアップ (R-03)
    if not args.dry_run:
        backup_csv(args.csv_path, _BACKUP_DIR, run_ts)

    # パイプライン実行
    try:
        run_pipeline(
            query_keys=query_keys,
            csv_path=args.csv_path,
            max_results=args.max_results,
            dry_run=args.dry_run,
        )
    except IOError:
        logger.critical("致命的エラーによりパイプラインを中断しました")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("ユーザーによる中断")
        sys.exit(0)


if __name__ == "__main__":
    main()
