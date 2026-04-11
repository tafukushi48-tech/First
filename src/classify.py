"""
HAE論文のルールベース分類モジュール。

分類軸:
  1. disease_subtype  — 疾患サブタイプ
  2. treatment_area   — 治療領域
  3. publication_type — 論文種別
  4. evidence_level   — エビデンスレベル (high / medium / low / unknown)
  5. ma_relevance     — Medical Affairs 関連度 (high / medium / low)

設計方針:
  - 各軸は Rule オブジェクトのリストとして定義する
  - ルールは上から順に評価し、最初にマッチしたラベルを返す
  - 新規ルールの追加はリストへの Rule 追記のみで完結する
  - 分類根拠は Rule.description で明示する

ルール変更時は CLASSIFIER_VERSION をインクリメントし、CLAUDE.md も更新すること。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 分類ルールのバージョン (semver)
CLASSIFIER_VERSION = "2.0.0"


# ---------------------------------------------------------------------------
# Rule データクラス
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    """
    単一の分類ルール。

    Attributes:
        label:       分類値 (CSV に出力される文字列)
        patterns:    正規表現パターンのタプル (いずれか一致で採用)
        description: 分類根拠の説明 (デバッグ・レビュー・拡張時の参考用)
    """
    label:       str
    patterns:    tuple[str, ...]
    description: str = ""


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
# 1. disease_subtype 分類ルール
# ---------------------------------------------------------------------------
# 評価順: HAE-nC1INH (最も特異的) → HAE type 1/2 → unspecified HAE

DISEASE_SUBTYPE_RULES: list[Rule] = [
    Rule(
        label="HAE-nC1INH",
        patterns=(
            r"normal\s+C1.?INH",
            r"normal\s+C1.?inhibitor",
            r"HAE.{0,10}n[Cc]1.?INH",
            r"HAE.?nC1.?INH",
            r"HAE.{0,10}FXII",
            r"FXII.{0,10}HAE",
            r"factor\s+XII.{0,20}(hereditary|HAE|angioedema)",
            r"(hereditary|HAE|angioedema).{0,30}factor\s+XII",
            r"plasminogen.{0,30}(HAE|angioedema)",
            r"\bPLG\b.{0,20}(mutation|variant|HAE|angioedema)",
            r"\bANGPT1\b",
            r"\bKNG1\b",
            r"\bMYOF\b",
            r"\bHS3ST6\b",
            r"estrogen.?dependent.{0,20}(HAE|angioedema)",
            r"(HAE|angioedema).{0,30}estrogen.?dependent",
        ),
        description="正常C1-INH型HAE: FXII/PLG/ANGPT1/KNG1/MYOF/HS3ST6変異を含む",
    ),
    Rule(
        label="HAE type 1/2",
        patterns=(
            r"HAE.{0,5}type\s*(1|I|2|II)\b",
            r"HAE.{0,5}(1|2)\b",
            r"type\s*(1|I|2|II).{0,5}HAE",
            r"C1.?INH\s+deficien",
            r"C1.?inhibitor\s+deficien",
            r"C1\s+inhibitor\s+deficien",
            r"C1.?esterase\s+inhibitor\s+deficien",
            r"\bSERPING1\b",
        ),
        description="HAE type 1/2: C1-INH欠乏、SERPING1変異",
    ),
    Rule(
        label="unspecified HAE",
        patterns=(
            r"\bhereditary\s+angioedema\b",
            r"\bHAE\b",
            r"\bC1.?INH.?HAE\b",
            r"bradykinin.{0,20}angioedema",
            r"angioedema.{0,20}bradykinin",
        ),
        description="サブタイプ不明または横断的なHAE総論",
    ),
]


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
# 2. treatment_area 分類ルール
# ---------------------------------------------------------------------------
# 評価順: guidelines (論文種別の属性が強い) → 治療モダリティ → 疾患側面

TREATMENT_AREA_RULES: list[Rule] = [
    Rule(
        label="guidelines",
        patterns=(
            r"\bguideline",
            r"consensus\s+(statement|document|recommendation|paper)",
            r"management\s+(guideline|recommendation|algorithm)",
            r"\bWAO\b",
            r"\bHAWK\b",
            r"expert\s+(consensus|panel|recommendation)",
            r"position\s+paper",
        ),
        description="ガイドライン・コンセンサス文書",
    ),
    Rule(
        label="acute treatment",
        patterns=(
            r"\bicatibant\b",
            r"\bFirazyr\b",
            r"\becallantide\b",
            r"\bKalbitor\b",
            r"\bBerinert\b",
            r"\bRuconest\b",
            r"\bConestat\b",
            r"on.?demand\s+(treatment|therapy)",
            r"acute\s+(attack\s+treatment|treatment|therapy|management)",
            r"treatment\s+of\s+acute\s+(attack|episode)",
            r"rescue\s+(therapy|treatment|medication)",
            r"C1.?INH.{0,20}(intravenous|IV|concentrate).{0,30}(acute|attack)",
        ),
        description="急性発作治療: icatibant, ecallantide, C1-INH静注など",
    ),
    Rule(
        label="long-term prophylaxis",
        patterns=(
            r"\blanadelumab\b",
            r"\bTakhzyro\b",
            r"\bberotralstat\b",
            r"\bOrladeyo\b",
            r"\bHaegarda\b",
            r"C1.?INH\s+subcutaneous",
            r"subcutaneous\s+C1.?INH",
            r"long.?term\s+prophylaxis",
            r"\bLTP\b",
            r"\bdanazol\b",
            r"\bstanozolol\b",
            r"attenuated\s+androgen",
            r"tranexamic\s+acid.{0,30}(prophylaxis|HAE)",
            r"\bdonidalorsen\b",
            r"\bgaradacimab\b",
            r"anti.?FXII\b",
            r"anti.?factor\s*XII",
            r"short.?term\s+prophylaxis",
            r"pre.?procedur",
            r"perioperative\s+prophylaxis",
            r"gene\s+therapy",
            r"gene\s+editing",
            r"\bCRISPR\b",
            r"\bsiRNA\b",
            r"\bNTLA.?2002\b",
        ),
        description="長期予防療法 (LTP/STP): lanadelumab, berotralstat, 遺伝子治療など",
    ),
    Rule(
        label="diagnosis",
        patterns=(
            r"\bbiomarker",
            r"\bdiagnos",
            r"genetic\s+(test|screen|analys)",
            r"\bC4\s+level",
            r"\bC1q\b",
            r"complement\s+(test|level|assay|screen)",
            r"delayed\s+diagnosis",
            r"diagnostic\s+(criteria|tool|method|delay)",
        ),
        description="診断・バイオマーカー・遺伝子検査",
    ),
    Rule(
        label="epidemiology",
        patterns=(
            r"\bprevalence\b",
            r"\bincidence\b",
            r"\bepidemiolog",
            r"\bregistry\b",
            r"attack\s+(rate|frequency)",
            r"hospitaliz",
            r"emergency\s+(visit|department|room)",
            r"population.?based",
        ),
        description="疫学・発症頻度・医療資源利用",
    ),
    Rule(
        label="burden/QoL",
        patterns=(
            r"quality\s+of\s+life",
            r"\bQoL\b",
            r"health.?related\s+quality",
            r"patient.?reported\s+outcome",
            r"\bPRO\b",
            r"\bHAE.?QoL\b",
            r"\bEQ.?5D\b",
            r"\bSF.?36\b",
            r"disease\s+burden",
            r"economic\s+burden",
            r"cost.?of.?illness",
            r"healthcare\s+(utilization|cost|resource)",
            r"psychological\s+(impact|burden)",
            r"anxiety.{0,30}(HAE|angioedema)",
            r"depression.{0,30}(HAE|angioedema)",
        ),
        description="疾患負荷・QoL・患者報告アウトカム・経済的影響",
    ),
    Rule(
        label="basic science",
        patterns=(
            r"kallikrein.?kinin",
            r"bradykinin\s+(pathway|production|release|receptor|level)",
            r"plasma\s+kallikrein",
            r"complement\s+(activation|pathway|cascade|system)",
            r"C1.?INH\s+(function|mechanism|activity|structure)",
            r"\bpathogenesis\b",
            r"\bpathophysiolog",
            r"mechanism\s+of\s+(action|disease)",
            r"\bin\s+vitro\b",
            r"\bin\s+vivo\b",
            r"animal\s+model",
            r"mouse\s+model",
            r"cell\s+(line|culture|assay)",
            r"crystal\s+structure",
            r"molecular\s+(dynamics|mechanism)",
        ),
        description="基礎研究・病態生理・分子メカニズム",
    ),
]


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
# 3. publication_type 分類ルール
# ---------------------------------------------------------------------------
# 評価順: guideline/consensus → RCT → OLE/extension → RWE → review → letter → case report

PUBLICATION_TYPE_RULES: list[Rule] = [
    Rule(
        label="guideline/consensus",
        patterns=(
            r"\bguideline",
            r"consensus\s+(statement|document|recommendation)",
            r"position\s+paper",
            r"management\s+recommendation",
            r"expert\s+(consensus|panel\s+recommendation)",
        ),
        description="診療ガイドライン・コンセンサス文書",
    ),
    Rule(
        label="RCT",
        patterns=(
            r"randomized\s+(controlled\s+)?trial",
            r"randomised\s+(controlled\s+)?trial",
            r"\bRCT\b",
            r"double.?blind.{0,40}placebo",
            r"placebo.{0,40}controlled.{0,40}(trial|study)",
            r"phase\s+(2|3|II|III)\s+(randomized|randomised|controlled)",
        ),
        description="ランダム化比較試験",
    ),
    Rule(
        label="OLE/extension",
        patterns=(
            r"open.?label\s+extension",
            r"\bOLE\b",
            r"long.?term\s+(safety|tolerability|follow.?up).{0,30}(HAE|angioedema|study)",
            r"extension\s+(study|period|phase)",
            r"continued\s+(treatment|therapy).{0,30}(open.?label|extension)",
        ),
        description="オープンラベル延長試験・長期安全性試験",
    ),
    Rule(
        label="RWE/observational",
        patterns=(
            r"cohort\s+study",
            r"prospective\s+(cohort|study|observational)",
            r"retrospective\s+(cohort|study|analysis|review)",
            r"case.?control\s+study",
            r"cross.?sectional\s+study",
            r"observational\s+study",
            r"real.?world\s+(evidence|study|data|analysis)",
            r"\bRWE\b",
            r"\bregistry\s+study\b",
            r"claims\s+(database|data|analysis)",
            r"population.?based\s+study",
        ),
        description="リアルワールドエビデンス・観察研究",
    ),
    Rule(
        label="review",
        patterns=(
            r"meta.?analys",
            r"systematic\s+review",
            r"network\s+meta.?analys",
            r"\bSLR\b",
            r"\bNMA\b",
            r"\breview\s+article\b",
            r"\bnarrative\s+review\b",
            r"\bscoping\s+review\b",
            r"\bstate.?of.?the.?art\b",
            r"\breview\s+of\s+the\s+literature\b",
            r"\bcurrent\s+(concepts|perspectives|status)\b",
        ),
        description="レビュー (メタ解析・システマティックレビュー・ナラティブレビュー)",
    ),
    Rule(
        label="letter/commentary",
        patterns=(
            r"\beditorial\b",
            r"\bletter\s+to\s+the\s+editor",
            r"\bcorrespondence\b",
            r"\bcommentary\b",
            r"\bresponse\s+to\b",
            r"\bin\s+reply\b",
            r"\bpoint\s+of\s+view\b",
        ),
        description="レター・エディトリアル・コメンタリー",
    ),
    Rule(
        label="case report",
        patterns=(
            r"\bcase\s+report\b",
            r"\bcase\s+series\b",
            r"\bcase\s+presentation\b",
            r"we\s+report\s+a\s+case",
            r"report\s+of\s+a\s+(rare|novel|unusual)",
        ),
        description="症例報告・症例集積",
    ),
]


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
# 4. evidence_level 分類ルール (publication_type からマッピング)
# ---------------------------------------------------------------------------
# "review" はメタ解析を含む場合は "high" に昇格する

# メタ解析・システマティックレビューの検出パターン (内部使用)
_META_ANALYSIS_PATTERNS: tuple[str, ...] = (
    r"meta.?analys",
    r"systematic\s+review",
    r"network\s+meta.?analys",
    r"\bSLR\b",
    r"\bNMA\b",
)

# publication_type → evidence_level の基本マッピング
_PUBTYPE_TO_EVIDENCE: dict[str, str] = {
    "RCT":               "high",
    "guideline/consensus": "high",
    "OLE/extension":     "medium",
    "RWE/observational": "medium",
    "review":            "medium",   # メタ解析の場合は関数内で "high" に昇格
    "letter/commentary": "low",
    "case report":       "low",
    "unknown":           "unknown",
}


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
    base = _PUBTYPE_TO_EVIDENCE.get(publication_type, "unknown")

    # review がメタ解析/SRを含む場合は高エビデンスに昇格
    if base == "medium" and publication_type == "review":
        text = _combined_text(title, abstract)
        if _match_any(_META_ANALYSIS_PATTERNS, text):
            return "high"

    return base


# ---------------------------------------------------------------------------
# 5. MA relevance 分類ルール
# ---------------------------------------------------------------------------

_HAE_SUBTYPES: frozenset[str] = frozenset({
    "HAE type 1/2", "HAE-nC1INH", "unspecified HAE",
})

_TREATMENT_FOCUSED_AREAS: frozenset[str] = frozenset({
    "acute treatment", "long-term prophylaxis", "guidelines",
})

# ma_relevance ラベル → ma_relevance_score の変換マップ (CSV スキーマ互換)
MA_RELEVANCE_TO_SCORE: dict[str, int] = {
    "high":   3,
    "medium": 2,
    "low":    1,
}


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
    is_hae             = disease_subtype in _HAE_SUBTYPES
    is_treatment_focus = treatment_area in _TREATMENT_FOCUSED_AREAS

    # --- high ---
    if publication_type in {"RCT", "guideline/consensus"} and is_hae:
        return "high", "RCTまたはガイドライン文献はMA活動に直接使用可能"
    if evidence_level == "high" and is_hae:
        return "high", "高エビデンスのHAE文献はMA活動に直接使用可能"

    # --- medium ---
    if publication_type in {"OLE/extension"} and is_hae:
        return "medium", "OLE試験データはHAE治療の長期安全性訴求で間接的に有用"
    if publication_type in {"RWE/observational"} and is_hae:
        return "medium", "リアルワールドエビデンスとして間接的に有用"
    if publication_type == "review" and is_hae and is_treatment_focus:
        return "medium", "HAE治療領域のレビューとして間接的に有用"
    if treatment_area in {"epidemiology", "burden/QoL"} and is_hae:
        return "medium", "疫学・QoLデータはペイヤー対応・価値訴求で間接的に有用"
    if treatment_area == "diagnosis" and is_hae:
        return "medium", "診断・バイオマーカー文献として間接的に有用"

    # --- low ---
    if publication_type in {"letter/commentary", "case report"}:
        return "low", "症例報告またはコメンタリーとして参考資料に保持"
    if treatment_area == "basic science":
        return "low", "基礎研究として参考資料に保持"
    if publication_type == "review":
        return "low", "総説文献として参考資料に保持"

    # デフォルト (non-HAE 疾患など)
    return "low", "HAE直接関連性が低いため参考資料に保持"


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
    ma_label, ma_reason = classify_ma_relevance(
        publication_type, evidence_level, treatment_area, disease_subtype
    )

    # CSV スキーマ互換の整数スコアに変換
    ma_score = MA_RELEVANCE_TO_SCORE.get(ma_label, 0)

    # review_flag: 手動レビューが必要な条件に1つでも該当すれば True
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
        "ma_relevance_score":  ma_score,
        "ma_relevance_reason": ma_reason[:100],
        "classifier_version":  CLASSIFIER_VERSION,
        "review_flag":         needs_review,
    }
