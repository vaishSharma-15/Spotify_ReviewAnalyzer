"""Embedding model wrapper (local, no API key).

Uses sentence-transformers all-MiniLM-L6-v2: 384-dim, fast, ~80MB, fully local.
Embeddings are L2-normalized so a dot product equals cosine similarity, which
keeps Phase 5 retrieval to a single matrix multiply.
"""

from __future__ import annotations

from functools import lru_cache

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384


@lru_cache(maxsize=1)
def load_model():
    """Load (and cache) the embedding model. First call downloads ~80MB."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBED_MODEL)


def embed_texts(texts: list[str]):
    """Return an (N, 384) float32 numpy array of L2-normalized embeddings."""
    model = load_model()
    return model.encode(
        texts,
        batch_size=64,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype("float32")
