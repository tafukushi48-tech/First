"""
重複除去モジュール。

DOI → PMID → 正規化タイトルの優先順位でレコードの重複を判定する。
既存の papers_master.csv との照合と、同一バッチ内の重複の両方に対応する。

重複判定ルール:
  1. doi  が一致（正規化後）→ 重複として除外
  2. pmid が一致           → 重複として除外
  3. doi・pmid が両方空 かつ 正規化タイトルが一致 → 重複として除外
  4. doi・pmid が両方空 かつ タイトルが不一致    → 保持、review_flag=True

返却する stats のキー:
  total           : 入力レコード総数
  dup_doi         : DOI 一致で除外した件数
  dup_pmid        : PMID 一致で除外した件数
  dup_title       : タイトル一致で除外した件数 (doi/pmid が両方空の場合のみ)
  title_candidate : 識別子なしで保持したレコード数 (review_flag=True で保持)
  excluded        : 除外した合計件数 (dup_doi + dup_pmid + dup_title)
  kept            : 採用したレコード数
"""
from __future__ import annotations

import logging
import os
import re

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 正規化ユーティリティ
# ---------------------------------------------------------------------------

def normalize_doi(doi: str) -> str:
    """
    DOI を比較用に正規化する。

    処理内容:
      - 前後の空白を除去
      - 小文字に変換
      - URL プレフィックス (https://doi.org/ 等) を除去

    Args:
        doi: 正規化前の DOI 文字列

    Returns:
        正規化済み DOI 文字列 (例: "10.1234/example.2024")
    """
    doi = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "doi/"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi


def normalize_title(title: str) -> str:
    """
    タイトルを比較用に正規化する。

    処理内容:
      1. 小文字化
      2. 英数字・スペース・Unicode 文字以外の記号をすべて除去
         (句読点、ハイフン、アンダースコア等も除去)
      3. 連続する空白を単一スペースに圧縮
      4. 前後の空白を除去

    Args:
        title: 正規化前のタイトル文字列

    Returns:
        正規化済みタイトル文字列 (例: "randomized trial of icatibant in hae")
    """
    title = title.lower()
    # \w はアンダースコアを含むため、代わりに Unicode 文字と数字だけ残す
    title = re.sub(r"[^\w\s]", " ", title)      # 記号・句読点を空白に
    title = re.sub(r"_", " ", title)            # アンダースコアも空白に
    title = re.sub(r"\s+", " ", title).strip()  # 余分な空白を圧縮
    return title


# ---------------------------------------------------------------------------
# 既存 CSV からのキー読み込み
# ---------------------------------------------------------------------------

def load_existing_keys(
    csv_path: str,
) -> tuple[set[str], set[str], set[str]]:
    """
    papers_master.csv から既存レコードのキーセットを読み込む。

    ファイルが存在しない場合や列が欠損している場合は空セットを返し、
    パイプラインを止めない。

    Args:
        csv_path: papers_master.csv の絶対パスまたは相対パス

    Returns:
        (doi_set, pmid_set, title_set) — それぞれ正規化済みの文字列セット。
        ファイル不在・読み込み失敗時はすべて空セット。
    """
    if not os.path.exists(csv_path):
        logger.debug("既存 CSV が見つかりません (初回実行): %s", csv_path)
        return set(), set(), set()

    try:
        # usecols で必要な列のみ読み込む。列が欠損していても errors='ignore' で継続
        df = pd.read_csv(
            csv_path,
            encoding="utf-8",
            dtype=str,
        )
    except Exception as e:
        logger.warning("既存 CSV の読み込みに失敗しました: %s — %s", csv_path, e)
        return set(), set(), set()

    def _to_set(col: str, normalizer=None) -> set[str]:
        """指定列を正規化して文字列セットに変換する。列が存在しない場合は空セット。"""
        if col not in df.columns:
            logger.debug("列 '%s' が CSV に存在しません", col)
            return set()
        series = df[col].dropna().str.strip()
        series = series[series != ""]
        if normalizer:
            series = series.apply(normalizer)
        result = set(series)
        result.discard("")
        return result

    doi_set   = _to_set("doi",   normalize_doi)
    pmid_set  = _to_set("pmid")
    title_set = _to_set("title", normalize_title)

    logger.debug(
        "既存キーを読み込みました — DOI: %d件, PMID: %d件, タイトル: %d件",
        len(doi_set), len(pmid_set), len(title_set),
    )
    return doi_set, pmid_set, title_set


# ---------------------------------------------------------------------------
# 重複除去
# ---------------------------------------------------------------------------

def deduplicate(
    records:         list[dict],
    existing_dois:   set[str],
    existing_pmids:  set[str],
    existing_titles: set[str],
) -> tuple[list[dict], dict[str, int]]:
    """
    新規レコードリストから重複を除去する。

    重複判定の優先順位: DOI → PMID → 正規化タイトル

    既存 CSV のキーセットとの照合に加え、同一バッチ内の重複も検出する。
    DOI・PMID が両方空でタイトルが未一致のレコードは識別子なしとして
    review_flag=True を立てて保持する。

    Args:
        records:         新規取得レコードのリスト
        existing_dois:   既存 CSV の DOI セット (正規化済み)
        existing_pmids:  既存 CSV の PMID セット
        existing_titles: 既存 CSV の正規化タイトルセット

    Returns:
        (unique_records, stats)
        stats のキー: total, dup_doi, dup_pmid, dup_title,
                      title_candidate, excluded, kept
    """
    unique: list[dict] = []
    stats: dict[str, int] = {
        "total":           len(records),
        "dup_doi":         0,   # DOI 一致で除外
        "dup_pmid":        0,   # PMID 一致で除外
        "dup_title":       0,   # タイトル一致で除外 (doi/pmid 両方空の場合)
        "title_candidate": 0,   # 識別子なしで要レビュー保持
        "excluded":        0,   # 除外合計 (dup_doi + dup_pmid + dup_title)
        "kept":            0,
    }

    # 既存セットをコピーしてバッチ内重複も追跡するワーキングセットを用意
    seen_dois:   set[str] = set(existing_dois)
    seen_pmids:  set[str] = set(existing_pmids)
    seen_titles: set[str] = set(existing_titles)

    for record in records:
        raw_doi = (record.get("doi")  or "").strip()
        pmid    = (record.get("pmid") or "").strip()
        doi     = normalize_doi(raw_doi) if raw_doi else ""
        title   = normalize_title(record.get("title") or "")

        # ------------------------------------------------------------------
        # 優先順位 1: DOI 一致
        # ------------------------------------------------------------------
        if doi and doi in seen_dois:
            stats["dup_doi"] += 1
            logger.debug("DOI重複スキップ: %s", doi)
            continue

        # ------------------------------------------------------------------
        # 優先順位 2: PMID 一致
        # ------------------------------------------------------------------
        if pmid and pmid in seen_pmids:
            stats["dup_pmid"] += 1
            logger.debug("PMID重複スキップ: %s", pmid)
            continue

        # ------------------------------------------------------------------
        # 優先順位 3: タイトル照合 (doi・pmid が両方空の場合のみ)
        # ------------------------------------------------------------------
        if not doi and not pmid:
            if title and title in seen_titles:
                stats["dup_title"] += 1
                logger.debug(
                    "タイトル重複スキップ (doi/pmid なし): %s",
                    (record.get("title") or "")[:60],
                )
                continue
            # 識別子なし・タイトル不一致 → 要レビューフラグを立てて保持
            if title:
                record = {**record, "review_flag": True}
                stats["title_candidate"] += 1
                logger.debug(
                    "識別子なし論文を要レビューとして保持: %s",
                    (record.get("title") or "")[:60],
                )

        # ------------------------------------------------------------------
        # ユニークとして採用
        # ------------------------------------------------------------------
        unique.append(record)
        stats["kept"] += 1

        # バッチ内の次レコードとの重複を防ぐためワーキングセットに追加
        if doi:
            seen_dois.add(doi)
        if pmid:
            seen_pmids.add(pmid)
        if title:
            seen_titles.add(title)

    # 除外合計を集計
    stats["excluded"] = stats["dup_doi"] + stats["dup_pmid"] + stats["dup_title"]

    logger.info(
        "重複除去完了 — "
        "入力: %d件 | 除外: %d件 (DOI: %d, PMID: %d, タイトル: %d) | "
        "識別子なし要レビュー: %d件 | 採用: %d件",
        stats["total"],
        stats["excluded"],
        stats["dup_doi"],
        stats["dup_pmid"],
        stats["dup_title"],
        stats["title_candidate"],
        stats["kept"],
    )
    return unique, stats
