"""
Europe PMC 論文検索モジュール。

Europe PMC REST API を使用して HAE 関連論文を検索・取得する。
カーソルベースのページネーションで大量結果に対応する。

API ドキュメント: https://europepmc.org/RestfulWebService

CLAUDE.md R-05 準拠 (レート制限: 10 req/s)。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API 定数
# ---------------------------------------------------------------------------
_BASE_URL      = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_PAGE_SIZE     = 1000   # Europe PMC は最大 1000件/リクエスト
_SLEEP_INTERVAL = 0.12  # 10 req/s 制限に対応 (~0.1s + マージン)


# ---------------------------------------------------------------------------
# 内部ユーティリティ
# ---------------------------------------------------------------------------

def _http_get(
    url: str,
    params: dict,
    max_retries: int = 3,
    timeout: int = 30,
) -> Optional[dict]:
    """
    リトライ付き HTTP GET を実行し、JSON レスポンスを返す。

    失敗時は指数バックオフ (2s, 4s, 8s) でリトライする。
    すべて失敗した場合は None を返す。
    """
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            time.sleep(_SLEEP_INTERVAL)
            return resp.json()
        except requests.RequestException as e:
            wait = 2 ** attempt
            logger.warning(
                "HTTP GETエラー (試行 %d/%d): %s — %d秒後リトライ",
                attempt, max_retries, e, wait,
            )
            if attempt < max_retries:
                time.sleep(wait)
        except Exception as e:
            logger.error("Europe PMC レスポンスのデコードに失敗: %s", e)
            return None

    logger.error("HTTP GET が %d回失敗しました: %s", max_retries, url)
    return None


def _parse_pubdate(result: dict) -> tuple[int, str]:
    """
    Europe PMC の結果 dict から (pub_year: int, pub_date: str) を返す。

    フィールド候補: firstPublicationDate > pubYear
    パース失敗時は (0, "") を返す。
    """
    # firstPublicationDate (例: "2024-01-15")
    raw_date = result.get("firstPublicationDate", "")
    if raw_date:
        try:
            dt = dateparser.parse(raw_date)
            return dt.year, dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    # pubYear フォールバック (例: "2024")
    pub_year_str = str(result.get("pubYear", ""))
    try:
        year = int(pub_year_str)
        return year, f"{year}-01-01"
    except ValueError:
        return 0, ""


def _parse_article(result: dict) -> Optional[dict]:
    """
    Europe PMC 検索結果の 1件 (dict) を論文レコード dict に変換する。

    必須フィールドが欠けている場合は None を返す。
    """
    title    = (result.get("title") or "").strip()
    abstract = (result.get("abstractText") or "").strip()
    pmid     = str(result.get("pmid") or "").strip()
    doi      = (result.get("doi") or "").strip()
    journal  = (result.get("journalTitle") or result.get("journal", {}).get("title", "")).strip()
    authors  = (result.get("authorString") or "").strip()

    pub_year, pub_date = _parse_pubdate(result)

    # バリデーション
    if not title:
        return None
    if not pmid and not doi:
        logger.debug("識別子なし (pmid/doi 両方空) のレコードをスキップ: %s", title[:60])
        return None

    # authorString は "Smith JA, Jones B" 形式 → セミコロン区切りに統一
    authors = authors.replace(", ", "; ")

    return {
        "pmid":     pmid,
        "doi":      doi,
        "title":    title,
        "abstract": abstract,
        "authors":  authors,
        "journal":  journal,
        "pub_year": pub_year,
        "pub_date": pub_date,
        "source":   "europepmc",
    }


# ---------------------------------------------------------------------------
# パブリックインターフェース
# ---------------------------------------------------------------------------

def search(query: str, max_results: int = 500) -> list[dict]:
    """
    Europe PMC を検索し、論文レコードのリストを返す。

    カーソルベースのページネーションを使用して max_results 件まで取得する。

    Args:
        query:       Europe PMC 検索クエリ (Lucene 構文)
        max_results: 最大取得件数 (デフォルト 500)

    Returns:
        論文レコード dict のリスト。各レコードには以下のキーが含まれる:
        pmid, doi, title, abstract, authors, journal, pub_year, pub_date, source
        エラー時は空リストを返す。
    """
    logger.info("Europe PMC 検索開始: '%s...' (最大 %d件)", query[:60], max_results)

    records:    list[dict] = []
    cursor:     str = "*"
    page_size   = min(_PAGE_SIZE, max_results)

    while len(records) < max_results:
        params = {
            "query":       query,
            "format":      "json",
            "resultType":  "core",
            "pageSize":    str(page_size),
            "cursorMark":  cursor,
            "sort":        "P_PDATE_D desc",  # 新しい順
        }

        data = _http_get(_BASE_URL, params)
        if data is None:
            logger.warning("Europe PMC API 呼び出し失敗。ここまでの取得分 (%d件) を返します", len(records))
            break

        result_list = data.get("resultList", {}).get("result", [])
        if not result_list:
            logger.debug("Europe PMC 結果が空。取得終了")
            break

        # 個別パース (エラーはスキップ)
        for item in result_list:
            try:
                rec = _parse_article(item)
                if rec is not None:
                    records.append(rec)
            except Exception as e:
                logger.warning("Europe PMC 記事パースエラー: %s — %s",
                               item.get("id", "unknown"), e)

        # ページネーション: nextCursorMark が同じ or なければ終了
        next_cursor = data.get("nextCursorMark", "")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

        # 総ヒット件数のログ (初回のみ)
        if len(records) <= page_size:
            total = data.get("hitCount", "?")
            logger.info("Europe PMC 総ヒット数: %s件", total)

        # max_results に近づいたらページサイズを調整
        remaining = max_results - len(records)
        if remaining <= 0:
            break
        page_size = min(_PAGE_SIZE, remaining)

    logger.info("Europe PMC 検索完了: %d件取得", len(records))
    return records[:max_results]
