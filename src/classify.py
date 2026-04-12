"""
HAE論文のルールベース分類モジュール。

分類軸:
  1. disease_subtype  — 疾患サブタイプ
  2. treatment_area   — 治療領域
  3. publication_type — 論文種別
  4. evidence_level   — エビデンスレベル (high / medium / low / unknown)
  5. ma_relevance     — Medical Affairs 関連度 (high / medium / low)

設計方針:
  - 分類ルール・キーワード・マッピング定数はすべて rules.py で管理する
  - このモジュールは分類ロジックのみを含む
  - ルールを追加・修正する場合は rules.py のみを編集すれば良い

ルール変更時は CLASSIFIER_VERSION をインクリメントし、CLAUDE.md も更新すること。
"""
from __future__ import annotations

import re

from rules import (
    Rule,
    DISEASE_SUBTYPE_RULES,
    TREATMENT_AREA_RULES,
    PUBLICATION_TYPE_RULES,
    META_ANALYSIS_PATTERNS,
    PUBTYPE_TO_EVIDENCE,
    MA_RELEVANCE_TO_SCORE,
    HAE_SUBTYPES,
    TREATMENT_FOCUSED_AREAS,
    HIGH_MA_PUBTYPES,
    MEDIUM_MA_PUBTYPES,
    LOW_MA_PUBTYPES,
    MEDIUM_MA_AREAS,
)

# 分類ルールのバージョン (semver)
CLASSIFIER_VERSION = "2.1.1"


# ---------------------------------------------------------------------------
# 内部ユーティリティ
# ---------------------------------------------------------------------------

def _combined_text(title: str, abstract: str) -> str:
    """
    タイトルとアブストラクトを結合して検索対象テキストを生成する。

    Args:
        title:    論文タイトル
        abstract: アブストラクト

    Returns:
        "タイトル アブストラクト" 形式の結合文字列
    """
    return f"{title} {abstract}"


def _match_any(patterns: tuple[str, ...], text: str) -> bool:
    """
    パターンタプルのいずれかが text にマッチするか判定する。

    大文字小文字を無視する (re.IGNORECASE)。
    パターンが空の場合は False を返す。

    Args:
        patterns: 正規表現パターンのタプル
        text:     検索対象テキスト

    Returns:
        いずれかのパターンがマッチすれば True
    """
    return any(bool(re.search(p, text, re.IGNORECASE)) for p in patterns)


def _first_match(rules: list[Rule], text: str) -> tuple[str, str]:
    """
    ルールリストを上から順に評価し、最初にマッチした (label, description) を返す。

    どのルールにもマッチしなかった場合は ("unknown", "") を返す。

    Args:
        rules: Rule オブジェクトのリスト (評価順)
        text:  検索対象テキスト

    Returns:
        (label, description) のタプル
    """
    for rule in rules:
        if _match_any(rule.patterns, text):
            return rule.label, rule.description
    return "unknown", ""


# ---------------------------------------------------------------------------
# 1. disease_subtype 分類
# ---------------------------------------------------------------------------

def classify_disease_subtype(title: str, abstract: str) -> str:
    """
    疾患サブタイプを分類する。

    DISEASE_SUBTYPE_RULES を上から順に評価し、最初にマッチした
    ラベルを返す。どのルールにもマッチしない場合は "unspecified HAE" を返す
    (検索クエリがHAE特化のため、取得される論文はすべてHAE関連を前提とする)。

    Args:
        title:    論文タイトル
        abstract: アブストラクト

    Returns:
        "HAE-nC1INH" | "HAE type 1/2" | "unspecified HAE"
    """
    text = _combined_text(title, abstract)
    label, _ = _first_match(DISEASE_SUBTYPE_RULES, text)
    # どのルールにもマッチしない場合はHAE総論として扱う
    return label if label != "unknown" else "unspecified HAE"


# ---------------------------------------------------------------------------
# 2. treatment_area 分類
# ---------------------------------------------------------------------------

def classify_treatment_area(title: str, abstract: str) -> str:
    """
    治療領域を分類する。

    TREATMENT_AREA_RULES を上から順に評価する。
    どのルールにもマッチしない場合は "other" を返す。

    Args:
        title:    論文タイトル
        abstract: アブストラクト

    Returns:
        "guidelines" | "acute treatment" | "long-term prophylaxis" |
        "diagnosis" | "epidemiology" | "burden/QoL" | "basic science" | "other"
    """
    text = _combined_text(title, abstract)
    label, _ = _first_match(TREATMENT_AREA_RULES, text)
    return label if label != "unknown" else "other"


# ---------------------------------------------------------------------------
# 3. publication_type 分類
# ---------------------------------------------------------------------------

def classify_publication_type(title: str, abstract: str) -> str:
    """
    論文種別を分類する。

    PUBLICATION_TYPE_RULES を上から順に評価する。
    どのルールにもマッチしない場合は "unknown" を返す。

    Args:
        title:    論文タイトル
        abstract: アブストラクト

    Returns:
        "guideline/consensus" | "RCT" | "OLE/extension" | "RWE/observational" |
        "review" | "letter/commentary" | "case report" | "unknown"
    """
    text = _combined_text(title, abstract)
    label, _ = _first_match(PUBLICATION_TYPE_RULES, text)
    return label


# ---------------------------------------------------------------------------
# 4. evidence_level 分類 (publication_type からマッピング)
# ---------------------------------------------------------------------------
# "review" はメタ解析を含む場合は "high" に昇格する

def classify_evidence_level(
    publication_type: str,
    title: str = "",
    abstract: str = "",
) -> str:
    """
    publication_type からエビデンスレベルを返す。

    "review" かつメタ解析・システマティックレビューと判定される場合は
    "medium" から "high" に昇格する。

    Args:
        publication_type: classify_publication_type() の返り値
        title:            論文タイトル (メタ解析検出用、省略可)
        abstract:         アブストラクト (メタ解析検出用、省略可)

    Returns:
        "high" | "medium" | "low" | "unknown"
    """
    base = PUBTYPE_TO_EVIDENCE.get(publication_type, "unknown")

    # review がメタ解析/SRを含む場合は高エビデンスに昇格
    if base == "medium" and publication_type == "review":
        text = _combined_text(title, abstract)
        if _match_any(META_ANALYSIS_PATTERNS, text):
            return "high"

    return base


# ---------------------------------------------------------------------------
# 5. MA relevance 分類
# ---------------------------------------------------------------------------

def classify_ma_relevance(
    publication_type: str,
    evidence_level:   str,
    treatment_area:   str,
    disease_subtype:  str,
) -> tuple[str, str]:
    """
    Medical Affairs 関連度ラベルと根拠文字列を返す。

    ラベル基準:
      high   — MA活動に直接使用できる
               (RCT/ガイドライン/コンセンサス + HAE対象)
      medium — 間接的に有用
               (OLE/RWE/レビュー + HAE + 治療・疫学・QoL領域)
      low    — 参考資料として保持
               (症例報告・レター・基礎研究)

    Args:
        publication_type: 論文種別
        evidence_level:   エビデンスレベル
        treatment_area:   治療領域
        disease_subtype:  疾患サブタイプ

    Returns:
        (label, reason) のタプル
        label:  "high" | "medium" | "low"
        reason: 根拠を示す日本語文字列 (100字以内)
    """
    is_hae             = disease_subtype in HAE_SUBTYPES
    is_treatment_focus = treatment_area in TREATMENT_FOCUSED_AREAS

    # --- high ---
    if publication_type in HIGH_MA_PUBTYPES and is_hae:
        return "high", "RCTまたはガイドライン文献はMA活動に直接使用可能"
    if evidence_level == "high" and is_hae:
        return "high", "高エビデンスのHAE文献はMA活動に直接使用可能"

    # --- medium ---
    if publication_type in MEDIUM_MA_PUBTYPES and is_hae:
        if publication_type == "OLE/extension":
            return "medium", "OLE試験データはHAE治療の長期安全性訴求で間接的に有用"
        return "medium", "リアルワールドエビデンスとして間接的に有用"
    if publication_type == "review" and is_hae and is_treatment_focus:
        return "medium", "HAE治療領域のレビューとして間接的に有用"
    if treatment_area in MEDIUM_MA_AREAS and is_hae:
        if treatment_area == "diagnosis":
            return "medium", "診断・バイオマーカー文献として間接的に有用"
        if treatment_area == "short-term prophylaxis":
            return "medium", "短期予防 (処置前投与) の管理根拠として医師への情報提供に間接的に有用"
        return "medium", "疫学・QoLデータはペイヤー対応・価値訴求で間接的に有用"

    # --- low ---
    if publication_type in LOW_MA_PUBTYPES:
        return "low", "症例報告またはコメンタリーとして参考資料に保持"
    if treatment_area == "basic science":
        return "low", "基礎研究として参考資料に保持"
    if publication_type == "review":
        return "low", "治療に直結しない総説として参考資料に保持"
    if publication_type == "unknown":
        return "low", "論文種別が自動判定不能のため手動レビューが必要"

    # デフォルト: HAE 関連だが上記のいずれにも該当しないケース
    return "low", "自動分類外のため参考資料として保持・手動確認を推奨"


# ---------------------------------------------------------------------------
# why_it_matters_for_ma 生成 (ルールベース)
# ---------------------------------------------------------------------------

# 疾患サブタイプの表示用ラベル (日本語出力向け短縮形)
_DISEASE_DISPLAY: dict[str, str] = {
    "HAE type 1/2":    "C1-INH欠乏型HAE",
    "HAE-nC1INH":      "正常C1-INH型HAE",
    "unspecified HAE": "HAE",
}


def generate_why_it_matters_for_ma(
    publication_type: str,
    treatment_area:   str,
    disease_subtype:  str,
    evidence_level:   str,
) -> str:
    """
    publication_type / treatment_area / disease_subtype / evidence_level の組合せから、
    日本のMedical Affairsにとっての意義を示す1文（日本語）を生成する。

    LLMを使用しないルールベース実装。
    「可能性があります」「となりえます」等の表現を用い、過度な断定を避ける。

    評価順:
      1. guideline/consensus
      2. RCT (treatment_area で細分化)
      3. OLE/extension
      4. review (evidence_level で meta-analysis/SR とナラティブを区別)
      5. RWE/observational (treatment_area で細分化)
      6. treatment_area によるフォールバック (epidemiology / burden/QoL / diagnosis)
      7. publication_type によるフォールバック (case report / letter/commentary)
      8. basic science フォールバック
      9. デフォルト

    Args:
        publication_type: 論文種別 (classify_publication_type の出力値)
        treatment_area:   治療領域 (classify_treatment_area の出力値)
        disease_subtype:  疾患サブタイプ (classify_disease_subtype の出力値)
        evidence_level:   エビデンスレベル (classify_evidence_level の出力値)
                          "high" かつ publication_type == "review" → meta-analysis/SR と判断

    Returns:
        MA関連性を説明する日本語文字列 (概ね100字以内)
    """
    d = _DISEASE_DISPLAY.get(disease_subtype, "HAE")

    # ── ガイドライン・コンセンサス ─────────────────────────────────────────
    if publication_type == "guideline/consensus":
        return (
            f"{d}の診療ガイドライン・コンセンサス文書として、"
            "標準治療の推奨根拠を示す参照資料となりえます。"
        )

    # ── RCT ───────────────────────────────────────────────────────────────
    if publication_type == "RCT":
        if treatment_area == "long-term prophylaxis":
            return (
                f"{d}の長期予防を対象としたRCTとして、"
                "有効性・安全性の根拠として医師説明やpayer交渉で活用できる可能性があります。"
            )
        if treatment_area == "acute treatment":
            return (
                f"{d}の急性発作治療に関するRCTとして、"
                "治療選択の臨床的根拠として医療者への情報提供に活用できる可能性があります。"
            )
        if treatment_area == "short-term prophylaxis":
            return (
                f"{d}の短期予防（処置前投与）に関するRCTとして、"
                "周術期管理の臨床的根拠として医療者への情報提供に活用できる可能性があります。"
            )
        return (
            f"{d}を対象としたRCTとして、"
            "MA活動における高エビデンスの参照文献として活用できる可能性があります。"
        )

    # ── OLE / 延長試験 ────────────────────────────────────────────────────
    if publication_type == "OLE/extension":
        return (
            f"{d}の治療に関する延長試験として、"
            "長期安全性・持続的有効性の訴求資料として活用できる可能性があります。"
        )

    # ── レビュー (meta-analysis/SR vs ナラティブ) ─────────────────────────
    if publication_type == "review":
        _treatment_focus_areas = {
            "long-term prophylaxis", "acute treatment",
            "short-term prophylaxis", "guidelines",
        }
        if evidence_level == "high":
            # evidence_level が "high" に昇格 → meta-analysis または SR と判断
            if treatment_area in _treatment_focus_areas:
                return (
                    f"{d}の治療に関するメタ解析・SRとして、"
                    "エビデンス総括の根拠資料として活用できる可能性があります。"
                )
            return (
                f"{d}に関するメタ解析・SRとして、"
                "エビデンスの全体像把握に活用できる可能性があります。"
            )
        # ナラティブレビュー (evidence_level == "medium")
        if treatment_area in _treatment_focus_areas:
            return (
                f"{d}の治療に関する総説として、"
                "医師・payer向け教育資料の補足として活用できる可能性があります。"
            )
        return (
            f"{d}に関する総説として、"
            "疾患・治療の包括的理解のための参考資料として保持します。"
        )

    # ── RWE / 観察研究 ────────────────────────────────────────────────────
    if publication_type == "RWE/observational":
        if treatment_area in {"long-term prophylaxis", "acute treatment"}:
            return (
                f"{d}の治療実態を示すリアルワールドデータとして、"
                "payer対応や医療資源活用の根拠として有用な可能性があります。"
            )
        if treatment_area == "short-term prophylaxis":
            return (
                f"{d}の短期予防に関するリアルワールドデータとして、"
                "周術期管理の実態把握とpayer対応の根拠として活用できる可能性があります。"
            )
        if treatment_area == "epidemiology":
            return (
                f"{d}の疫学・医療資源利用に関する実態調査として、"
                "payer対応の定量的根拠として活用できる可能性があります。"
            )
        return (
            f"{d}に関する観察研究として、"
            "実臨床での疾患管理状況を把握するための参考資料として保持します。"
        )

    # ── 治療領域フォールバック ────────────────────────────────────────────
    if treatment_area == "epidemiology":
        return (
            f"{d}の疫学データとして、"
            "患者規模の把握やpayer・行政への疾患啓発活動の根拠として活用できる可能性があります。"
        )
    if treatment_area == "burden/QoL":
        return (
            f"{d}患者のQoL・疾患負荷データとして、"
            "患者アウトカムの重要性をpayerや医療者に伝える際の根拠として活用できる可能性があります。"
        )
    if treatment_area == "diagnosis":
        return (
            f"{d}の診断・バイオマーカーに関する知見として、"
            "早期診断啓発や診断精度向上に向けた医師教育の参考資料として活用できる可能性があります。"
        )
    if treatment_area == "short-term prophylaxis":
        return (
            f"{d}の短期予防（処置前投与）に関する文献として、"
            "周術期管理の根拠として医師への情報提供に活用できる可能性があります。"
        )

    # ── 論文種別フォールバック ────────────────────────────────────────────
    if publication_type == "case report":
        return (
            f"{d}に関する症例報告として、"
            "個別の治療経験を共有する参考資料として保持します。"
        )
    if publication_type == "letter/commentary":
        return (
            f"{d}に関する専門家のコメンタリーとして、"
            "議論の動向を把握するための参考資料として保持します。"
        )
    if treatment_area == "basic science":
        return (
            f"{d}の病態・メカニズムに関する基礎研究として、"
            "科学的背景の理解を深める参考資料として保持します。"
        )

    # ── デフォルト ────────────────────────────────────────────────────────
    return f"{d}に関する文献として、MA活動の参考資料として保持します。"


# ---------------------------------------------------------------------------
# 統合エントリーポイント
# ---------------------------------------------------------------------------

def classify_paper(record: dict) -> dict:
    """
    論文レコード dict に対して5軸分類を適用し、更新した dict を返す。

    入力 dict には 'title' および 'abstract' キーが必要。
    分類結果は元の dict にマージして返す (破壊的変更なし)。

    追加されるキー:
      disease_subtype    : 疾患サブタイプ
      treatment_area     : 治療領域
      publication_type   : 論文種別
      evidence_level     : エビデンスレベル (high/medium/low/unknown)
      ma_relevance       : MA関連度ラベル (high/medium/low)
      ma_relevance_score : MA関連度スコア (3/2/1, CSV スキーマ互換)
      ma_relevance_reason: MA関連度の根拠 (日本語、100字以内)
      classifier_version : 分類ルールのバージョン
      review_flag        : 手動レビュー要否 (bool)

    Args:
        record: pmid/doi/title/abstract を含む論文レコード dict

    Returns:
        分類結果を追加した dict
    """
    title    = str(record.get("title",    "") or "")
    abstract = str(record.get("abstract", "") or "")

    disease_subtype  = classify_disease_subtype(title, abstract)
    treatment_area   = classify_treatment_area(title, abstract)
    publication_type = classify_publication_type(title, abstract)
    evidence_level   = classify_evidence_level(publication_type, title, abstract)
    ma_label, _ = classify_ma_relevance(
        publication_type, evidence_level, treatment_area, disease_subtype
    )

    # why_it_matters_for_ma: publication_type / treatment_area / disease_subtype を
    # 踏まえた日本語の1文（100字以内）
    why_text = generate_why_it_matters_for_ma(
        publication_type, treatment_area, disease_subtype, evidence_level
    )[:100]

    # CSV スキーマ互換の整数スコアに変換 (dry-run レポート等の内部用)
    ma_score = MA_RELEVANCE_TO_SCORE.get(ma_label, 0)

    # review_flag: 手動レビューが必要な条件に1つでも該当すれば True (内部用)
    needs_review = (
        publication_type == "unknown"
        or evidence_level == "unknown"
        or ma_label == "low"
    )

    return {
        **record,
        "disease_subtype":     disease_subtype,
        "treatment_area":      treatment_area,
        "publication_type":    publication_type,
        "evidence_level":      evidence_level,
        "ma_relevance":        ma_label,
        "ma_relevance_score":  ma_score,       # 内部用 (CSV スキーマ外)
        "ma_relevance_reason": why_text,       # run_pipeline で why_it_matters_for_ma へリネーム
        "classifier_version":  CLASSIFIER_VERSION,
        "review_flag":         needs_review,   # 内部用 (CSV スキーマ外)
    }
