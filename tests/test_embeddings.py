from second_brain_core.embeddings import DeterministicEmbedder


def test_embedder_is_deterministic_and_normalized():
    embedder = DeterministicEmbedder(32)
    left = embedder.embed("alpha beta beta")
    right = embedder.embed("alpha beta beta")
    assert left == right
    assert round(sum(value * value for value in left), 6) == 1.0
