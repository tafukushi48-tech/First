"""
重複除去モジュール。

PMID → DOI → タイトル正規化の優先順位でレコードの重複を判定する。
既存の papers_master.csv との照合、および同一バッチ内の重複も検出する。

重複判定ルール (CLAUDE.md R-02 準拠):
  1. pmid が一致 → 重複
  2. doi が一致（正規化後） → 重複
  3. pmid・doi が両方空 かつ タイトルが一致（正規化後） → 重複候補
     ※ この場合は保存するが review_flag = True を立てる（呼び出し元で処理）
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
    DOI を正規化する。

    - 前後の空白を除去
    - 小文字に変換
    - URL プレフィックス (https://doi.org/ 等) を除去
    """
    doi = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "doi/"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi


def normalize_title(title: str) -> str:
    """
    タイトルを正規化する。

    - 小文字に変換
    - 英数字・スペース以外を除去
    - 連続する空白を単一スペースに圧縮
    """
    title = title.lower()
    title = re.sub(r"[^\w\s]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


# ---------------------------------------------------------------------------
# 既存 CSV からのキー読み込み
# ---------------------------------------------------------------------------

def load_existing_keys(
    csv_path: str,
) -> tuple[set[str], set[str], set[str]]:
    """
    papers_master.csv から既存レコードのキーセットを読み込む。

    Returns:
        (pmid_set, doi_set, title_set) — それぞれ正規化済みの文字列セット
    """
    if not os.path.exists(csv_path):
        logger.debug("既存CSV が見つかりません。空のキーセットを返します: %s", csv_path)
        return set(), set(), set()

    try:
        df = pd.read_csv(csv_path, encoding="utf-8", dtype=str, usecols=["pmid", "doi", "title"])
    except Exception as e:
        logger.warning("既存CSV の読み込みに失敗しました: %s — %s", csv_path, e)
        return set(), set(), set()

    pmid_set: set[str] = set(
        df["pmid"].dropna().str.strip().replace("", pd.NA).dropna()
    )

    doi_set: set[str] = set(
        df["doi"].dropna().str.strip().replace("", pd.NA).dropna().apply(normalize_doi)
    )
    doi_set.discard("")

    title_set: set[str] = set(
        df["title"].dropna().str.strip().replace("", pd.NA).dropna().apply(normalize_title)
    )
    title_set.discard("")

    logger.debug(
        "既存キーを読み込みました — PMID: %d件, DOI: %d件, タイトル: %d件",
        len(pmid_set), len(doi_set), len(title_set),
    )
    return pmid_set, doi_set, title_set


# ---------------------------------------------------------------------------
# 重複除去
# ---------------------------------------------------------------------------

def deduplicate(
    records: list[dict],
    existing_pmids: set[str],
    existing_dois: set[str],
    existing_titles: set[str],
) -> tuple[list[dict], dict[str, int]]:
    """
    新規レコードリストから重複を除去する。

    既存 CSV のキーセットに加え、同一バッチ内の重複も検出する。
    PMID・DOI が両方空でタイトル一致のレコードは「重複候補」として
    review_flag を True に設定したうえで保持する。

    Args:
        records:         新規取得レコードのリスト
        existing_pmids:  既存 CSV の PMID セット
        existing_dois:   既存 CSV の DOI セット (正規化済み)
        existing_titles: 既存 CSV のタイトルセット (正規化済み)

    Returns:
        (unique_records, stats)
        stats のキー: total, dup_pmid, dup_doi, dup_title_hard, title_candidate, kept
    """
    unique: list[dict] = []
    stats: dict[str, int] = {
        "total":            len(records),
        "dup_pmid":         0,
        "dup_doi":          0,
        "dup_title_hard":   0,   # 既存CSV とのタイトル重複
        "title_candidate":  0,   # PMID/DOI なしでタイトルが一致 → 保持だが要レビュー
        "kept":             0,
    }

    # バッチ内重複防止用のワーキングセット
    seen_pmids:  set[str] = set(existing_pmids)
    seen_dois:   set[str] = set(existing_dois)
    seen_titles: set[str] = set(existing_titles)

    for record in records:
        pmid  = (record.get("pmid")  or "").strip()
        raw_doi = (record.get("doi") or "").strip()
        doi   = normalize_doi(raw_doi) if raw_doi else ""
        title = normalize_title(record.get("title") or "")

        # --- 優先順位 1: PMID 一致 ---
        if pmid and pmid in seen_pmids:
            stats["dup_pmid"] += 1
            logger.debug("PMID重複スキップ: %s", pmid)
            continue

        # --- 優先順位 2: DOI 一致 ---
        if doi and doi in seen_dois:
            stats["dup_doi"] += 1
            logger.debug("DOI重複スキップ: %s", doi)
            continue

        # --- 優先順位 3: タイトル照合 (PMID・DOI が両方空の場合) ---
        if not pmid and not doi:
            if title and title in seen_titles:
                # 既存 CSV との一致 → 重複として除外
                stats["dup_title_hard"] += 1
                logger.debug("タイトル重複スキップ (PMID/DOI なし): %s", record.get("title", "")[:60])
                continue
            if title:
                # 重複確認できないが識別子なし → 要レビューフラグを立てて保持
                record = {**record, "review_flag": True}
                stats["title_candidate"] += 1
                logger.debug("識別子なし論文を要レビューとして保持: %s", record.get("title", "")[:60])

        # --- ユニークなレコードとして採用 ---
        unique.append(record)
        stats["kept"] += 1

        # バッチ内重複防止のためワーキングセットに追加
        if pmid:
            seen_pmids.add(pmid)
        if doi:
            seen_dois.add(doi)
        if title:
            seen_titles.add(title)

    logger.info(
        "重複除去完了 — 入力: %d件, PMID重複: %d件, DOI重複: %d件, "
        "タイトル重複: %d件, 識別子なし要レビュー: %d件, 採用: %d件",
        stats["total"], stats["dup_pmid"], stats["dup_doi"],
        stats["dup_title_hard"], stats["title_candidate"], stats["kept"],
    )
    return unique, stats
