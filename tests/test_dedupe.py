"""
dedupe モジュールのユニットテスト。

対象:
  - normalize_title: タイトル正規化
  - deduplicate:     DOI重複判定（既存セット照合・バッチ内重複・タイトル重複）
"""
import pytest
from dedupe import normalize_doi, normalize_title, deduplicate


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

    def test_equivalent_titles_match(self):
        """
        表記揺れのある2タイトルが正規化後に一致することを確認する。
        重複除去の中核ユースケース。
        """
        t1 = "Hereditary Angioedema: A Randomized, Double-Blind Trial"
        t2 = "hereditary angioedema a randomized double blind trial"
        assert normalize_title(t1) == normalize_title(t2)


# ---------------------------------------------------------------------------
# DOI 重複判定
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

    def test_plain_doi_unchanged(self):
        assert normalize_doi("10.1234/test") == "10.1234/test"


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
