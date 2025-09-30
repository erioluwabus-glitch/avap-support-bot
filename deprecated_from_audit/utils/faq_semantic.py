"""
Semantic FAQ helper using sentence-transformers + FAISS (optional).
This module is optional and degrades gracefully if dependencies are missing.
"""
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Optional heavy dependencies
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    import faiss  # type: ignore
    _SEMANTIC_AVAILABLE = True
except Exception:
    _SEMANTIC_AVAILABLE = False
    SentenceTransformer = None  # type: ignore
    np = None  # type: ignore
    faiss = None  # type: ignore

_model: Optional["SentenceTransformer"] = None
_index = None
_faq_pairs: List[Tuple[str, str]] = []  # (question, answer)


def _ensure_model() -> bool:
    global _model
    if not _SEMANTIC_AVAILABLE:
        return False
    if _model is None:
        try:
            _model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as e:
            logger.exception(f"Failed to load sentence-transformers model: {e}")
            return False
    return True


def _rebuild_index() -> None:
    global _index
    if not _SEMANTIC_AVAILABLE or _model is None:
        return
    if not _faq_pairs:
        _index = None
        return
    try:
        embeddings = [_model.encode(q) for q, _ in _faq_pairs]
        dim = len(embeddings[0])
        arr = np.array(embeddings).astype("float32")
        # Normalize for cosine similarity via inner product
        faiss.normalize_L2(arr)
        idx = faiss.IndexFlatIP(dim)
        idx.add(arr)
        _index = idx
    except Exception as e:
        logger.exception(f"Failed to build FAISS index: {e}")
        _index = None


def add_to_index(question: str, answer: str) -> None:
    """Add a new (question, answer) pair to the in-memory index."""
    if not _ensure_model():
        return
    try:
        _faq_pairs.append((question, answer))
        _rebuild_index()
    except Exception:
        logger.exception("Failed to add FAQ to semantic index")


def semantic_find(query: str, threshold: float = 0.70) -> Optional[str]:
    """Return best matched answer if semantic score exceeds threshold."""
    if not _ensure_model() or _index is None or not _faq_pairs:
        return None
    try:
        q_emb = _model.encode(query)
        q_emb = np.array([q_emb]).astype("float32")
        faiss.normalize_L2(q_emb)
        scores, indices = _index.search(q_emb, k=1)
        best_score = float(scores[0][0]) if scores is not None else 0.0
        best_idx = int(indices[0][0]) if indices is not None else -1
        if best_idx >= 0 and best_score >= threshold:
            return _faq_pairs[best_idx][1]
        return None
    except Exception as e:
        logger.exception(f"Semantic search failed: {e}")
        return None


