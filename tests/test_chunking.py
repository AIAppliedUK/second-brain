from second_brain_core.chunking import ChunkingConfig, chunk_document


def test_chunk_document_respects_overlap_and_headings():
    sections = [(["Intro"], " ".join(f"word{i}" for i in range(30)))]
    chunks = chunk_document("", sections, ChunkingConfig(target_words=10, overlap_words=2))
    assert len(chunks) == 4
    assert chunks[0][0] == ["Intro"]
    assert chunks[1][1].split()[0] == "word8"
