"""
HAE論文の5軸ルールベース分類モジュール。

分類軸:
  1. disease_subtype   — 疾患サブタイプ
  2. treatment_area    — 治療領域
  3. publication_type  — 論文種別
  4. evidence_level    — エビデンスレベル (Oxford EBM 2011)
  5. ma_relevance      — Medical Affairs 関連度 (スコア 0–3)

ルール変更時は CLASSIFIER_VERSION をインクリメントし、CLAUDE.md も更新すること。
"""
from __future__ import annotations

import re

# 分類ルールのバージョン (semver)
CLASSIFIER_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# 内部ユーティリティ
# ---------------------------------------------------------------------------

def _text(title: str, abstract: str) -> str:
    """タイトルとアブストラクトを結合して検索対象テキストを生成する。"""
    return f"{title} {abstract}"


def _match(pattern: str, text: str) -> bool:
    """大文字小文字を無視してパターンが一致するか判定する。"""
    return bool(re.search(pattern, text, re.IGNORECASE))


def _match_any(patterns: list[str], text: str) -> bool:
    """パターンリストのいずれかが一致するか判定する。"""
    return any(_match(p, text) for p in patterns)


# ---------------------------------------------------------------------------
# 1. disease_subtype 分類ルール
# ---------------------------------------------------------------------------

# HAE-nC1-INH 特異的パターン（より具体的なので先に評価）
_NC1INH_PATTERNS: list[str] = [
    r"normal\s+C1.?INH",
    r"normal\s+C1.?inhibitor",
    r"HAE.{0,10}n[Cc]1.?INH",
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
    r"HAE.?nC1.?INH",
]

# HAE type 1 / type 2 パターン
_TYPE12_PATTERNS: list[str] = [
    r"HAE.{0,5}type\s*(1|I|2|II)\b",
    r"HAE.{0,5}(1|2)\b",
    r"type\s*(1|I|2|II).{0,5}HAE",
    r"C1.?INH\s+deficien",
    r"C1.?inhibitor\s+deficien",
    r"C1\s+inhibitor\s+deficien",
    r"\bSERPING1\b",
    r"C1.?esterase\s+inhibitor\s+deficien",
]

# HAE 総論パターン（サブタイプ不明または横断的）
_HAE_GENERAL_PATTERNS: list[str] = [
    r"\bhereditary\s+angioedema\b",
    r"\bHAE\b",
    r"\bC1.?INH.?HAE\b",
]

# bradykinin 性浮腫（HAE 非特異的）
_BRADYKININ_AE_PATTERNS: list[str] = [
    r"ACE.?inhibitor.{0,30}(induced|angioedema)",
    r"ACEi.{0,20}angioedema",
    r"ACEI.{0,20}angioedema",
    r"bradykinin.{0,20}angioedema",
    r"angioedema.{0,20}bradykinin",
    r"drug.?induced\s+angioedema",
]

# その他の血管性浮腫
_OTHER_AE_PATTERNS: list[str] = [
    r"allergic\s+angioedema",
    r"histaminergic\s+angioedema",
    r"idiopathic\s+angioedema",
    r"urticaria.{0,20}angioedema",
    r"angioedema.{0,20}urticaria",
    r"mast\s+cell.{0,20}angioedema",
]


def classify_disease_subtype(title: str, abstract: str) -> str:
    """
    疾患サブタイプを分類する。

    優先順位: HAE_nC1INH > HAE_type1_2 > bradykinin_AE > HAE_general > other_AE > unclassified
    """
    t = _text(title, abstract)

    if _match_any(_NC1INH_PATTERNS, t):
        return "HAE_nC1INH"
    if _match_any(_TYPE12_PATTERNS, t):
        return "HAE_type1_2"
    if _match_any(_BRADYKININ_AE_PATTERNS, t):
        return "bradykinin_AE"
    if _match_any(_HAE_GENERAL_PATTERNS, t):
        return "HAE_general"
    if _match_any(_OTHER_AE_PATTERNS, t):
        return "other_AE"
    return "unclassified"


# ---------------------------------------------------------------------------
# 2. treatment_area 分類ルール
# ---------------------------------------------------------------------------

_GUIDELINE_AREA_PATTERNS: list[str] = [
    r"\bguideline",
    r"consensus\s+(statement|document|recommendation|paper)",
    r"management\s+(guideline|recommendation)",
    r"\bWAO\b",
    r"\bHAWK\b",
    r"expert\s+(consensus|panel|recommendation)",
    r"position\s+paper",
    r"treatment\s+algorithm",
]

_GENE_THERAPY_PATTERNS: list[str] = [
    r"gene\s+therapy",
    r"gene\s+editing",
    r"\bCRISPR\b",
    r"\bsiRNA\b",
    r"RNA\s+interference",
    r"antisense\s+oligonucleotide",
    r"\bASO\b",
    r"mRNA\s+(therapy|treatment|vaccine)",
    r"\bNTLA.?2002\b",
    r"\bBMN.?331\b",
    r"gene\s+silencing",
]

_LTP_PATTERNS: list[str] = [
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
    r"tranexamic\s+acid.{0,30}(HAE|angioedema|prophylaxis)",
    r"\bdonidalorsen\b",
    r"\bgaradacimab\b",
    r"anti.?FXII\b",
    r"anti.?factor\s*XII",
    r"kallikrein\s+inhibitor.{0,30}prophylaxis",
]

_STP_PATTERNS: list[str] = [
    r"short.?term\s+prophylaxis",
    r"\bSTP\b",
    r"pre.?procedur",
    r"perioperative\s+prophylaxis",
    r"pre.?surgical",
    r"before\s+(surgery|procedure|dental\s+procedure|operation)",
    r"pre.?operative\s+(prophylaxis|management)",
]

_ACUTE_PATTERNS: list[str] = [
    r"\bicatibant\b",
    r"\bFirazyr\b",
    r"\becallantide\b",
    r"\bKalbitor\b",
    r"\bBerinert\b",
    r"\bRuconest\b",
    r"\bConestat\b",
    r"on.?demand\s+treatment",
    r"on.?demand\s+therapy",
    r"acute\s+(attack\s+treatment|treatment|therapy|management)",
    r"treatment\s+of\s+acute\s+(attack|episode)",
    r"rescue\s+(therapy|treatment|medication)",
    r"C1.?INH\s+(intravenous|IV|concentrate).{0,30}(acute|attack|on.?demand)",
]

_DIAGNOSIS_PATTERNS: list[str] = [
    r"\bbiomarker",
    r"\bdiagnos",
    r"genetic\s+(test|screen|analys)",
    r"\bC4\s+level",
    r"\bC1q\b",
    r"complement\s+(test|level|assay|screen)",
    r"delayed\s+diagnosis",
    r"diagnostic\s+(criteria|tool|method|delay|workup)",
    r"tryptase",
]

_EPIDEMIOLOGY_PATTERNS: list[str] = [
    r"\bprevalence\b",
    r"\bincidence\b",
    r"\bepidemiolog",
    r"disease\s+burden",
    r"\bregistry\b",
    r"healthcare\s+(utilization|utilisation|resource|cost)",
    r"economic\s+burden",
    r"cost.?of.?illness",
    r"attack\s+(rate|frequency|burden)",
    r"hospitaliz",
    r"emergency\s+(visit|department|room)",
]

_QOL_PATTERNS: list[str] = [
    r"quality\s+of\s+life",
    r"\bQoL\b",
    r"health.?related\s+quality",
    r"patient.?reported\s+outcome",
    r"\bPRO\b",
    r"\bHAE.?QoL\b",
    r"\bEQ.?5D\b",
    r"\bSF.?36\b",
    r"\bHAE.?specific.{0,20}questionnaire",
    r"psychological\s+(impact|burden|well.?being)",
    r"anxiety.{0,30}(HAE|angioedema)",
    r"depression.{0,30}(HAE|angioedema)",
    r"emotional\s+(impact|burden)",
]

_PATHOPHYSIOLOGY_PATTERNS: list[str] = [
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
    r"rat\s+model",
    r"cell\s+(line|culture|assay)",
]


def classify_treatment_area(title: str, abstract: str) -> str:
    """
    治療領域を分類する。

    優先順位: guideline_review > gene_therapy > long_term_prophylaxis >
              short_term_prophylaxis > acute_treatment > diagnosis_biomarker >
              quality_of_life > epidemiology_burden > pathophysiology > other
    """
    t = _text(title, abstract)

    if _match_any(_GUIDELINE_AREA_PATTERNS, t):
        return "guideline_review"
    if _match_any(_GENE_THERAPY_PATTERNS, t):
        return "gene_therapy"
    if _match_any(_LTP_PATTERNS, t):
        return "long_term_prophylaxis"
    if _match_any(_STP_PATTERNS, t):
        return "short_term_prophylaxis"
    if _match_any(_ACUTE_PATTERNS, t):
        return "acute_treatment"
    if _match_any(_DIAGNOSIS_PATTERNS, t):
        return "diagnosis_biomarker"
    if _match_any(_QOL_PATTERNS, t):
        return "quality_of_life"
    if _match_any(_EPIDEMIOLOGY_PATTERNS, t):
        return "epidemiology_burden"
    if _match_any(_PATHOPHYSIOLOGY_PATTERNS, t):
        return "pathophysiology"
    return "other"


# ---------------------------------------------------------------------------
# 3. publication_type 分類ルール
# ---------------------------------------------------------------------------

_META_ANALYSIS_PATTERNS: list[str] = [
    r"meta.?analys",
    r"systematic\s+review",
    r"network\s+meta.?analys",
    r"systematic\s+literature\s+review",
    r"\bSLR\b",
    r"\bNMA\b",
]

_GUIDELINE_PUB_PATTERNS: list[str] = [
    r"\bguideline",
    r"consensus\s+(statement|document|recommendation)",
    r"position\s+paper",
    r"management\s+recommendation",
    r"expert\s+(consensus|panel\s+recommendation)",
]

_RCT_PATTERNS: list[str] = [
    r"randomized\s+(controlled\s+)?trial",
    r"randomised\s+(controlled\s+)?trial",
    r"\bRCT\b",
    r"double.?blind.{0,40}placebo",
    r"placebo.{0,40}controlled.{0,40}(trial|study)",
    r"phase\s+(2|3|II|III)\s+(randomized|randomised)",
]

_OBSERVATIONAL_PATTERNS: list[str] = [
    r"cohort\s+study",
    r"prospective\s+(cohort|study|observational)",
    r"retrospective\s+(cohort|study|analysis|review)",
    r"case.?control\s+study",
    r"cross.?sectional\s+study",
    r"observational\s+study",
    r"real.?world\s+(evidence|study|data|analysis)",
    r"\bregistry\s+study\b",
    r"claims\s+(database|data|analysis)",
    r"population.?based\s+study",
]

_CASE_REPORT_PATTERNS: list[str] = [
    r"\bcase\s+report\b",
    r"\bcase\s+series\b",
    r"\bcase\s+presentation\b",
    r"we\s+report\s+a\s+case",
    r"report\s+of\s+a\s+(rare|novel|unusual)",
]

_REVIEW_PATTERNS: list[str] = [
    r"\breview\s+article\b",
    r"\bnarrative\s+review\b",
    r"\bscoping\s+review\b",
    r"\bstate.?of.?the.?art\b",
    r"\breview\s+of\s+the\s+literature\b",
    r"\bcurrent\s+(concepts|perspectives|status)\b",
    r"\bupdate\s+on\b",
    r"\boverview\s+of\b",
]

_EDITORIAL_PATTERNS: list[str] = [
    r"\beditorial\b",
    r"\bletter\s+to\s+the\s+editor",
    r"\bcorrespondence\b",
    r"\bcommentary\b",
    r"\bresponse\s+to\b",
    r"\bin\s+reply\b",
    r"\bpoint\s+of\s+view\b",
]

_BASIC_RESEARCH_PATTERNS: list[str] = [
    r"\bin\s+vitro\b",
    r"\bin\s+vivo\b",
    r"animal\s+model",
    r"mouse\s+model",
    r"rat\s+model",
    r"cell\s+(line|culture)",
    r"crystal\s+structure",
    r"molecular\s+(dynamics|simulation|mechanism)",
    r"protein\s+(structure|binding|expression)",
]


def classify_publication_type(title: str, abstract: str) -> str:
    """
    論文種別を分類する。

    優先順位: meta_analysis > guideline > RCT > observational >
              case_report > review > editorial_letter > basic_research > other
    """
    t = _text(title, abstract)

    if _match_any(_META_ANALYSIS_PATTERNS, t):
        return "meta_analysis"
    if _match_any(_GUIDELINE_PUB_PATTERNS, t):
        return "guideline"
    if _match_any(_RCT_PATTERNS, t):
        return "RCT"
    if _match_any(_OBSERVATIONAL_PATTERNS, t):
        return "observational"
    if _match_any(_CASE_REPORT_PATTERNS, t):
        return "case_report"
    if _match_any(_REVIEW_PATTERNS, t):
        return "review"
    if _match_any(_EDITORIAL_PATTERNS, t):
        return "editorial_letter"
    if _match_any(_BASIC_RESEARCH_PATTERNS, t):
        return "basic_research"
    return "other"


# ---------------------------------------------------------------------------
# 4. evidence_level 分類ルール (publication_type からマッピング)
# ---------------------------------------------------------------------------

# Oxford Centre for Evidence-Based Medicine 2011 に準拠
_PUBTYPE_TO_EVIDENCE: dict[str, str] = {
    "meta_analysis":    "1a",
    "RCT":              "1b",
    "observational":    "2b",
    "case_report":      "4",
    "review":           "5",
    "guideline":        "5",
    "editorial_letter": "5",
    "basic_research":   "5",
    "other":            "unclassified",
}


def classify_evidence_level(publication_type: str) -> str:
    """
    publication_type から Oxford EBM エビデンスレベルを返す。

    マッピングは _PUBTYPE_TO_EVIDENCE に定義。
    未知の publication_type は 'unclassified' を返す。
    """
    return _PUBTYPE_TO_EVIDENCE.get(publication_type, "unclassified")


# ---------------------------------------------------------------------------
# 5. MA relevance 分類ルール
# ---------------------------------------------------------------------------

_TREATMENT_RELEVANT_AREAS: set[str] = {
    "acute_treatment",
    "long_term_prophylaxis",
    "short_term_prophylaxis",
    "gene_therapy",
}

_HAE_SUBTYPES: set[str] = {"HAE_type1_2", "HAE_nC1INH", "HAE_general"}


def classify_ma_relevance(
    publication_type: str,
    evidence_level: str,
    treatment_area: str,
    disease_subtype: str,
) -> tuple[int, str]:
    """
    Medical Affairs 関連度スコア (0–3) と理由文字列を返す。

    スコア基準:
      3 — MA活動に直接使用できる (RCT/メタ解析/ガイドライン)
      2 — 間接的に有用 (疫学・QoL・リアルワールド)
      1 — 参考資料として保持 (基礎研究・症例報告・editorial)
      0 — MA関連性が低いまたは自動判定不能 (要レビュー)
    """
    is_hae = disease_subtype in _HAE_SUBTYPES
    is_treatment_relevant = treatment_area in _TREATMENT_RELEVANT_AREAS

    # HAE 以外の疾患が主題
    if not is_hae:
        if disease_subtype in {"bradykinin_AE", "other_AE"}:
            return 1, "HAE関連疾患の参考文献として保持"
        return 1, "HAE以外の疾患が主題のため参考資料に分類"

    # スコア 3: 直接使用可能
    if publication_type in {"meta_analysis", "guideline"}:
        return 3, "メタ解析またはガイドライン文献はMA活動に直接使用可能"
    if publication_type == "RCT" and is_treatment_relevant:
        return 3, "治療領域RCTのエビデンスはMA活動に直接使用可能"
    if publication_type == "RCT":
        return 3, "RCT文献はエビデンス訴求の中核としてMA活動に直接使用可能"

    # スコア 2: 間接的に有用
    if publication_type == "observational" and is_treatment_relevant:
        return 2, "治療関連リアルワールドエビデンスとして間接的に有用"
    if treatment_area in {"epidemiology_burden", "quality_of_life"}:
        return 2, "疫学・QoLデータはペイヤー対応・価値訴求で間接的に有用"
    if publication_type == "observational":
        return 2, "観察研究エビデンスとして間接的に有用"
    if treatment_area == "diagnosis_biomarker":
        return 2, "診断・バイオマーカー文献として間接的に有用"
    if publication_type == "review" and is_treatment_relevant:
        return 2, "治療領域レビューとして間接的に有用"

    # スコア 1: 参考資料
    if publication_type in {"case_report", "editorial_letter"}:
        return 1, "症例報告またはeditorialとして参考資料に保持"
    if publication_type == "basic_research" or treatment_area == "pathophysiology":
        return 1, "基礎・病態研究として参考資料に保持"
    if publication_type == "review":
        return 1, "総説文献として参考資料に保持"

    # スコア 0: 自動判定不能
    return 0, "自動分類でMA関連度を確定できず。手動レビュー要"


# ---------------------------------------------------------------------------
# 統合エントリーポイント
# ---------------------------------------------------------------------------

def classify_paper(record: dict) -> dict:
    """
    論文レコード dict に対して5軸分類を適用し、更新した dict を返す。

    入力 dict には 'title' および 'abstract' キーが必要。
    分類結果は元の dict にマージして返す（破壊的変更なし）。
    """
    title = str(record.get("title", ""))
    abstract = str(record.get("abstract", ""))

    disease_subtype = classify_disease_subtype(title, abstract)
    treatment_area = classify_treatment_area(title, abstract)
    publication_type = classify_publication_type(title, abstract)
    evidence_level = classify_evidence_level(publication_type)
    ma_score, ma_reason = classify_ma_relevance(
        publication_type, evidence_level, treatment_area, disease_subtype
    )

    # review_flag: 手動レビューが必要な条件に1つでも該当すれば True
    needs_review = (
        disease_subtype == "unclassified"
        or evidence_level == "unclassified"
        or ma_score == 0
    )

    # ma_reason を100字以内に収める
    ma_reason = ma_reason[:100]

    return {
        **record,
        "disease_subtype":    disease_subtype,
        "treatment_area":     treatment_area,
        "publication_type":   publication_type,
        "evidence_level":     evidence_level,
        "ma_relevance_score": ma_score,
        "ma_relevance_reason": ma_reason,
        "classifier_version": CLASSIFIER_VERSION,
        "review_flag":        needs_review,
    }
