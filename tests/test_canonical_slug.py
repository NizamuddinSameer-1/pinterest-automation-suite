"""
Regression guards for lookbook slug generation.

Context: the original slug scheme was
    prod_name_slug = re.sub(...)[:40]
    slug = f"{prod_name_slug}-{job_id[:8]}"

Two defects came out of that, both found in production:

1. `[:40]` sliced mid-word, producing dangling fragments and sometimes a
   trailing separator that collapsed into a double hyphen:
       lighted-human-dog-skeleton-halloween-dec-7c336083
       classic-cast-iron-skillet-test-com
       wishten-3-pcs-pumpkin-costume-for-women--5d692a6d

2. Appending `job_id[:8]` minted a NEW url on every generation run, so a single
   product accumulated competing pages:
       black-leggings-5fa494c3.html / -84153c9d.html / -cc6a4c9b.html / -2c9aae73.html
       leggings-f5c95d65.html
   Five near-duplicate pages for one keyword means search engines rank none.

These tests pin the corrected contract.
"""
from app.services.article_generator import build_canonical_slug, slugify_product_name


class TestSlugifyProductName:
    def test_lowercases_and_joins_on_single_hyphen(self):
        assert slugify_product_name("Black Leggings") == "black-leggings"

    def test_collapses_punctuation_runs_into_one_separator(self):
        # The real WISHTEN title has a comma and no space after it.
        out = slugify_product_name(
            "WISHTEN 3 PCS Pumpkin Costume for Women,Halloween Costumes for Women Adult"
        )
        assert "--" not in out
        assert out.startswith("wishten-3-pcs-pumpkin-costume-for-women-halloween")

    def test_truncation_lands_on_a_word_boundary(self):
        long_name = (
            "Lighted Human & Dog Skeleton Halloween Decorations Outdoor/Indoor - 36 Inch "
            "Realistic Full Body Movable Posable Skeleton Spooky Halloween Decor for Garden"
        )
        out = slugify_product_name(long_name)
        assert len(out) <= 60
        # Must not end on a dangling fragment of a word.
        assert not out.endswith(("-dec", "-com", "-batc", "-tld"))
        # The trailing token must be a whole word from the source.
        assert out.rsplit("-", 1)[-1] in long_name.lower()

    def test_never_emits_a_double_hyphen(self):
        for name in (
            "Halloween Pajama Pants for Women Spooky Pumpkin",
            "Adult Pumpkin Costume Poncho Set",
            "Topdress Women'sVintage Polka Audrey Dress 1950s",
        ):
            assert "--" not in slugify_product_name(name)

    def test_empty_or_symbol_only_name_falls_back(self):
        assert slugify_product_name("") == "curated-item"
        assert slugify_product_name("!!!") == "curated-item"
        assert slugify_product_name(None) == "curated-item"


class TestBuildCanonicalSlug:
    def test_slug_is_stable_across_generation_runs(self):
        """The whole point: same product => same url, whatever the job id is."""
        slugs = {
            build_canonical_slug("Black Leggings", asin="B0CHQJLQTC", job_id=job)
            for job in ("5fa494c3-aaaa", "84153c9d-bbbb", "2c9aae73-cccc")
        }
        assert len(slugs) == 1, f"slug drifted between runs: {slugs}"
        assert slugs.pop() == "black-leggings-b0chqjlqtc"

    def test_asins_disambiguate_products_sharing_a_title(self):
        """Two distinct Wedtrend tea dresses share a title but not an ASIN."""
        a = build_canonical_slug("Wedtrend Vintage Tea Dress", asin="B0B5QV6XW7", job_id="x")
        b = build_canonical_slug("Wedtrend Vintage Tea Dress", asin="B0BQW5G4S8", job_id="x")
        assert a != b
        assert a.endswith("b0b5qv6xw7")
        assert b.endswith("b0bqw5g4s8")

    def test_asin_is_normalised_to_lowercase(self):
        assert build_canonical_slug("Thing", asin="B0CHQJLQTC").endswith("b0chqjlqtc")

    def test_no_asin_falls_back_to_job_hash(self):
        """Placeholders without an ASIN cannot monetise; they still need a url."""
        out = build_canonical_slug("Reference Product", asin=None, job_id="88729bb1-1111")
        assert out == "reference-product-88729bb1"

    def test_blank_asin_string_is_treated_as_missing(self):
        out = build_canonical_slug("Reference Product", asin="   ", job_id="88729bb1-1111")
        assert out == "reference-product-88729bb1"


class TestPublicLookbookSlugPolicy:
    """
    Test/dev scaffolding must stay out of the catalog grid and sitemap.

    Eleven such pages were publicly deployed AND listed in sitemap.xml at
    priority 0.8, which burns crawl budget and dilutes quality signals on a
    young domain. `is_public_lookbook_slug` is the single predicate both the
    catalog and the sitemap consult, so they can never disagree.
    """

    def test_real_review_slugs_stay_public(self):
        from app.services.git_publisher import is_public_lookbook_slug

        for slug in (
            "early-september-nails-viral-inspo-guide-4146d8b2",
            "maid-costume-87a5f232",
            "black-leggings-b0chqjlqtc",
        ):
            assert is_public_lookbook_slug(slug) is True, slug

    def test_test_scaffolding_is_excluded(self):
        from app.services.git_publisher import is_public_lookbook_slug

        for slug in (
            "test-tldr-render",
            "test-job",
            "test-compliance-job",
            "prod-job1",
            "prod-test-job",
            "job1",
            "job-batch-777",
            "reference-product-88729bb1",
            "classic-cast-iron-skillet-test-com",
            "vasagle-slim-3-tier-bar-cart-test-tld",
            "linen-duvet-cover-job-batc",
        ):
            assert is_public_lookbook_slug(slug) is False, slug

    def test_empty_slug_is_not_public(self):
        from app.services.git_publisher import is_public_lookbook_slug

        assert is_public_lookbook_slug("") is False
