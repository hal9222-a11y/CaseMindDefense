from app.services.text_service import chunk_text_with_offsets

def test_chunk_text_with_offsets_returns_character_ranges():
    text = "A" * 100 + " white vehicle " + "B" * 100
    chunks = chunk_text_with_offsets(text, chunk_size=50, overlap=10)
    assert len(chunks) >= 1
    first = chunks[0]
    assert "text" in first
    assert "start_char" in first
    assert "end_char" in first
    assert "source_location" in first
    assert first["start_char"] == 0
    assert first["end_char"] > first["start_char"]
    assert first["source_location"].startswith("chars:")
