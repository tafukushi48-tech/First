"""
dedupe モジュールのユニットテスト。

対象:
  - normalize_doi:      DOI 正規化
  - normalize_title:    タイトル正規化
  - load_existing_keys: 既存 CSV からのキー読み込み
  - deduplicate:        DOI重複・PMID重複・タイトル重複・優先順位・既存CSV照合
"""
import pytest
import pandas as pd
from dedupe import normalize_doi, normalize_title, load_existing_keys, deduplicate


# ---------------------------------------------------------------------------
# DOI 正規化
# ---------------------------------------------------------------------------

class TestNormalizeDoi:
    def test_strips_whitespace_and_lowercases(self):
        assert normalize_doi("  10.1234/TEST  ") == "10.1234/test"

    def test_strips_https_prefix(self):
        assert normalize_doi("https://doi.org/10.1234/test") == "10.1234/test"

    def test_strips_http_prefix(self):
        assert normalize_doi("http://doi.org/10.1234/test") == "10.1234/test"

    def test_strips_doi_colon_prefix(self):
        assert normalize_doi("DOI:10.1234/test") == "10.1234/test"

    def test_strips_doi_slash_prefix(self):
        """doi/ プレフィックスが除去される"""
        assert normalize_doi("doi/10.1234/test") == "10.1234/test"

    def test_plain_doi_unchanged(self):
        assert normalize_doi("10.1234/test") == "10.1234/test"

    def test_empty_string(self):
        """空文字はそのまま空文字を返す"""
        assert normalize_doi("") == ""

    def test_whitespace_only(self):
        """空白のみの文字列は空文字になる"""
        assert normalize_doi("   ") == ""

    def test_mixed_case_lowercased(self):
        """大文字を含む DOI は小文字に変換される"""
        assert normalize_doi("10.1234/ABC.DEF") == "10.1234/abc.def"


# ---------------------------------------------------------------------------
# タイトル正規化
# ---------------------------------------------------------------------------

class TestNormalizeTitle:
    def test_lowercase(self):
        """大文字は小文字に変換される"""
        assert normalize_title("Randomized Trial in HAE") == "randomized trial in hae"

    def test_punctuation_removed(self):
        """コロン・ピリオド・ハイフン等の記号は空白に置換される"""
        assert normalize_title("Long-term prophylaxis: a review.") == "long term prophylaxis a review"

    def test_underscore_replaced(self):
        """アンダースコアは空白に置換される"""
        assert normalize_title("some_gene_study") == "some gene study"

    def test_whitespace_compressed(self):
        """連続する空白は1つに圧縮され、前後の空白は除去される"""
        assert normalize_title("  multiple   spaces  ") == "multiple spaces"

    def test_empty_string(self):
        """空文字は空文字のまま返る"""
        assert normalize_title("") == ""

    def test_parentheses_removed(self):
        """括弧は空白に置換される"""
        assert normalize_title("HAE (type 1/2) treatment") == "hae  type 1 2  treatment".replace("  ", " ").strip()

    def test_slash_replaced(self):
        """スラッシュは空白に置換される"""
        norm = normalize_title("type 1/2 HAE")
        assert "1" in norm and "2" in norm and "/" not in norm

    def test_numbers_preserved(self):
        """数字は除去されない"""
        assert "2023" in normalize_title("HAE guidelines 2023")

    def test_equivalent_titles_match(self):
        """
        表記揺れのある2タイトルが正規化後に一致することを確認する。
        重複除去の中核ユースケース。
        """
        t1 = "Hereditary Angioedema: A Randomized, Double-Blind Trial"
        t2 = "hereditary angioedema a randomized double blind trial"
        assert normalize_title(t1) == normalize_title(t2)

    def test_trailing_period_removed(self):
        """末尾ピリオドは空白変換後に圧縮される"""
        assert normalize_title("A study.") == "a study"

    def test_unicode_letters_preserved(self):
        """Unicode 文字 (アクセント付き文字等) は除去されない"""
        result = normalize_title("Étude sur l'angioédème")
        assert "tude" in result  # É → é → preserved by \w


# ---------------------------------------------------------------------------
# DOI 重複判定 (既存セット・バッチ内)
# ---------------------------------------------------------------------------

class TestDeduplicateDoi:
    """DOI を用いた重複除去テスト。"""

    def _make_record(self, doi="", pmid="", title="A paper"):
        return {"doi": doi, "pmid": pmid, "title": title}

    def test_doi_matches_existing_excluded(self):
        """既存 CSV に同一 DOI があるレコードは除外される"""
        records = [self._make_record(doi="10.1234/test")]
        unique, stats = deduplicate(records, {"10.1234/test"}, set(), set())
        assert unique == []
        assert stats["dup_doi"] == 1
        assert stats["excluded"] == 1
        assert stats["kept"] == 0

    def test_doi_case_insensitive(self):
        """DOI の大文字小文字の違いは無視される"""
        records = [self._make_record(doi="10.1234/TEST")]
        unique, stats = deduplicate(records, {"10.1234/test"}, set(), set())
        assert stats["dup_doi"] == 1

    def test_doi_url_prefix_stripped_then_matched(self):
        """URL プレフィックス付き DOI は正規化後に既存と照合される"""
        records = [self._make_record(doi="https://doi.org/10.1234/test")]
        unique, stats = deduplicate(records, {"10.1234/test"}, set(), set())
        assert stats["dup_doi"] == 1

    def test_doi_http_prefix_stripped_then_matched(self):
        """http:// プレフィックス付き DOI も正規化後に照合される"""
        records = [self._make_record(doi="http://doi.org/10.1234/test")]
        unique, stats = deduplicate(records, {"10.1234/test"}, set(), set())
        assert stats["dup_doi"] == 1

    def test_different_doi_kept(self):
        """異なる DOI のレコードは採用される"""
        records = [self._make_record(doi="10.9999/other")]
        unique, stats = deduplicate(records, {"10.1234/test"}, set(), set())
        assert len(unique) == 1
        assert stats["kept"] == 1
        assert stats["excluded"] == 0

    def test_intra_batch_doi_dedup(self):
        """同一バッチ内で同じ DOI が重複する場合、2件目は除外される"""
        records = [
            self._make_record(doi="10.1234/same", title="Paper A"),
            self._make_record(doi="10.1234/same", title="Paper B"),
        ]
        unique, stats = deduplicate(records, set(), set(), set())
        assert len(unique) == 1
        assert stats["dup_doi"] == 1

    def test_intra_batch_doi_case_insensitive(self):
        """バッチ内 DOI 重複も大文字小文字を無視する"""
        records = [
            self._make_record(doi="10.1234/ABC", title="Paper A"),
            self._make_record(doi="10.1234/abc", title="Paper B"),
        ]
        unique, stats = deduplicate(records, set(), set(), set())
        assert len(unique) == 1
        assert stats["dup_doi"] == 1

    def test_title_dedup_when_no_identifiers(self):
        """DOI・PMID が両方空のレコードはタイトルで重複判定される"""
        existing_title = normalize_title("Randomized Trial of Icatibant in HAE!")
        records = [self._make_record(title="Randomized Trial of Icatibant in HAE!")]
        unique, stats = deduplicate(records, set(), set(), {existing_title})
        assert unique == []
        assert stats["dup_title"] == 1

    def test_no_id_no_title_match_kept_with_review_flag(self):
        """DOI・PMID が両方空でタイトルも既存と一致しない場合は review_flag=True で保持"""
        records = [self._make_record(title="A completely new HAE study")]
        unique, stats = deduplicate(records, set(), set(), set())
        assert len(unique) == 1
        assert unique[0].get("review_flag") is True
        assert stats["title_candidate"] == 1
        assert stats["kept"] == 1

    def test_stats_total_equals_excluded_plus_kept(self):
        """total = excluded + kept が常に成立する"""
        records = [
            self._make_record(doi="10.1234/dup"),   # 除外
            self._make_record(doi="10.9999/new"),   # 採用
        ]
        _, stats = deduplicate(records, {"10.1234/dup"}, set(), set())
        assert stats["total"] == stats["excluded"] + stats["kept"]


# ---------------------------------------------------------------------------
# PMID 重複判定
# ---------------------------------------------------------------------------

class TestDeduplicatePmid:
    """PMID を用いた重複除去テスト。"""

    def _make_record(self, doi="", pmid="", title="A paper"):
        return {"doi": doi, "pmid": pmid, "title": title}

    def test_pmid_matches_existing_excluded(self):
        """既存 CSV に同一 PMID があるレコードは除外される"""
        records = [self._make_record(pmid="12345678")]
        unique, stats = deduplicate(records, set(), {"12345678"}, set())
        assert unique == []
        assert stats["dup_pmid"] == 1
        assert stats["excluded"] == 1

    def test_pmid_different_kept(self):
        """異なる PMID のレコードは採用される"""
        records = [self._make_record(pmid="99999999")]
        unique, stats = deduplicate(records, set(), {"12345678"}, set())
        assert len(unique) == 1
        assert stats["kept"] == 1
        assert stats["dup_pmid"] == 0

    def test_intra_batch_pmid_dedup(self):
        """同一バッチ内で同じ PMID が重複する場合、2件目は除外される"""
        records = [
            self._make_record(pmid="11111111", title="Paper A"),
            self._make_record(pmid="11111111", title="Paper B"),
        ]
        unique, stats = deduplicate(records, set(), set(), set())
        assert len(unique) == 1
        assert stats["dup_pmid"] == 1

    def test_intra_batch_three_pmid_dedup(self):
        """バッチ内で3件同一 PMID がある場合、1件のみ残る"""
        records = [
            self._make_record(pmid="11111111", title="Paper A"),
            self._make_record(pmid="11111111", title="Paper B"),
            self._make_record(pmid="11111111", title="Paper C"),
        ]
        unique, stats = deduplicate(records, set(), set(), set())
        assert len(unique) == 1
        assert stats["dup_pmid"] == 2

    def test_pmid_empty_not_matched(self):
        """空 PMID は既存 PMID セットにマッチしない"""
        records = [self._make_record(pmid="", doi="10.1234/new")]
        unique, stats = deduplicate(records, set(), {""}, set())
        assert len(unique) == 1
        assert stats["dup_pmid"] == 0


# ---------------------------------------------------------------------------
# 優先順位: DOI > PMID > タイトル
# ---------------------------------------------------------------------------

class TestDeduplicatePriority:
    """DOI → PMID → タイトル の優先順位検証。"""

    def _make_record(self, doi="", pmid="", title="A paper"):
        return {"doi": doi, "pmid": pmid, "title": title}

    def test_doi_takes_priority_over_pmid(self):
        """DOI が一致する場合は dup_doi でカウントされ、PMID チェックには進まない"""
        records = [self._make_record(doi="10.1234/test", pmid="12345678")]
        _, stats = deduplicate(records, {"10.1234/test"}, set(), set())
        assert stats["dup_doi"] == 1
        assert stats["dup_pmid"] == 0
        assert stats["dup_title"] == 0

    def test_doi_takes_priority_over_title(self):
        """DOI が一致する場合、タイトルが一致してもタイトル重複はカウントされない"""
        title = "Some HAE paper"
        records = [self._make_record(doi="10.1234/test", title=title)]
        _, stats = deduplicate(
            records, {"10.1234/test"}, set(), {normalize_title(title)}
        )
        assert stats["dup_doi"] == 1
        assert stats["dup_title"] == 0

    def test_pmid_takes_priority_over_title(self):
        """PMID が一致する場合は dup_pmid でカウントされ、タイトルチェックには進まない"""
        title = "Some HAE paper"
        records = [self._make_record(pmid="12345678", title=title)]
        _, stats = deduplicate(records, set(), {"12345678"}, {normalize_title(title)})
        assert stats["dup_pmid"] == 1
        assert stats["dup_title"] == 0

    def test_title_only_when_both_ids_empty(self):
        """DOI・PMID が両方空の場合のみタイトル重複判定が行われる"""
        title = "Some HAE paper"
        # DOI あり → タイトル重複は無視
        records = [self._make_record(doi="10.1234/new", title=title)]
        _, stats = deduplicate(records, set(), set(), {normalize_title(title)})
        assert stats["dup_title"] == 0
        assert stats["kept"] == 1

    def test_doi_match_skips_despite_pmid_and_title_new(self):
        """DOI 重複の場合、PMID・タイトルが新規でも除外される"""
        records = [self._make_record(doi="10.1234/dup", pmid="99999999", title="Brand New Title")]
        _, stats = deduplicate(records, {"10.1234/dup"}, set(), set())
        assert stats["dup_doi"] == 1
        assert stats["kept"] == 0


# ---------------------------------------------------------------------------
# タイトル表記ゆれ重複
# ---------------------------------------------------------------------------

class TestDeduplicateTitleVariations:
    """タイトルの表記ゆれによる重複除去テスト。"""

    def _no_id(self, title):
        """DOI・PMID を持たないレコードを作成する"""
        return {"doi": "", "pmid": "", "title": title}

    def test_case_variation(self):
        """大文字小文字の違いは無視される"""
        existing = {normalize_title("Hereditary Angioedema Treatment Review")}
        records = [self._no_id("HEREDITARY ANGIOEDEMA TREATMENT REVIEW")]
        unique, stats = deduplicate(records, set(), set(), existing)
        assert stats["dup_title"] == 1

    def test_punctuation_variation(self):
        """句読点・コロン・カンマの有無は無視される"""
        existing = {normalize_title("HAE: A Systematic Review, 2022")}
        records = [self._no_id("HAE A Systematic Review 2022")]
        unique, stats = deduplicate(records, set(), set(), existing)
        assert stats["dup_title"] == 1

    def test_hyphen_variation(self):
        """ハイフン有無は無視される (normalize_title が空白に変換する)"""
        existing = {normalize_title("Long-term Prophylaxis for HAE")}
        records = [self._no_id("Long term Prophylaxis for HAE")]
        unique, stats = deduplicate(records, set(), set(), existing)
        assert stats["dup_title"] == 1

    def test_extra_whitespace_variation(self):
        """余分な空白は正規化により無視される"""
        existing = {normalize_title("Icatibant for HAE attacks")}
        records = [self._no_id("Icatibant  for  HAE  attacks")]
        unique, stats = deduplicate(records, set(), set(), existing)
        assert stats["dup_title"] == 1

    def test_trailing_period_variation(self):
        """末尾ピリオドの有無は無視される"""
        existing = {normalize_title("A randomized trial of lanadelumab")}
        records = [self._no_id("A randomized trial of lanadelumab.")]
        unique, stats = deduplicate(records, set(), set(), existing)
        assert stats["dup_title"] == 1

    def test_mixed_case_and_punctuation_combined(self):
        """大文字小文字差異と記号差異が組み合わさっても一致する"""
        existing = {normalize_title("Long-Term Prophylaxis: A Review of HAE Treatment")}
        records = [self._no_id("long term prophylaxis a review of hae treatment")]
        unique, stats = deduplicate(records, set(), set(), existing)
        assert stats["dup_title"] == 1

    def test_different_title_kept_with_review_flag(self):
        """異なるタイトルのレコードは review_flag=True で保持される"""
        existing = {normalize_title("Randomized Trial of Icatibant")}
        records = [self._no_id("Completely Different HAE Study")]
        unique, stats = deduplicate(records, set(), set(), existing)
        assert len(unique) == 1
        assert unique[0].get("review_flag") is True
        assert stats["title_candidate"] == 1

    def test_intra_batch_exact_title_dedup(self):
        """バッチ内で同一タイトル (doi/pmid 両方空) は2件目が除外される"""
        records = [
            self._no_id("Hereditary Angioedema: A Review"),
            self._no_id("Hereditary Angioedema: A Review"),
        ]
        unique, stats = deduplicate(records, set(), set(), set())
        assert len(unique) == 1
        assert stats["dup_title"] == 1

    def test_intra_batch_title_variation_dedup(self):
        """バッチ内でタイトル表記ゆれがある2件も重複と判定される"""
        records = [
            self._no_id("Hereditary angioedema: a review"),
            self._no_id("HEREDITARY ANGIOEDEMA A REVIEW"),
        ]
        unique, stats = deduplicate(records, set(), set(), set())
        assert len(unique) == 1
        assert stats["dup_title"] == 1

    def test_review_flag_not_set_when_has_doi(self):
        """DOI を持つレコードには review_flag が立たない"""
        records = [{"doi": "10.1234/test", "pmid": "", "title": "Some HAE paper"}]
        unique, stats = deduplicate(records, set(), set(), set())
        assert len(unique) == 1
        assert unique[0].get("review_flag") is not True


# ---------------------------------------------------------------------------
# 既存 CSV からのキー読み込み (load_existing_keys)
# ---------------------------------------------------------------------------

class TestLoadExistingKeys:
    """load_existing_keys の単体テスト。"""

    def test_file_not_found_returns_empty_sets(self, tmp_path):
        """存在しないファイルパスを渡すと空セットが返り、エラーにならない"""
        doi_set, pmid_set, title_set = load_existing_keys(
            str(tmp_path / "nonexistent.csv")
        )
        assert doi_set == set()
        assert pmid_set == set()
        assert title_set == set()

    def test_loads_doi_pmid_title(self, tmp_path):
        """CSV から DOI・PMID・タイトルが正しく読み込まれる"""
        csv_path = tmp_path / "papers_master.csv"
        pd.DataFrame([
            {"doi": "10.1234/abc", "pmid": "11111111", "title": "HAE Trial Study"},
            {"doi": "10.5678/def", "pmid": "22222222", "title": "HAE Observational"},
        ]).to_csv(str(csv_path), index=False, encoding="utf-8")

        doi_set, pmid_set, title_set = load_existing_keys(str(csv_path))

        assert "10.1234/abc" in doi_set
        assert "10.5678/def" in doi_set
        assert "11111111" in pmid_set
        assert "22222222" in pmid_set
        assert normalize_title("HAE Trial Study") in title_set
        assert normalize_title("HAE Observational") in title_set

    def test_doi_normalized_on_load(self, tmp_path):
        """CSV に URL プレフィックス付き DOI があっても正規化して読み込む"""
        csv_path = tmp_path / "papers_master.csv"
        pd.DataFrame([
            {"doi": "https://doi.org/10.1234/abc", "pmid": "11111111", "title": "Test"}
        ]).to_csv(str(csv_path), index=False, encoding="utf-8")

        doi_set, _, _ = load_existing_keys(str(csv_path))
        assert "10.1234/abc" in doi_set
        # URL 付き元の文字列は含まれない
        assert "https://doi.org/10.1234/abc" not in doi_set

    def test_empty_doi_pmid_excluded_from_sets(self, tmp_path):
        """空文字・NaN の DOI/PMID はキーセットに含まれない"""
        csv_path = tmp_path / "papers_master.csv"
        pd.DataFrame([
            {"doi": "",   "pmid": "",   "title": "Paper A"},
            {"doi": None, "pmid": None, "title": "Paper B"},
        ]).to_csv(str(csv_path), index=False, encoding="utf-8")

        doi_set, pmid_set, _ = load_existing_keys(str(csv_path))
        assert "" not in doi_set
        assert "" not in pmid_set
        assert doi_set == set()
        assert pmid_set == set()

    def test_missing_doi_column_returns_empty_doi_set(self, tmp_path):
        """doi 列が欠損した CSV でもエラーにならず空セットを返す"""
        csv_path = tmp_path / "papers_master.csv"
        pd.DataFrame([
            {"pmid": "11111111", "title": "Some Paper"}
        ]).to_csv(str(csv_path), index=False, encoding="utf-8")

        doi_set, pmid_set, title_set = load_existing_keys(str(csv_path))
        assert doi_set == set()
        assert "11111111" in pmid_set

    def test_missing_all_key_columns_returns_empty_sets(self, tmp_path):
        """doi/pmid/title 列がすべて欠損した CSV でもエラーにならない"""
        csv_path = tmp_path / "papers_master.csv"
        pd.DataFrame([
            {"journal": "Allergy", "source": "pubmed"}
        ]).to_csv(str(csv_path), index=False, encoding="utf-8")

        doi_set, pmid_set, title_set = load_existing_keys(str(csv_path))
        assert doi_set == set()
        assert pmid_set == set()
        assert title_set == set()

    def test_whitespace_doi_pmid_excluded_from_sets(self, tmp_path):
        """空白のみの DOI/PMID はキーセットに含まれない"""
        csv_path = tmp_path / "papers_master.csv"
        pd.DataFrame([
            {"doi": "   ", "pmid": "  ", "title": "Paper"}
        ]).to_csv(str(csv_path), index=False, encoding="utf-8")

        doi_set, pmid_set, _ = load_existing_keys(str(csv_path))
        assert doi_set == set()
        assert pmid_set == set()

    def test_duplicate_dois_in_csv_deduplicated_in_set(self, tmp_path):
        """CSV 内に同一 DOI が複数行あっても set なので1件として扱われる"""
        csv_path = tmp_path / "papers_master.csv"
        pd.DataFrame([
            {"doi": "10.1234/dup", "pmid": "11111111", "title": "Paper A"},
            {"doi": "10.1234/dup", "pmid": "22222222", "title": "Paper B"},
        ]).to_csv(str(csv_path), index=False, encoding="utf-8")

        doi_set, _, _ = load_existing_keys(str(csv_path))
        assert len([d for d in doi_set if d == "10.1234/dup"]) == 1


# ---------------------------------------------------------------------------
# 既存 CSV との統合フロー (load_existing_keys → deduplicate)
# ---------------------------------------------------------------------------

class TestDeduplicateWithExistingCsv:
    """load_existing_keys と deduplicate を組み合わせた統合テスト。"""

    def _make_csv(self, tmp_path, rows: list[dict]) -> str:
        csv_path = tmp_path / "papers_master.csv"
        pd.DataFrame(rows).to_csv(str(csv_path), index=False, encoding="utf-8")
        return str(csv_path)

    def test_new_record_not_in_existing_is_kept(self, tmp_path):
        """既存 CSV に存在しないレコードは採用される"""
        csv_path = self._make_csv(tmp_path, [
            {"doi": "10.1234/old", "pmid": "10000001", "title": "Old HAE Paper"}
        ])
        existing_dois, existing_pmids, existing_titles = load_existing_keys(csv_path)

        new_records = [{"doi": "10.9999/new", "pmid": "99999999", "title": "New HAE Study"}]
        unique, stats = deduplicate(new_records, existing_dois, existing_pmids, existing_titles)
        assert len(unique) == 1
        assert stats["kept"] == 1

    def test_doi_duplicate_with_existing_csv_excluded(self, tmp_path):
        """既存 CSV の DOI と一致するレコードは除外される"""
        csv_path = self._make_csv(tmp_path, [
            {"doi": "10.1234/existing", "pmid": "10000001", "title": "Existing Paper"}
        ])
        existing_dois, existing_pmids, existing_titles = load_existing_keys(csv_path)

        new_records = [{"doi": "10.1234/existing", "pmid": "99999999", "title": "Dup DOI"}]
        unique, stats = deduplicate(new_records, existing_dois, existing_pmids, existing_titles)
        assert unique == []
        assert stats["dup_doi"] == 1

    def test_doi_url_prefix_duplicate_with_existing_csv_excluded(self, tmp_path):
        """URL プレフィックス付き DOI でも既存 CSV と照合できる"""
        csv_path = self._make_csv(tmp_path, [
            {"doi": "10.1234/existing", "pmid": "10000001", "title": "Existing Paper"}
        ])
        existing_dois, existing_pmids, existing_titles = load_existing_keys(csv_path)

        new_records = [
            {"doi": "https://doi.org/10.1234/existing", "pmid": "99999999", "title": "URL Prefix DOI"}
        ]
        unique, stats = deduplicate(new_records, existing_dois, existing_pmids, existing_titles)
        assert unique == []
        assert stats["dup_doi"] == 1

    def test_pmid_duplicate_with_existing_csv_excluded(self, tmp_path):
        """既存 CSV の PMID と一致するレコードは除外される"""
        csv_path = self._make_csv(tmp_path, [
            {"doi": "10.1234/abc", "pmid": "12345678", "title": "Existing HAE Paper"}
        ])
        existing_dois, existing_pmids, existing_titles = load_existing_keys(csv_path)

        new_records = [{"doi": "10.9999/new", "pmid": "12345678", "title": "New Title Same PMID"}]
        unique, stats = deduplicate(new_records, existing_dois, existing_pmids, existing_titles)
        assert unique == []
        assert stats["dup_pmid"] == 1

    def test_title_duplicate_with_existing_csv_excluded(self, tmp_path):
        """既存 CSV のタイトルと表記ゆれがあっても正規化後に一致すれば除外される"""
        csv_path = self._make_csv(tmp_path, [
            {"doi": "", "pmid": "", "title": "Long-term Prophylaxis: A Review of HAE"}
        ])
        existing_dois, existing_pmids, existing_titles = load_existing_keys(csv_path)

        new_records = [{"doi": "", "pmid": "", "title": "Long term Prophylaxis A Review of HAE"}]
        unique, stats = deduplicate(new_records, existing_dois, existing_pmids, existing_titles)
        assert unique == []
        assert stats["dup_title"] == 1

    def test_mixed_outcomes_doi_pmid_new(self, tmp_path):
        """DOI重複・PMID重複・新規が混在する場合、それぞれが正しく処理される"""
        csv_path = self._make_csv(tmp_path, [
            {"doi": "10.1111/existing", "pmid": "10000001", "title": "Existing Paper 1"},
            {"doi": "10.2222/existing", "pmid": "10000002", "title": "Existing Paper 2"},
        ])
        existing_dois, existing_pmids, existing_titles = load_existing_keys(csv_path)

        new_records = [
            {"doi": "10.1111/existing", "pmid": "99990001", "title": "DOI dup"},       # DOI重複
            {"doi": "10.9999/new1",     "pmid": "10000002", "title": "PMID dup"},       # PMID重複
            {"doi": "10.9999/new2",     "pmid": "99990003", "title": "Completely New"}, # 新規
        ]
        unique, stats = deduplicate(new_records, existing_dois, existing_pmids, existing_titles)

        assert len(unique) == 1
        assert unique[0]["doi"] == "10.9999/new2"
        assert stats["dup_doi"] == 1
        assert stats["dup_pmid"] == 1
        assert stats["kept"] == 1
        assert stats["total"] == stats["excluded"] + stats["kept"]

    def test_second_run_deduplication(self, tmp_path):
        """2回目の実行では前回保存済みレコードがすべて除外される"""
        # 1回目のデータ
        csv_path = self._make_csv(tmp_path, [
            {"doi": "10.1111/p1", "pmid": "10000001", "title": "Paper 1"},
            {"doi": "10.2222/p2", "pmid": "10000002", "title": "Paper 2"},
            {"doi": "10.3333/p3", "pmid": "10000003", "title": "Paper 3"},
        ])
        existing_dois, existing_pmids, existing_titles = load_existing_keys(csv_path)

        # 2回目: 既存3件 + 新規1件
        new_records = [
            {"doi": "10.1111/p1", "pmid": "10000001", "title": "Paper 1"},  # 重複
            {"doi": "10.2222/p2", "pmid": "10000002", "title": "Paper 2"},  # 重複
            {"doi": "10.3333/p3", "pmid": "10000003", "title": "Paper 3"},  # 重複
            {"doi": "10.9999/p4", "pmid": "99999999", "title": "Paper 4"},  # 新規
        ]
        unique, stats = deduplicate(new_records, existing_dois, existing_pmids, existing_titles)

        assert len(unique) == 1
        assert unique[0]["doi"] == "10.9999/p4"
        assert stats["excluded"] == 3
        assert stats["kept"] == 1

