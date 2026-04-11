"""
Europe PMC 論文検索モジュール。

Europe PMC REST API を使用して HAE 関連論文を検索・取得する。
カーソルベースのページネーションで大量結果に対応する。

返却フィールド名は search_pubmed.py と統一されており、main.py の
_normalize_raw_record() で pub_date / pub_year に変換される。

API ドキュメント: https://europepmc.org/RestfulWebService

CLAUDE.md R-05 準拠 (レート制限: 10 req/s)。
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

import requests
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API 定数
# ---------------------------------------------------------------------------
_BASE_URL       = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_MAX_PAGE_SIZE  = 1000   # Europe PMC の 1リクエストあたり上限
_SLEEP_INTERVAL = 0.12   # 10 req/s 制限に対応 (~0.1s + マージン)


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

    失敗時は指数バックオフ (2s → 4s → 8s) でリトライする。
    すべて失敗した場合は None を返す。

    Args:
        url:         リクエスト先 URL
        params:      クエリパラメータ dict
        max_retries: 最大リトライ回数 (デフォルト 3)
        timeout:     タイムアウト秒数 (デフォルト 30)

    Returns:
        JSON レスポンスを dict で返す。失敗時は None。
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

    logger.error("HTTP GET が %d回すべて失敗しました: %s", max_retries, url)
    return None


def _build_query(
    query:      str,
    start_date: Optional[str],
    end_date:   Optional[str],
) -> str:
    """
    ベースクエリに日付フィルタを付加した Lucene クエリ文字列を生成する。

    Europe PMC では mindate/maxdate パラメータは存在しないため、
    FIRST_PDATE フィールドを Lucene Range Query 形式でクエリに追記する。

    例:
      start_date="2020-01-01", end_date="2024-12-31"
      → 末尾に AND FIRST_PDATE:[2020-01-01 TO 2024-12-31] を追加

    Args:
        query:      ベース検索クエリ
        start_date: 開始日 (YYYY-MM-DD 形式、省略可)
        end_date:   終了日 (YYYY-MM-DD 形式、省略可)

    Returns:
        日付フィルタを含む Lucene クエリ文字列
    """
    if not start_date and not end_date:
        return query

    low  = start_date if start_date else "*"
    high = end_date   if end_date   else "*"
    date_filter = f"FIRST_PDATE:[{low} TO {high}]"
    return f"({query}) AND {date_filter}"


# ---------------------------------------------------------------------------
# フィールド正規化ヘルパー
# ---------------------------------------------------------------------------

def _normalize_doi(doi: str) -> str:
    """
    DOI 文字列から URL プレフィックスを除去して正規化する。

    "https://doi.org/10.xxx" や "doi:10.xxx" 形式をそのまま保存すると
    重複除去で不一致になるため、純粋な DOI 形式 ("10.xxx/...") に統一する。

    Args:
        doi: 生 DOI 文字列

    Returns:
        正規化済み DOI 文字列 (例: "10.1234/example")
    """
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
    return doi


def _normalize_authors(author_string: str) -> str:
    """
    Europe PMC の authorString を "LastName FI; LastName FI" 形式に正規化する。

    Europe PMC は "Smith JA, Jones B." のようにカンマ区切りかつ末尾ピリオドを
    付ける形式を取る。search_pubmed.py の出力に揃えてセミコロン区切りにする。

    Args:
        author_string: Europe PMC の authorString フィールド値

    Returns:
        セミコロン区切りの著者文字列 (例: "Smith JA; Jones B")
    """
    if not author_string:
        return ""

    # 末尾ピリオドを除去
    author_string = author_string.rstrip(". ")

    # セミコロン区切りがすでに含まれる場合はセミコロンをカンマに統一してから処理
    author_string = author_string.replace("; ", ", ")

    # カンマ区切りで分割し、各著者名をトリム
    authors = [a.strip() for a in author_string.split(",") if a.strip()]
    return "; ".join(authors)


def _normalize_journal(result: dict) -> str:
    """
    Europe PMC の結果 dict からジャーナル名を取得して正規化する。

    取得優先順位:
      1. journalInfo.journal.title (フルタイトル)
      2. journalTitle (短縮名または代替フィールド)

    Args:
        result: Europe PMC 検索結果の 1件 dict

    Returns:
        ジャーナル名文字列。取得失敗時は空文字列。
    """
    try:
        journal_info = result.get("journalInfo") or {}
        journal_obj  = journal_info.get("journal") or {}
        full_title   = (journal_obj.get("title") or "").strip()
        if full_title:
            return full_title
        return (result.get("journalTitle") or "").strip()
    except Exception as e:
        logger.debug("ジャーナル取得エラー: %s", e)
        return ""


def _normalize_publication_date(result: dict) -> str:
    """
    Europe PMC の結果 dict から出版日を YYYY-MM-DD 形式で取得する。

    取得優先順位:
      1. firstPublicationDate  (例: "2024-01-15")
      2. pubYear               (例: "2024") → "2024-01-01" に補完

    どちらも存在しない、またはパース失敗時は空文字列を返す。

    Args:
        result: Europe PMC 検索結果の 1件 dict

    Returns:
        "YYYY-MM-DD" 形式の文字列。取得失敗時は空文字列。
    """
    # firstPublicationDate を試みる
    raw = (result.get("firstPublicationDate") or "").strip()
    if raw:
        try:
            # "YYYY-MM-DD" または "YYYY-MM-DDTHH:MM:SSZ" 形式を想定
            dt = dateparser.parse(raw)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            # 正規表現で年だけでも拾う
            m = re.match(r"(\d{4})", raw)
            if m:
                return f"{m.group(1)}-01-01"

    # pubYear フォールバック
    pub_year_str = str(result.get("pubYear") or "").strip()
    if pub_year_str.isdigit():
        return f"{pub_year_str}-01-01"

    return ""


# ---------------------------------------------------------------------------
# 記事パース
# ---------------------------------------------------------------------------

def _parse_article(result: dict) -> Optional[dict]:
    """
    Europe PMC 検索結果の 1件 (dict) を論文レコード dict に変換する。

    各フィールドを個別に取得し、1フィールドの失敗が全体に波及しないよう設計する。
    abstract が欠損している場合は空文字列を設定してスキップしない。

    以下の条件に該当するレコードは None を返してスキップする:
      - title が空
      - pmid と doi が両方空

    Args:
        result: Europe PMC REST API の result 1件 dict

    Returns:
        論文レコード dict。スキップ対象の場合は None。
        キー: pmid, doi, title, abstract, authors, journal, publication_date, source
    """
    # --- title ---
    try:
        title = (result.get("title") or "").strip()
        # タイトル末尾に付く余分なピリオドを除去
        title = title.rstrip(". ")
    except Exception:
        title = ""

    if not title:
        return None

    # --- pmid ---
    try:
        pmid = str(result.get("pmid") or "").strip()
    except Exception:
        pmid = ""

    # --- doi ---
    try:
        raw_doi = str(result.get("doi") or "").strip()
        doi = _normalize_doi(raw_doi) if raw_doi else ""
    except Exception:
        doi = ""

    if not pmid and not doi:
        logger.debug("識別子なし (pmid/doi 両方空) のためスキップ: %s", title[:60])
        return None

    # --- abstract (欠損でも空文字列として継続) ---
    try:
        abstract = (result.get("abstractText") or "").strip()
    except Exception:
        abstract = ""

    # --- authors ---
    try:
        raw_authors = (result.get("authorString") or "").strip()
        authors = _normalize_authors(raw_authors)
    except Exception:
        authors = ""

    # --- journal ---
    try:
        journal = _normalize_journal(result)
    except Exception:
        journal = ""

    # --- publication_date ---
    try:
        publication_date = _normalize_publication_date(result)
    except Exception:
        publication_date = ""

    return {
        "pmid":             pmid,
        "doi":              doi,
        "title":            title,
        "abstract":         abstract,
        "authors":          authors,
        "journal":          journal,
        "publication_date": publication_date,
        "source":           "EuropePMC",
    }


# ---------------------------------------------------------------------------
# パブリックインターフェース
# ---------------------------------------------------------------------------

def search(
    query:      str,
    start_date: Optional[str] = None,
    end_date:   Optional[str] = None,
    page_size:  int = 500,
) -> list[dict]:
    """
    Europe PMC を検索し、論文レコードのリストを返す。

    カーソルベースのページネーション (cursorMark) を使用して
    page_size 件まで取得する。API 失敗時は空リストを返す。

    返却フィールドは search_pubmed.search() と同一のキー名を使用する:
      pmid, doi, title, abstract, authors, journal, publication_date, source

    Args:
        query:      Europe PMC 検索クエリ (Lucene 構文)
        start_date: 検索開始日 (YYYY-MM-DD 形式、省略可)
        end_date:   検索終了日 (YYYY-MM-DD 形式、省略可)
        page_size:  最大取得件数 (デフォルト 500)

    Returns:
        論文レコード dict のリスト。エラー時は空リストを返す。
    """
    full_query = _build_query(query, start_date, end_date)

    date_info = ""
    if start_date or end_date:
        date_info = f" [{start_date or ''}〜{end_date or ''}]"

    logger.info(
        "Europe PMC 検索開始: '%s...'%s (最大 %d件)",
        query[:60], date_info, page_size,
    )

    records:    list[dict] = []
    cursor:     str = "*"
    # 1リクエストあたりの件数: API 上限と page_size の小さい方
    fetch_size  = min(_MAX_PAGE_SIZE, page_size)
    logged_total = False

    while len(records) < page_size:
        params = {
            "query":      full_query,
            "format":     "json",
            "resultType": "core",
            "pageSize":   str(fetch_size),
            "cursorMark": cursor,
            "sort":       "P_PDATE_D desc",   # 新しい順
        }

        data = _http_get(_BASE_URL, params)
        if data is None:
            logger.warning(
                "Europe PMC API 呼び出し失敗。ここまでの取得分 (%d件) を返します",
                len(records),
            )
            break

        result_list = (data.get("resultList") or {}).get("result") or []
        if not result_list:
            logger.debug("Europe PMC 結果が空。取得終了")
            break

        # 総ヒット数のログ (初回のみ)
        if not logged_total:
            total = data.get("hitCount", "?")
            logger.info("Europe PMC 総ヒット数: %s件", total)
            logged_total = True

        # 個別パース (エラーはスキップ)
        for item in result_list:
            try:
                rec = _parse_article(item)
                if rec is not None:
                    records.append(rec)
            except Exception as e:
                logger.warning(
                    "Europe PMC 記事パースエラー (id: %s): %s",
                    item.get("id", "不明"), e,
                )

        # ページネーション: nextCursorMark が同じ or なければ終了
        next_cursor = data.get("nextCursorMark", "")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

        # 残り件数に合わせて fetch_size を調整
        remaining = page_size - len(records)
        if remaining <= 0:
            break
        fetch_size = min(_MAX_PAGE_SIZE, remaining)

    result = records[:page_size]
    logger.info("Europe PMC 検索完了: %d件取得", len(result))
    return result
