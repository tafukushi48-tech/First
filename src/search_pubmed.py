"""
PubMed 論文検索モジュール。

NCBI E-utilities REST API を使用して HAE 関連論文を検索・取得する。
  - ESearch: 検索クエリから PMID リストを取得
  - EFetch:  PMID リストから論文メタデータ (XML) を一括取得

環境変数:
  NCBI_API_KEY — NCBI API キー (省略可。なし: 3 req/s, あり: 10 req/s)
  NCBI_EMAIL   — NCBI への連絡先メール (推奨)

CLAUDE.md R-04, R-05 準拠。
"""
from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API エンドポイント定数
# ---------------------------------------------------------------------------
_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# EFetch 1回あたりの最大取得件数
_BATCH_SIZE = 200

# レート制限: APIキーなし 3 req/s → 間隔 0.34s、あり 10 req/s → 0.11s
_SLEEP_WITHOUT_KEY = 0.34
_SLEEP_WITH_KEY    = 0.11


# ---------------------------------------------------------------------------
# 内部ユーティリティ
# ---------------------------------------------------------------------------

def _base_params() -> dict[str, str]:
    """環境変数から NCBI 共通パラメータを組み立てる。"""
    params: dict[str, str] = {}
    api_key = os.environ.get("NCBI_API_KEY", "")
    email   = os.environ.get("NCBI_EMAIL", "")
    if api_key:
        params["api_key"] = api_key
    if email:
        params["email"] = email
    return params


def _sleep_interval() -> float:
    """API キーの有無に応じたスリープ間隔(秒)を返す。"""
    return _SLEEP_WITH_KEY if os.environ.get("NCBI_API_KEY") else _SLEEP_WITHOUT_KEY


def _http_get(
    url: str,
    params: dict,
    max_retries: int = 3,
    timeout: int = 30,
) -> Optional[requests.Response]:
    """
    シンプルなリトライ付き HTTP GET。

    失敗時は指数バックオフ (2s, 4s, 8s) で最大 max_retries 回リトライする。
    すべて失敗した場合は None を返す。
    """
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            time.sleep(_sleep_interval())
            return resp
        except requests.RequestException as e:
            wait = 2 ** attempt
            logger.warning(
                "HTTP GETエラー (試行 %d/%d): %s — %s — %d秒後リトライ",
                attempt, max_retries, url, e, wait,
            )
            if attempt < max_retries:
                time.sleep(wait)
    logger.error("HTTP GET が %d回失敗しました: %s", max_retries, url)
    return None


# ---------------------------------------------------------------------------
# ESearch — PMID リスト取得
# ---------------------------------------------------------------------------

def _esearch(query: str, max_results: int) -> list[str]:
    """
    ESearch API でクエリを実行し、PMID のリストを返す。

    Args:
        query:       PubMed 検索クエリ文字列
        max_results: 最大取得件数

    Returns:
        PMID 文字列のリスト (空の場合は空リスト)
    """
    params = {
        **_base_params(),
        "db":       "pubmed",
        "term":     query,
        "retmax":   str(max_results),
        "retmode":  "json",
        "usehistory": "n",
    }
    resp = _http_get(_ESEARCH_URL, params)
    if resp is None:
        return []

    try:
        data = resp.json()
        pmids: list[str] = data.get("esearchresult", {}).get("idlist", [])
        total = data.get("esearchresult", {}).get("count", "?")
        logger.info("ESearch完了 — クエリ: '%s...' 総ヒット: %s件, 取得PMID: %d件",
                    query[:60], total, len(pmids))
        return pmids
    except Exception as e:
        logger.error("ESearch JSONパースエラー: %s", e)
        return []


# ---------------------------------------------------------------------------
# EFetch — 論文メタデータ取得・パース
# ---------------------------------------------------------------------------

def _efetch_xml(pmid_batch: list[str]) -> Optional[str]:
    """
    PMID のバッチに対して EFetch を実行し、XML テキストを返す。
    """
    params = {
        **_base_params(),
        "db":      "pubmed",
        "id":      ",".join(pmid_batch),
        "rettype": "xml",
        "retmode": "xml",
    }
    resp = _http_get(_EFETCH_URL, params)
    return resp.text if resp is not None else None


def _parse_pubdate(pubdate_elem: Optional[ET.Element]) -> tuple[int, str]:
    """
    PubDate XML 要素から (pub_year: int, pub_date: str) を返す。

    XML には Year/Month/Day または MedlineDate の形式がある。
    パース失敗時は (0, "") を返す。
    """
    if pubdate_elem is None:
        return 0, ""

    year_text  = pubdate_elem.findtext("Year", "").strip()
    month_text = pubdate_elem.findtext("Month", "").strip()
    day_text   = pubdate_elem.findtext("Day", "").strip()

    # MedlineDate フォールバック (例: "2023 Jan-Feb")
    if not year_text:
        medline = pubdate_elem.findtext("MedlineDate", "").strip()
        if medline:
            year_text = medline[:4]

    try:
        year = int(year_text)
    except ValueError:
        return 0, ""

    # 月名を数値に変換
    month_map = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "may": "05", "jun": "06", "jul": "07", "aug": "08",
        "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }
    month_num = month_map.get(month_text[:3].lower(), "01") if month_text else "01"
    day_num   = day_text.zfill(2) if day_text.isdigit() else "01"

    pub_date = f"{year}-{month_num}-{day_num}"
    return year, pub_date


def _parse_article(article_elem: ET.Element) -> Optional[dict]:
    """
    PubmedArticle XML 要素を論文レコード dict に変換する。

    必須フィールド (title, および pmid か doi のいずれか) が欠けている場合は
    None を返す。
    """
    mc = article_elem.find("MedlineCitation")
    if mc is None:
        return None

    # PMID
    pmid_elem = mc.find("PMID")
    pmid = pmid_elem.text.strip() if (pmid_elem is not None and pmid_elem.text) else ""

    article = mc.find("Article")
    if article is None:
        return None

    # タイトル (インラインタグ <i>, <sup> 等を含む場合は itertext で結合)
    title_elem = article.find("ArticleTitle")
    title = "".join(title_elem.itertext()).strip() if title_elem is not None else ""

    # アブストラクト (複数セクションを結合)
    abstract_parts: list[str] = []
    for at in article.findall(".//Abstract/AbstractText"):
        label = at.get("Label", "")
        text  = "".join(at.itertext()).strip()
        if text:
            abstract_parts.append(f"{label}: {text}" if label else text)
    abstract = " ".join(abstract_parts)

    # 著者 (LastName + Initials)
    author_list: list[str] = []
    for author in article.findall(".//AuthorList/Author"):
        last     = author.findtext("LastName", "").strip()
        initials = author.findtext("Initials", "").strip()
        if last:
            author_list.append(f"{last} {initials}".strip())
    authors = "; ".join(author_list)

    # ジャーナル名
    journal = article.findtext(".//Journal/Title", "").strip()

    # 出版日
    pubdate_elem = article.find(".//Journal/JournalIssue/PubDate")
    pub_year, pub_date = _parse_pubdate(pubdate_elem)

    # DOI は PubmedData/ArticleIdList から取得
    doi = ""
    pubmed_data = article_elem.find("PubmedData")
    if pubmed_data is not None:
        for aid in pubmed_data.findall(".//ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi" and aid.text:
                doi = aid.text.strip()
                break

    # バリデーション: タイトルが空、または pmid・doi が両方空 → スキップ
    if not title:
        return None
    if not pmid and not doi:
        logger.debug("タイトルのみのレコードをスキップ (pmid/doi なし): %s", title[:60])
        return None

    return {
        "pmid":     pmid,
        "doi":      doi,
        "title":    title,
        "abstract": abstract,
        "authors":  authors,
        "journal":  journal,
        "pub_year": pub_year,
        "pub_date": pub_date,
        "source":   "pubmed",
    }


def _parse_xml_articles(xml_text: str) -> list[dict]:
    """
    EFetch XML テキストを論文レコードのリストに変換する。

    パースエラーのある個別記事はスキップしてログに記録する。
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error("PubMed XML のパースに失敗しました: %s", e)
        return []

    records: list[dict] = []
    for article_elem in root.findall(".//PubmedArticle"):
        try:
            rec = _parse_article(article_elem)
            if rec is not None:
                records.append(rec)
        except Exception as e:
            pmid = article_elem.findtext(".//PMID", "unknown")
            logger.warning("記事パースエラー (PMID: %s): %s", pmid, e)

    return records


# ---------------------------------------------------------------------------
# パブリックインターフェース
# ---------------------------------------------------------------------------

def search(query: str, max_results: int = 500) -> list[dict]:
    """
    PubMed を検索し、論文レコードのリストを返す。

    Args:
        query:       PubMed 検索クエリ (MeSH タグや [Title/Abstract] を含む形式)
        max_results: 最大取得件数 (デフォルト 500)

    Returns:
        論文レコード dict のリスト。各レコードには以下のキーが含まれる:
        pmid, doi, title, abstract, authors, journal, pub_year, pub_date, source
        エラー時は空リストを返す。
    """
    logger.info("PubMed 検索開始: '%s...' (最大 %d件)", query[:60], max_results)

    pmids = _esearch(query, max_results)
    if not pmids:
        logger.info("PubMed 検索結果: 0件")
        return []

    records: list[dict] = []
    # バッチ処理
    for i in range(0, len(pmids), _BATCH_SIZE):
        batch = pmids[i: i + _BATCH_SIZE]
        logger.debug("EFetch バッチ %d–%d / %d件", i + 1, i + len(batch), len(pmids))

        xml_text = _efetch_xml(batch)
        if xml_text is None:
            logger.warning("EFetch 失敗 — バッチ %d–%d をスキップします", i + 1, i + len(batch))
            continue

        batch_records = _parse_xml_articles(xml_text)
        records.extend(batch_records)
        logger.debug("バッチ取得: %d件", len(batch_records))

    logger.info("PubMed 検索完了: %d件取得", len(records))
    return records
