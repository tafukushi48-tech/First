"""
PubMed 論文検索モジュール。

NCBI E-utilities REST API を使用して HAE 関連論文を検索・取得する。
  - ESearch: 検索クエリ・日付範囲から PMID リストを取得
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
# API エンドポイント・レート制限定数
# ---------------------------------------------------------------------------
_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# EFetch 1回あたりのバッチサイズ (NCBI 推奨上限 500 より余裕を持たせる)
_BATCH_SIZE = 200

# APIキーなし 3 req/s → 0.34s、あり 10 req/s → 0.11s
_SLEEP_WITHOUT_KEY = 0.34
_SLEEP_WITH_KEY    = 0.11

# 月名 → ゼロ埋め数値のマッピング
_MONTH_MAP: dict[str, str] = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


# ---------------------------------------------------------------------------
# 内部ユーティリティ
# ---------------------------------------------------------------------------

def _base_params() -> dict[str, str]:
    """
    環境変数から NCBI E-utilities 共通パラメータを組み立てる。

    NCBI_API_KEY と NCBI_EMAIL が設定されていれば自動付与する。
    どちらも省略可能だが、EMAIL の設定を NCBI は推奨している。

    Returns:
        NCBI API 共通パラメータの dict
    """
    params: dict[str, str] = {}
    api_key = os.environ.get("NCBI_API_KEY", "").strip()
    email   = os.environ.get("NCBI_EMAIL",   "").strip()
    if api_key:
        params["api_key"] = api_key
    if email:
        params["email"] = email
    return params


def _sleep_interval() -> float:
    """
    API キーの有無に応じたリクエスト間スリープ時間(秒)を返す。

    APIキーあり: 10 req/s → 0.11s
    APIキーなし:  3 req/s → 0.34s

    Returns:
        スリープ秒数 (float)
    """
    return _SLEEP_WITH_KEY if os.environ.get("NCBI_API_KEY") else _SLEEP_WITHOUT_KEY


def _http_get(
    url: str,
    params: dict,
    max_retries: int = 3,
    timeout: int = 30,
) -> Optional[requests.Response]:
    """
    リトライ付き HTTP GET を実行する。

    失敗時は指数バックオフ (2s → 4s → 8s) で最大 max_retries 回リトライする。
    すべて失敗した場合は None を返し、呼び出し元が空リストを返すことを想定する。

    Args:
        url:         リクエスト先 URL
        params:      クエリパラメータ dict
        max_retries: 最大リトライ回数 (デフォルト 3)
        timeout:     タイムアウト秒数 (デフォルト 30)

    Returns:
        成功時は Response オブジェクト、失敗時は None
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
                "HTTP GETエラー (試行 %d/%d): %s — %d秒後リトライ",
                attempt, max_retries, e, wait,
            )
            if attempt < max_retries:
                time.sleep(wait)

    logger.error("HTTP GET が %d回すべて失敗しました: %s", max_retries, url)
    return None


def _to_entrez_date(date_str: str) -> str:
    """
    YYYY-MM-DD 形式の日付文字列を Entrez API の YYYY/MM/DD 形式に変換する。

    不正な形式の場合はそのまま返す (API 側でエラーとなるが呼び出しは継続)。

    Args:
        date_str: YYYY-MM-DD または YYYY-MM 形式の文字列

    Returns:
        YYYY/MM/DD 形式の文字列
    """
    return date_str.replace("-", "/")


# ---------------------------------------------------------------------------
# ESearch — PMID リスト取得
# ---------------------------------------------------------------------------

def _esearch(
    query:      str,
    retmax:     int,
    start_date: Optional[str] = None,
    end_date:   Optional[str] = None,
) -> list[str]:
    """
    ESearch API でクエリを実行し、PMID のリストを返す。

    start_date / end_date を指定すると出版日フィルタ (datetype=pdat) が有効になる。
    API 失敗時・JSON パースエラー時は空リストを返す。

    Args:
        query:      PubMed 検索クエリ文字列 (MeSH タグや [Field] 指定を含む)
        retmax:     最大取得件数
        start_date: 検索開始日 (YYYY-MM-DD 形式、省略可)
        end_date:   検索終了日 (YYYY-MM-DD 形式、省略可)

    Returns:
        PMID 文字列のリスト。エラー時は空リスト。
    """
    params: dict[str, str] = {
        **_base_params(),
        "db":         "pubmed",
        "term":       query,
        "retmax":     str(retmax),
        "retmode":    "json",
        "usehistory": "n",
    }

    # 日付フィルタ: 片方だけ指定された場合は未指定側を省略 (API のデフォルトに委ねる)
    if start_date or end_date:
        params["datetype"] = "pdat"
        if start_date:
            params["mindate"] = _to_entrez_date(start_date)
        if end_date:
            params["maxdate"] = _to_entrez_date(end_date)

    resp = _http_get(_ESEARCH_URL, params)
    if resp is None:
        return []

    try:
        data  = resp.json()
        pmids: list[str] = data.get("esearchresult", {}).get("idlist", [])
        total = data.get("esearchresult", {}).get("count", "?")
        logger.info(
            "ESearch完了 — クエリ: '%s...' 総ヒット: %s件, 取得PMID: %d件",
            query[:60], total, len(pmids),
        )
        return pmids
    except Exception as e:
        logger.error("ESearch JSONパースエラー: %s", e)
        return []


# ---------------------------------------------------------------------------
# EFetch — XML 取得
# ---------------------------------------------------------------------------

def _efetch_xml(pmid_batch: list[str]) -> Optional[str]:
    """
    PMID のバッチに対して EFetch を実行し、レスポンス XML テキストを返す。

    API 失敗時は None を返す。呼び出し元でバッチをスキップする。

    Args:
        pmid_batch: PMID 文字列のリスト (最大 _BATCH_SIZE 件)

    Returns:
        XML テキスト文字列。失敗時は None。
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


# ---------------------------------------------------------------------------
# XML フィールド抽出ヘルパー (各フィールドを独立して取得)
# ---------------------------------------------------------------------------

def _get_elem_text(elem: Optional[ET.Element]) -> str:
    """
    XML 要素のテキストを安全に取得する。

    <i>, <sup> などのインラインタグを含む要素も itertext() で正確に結合する。
    要素が None またはテキストなしの場合は空文字列を返す。

    Args:
        elem: XML Element オブジェクト (None 可)

    Returns:
        要素のテキスト文字列 (前後の空白を除去済み)
    """
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def _get_pmid(mc: ET.Element) -> str:
    """
    MedlineCitation 要素から PMID を取得する。

    Args:
        mc: MedlineCitation XML 要素

    Returns:
        PMID 文字列。取得失敗時は空文字列。
    """
    try:
        elem = mc.find("PMID")
        return (elem.text or "").strip() if elem is not None else ""
    except Exception as e:
        logger.debug("PMID取得エラー: %s", e)
        return ""


def _get_title(article: ET.Element) -> str:
    """
    Article 要素からタイトルを取得する。

    インラインタグ (<i>, <sup> 等) を含む場合も itertext() で正確に結合する。

    Args:
        article: Article XML 要素

    Returns:
        論文タイトル文字列。取得失敗時は空文字列。
    """
    try:
        return _get_elem_text(article.find("ArticleTitle"))
    except Exception as e:
        logger.debug("タイトル取得エラー: %s", e)
        return ""


def _get_abstract(article: ET.Element) -> str:
    """
    Article 要素からアブストラクトを取得する。

    BACKGROUND / METHODS などのラベル付きセクションは "ラベル: テキスト" 形式で
    結合する。セクション区切りがない場合はテキストをそのまま返す。

    Args:
        article: Article XML 要素

    Returns:
        アブストラクト文字列。存在しない場合は空文字列。
    """
    try:
        parts: list[str] = []
        for at in article.findall(".//Abstract/AbstractText"):
            label = (at.get("Label") or "").strip()
            text  = _get_elem_text(at)
            if text:
                parts.append(f"{label}: {text}" if label else text)
        return " ".join(parts)
    except Exception as e:
        logger.debug("アブストラクト取得エラー: %s", e)
        return ""


def _get_authors(article: ET.Element) -> str:
    """
    Article 要素から著者リストを取得する。

    "LastName Initials" 形式で取得し、セミコロン区切りで結合する。
    CollectiveName (組織名著者) も含める。

    Args:
        article: Article XML 要素

    Returns:
        "Smith JA; Jones B" 形式の著者文字列。存在しない場合は空文字列。
    """
    try:
        author_list: list[str] = []
        for author in article.findall(".//AuthorList/Author"):
            last     = (author.findtext("LastName") or "").strip()
            initials = (author.findtext("Initials")  or "").strip()
            collective = (author.findtext("CollectiveName") or "").strip()
            if last:
                author_list.append(f"{last} {initials}".strip())
            elif collective:
                author_list.append(collective)
        return "; ".join(author_list)
    except Exception as e:
        logger.debug("著者取得エラー: %s", e)
        return ""


def _get_journal(article: ET.Element) -> str:
    """
    Article 要素からジャーナル名を取得する。

    ISOAbbreviation → Title の順でフォールバックする。

    Args:
        article: Article XML 要素

    Returns:
        ジャーナル名文字列。取得失敗時は空文字列。
    """
    try:
        abbrev = (article.findtext(".//Journal/ISOAbbreviation") or "").strip()
        full   = (article.findtext(".//Journal/Title")           or "").strip()
        return abbrev or full
    except Exception as e:
        logger.debug("ジャーナル取得エラー: %s", e)
        return ""


def _get_publication_date(article: ET.Element) -> str:
    """
    Article 要素から出版日を YYYY-MM-DD 形式で取得する。

    優先順位: JournalIssue/PubDate > ArticleDate
    月が英語名 (Jan 等) の場合は数値に変換する。
    日付の一部が欠損している場合は "-01" で補完する。

    Args:
        article: Article XML 要素

    Returns:
        "YYYY-MM-DD" 形式の文字列。取得失敗時は空文字列。
    """
    try:
        # 優先: JournalIssue/PubDate
        pubdate = article.find(".//Journal/JournalIssue/PubDate")
        # フォールバック: ArticleDate (電子出版日)
        if pubdate is None:
            pubdate = article.find(".//ArticleDate")

        if pubdate is None:
            return ""

        year_text  = (pubdate.findtext("Year")  or "").strip()
        month_text = (pubdate.findtext("Month") or "").strip()
        day_text   = (pubdate.findtext("Day")   or "").strip()

        # MedlineDate フォールバック (例: "2023 Jan-Feb" → 年だけ使う)
        if not year_text:
            medline = (pubdate.findtext("MedlineDate") or "").strip()
            year_text = medline[:4] if medline else ""

        if not year_text:
            return ""

        int(year_text)  # 年が数値でなければ ValueError → 空文字列を返す

        # 月: 英語名を数値に変換、数値はゼロ埋め、なければ "01"
        if month_text:
            month_num = _MONTH_MAP.get(month_text[:3].lower())
            if month_num is None:
                # 既に数値の場合
                month_num = month_text.zfill(2) if month_text.isdigit() else "01"
        else:
            month_num = "01"

        day_num = day_text.zfill(2) if day_text.isdigit() else "01"

        return f"{year_text}-{month_num}-{day_num}"

    except (ValueError, TypeError):
        return ""
    except Exception as e:
        logger.debug("出版日取得エラー: %s", e)
        return ""


def _get_doi(article_elem: ET.Element) -> str:
    """
    PubmedArticle 要素から DOI を取得する。

    PubmedData/ArticleIdList の IdType="doi" 要素を参照する。
    存在しない場合は空文字列を返す。

    Args:
        article_elem: PubmedArticle XML 要素 (最上位)

    Returns:
        DOI 文字列 (例: "10.1234/example")。取得失敗時は空文字列。
    """
    try:
        pubmed_data = article_elem.find("PubmedData")
        if pubmed_data is None:
            return ""
        for aid in pubmed_data.findall(".//ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi" and aid.text:
                return aid.text.strip()
        return ""
    except Exception as e:
        logger.debug("DOI取得エラー: %s", e)
        return ""


# ---------------------------------------------------------------------------
# XML パース
# ---------------------------------------------------------------------------

def _parse_article(article_elem: ET.Element) -> Optional[dict]:
    """
    PubmedArticle XML 要素を論文レコード dict に変換する。

    各フィールドを独立したヘルパーで取得するため、1フィールドの失敗が
    他のフィールドの取得を妨げない。

    以下の条件に該当する場合は None を返してスキップする:
      - MedlineCitation または Article 要素が存在しない
      - title が空
      - pmid と doi が両方空

    Args:
        article_elem: PubmedArticle XML 要素

    Returns:
        論文レコード dict。スキップ対象の場合は None。
        キー: pmid, doi, title, abstract, authors, journal, publication_date, source
    """
    mc = article_elem.find("MedlineCitation")
    if mc is None:
        return None

    article = mc.find("Article")
    if article is None:
        return None

    pmid             = _get_pmid(mc)
    title            = _get_title(article)
    abstract         = _get_abstract(article)
    authors          = _get_authors(article)
    journal          = _get_journal(article)
    publication_date = _get_publication_date(article)
    doi              = _get_doi(article_elem)

    if not title:
        logger.debug("タイトル空のためスキップ (PMID: %s)", pmid or "不明")
        return None
    if not pmid and not doi:
        logger.debug("識別子なし (pmid/doi 両方空) のためスキップ: %s", title[:60])
        return None

    return {
        "pmid":             pmid,
        "doi":              doi,
        "title":            title,
        "abstract":         abstract,
        "authors":          authors,
        "journal":          journal,
        "publication_date": publication_date,
        "source":           "PubMed",
    }


def _parse_xml_articles(xml_text: str) -> list[dict]:
    """
    EFetch XML テキストを論文レコードのリストに変換する。

    XML 全体のパースエラーは空リストを返す。
    個別記事のパースエラーはログに記録してスキップし、他の記事の処理を継続する。

    Args:
        xml_text: EFetch API から取得した XML テキスト

    Returns:
        論文レコード dict のリスト。パース失敗時は空リスト。
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
            pmid = article_elem.findtext(".//PMID", "不明")
            logger.warning("記事パースエラー (PMID: %s): %s", pmid, e)

    return records


# ---------------------------------------------------------------------------
# パブリックインターフェース
# ---------------------------------------------------------------------------

def search(
    query:      str,
    start_date: Optional[str] = None,
    end_date:   Optional[str] = None,
    retmax:     int = 500,
) -> list[dict]:
    """
    PubMed を検索し、論文レコードのリストを返す。

    ESearch で PMID を取得後、EFetch でバッチ処理してメタデータを取得する。
    API 失敗・XML パースエラーは空リストを返し、例外を外部に伝播させない。

    Args:
        query:      PubMed 検索クエリ (MeSH タグや [Title/Abstract] を含む形式)
        start_date: 検索開始日 (YYYY-MM-DD 形式、省略可)
        end_date:   検索終了日 (YYYY-MM-DD 形式、省略可)
        retmax:     最大取得件数 (デフォルト 500)

    Returns:
        論文レコード dict のリスト。各 dict のキー:
          pmid, doi, title, abstract, authors, journal, publication_date, source
        エラー時は空リストを返す。
    """
    date_info = ""
    if start_date or end_date:
        date_info = f" [{start_date or ''}〜{end_date or ''}]"

    logger.info("PubMed 検索開始: '%s...'%s (最大 %d件)", query[:60], date_info, retmax)

    pmids = _esearch(query, retmax, start_date, end_date)
    if not pmids:
        logger.info("PubMed 検索結果: 0件")
        return []

    records: list[dict] = []
    total = len(pmids)

    for i in range(0, total, _BATCH_SIZE):
        batch = pmids[i: i + _BATCH_SIZE]
        logger.debug("EFetch バッチ %d–%d / %d件", i + 1, i + len(batch), total)

        xml_text = _efetch_xml(batch)
        if xml_text is None:
            logger.warning("EFetch 失敗 — バッチ %d–%d をスキップします", i + 1, i + len(batch))
            continue

        batch_records = _parse_xml_articles(xml_text)
        records.extend(batch_records)
        logger.debug("バッチ取得: %d件 (累計: %d件)", len(batch_records), len(records))

    logger.info("PubMed 検索完了: %d件取得", len(records))
    return records
