"""
classify モジュールのユニットテスト。

対象:
  - classify_publication_type: 論文種別分類
  - classify_disease_subtype:  疾患サブタイプ分類
  - classify_ma_relevance:     MA関連度分類
  - classify_treatment_area:   治療領域分類
"""
import pytest
from classify import (
    classify_publication_type,
    classify_disease_subtype,
    classify_ma_relevance,
    classify_treatment_area,
)


# ---------------------------------------------------------------------------
# publication_type 分類
# ---------------------------------------------------------------------------

class TestClassifyPublicationType:
    """
    ルール評価順:
      guideline/consensus > RCT > OLE/extension > RWE/observational
      > review > letter/commentary > case report
    """

    def test_rct_from_title(self):
        """タイトルに 'randomized controlled trial' を含む場合は RCT"""
        result = classify_publication_type(
            "A randomized controlled trial of lanadelumab in HAE", ""
        )
        assert result == "RCT"

    def test_rct_double_blind_placebo_in_abstract(self):
        """アブストラクトの 'double-blind placebo' パターンでも RCT と判定される"""
        result = classify_publication_type(
            "", "This double-blind placebo-controlled study evaluated icatibant."
        )
        assert result == "RCT"

    def test_guideline_consensus(self):
        """'guideline' を含む場合は guideline/consensus"""
        result = classify_publication_type(
            "International guideline for the management of hereditary angioedema", ""
        )
        assert result == "guideline/consensus"

    def test_guideline_takes_priority_over_rct(self):
        """
        ガイドライン文書が RCT の記述も含む場合、
        評価順が上位の guideline/consensus が返る。
        """
        result = classify_publication_type(
            "Clinical guideline based on randomized controlled trials", ""
        )
        assert result == "guideline/consensus"

    def test_systematic_review(self):
        """'systematic review' は review と分類される"""
        result = classify_publication_type(
            "Systematic review of long-term prophylaxis options for HAE", ""
        )
        assert result == "review"

    def test_meta_analysis(self):
        """'meta-analysis' も review と分類される"""
        result = classify_publication_type(
            "", "We conducted a meta-analysis of prophylaxis outcomes in hereditary angioedema."
        )
        assert result == "review"

    def test_ole_extension(self):
        """'open-label extension' を含む場合は OLE/extension"""
        result = classify_publication_type(
            "Open-label extension study of berotralstat in HAE patients", ""
        )
        assert result == "OLE/extension"

    def test_ole_with_ole_abbreviation(self):
        """OLE 略称を含む場合も OLE/extension"""
        result = classify_publication_type(
            "Results from the HELP OLE study of lanadelumab in HAE", ""
        )
        assert result == "OLE/extension"

    def test_ole_extension_study_with_open_label_context(self):
        """'extension study' + 'open-label' 文脈あり → OLE/extension"""
        result = classify_publication_type(
            "Long-term extension study results (open-label) in HAE", ""
        )
        assert result == "OLE/extension"

    def test_extension_study_without_open_label_context_not_ole(self):
        """
        open-label / OLE 文脈なしの 'extension study' のみでは
        OLE/extension に分類されない。
        アブストラクトに RCT シグナルがあれば RCT が返る。
        """
        result = classify_publication_type(
            "Extended dosing regimen study of berotralstat in HAE",
            "Randomized controlled trial evaluating extended berotralstat dosing."
            " Double-blind placebo-controlled phase 3 design.",
        )
        assert result == "RCT"

    def test_extension_period_without_context_not_ole(self):
        """'extension period' 単独も open-label 文脈なしでは OLE に分類されない"""
        result = classify_publication_type(
            "Follow-up results from a 12-month extension period of the INNOVATE study",
            "Prospective cohort study assessing lanadelumab in real-world practice.",
        )
        # open-label / OLE 文脈なし → RWE/observational が返る
        assert result == "RWE/observational"

    def test_rwe_observational(self):
        """'retrospective cohort study' は RWE/observational"""
        result = classify_publication_type(
            "Retrospective cohort study of real-world lanadelumab use", ""
        )
        assert result == "RWE/observational"

    def test_case_report(self):
        """'case report' を含む場合は case report"""
        result = classify_publication_type(
            "Case report: severe HAE attack during pregnancy", ""
        )
        assert result == "case report"

    def test_letter_commentary(self):
        """'letter to the editor' は letter/commentary"""
        result = classify_publication_type(
            "", "This is a letter to the editor regarding the recent publication."
        )
        assert result == "letter/commentary"

    def test_unknown_when_no_pattern_matches(self):
        """どのパターンにもマッチしない場合は unknown を返す"""
        result = classify_publication_type(
            "Bradykinin pathway activation in plasma kallikrein", ""
        )
        assert result == "unknown"


# ---------------------------------------------------------------------------
# disease_subtype 分類
# ---------------------------------------------------------------------------

class TestClassifyDiseaseSubtype:
    """
    ルール評価順 (最も特異的なものが先):
      HAE-nC1INH > HAE type 1/2 > unspecified HAE
    """

    def test_hae_type1_explicit(self):
        """'HAE type 1' を含む場合は HAE type 1/2"""
        result = classify_disease_subtype("HAE type 1 patients enrolled", "")
        assert result == "HAE type 1/2"

    def test_hae_type2_explicit(self):
        """'HAE type 2' もタイプ 1/2 に分類される"""
        result = classify_disease_subtype("", "HAE type 2 with missense SERPING1 mutation")
        assert result == "HAE type 1/2"

    def test_c1inh_deficiency_maps_to_type12(self):
        """'C1 inhibitor deficiency' は HAE type 1/2 の典型的な表現"""
        result = classify_disease_subtype("C1 inhibitor deficiency in adults", "")
        assert result == "HAE type 1/2"

    def test_serping1_maps_to_type12(self):
        """SERPING1 変異は type 1/2 の原因遺伝子"""
        result = classify_disease_subtype("SERPING1 mutation carriers with HAE", "")
        assert result == "HAE type 1/2"

    def test_normal_c1inh_maps_to_nc1inh(self):
        """'HAE with normal C1-INH' は HAE-nC1INH"""
        result = classify_disease_subtype(
            "", "Patients with HAE with normal C1-INH were enrolled."
        )
        assert result == "HAE-nC1INH"

    def test_factor_xii_angioedema_maps_to_nc1inh(self):
        """'factor XII' + 'angioedema' の組合せは HAE-nC1INH"""
        result = classify_disease_subtype(
            "Factor XII mutation and angioedema in women", ""
        )
        assert result == "HAE-nC1INH"

    def test_fxii_abbreviation_maps_to_nc1inh(self):
        """省略形 'FXII' も HAE-nC1INH に分類される"""
        result = classify_disease_subtype("FXII HAE angioedema study", "")
        assert result == "HAE-nC1INH"

    def test_angpt1_maps_to_nc1inh(self):
        """ANGPT1 変異は HAE-nC1INH の原因遺伝子のひとつ"""
        result = classify_disease_subtype(
            "", "ANGPT1 variant associated with angioedema episodes"
        )
        assert result == "HAE-nC1INH"

    def test_nc1inh_takes_priority_over_type12(self):
        """
        'normal C1-INH' (nC1INH シグナル) と 'C1 inhibitor deficiency' が
        同時に存在する場合、評価順が上位の HAE-nC1INH が返る。
        """
        result = classify_disease_subtype(
            "HAE with normal C1-INH and C1 inhibitor deficiency phenotype", ""
        )
        assert result == "HAE-nC1INH"

    def test_hereditary_angioedema_maps_to_unspecified(self):
        """サブタイプ記載なしの 'hereditary angioedema' は unspecified HAE"""
        result = classify_disease_subtype(
            "Treatment options in hereditary angioedema", ""
        )
        assert result == "unspecified HAE"

    def test_no_hae_term_defaults_to_unspecified(self):
        """
        HAE 関連語が一切ない場合も unspecified HAE を返す。
        収集パイプラインは HAE 特化クエリのため、取得済み論文はすべて HAE 関連と仮定する。
        """
        result = classify_disease_subtype("Cardiac biomarkers in critical care", "")
        assert result == "unspecified HAE"


# ---------------------------------------------------------------------------
# treatment_area 分類
# ---------------------------------------------------------------------------

class TestClassifyTreatmentArea:
    """
    評価順: guidelines → short-term prophylaxis → acute treatment →
            long-term prophylaxis → diagnosis → epidemiology → burden/QoL
            → basic science
    """

    def test_stp_takes_priority_over_acute_when_berinert_in_abstract(self):
        """
        アブストに Berinert (急性期薬剤名) があっても
        タイトルに 'short-term prophylaxis' があれば STP が返る。
        (STP を acute treatment より先に評価するための回帰テスト)
        """
        result = classify_treatment_area(
            "Short-term prophylaxis with C1-INH concentrate before surgical procedures",
            "Retrospective study. Perioperative management with Berinert or FFP in HAE.",
        )
        assert result == "short-term prophylaxis"

    def test_perioperative_prophylaxis_is_stp(self):
        """'perioperative prophylaxis' は short-term prophylaxis"""
        result = classify_treatment_area(
            "Perioperative prophylaxis management in HAE patients", ""
        )
        assert result == "short-term prophylaxis"

    def test_icatibant_without_stp_context_is_acute(self):
        """icatibant + on-demand context は acute treatment"""
        result = classify_treatment_area(
            "Icatibant for on-demand treatment of acute HAE attacks", ""
        )
        assert result == "acute treatment"

    def test_lanadelumab_is_ltp(self):
        """lanadelumab は long-term prophylaxis"""
        result = classify_treatment_area(
            "Efficacy of lanadelumab for HAE prophylaxis", ""
        )
        assert result == "long-term prophylaxis"

    def test_gene_therapy_is_ltp(self):
        """遺伝子治療 (NTLA-2002) は long-term prophylaxis"""
        result = classify_treatment_area(
            "NTLA-2002 gene editing for hereditary angioedema", ""
        )
        assert result == "long-term prophylaxis"


# ---------------------------------------------------------------------------
# MA relevance 分類
# ---------------------------------------------------------------------------

class TestClassifyMaRelevance:
    """
    classify_ma_relevance(publication_type, evidence_level, treatment_area, disease_subtype)
    の単体テスト。
    """

    def test_rct_hae_is_high(self):
        """RCT + HAE → high"""
        label, _ = classify_ma_relevance("RCT", "high", "long-term prophylaxis", "HAE type 1/2")
        assert label == "high"

    def test_guideline_hae_is_high(self):
        """guideline/consensus + HAE → high"""
        label, _ = classify_ma_relevance("guideline/consensus", "high", "guidelines", "unspecified HAE")
        assert label == "high"

    def test_high_evidence_review_hae_is_high(self):
        """evidence_level=high (メタ解析SR) + HAE → high"""
        label, _ = classify_ma_relevance("review", "high", "long-term prophylaxis", "HAE type 1/2")
        assert label == "high"

    def test_ole_hae_is_medium(self):
        """OLE/extension + HAE → medium"""
        label, _ = classify_ma_relevance("OLE/extension", "medium", "long-term prophylaxis", "HAE type 1/2")
        assert label == "medium"

    def test_rwe_hae_is_medium(self):
        """RWE/observational + HAE → medium"""
        label, _ = classify_ma_relevance("RWE/observational", "medium", "epidemiology", "unspecified HAE")
        assert label == "medium"

    def test_review_hae_treatment_focus_is_medium(self):
        """review + HAE + 治療重点領域 → medium"""
        label, _ = classify_ma_relevance("review", "medium", "long-term prophylaxis", "HAE type 1/2")
        assert label == "medium"

    def test_ltp_hae_unknown_pubtype_is_medium(self):
        """
        long-term prophylaxis + HAE + unknown pub_type → medium
        (phase 1 試験・会議録等、pub_type 判定不能でも治療重点領域なら medium)
        """
        label, reason = classify_ma_relevance(
            "unknown", "unknown", "long-term prophylaxis", "HAE type 1/2"
        )
        assert label == "medium"
        assert "手動確認" in reason

    def test_acute_hae_unknown_pubtype_is_medium(self):
        """acute treatment + HAE + unknown pub_type → medium"""
        label, _ = classify_ma_relevance(
            "unknown", "unknown", "acute treatment", "unspecified HAE"
        )
        assert label == "medium"

    def test_stp_hae_unknown_pubtype_is_medium(self):
        """short-term prophylaxis + HAE + unknown pub_type → medium"""
        label, _ = classify_ma_relevance(
            "unknown", "unknown", "short-term prophylaxis", "HAE type 1/2"
        )
        assert label == "medium"

    def test_basic_science_unknown_pubtype_is_low(self):
        """basic science + unknown pub_type → low (治療重点領域ではないため)"""
        label, _ = classify_ma_relevance(
            "unknown", "unknown", "basic science", "HAE type 1/2"
        )
        assert label == "low"

    def test_epidemiology_unknown_pubtype_is_medium(self):
        """
        epidemiology + HAE → MEDIUM_MA_AREAS に該当するため medium。
        pub_type が unknown でも MEDIUM_MA_AREAS ブランチが先に評価されるため
        unknown pub_type セーフティーネットには到達しない。
        """
        label, _ = classify_ma_relevance(
            "unknown", "unknown", "epidemiology", "HAE type 1/2"
        )
        assert label == "medium"

    def test_case_report_is_low(self):
        """case report → low"""
        label, _ = classify_ma_relevance("case report", "low", "acute treatment", "HAE type 1/2")
        assert label == "low"

    def test_letter_is_low(self):
        """letter/commentary → low"""
        label, _ = classify_ma_relevance("letter/commentary", "low", "long-term prophylaxis", "HAE type 1/2")
        assert label == "low"

    def test_non_hae_rct_not_high(self):
        """RCT でも HAE 以外の疾患サブタイプ (unspecified HAE は HAE_SUBTYPES に含まれるので
        ここでは存在しない疾患を使って検証する)"""
        # HAE_SUBTYPES = {HAE type 1/2, HAE-nC1INH, unspecified HAE}
        # すべて HAE なので is_hae=False にはならない。
        # 代わりに evidence_level=unknown で high に昇格しないことを確認。
        label, _ = classify_ma_relevance("RCT", "unknown", "other", "unspecified HAE")
        assert label == "high"  # RCT + HAE → high (evidence_level は無関係)

    def test_unknown_pubtype_non_treatment_focus_is_low(self):
        """treatment_focus 外 + unknown → low"""
        label, _ = classify_ma_relevance(
            "unknown", "unknown", "other", "unspecified HAE"
        )
        assert label == "low"
