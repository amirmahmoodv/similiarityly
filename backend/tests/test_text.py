import math

import pytest

from app.schemas import ChunkingConfig, NormalizationConfig
from app.services.chunking import chunk_text
from app.services.normalize import normalize
from app.services.parsers import read_table, split_text, table_records
from app.services.pipeline import unit_vectors
from app.services.vector_store import to_similarity


def test_normalize_unifies_arabic_and_persian_forms():
    cfg = NormalizationConfig()
    assert normalize("كتابِ علي ١٢٣", cfg) == normalize("کتاب علی ۱۲۳", cfg) == "کتاب علی 123"


def test_normalize_zwnj_modes():
    text = "می‌روم"
    assert normalize(text, NormalizationConfig(zwnj="keep")) == text
    assert normalize(text, NormalizationConfig(zwnj="space")) == "می روم"
    assert normalize(text, NormalizationConfig(zwnj="remove")) == "میروم"


def test_record_strategy_keeps_one_chunk():
    assert chunk_text("  یک رکورد کوتاه  ", ChunkingConfig()) == ["یک رکورد کوتاه"]


def test_fixed_chunks_overlap_and_cover_text():
    text = "".join(chr(ord("a") + i % 26) for i in range(100))
    chunks = chunk_text(text, ChunkingConfig(strategy="fixed", chunk_size=40, overlap=10))
    assert all(len(c) <= 40 for c in chunks)
    assert chunks[0][-10:] == chunks[1][:10]
    assert chunks[-1].endswith(text[-5:])


def test_sentence_chunks_respect_size_and_persian_delimiters():
    text = "جمله اول است. جمله دوم چیست؟ جمله سوم؛ جمله چهارم!"
    chunks = chunk_text(text, ChunkingConfig(strategy="sentence", chunk_size=30, overlap=0))
    assert len(chunks) >= 2
    assert all(len(c) <= 30 for c in chunks)


def test_csv_table_and_column_selection():
    data = "عنوان,شرح\nالف,متن یک\nب,متن دو\n".encode()
    columns, rows, _ = read_table(data, "x.csv")
    assert columns == ["عنوان", "شرح"]
    records = table_records(columns, rows, ["شرح"])
    assert [t for t, _ in records] == ["متن یک", "متن دو"]
    assert records[0][1]["row"] == 1


def test_unit_vectors_scale_to_length_one_and_keep_zero():
    out = unit_vectors([[3.0, 4.0], [0.0, 0.0]])
    assert out[0] == pytest.approx([0.6, 0.8])
    assert out[1] == [0.0, 0.0]


@pytest.mark.parametrize("cos", [1.0, 0.92, 0.75, 0.3, 0.0])
def test_to_similarity_is_cosine_for_every_metric(cos):
    assert to_similarity(cos, "cosine") == pytest.approx(cos)
    assert to_similarity(cos, "dot") == pytest.approx(cos)
    assert to_similarity(math.sqrt(2 - 2 * cos), "euclid") == pytest.approx(cos)


def test_to_similarity_clamps_to_zero_one():
    assert to_similarity(-0.4, "cosine") == 0
    assert to_similarity(1.0000001, "dot") == 1
    assert to_similarity(2.0, "euclid") == 0  # opposite vectors


def test_split_text_modes():
    text = "یک\nدو\n\nسه"
    assert len(split_text(text, "lines")) == 3
    assert len(split_text(text, "paragraphs")) == 2
    assert len(split_text(text, "whole")) == 1
