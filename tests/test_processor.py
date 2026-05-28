import pytest

from znlm.core.processor import ItemProcessor


@pytest.fixture
def processor() -> ItemProcessor:
    return ItemProcessor()


def test_process_full_item(processor, raw_zotero_item):
    item = processor.process(raw_zotero_item, {"COL001": "Machine Learning"})
    assert item.item_key == "ABC123"
    assert item.title == "Attention Is All You Need"
    assert item.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert item.year == 2017
    assert item.tags == ["deep learning", "transformers"]
    assert item.collection_names == ["Machine Learning"]


def test_uncategorized_when_no_collections(processor, raw_zotero_item):
    raw = {**raw_zotero_item, "data": {**raw_zotero_item["data"], "collections": []}}
    item = processor.process(raw, {})
    assert item.collection_names == ["Uncategorized"]


def test_uncategorized_when_collection_key_not_in_map(processor, raw_zotero_item):
    # Collection key exists on item but not in the map (e.g. stale key)
    item = processor.process(raw_zotero_item, {})
    assert item.collection_names == ["Uncategorized"]


def test_extract_authors_name_field(processor):
    creators = [{"creatorType": "author", "name": "The Beatles"}]
    assert processor._extract_authors(creators) == ["The Beatles"]


def test_extract_authors_last_name_only(processor):
    creators = [{"creatorType": "author", "lastName": "Smith"}]
    assert processor._extract_authors(creators) == ["Smith"]


def test_extract_authors_first_name_only(processor):
    creators = [{"creatorType": "author", "firstName": "Jane"}]
    assert processor._extract_authors(creators) == ["Jane"]


def test_extract_authors_skips_non_author_creators(processor):
    creators = [
        {"creatorType": "translator", "firstName": "John", "lastName": "Doe"},
        {"creatorType": "author", "firstName": "Jane", "lastName": "Smith"},
    ]
    assert processor._extract_authors(creators) == ["Jane Smith"]


def test_extract_authors_includes_editors(processor):
    creators = [{"creatorType": "editor", "firstName": "Ed", "lastName": "Editor"}]
    assert processor._extract_authors(creators) == ["Ed Editor"]


def test_parse_year_iso_date(processor):
    assert processor._parse_year("2023-06-15") == 2023


def test_parse_year_year_only(processor):
    assert processor._parse_year("2017") == 2017


def test_parse_year_messy_string(processor):
    assert processor._parse_year("circa 1998") == 1998


def test_parse_year_empty_string(processor):
    assert processor._parse_year("") is None


def test_parse_year_no_recognizable_year(processor):
    assert processor._parse_year("unknown date") is None


def test_extract_tags(processor):
    tags = [{"tag": "ml"}, {"tag": "nlp"}, {}]
    assert processor._extract_tags(tags) == ["ml", "nlp"]


def test_extract_tags_empty(processor):
    assert processor._extract_tags([]) == []
