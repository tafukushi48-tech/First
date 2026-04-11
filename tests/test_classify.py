"""
classify モジュールのユニットテスト。

対象:
  - classify_publication_type: 論文種別分類
  - classify_disease_subtype:  疾患サブタイプ分類
"""
import pytest
from classify import classify_publication_type, classify_disease_subtype


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
