"""
分類ルール定義モジュール。

classify.py から分離したすべてのキーワード・パターン・マッピングをここで一元管理する。
ルールを追加・修正するときはこのファイルのみを編集すればよい。

ファイル構成:
  1. Rule       — 単一ルールのデータクラス
  2. DRUG_REFERENCE      — 薬剤参照辞書 (ドキュメント・監査用)
  3. DISEASE_SUBTYPE_RULES
  4. TREATMENT_AREA_RULES
  5. PUBLICATION_TYPE_RULES
  6. エビデンスレベル関連定数
  7. MA relevance 関連定数

ルール変更時は classify.py の CLASSIFIER_VERSION をインクリメントし、
CLAUDE.md の「分類定義」セクションも更新すること。
"""
from __future__ import annotations

from dataclasses import dataclass


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
# 薬剤参照辞書
# ---------------------------------------------------------------------------
# ドキュメント・監査・将来の LLM 分類への移行を見据えた参照情報。
# 各エントリは治療領域・規制名・商品名・作用機序をまとめる。
# patterns フィールドの正規表現は TREATMENT_AREA_RULES に反映されている。

DRUG_REFERENCE: dict[str, dict] = {

    # ── 急性発作治療 (Acute treatment) ────────────────────────────────────
    "icatibant": {
        "category":    "acute_treatment",
        "brand":       ["Firazyr"],
        "other_names": ["HOE140"],
        "mechanism":   "bradykinin B2 受容体拮抗薬 (皮下注射)",
        "approval":    "EU 2008 / US 2011",
        "patterns": (
            r"\bicatibant\b",
            r"\bFirazyr\b",
        ),
    },
    "ecallantide": {
        "category":    "acute_treatment",
        "brand":       ["Kalbitor"],
        "other_names": ["DX-88"],
        "mechanism":   "血漿カリクレイン阻害薬 (皮下注射)",
        "approval":    "US 2009",
        "patterns": (
            r"\becallantide\b",
            r"\bKalbitor\b",
            r"\bDX.?88\b",
        ),
    },
    "c1inh_iv_berinert": {
        "category":    "acute_treatment",
        "brand":       ["Berinert"],
        "other_names": [],
        "mechanism":   "血漿由来 C1-INH 静注製剤",
        "approval":    "EU 1985 / US 2009",
        "patterns": (
            r"\bBerinert\b",
        ),
    },
    "c1inh_iv_ruconest": {
        "category":    "acute_treatment",
        "brand":       ["Ruconest", "Rhucin"],
        "other_names": ["conestat alfa"],
        "mechanism":   "組換えヒト C1-INH 静注製剤",
        "approval":    "EU 2010 / US 2014",
        "patterns": (
            r"\bRuconest\b",
            r"\bRhucin\b",
            r"\bConestat\b",
            r"\bconestat\s+alfa\b",
        ),
    },
    "c1inh_iv_cinryze": {
        "category":    "acute_treatment_and_ltp",  # 急性・LTP 両用
        "brand":       ["CINRYZE"],
        "other_names": [],
        "mechanism":   "血漿由来 C1-INH 静注製剤 (急性・LTP)",
        "approval":    "US 2008 (LTP) / EU 2011",
        "patterns": (
            r"\bCINRYZE\b",
            r"\bCinryze\b",
        ),
    },

    # ── 長期予防療法 (Long-term prophylaxis) ──────────────────────────────
    "lanadelumab": {
        "category":    "long_term_prophylaxis",
        "brand":       ["Takhzyro"],
        "other_names": ["SHP643", "DX-2930"],
        "mechanism":   "抗血漿カリクレイン モノクローナル抗体 (皮下注射、2〜4週毎)",
        "approval":    "US 2018 / EU 2018",
        "patterns": (
            r"\blanadelumab\b",
            r"\bTakhzyro\b",
            r"\bSHP.?643\b",
            r"\bDX.?2930\b",
        ),
    },
    "berotralstat": {
        "category":    "long_term_prophylaxis",
        "brand":       ["Orladeyo"],
        "other_names": ["BCX7353"],
        "mechanism":   "経口血漿カリクレイン阻害薬 (毎日内服)",
        "approval":    "US 2020 / EU 2021",
        "patterns": (
            r"\bberotralstat\b",
            r"\bOrladeyo\b",
            r"\bBCX.?7353\b",
        ),
    },
    "c1inh_sc_haegarda": {
        "category":    "long_term_prophylaxis",
        "brand":       ["Haegarda"],
        "other_names": ["CSL830"],
        "mechanism":   "血漿由来 C1-INH 皮下注射製剤 (2〜3.5 日毎)",
        "approval":    "US 2017 / EU 2018",
        "patterns": (
            r"\bHaegarda\b",
            r"\bCSL.?830\b",
        ),
    },
    "garadacimab": {
        "category":    "long_term_prophylaxis",
        "brand":       [],
        "other_names": ["CSL312", "anti-FXIIa"],
        "mechanism":   "抗活性型凝固第XII因子 モノクローナル抗体 (月1回皮下注射)",
        "approval":    "承認申請中 (2024年時点)",
        "patterns": (
            r"\bgaradacimab\b",
            r"\bCSL.?312\b",
            r"\banti.?FXIIa\b",
            r"\banti.?activated\s+factor\s*XII\b",
            r"\bfactor\s*XII\s+antibody\b",
        ),
    },
    "donidalorsen": {
        "category":    "long_term_prophylaxis",
        "brand":       [],
        "other_names": ["KVD824"],
        "mechanism":   "経口血漿カリクレイン阻害薬 (臨床開発中)",
        "approval":    "臨床開発中 (2024年時点)",
        "patterns": (
            r"\bdonidalorsen\b",
            r"\bKVD.?824\b",
        ),
    },
    "traditional_ltp": {
        "category":    "long_term_prophylaxis",
        "brand":       ["Danocrine"],
        "other_names": ["danazol", "stanozolol", "tranexamic acid"],
        "mechanism":   "減弱アンドロゲン / 抗線溶薬 (旧来の予防療法)",
        "approval":    "オフラベル使用",
        "patterns": (
            r"\bdanazol\b",
            r"\bDanocrine\b",
            r"\bstanozolol\b",
            r"attenuated\s+androgen",
            r"\btranexamic\s+acid\b.{0,40}(prophylaxis|HAE|angioedema)",
        ),
    },

    # ── 短期予防療法 (Short-term prophylaxis) ─────────────────────────────
    "stp_general": {
        "category":    "short_term_prophylaxis",
        "brand":       [],
        "other_names": [],
        "mechanism":   "処置前の短期予防 (C1-INH IV/SC、FFP)",
        "approval":    "各製剤に準じる",
        "patterns": (
            r"short.?term\s+prophylaxis",
            r"\bSTP\b",
            r"pre.?procedur",
            r"perioperative\s+prophylaxis",
            r"pre.?surgical",
            r"before\s+(surgery|procedure|dental\s+procedure|operation)",
            r"pre.?operative\s+(prophylaxis|management)",
            r"fresh\s+frozen\s+plasma",
            r"\bFFP\b",
        ),
    },

    # ── 遺伝子・核酸治療 (Gene / Nucleic acid therapy) ────────────────────
    "gene_therapy": {
        "category":    "gene_therapy",
        "brand":       [],
        "other_names": ["NTLA-2002", "BMN-331", "SerpinPC"],
        "mechanism":   "遺伝子編集・RNA 療法による根治的アプローチ",
        "approval":    "臨床開発中 (2024年時点)",
        "patterns": (
            r"\bNTLA.?2002\b",
            r"\bBMN.?331\b",
            r"\bSerpinPC\b",
            r"gene\s+(therapy|editing|silencing)",
            r"\bCRISPR\b",
            r"\bsiRNA\b",
            r"RNA\s+interference",
            r"antisense\s+oligonucleotide",
            r"\bASO\b",
        ),
    },
}

# ── C1-INH 共通キーワード (複数薬剤・文脈をカバー) ────────────────────────
# 単独の C1-INH 記載は急性・LTP・STP を横断するため、
# TREATMENT_AREA_RULES では投与経路を組み合わせて文脈を判断する。
_C1INH_TERMS: tuple[str, ...] = (
    r"C1.?INH",
    r"C1\s+inhibitor",
    r"C1.?esterase\s+inhibitor",
    r"C1\s+esterase\s+inhibitor",
    r"plasma.?derived\s+C1\s+inhibitor",
    r"recombinant\s+C1\s+inhibitor",
    r"C1.?inhibitor\s+concentrate",
)


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
        description=(
            "正常C1-INH型HAE (HAE-nC1INH): "
            "FXII/PLG/ANGPT1/KNG1/MYOF/HS3ST6 変異、エストロゲン依存性を含む"
        ),
    ),
    Rule(
        label="HAE type 1/2",
        patterns=(
            r"HAE.{0,5}type\s*(1|I|2|II)\b",
            r"HAE.{0,5}(1|2)\b",
            r"type\s*(1|I|2|II).{0,5}HAE",
            # C1-INH 欠乏の明示表現
            r"C1.?INH\s+deficien",
            r"C1.?inhibitor\s+deficien",
            r"C1\s+inhibitor\s+deficien",
            r"C1.?esterase\s+inhibitor\s+deficien",
            # 定量的・機能的 C1-INH 低下の表現 (type 1 = 量的, type 2 = 機能的)
            r"(low|reduced|absent|undetectable|decreased)\s+C1.?INH",
            r"quantitative\s+(C1.?INH|C1.?inhibitor)\s+deficien",
            r"functional\s+(C1.?INH|C1.?inhibitor)\s+deficien",
            r"\bSERPING1\b",
            r"C1.?INH.?HAE",
            r"HAE.?C1.?INH",   # "HAE-C1INH" 等の略称
        ),
        description=(
            "HAE type 1/2: C1-INH 量的・機能的欠乏 (SERPING1 変異)。"
            "low/reduced/absent C1-INH、quantitative/functional deficiency を含む"
        ),
    ),
    Rule(
        label="unspecified HAE",
        patterns=(
            r"\bhereditary\s+angioedema\b",
            r"\bHAE\b",
            r"bradykinin.{0,20}angioedema",
            r"angioedema.{0,20}bradykinin",
            r"ACE.?inhibitor.{0,30}(induced|angioedema)",
            r"ACEi.{0,20}angioedema",
            r"drug.?induced\s+angioedema",
        ),
        description=(
            "サブタイプ不明または横断的なHAE総論、bradykinin 性浮腫 (HAE関連)"
        ),
    ),
]


# ---------------------------------------------------------------------------
# 2. treatment_area 分類ルール
# ---------------------------------------------------------------------------
# 評価順: guidelines → short_term_prophylaxis → acute_treatment →
#         long_term_prophylaxis → diagnosis → epidemiology → burden/QoL
#         → basic science
#
# ※ short_term_prophylaxis を acute_treatment より先に評価する理由:
#   STP 論文のアブストに Berinert 等の急性期薬剤名が登場しても
#   STP として正しく分類するため。STP パターンはすべて
#   HAE/angioedema/prophylaxis コンテキストを必須とするため
#   acute treatment 論文が誤って STP に落ちるリスクは低い。

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
            r"treatment\s+algorithm",
        ),
        description="ガイドライン・エキスパートコンセンサス・治療アルゴリズム",
    ),
    Rule(
        label="short-term prophylaxis",
        patterns=(
            # 短期予防の直接表現 (最も強いシグナル — acute treatment より先に評価)
            r"short.?term\s+prophylaxis",
            # 処置前・手術前予防 (prophylaxis / management コンテキスト必須)
            r"pre.?procedur\w*\s+(prophylaxis|management|treatment|HAE|angioedema)",
            r"perioperative\s+(prophylaxis|management|HAE|angioedema)",
            r"pre.?surgical\s+(prophylaxis|management|treatment|HAE)",
            r"pre.?operative\s+(prophylaxis|management).{0,30}(HAE|angioedema|C1.?INH)",
            # 処置前投与で使われる製剤 (HAE/angioedema コンテキスト限定)
            r"fresh\s+frozen\s+plasma.{0,40}(HAE|angioedema|prophylaxis)",
            r"\bFFP\b.{0,20}(HAE|angioedema|prophylaxis)",
        ),
        description=(
            "短期予防療法 (STP): 処置前・周術期投与。"
            "C1-INH IV/SC、FFP を用いた手術・処置前の予防管理"
        ),
    ),
    Rule(
        label="acute treatment",
        patterns=(
            # 薬剤キーワード (DRUG_REFERENCE から抽出)
            r"\bicatibant\b",
            r"\bFirazyr\b",
            r"\becallantide\b",
            r"\bKalbitor\b",
            r"\bDX.?88\b",
            r"\bBerinert\b",
            r"\bRuconest\b",
            r"\bRhucin\b",
            r"\bConestat\b",
            r"\bconestat\s+alfa\b",
            r"\bCINRYZE\b",
            r"\bCinryze\b",
            # C1-INH 静注 (急性文脈)
            r"C1.?INH.{0,20}(intravenous|IV|i\.v\.|concentrate).{0,30}(acute|attack|on.?demand)",
            # 治療文脈キーワード
            r"on.?demand\s+(treatment|therapy)",
            r"acute\s+(attack\s+treatment|treatment|therapy|management)",
            r"treatment\s+of\s+acute\s+(attack|episode)",
            r"rescue\s+(therapy|treatment|medication)",
        ),
        description=(
            "急性発作治療: icatibant (Firazyr), ecallantide (Kalbitor), "
            "C1-INH 静注 (Berinert, Ruconest, Cinryze)"
        ),
    ),
    Rule(
        label="long-term prophylaxis",
        patterns=(
            # 薬剤キーワード (DRUG_REFERENCE から抽出)
            r"\blanadelumab\b",
            r"\bTakhzyro\b",
            r"\bSHP.?643\b",
            r"\bDX.?2930\b",
            r"\bberotralstat\b",
            r"\bOrladeyo\b",
            r"\bBCX.?7353\b",
            r"\bHaegarda\b",
            r"\bCSL.?830\b",
            r"\bgaradacimab\b",
            r"\bCSL.?312\b",
            r"\banti.?FXIIa\b",
            r"\banti.?activated\s+factor\s*XII\b",
            r"\bdonidalorsen\b",
            r"\bKVD.?824\b",
            r"\bdanazol\b",
            r"\bDanocrine\b",
            r"\bstanozolol\b",
            r"attenuated\s+androgen",
            r"\btranexamic\s+acid\b.{0,40}(prophylaxis|HAE|angioedema)",
            # C1-INH 皮下注
            r"C1.?INH\s+subcutaneous",
            r"subcutaneous\s+C1.?INH",
            # 治療文脈キーワード
            r"long.?term\s+prophylaxis",
            r"\bLTP\b",
            r"prophylactic\s+(treatment|therapy)",
            # 遺伝子・核酸治療
            r"\bNTLA.?2002\b",
            r"\bBMN.?331\b",
            r"\bSerpinPC\b",
            r"gene\s+(therapy|editing|silencing)",
            r"\bCRISPR\b",
            r"\bsiRNA\b",
            r"RNA\s+interference",
            r"antisense\s+oligonucleotide",
            r"\bASO\b",
        ),
        description=(
            "長期予防療法 (LTP): lanadelumab (Takhzyro), berotralstat (Orladeyo), "
            "C1-INH SC (Haegarda), garadacimab (CSL312, 抗FXIIa), "
            "donidalorsen (KVD824), 減弱アンドロゲン, 遺伝子治療"
        ),
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
            r"diagnostic\s+(criteria|tool|method|delay|workup)",
            r"tryptase",
            r"functional\s+C1.?INH",
            r"antigenic\s+C1.?INH",
        ),
        description="診断・バイオマーカー・遺伝子検査・補体測定",
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
            r"natural\s+history",
        ),
        description="疫学・発症頻度・医療資源利用・自然歴",
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
            r"healthcare\s+(utilization|utilisation|cost|resource)",
            r"psychological\s+(impact|burden|well.?being)",
            r"anxiety.{0,30}(HAE|angioedema)",
            r"depression.{0,30}(HAE|angioedema)",
            r"work\s+(productivity|impairment)",
            r"\bWPAI\b",
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
            r"preclinical",
        ),
        description="基礎研究・病態生理・分子メカニズム・前臨床試験",
    ),
]


# ---------------------------------------------------------------------------
# 3. publication_type 分類ルール
# ---------------------------------------------------------------------------
# 評価順: guideline/consensus → OLE/extension → RCT → RWE/observational
#         → review → letter/commentary → case report
#
# ※ OLE/extension を RCT より先に評価する理由:
#   OLE 論文のアブストには親 RCT の言及 ("randomized controlled trial") が
#   頻繁に登場し、RCT に誤分類されやすい。OLE パターンはすべて
#   extension/open-label 特有の表現を必須とするため RCT の誤捕捉はない。

PUBLICATION_TYPE_RULES: list[Rule] = [
    Rule(
        label="guideline/consensus",
        patterns=(
            r"\bguideline",
            r"consensus\s+(statement|document|recommendation)",
            r"\bclinical\s+practice\s+guideline",
            r"\bpractice\s+guideline",
            r"position\s+paper",
            r"position\s+statement",
            r"management\s+recommendation",
            r"\btreatment\s+recommendation",
            r"expert\s+(consensus|panel\s+recommendation)",
        ),
        description="診療ガイドライン・コンセンサス文書・エキスパート推奨",
    ),
    Rule(
        label="OLE/extension",
        patterns=(
            r"open.?label\s+extension",
            r"\bOLE\b",
            # "long-term safety" は RWE と混同しやすいため、extension / open-label との
            # 共起を必須にして観察研究への誤分類を防ぐ
            r"long.?term\s+(safety|tolerability).{0,50}(extension|open.?label|OLE)",
            # "extension study/period/phase/trial" は open-label または OLE の文脈が必須。
            # 文脈なしの "extension study" はRCTの延長投与デザインを指す場合もあり
            # 誤分類を防ぐため前後50字以内に open.?label または OLE\b が必要。
            r"extension\s+(study|period|phase|trial).{0,50}(open.?label|OLE\b)",
            r"(open.?label).{0,50}extension\s+(study|period|phase|trial)",
            r"continued\s+(treatment|therapy).{0,30}(open.?label|extension)",
        ),
        description="オープンラベル延長試験 (OLE)・長期フォローアップ試験",
    ),
    Rule(
        label="RCT",
        patterns=(
            r"randomized\s+(controlled\s+)?trial\b",   # \b で "trials" (複数形) を除外
            r"randomised\s+(controlled\s+)?trial\b",
            r"\bRCT\b",
            r"double.?blind.{0,40}placebo",
            r"placebo.{0,40}controlled.{0,40}(trial|study)",
            r"phase\s+(2|3|II|III)\s+(randomized|randomised|controlled)",
        ),
        description="ランダム化比較試験",
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
        description="リアルワールドエビデンス・観察研究・レジストリ",
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
            r"\bintegrative\s+review\b",
            r"\bliterature\s+review\b",
            r"\bstate.?of.?the.?art\b",
            r"\breview\s+of\s+the\s+literature\b",
            r"\bcurrent\s+(concepts|perspectives|status|evidence)\b",
            # 治療領域のアップデート系総説
            r"\bupdates?\s+(on|in)\s+(hereditary\s+angioedema|HAE|angioedema\s+treatment)",
        ),
        description="レビュー (メタ解析・SR・SLR・NMA・ナラティブレビュー・総説アップデート)",
    ),
    Rule(
        label="letter/commentary",
        patterns=(
            r"\beditorial\b",
            r"\bletter\s+to\s+the\s+editor",
            r"\bcorrespondence\b",
            r"\bcommentary\b",
            r"\bresponse\s+to\s+(the\s+)?(letter|editorial|comment|editor|authors)\b",
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


# ---------------------------------------------------------------------------
# エビデンスレベル関連定数
# ---------------------------------------------------------------------------

# メタ解析・SR の検出パターン (review ラベルを "high" に昇格させるために使用)
META_ANALYSIS_PATTERNS: tuple[str, ...] = (
    r"meta.?analys",
    r"systematic\s+review",
    r"network\s+meta.?analys",
    r"\bSLR\b",
    r"\bNMA\b",
)

# publication_type → evidence_level の基本マッピング
# "review" かつメタ解析検出時は classify.py 内で "high" に昇格する
PUBTYPE_TO_EVIDENCE: dict[str, str] = {
    "RCT":                "high",
    "guideline/consensus": "high",
    "OLE/extension":      "medium",
    "RWE/observational":  "medium",
    "review":             "medium",   # メタ解析の場合は classify.py 内で昇格
    "letter/commentary":  "low",
    "case report":        "low",
    "unknown":            "unknown",
}


# ---------------------------------------------------------------------------
# MA relevance 補助ルール定数
# ---------------------------------------------------------------------------

# ma_relevance ラベル → ma_relevance_score (CSV スキーマ互換の整数) 変換マップ
MA_RELEVANCE_TO_SCORE: dict[str, int] = {
    "high":   3,
    "medium": 2,
    "low":    1,
}

# HAE 疾患サブタイプセット (MA relevance 計算時に使用)
HAE_SUBTYPES: frozenset[str] = frozenset({
    "HAE type 1/2",
    "HAE-nC1INH",
    "unspecified HAE",
})

# MA 活動で特に関連度が高い治療領域セット
TREATMENT_FOCUSED_AREAS: frozenset[str] = frozenset({
    "acute treatment",
    "short-term prophylaxis",   # STP も臨床管理上の重要領域
    "long-term prophylaxis",
    "guidelines",
})

# "high" MA relevance を付与する publication_type セット (HAE 対象が前提)
HIGH_MA_PUBTYPES: frozenset[str] = frozenset({
    "RCT",
    "guideline/consensus",
})

# "medium" MA relevance を付与する publication_type セット (HAE 対象が前提)
MEDIUM_MA_PUBTYPES: frozenset[str] = frozenset({
    "OLE/extension",
    "RWE/observational",
})

# "low" MA relevance を付与する publication_type セット
LOW_MA_PUBTYPES: frozenset[str] = frozenset({
    "letter/commentary",
    "case report",
})

# "medium" MA relevance を付与する治療領域セット (HAE 対象かつ上記 pub_type 以外)
MEDIUM_MA_AREAS: frozenset[str] = frozenset({
    "epidemiology",
    "burden/QoL",
    "diagnosis",
    "short-term prophylaxis",   # 処置前管理の実態・エビデンスは間接的に有用
})
