from __future__ import annotations

import logging
import os
import random
import time
from typing import Dict, List

import google.genai as genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from fastapi import FastAPI, HTTPException, Query
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from fastembed import SparseTextEmbedding

DOC_COLLECTION = "documents_v2"
CHUNK_COLLECTION = "chunks_v2"
DOC_VECTOR_NAME = "v_doc"
CHUNK_VECTOR_NAME = "v_chunk"
BM25_VECTOR_NAME = "v_bm25"
EMBED_DIM = int(os.getenv("EMBED_DIM", "3072"))

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")

logger = logging.getLogger("search")
logging.basicConfig(level=logging.INFO)

qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
app = FastAPI(title="Search Service", version="2.0.0")

_client: genai.Client | None = None
_bm25_model: SparseTextEmbedding | None = None


def _get_client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _get_bm25_model() -> SparseTextEmbedding:
    """Lazy load BM25 model."""
    global _bm25_model
    if _bm25_model is None:
        _bm25_model = SparseTextEmbedding(model_name="Qdrant/bm25")
        logger.info("Loaded BM25 model for sparse vectors")
    return _bm25_model


def generate_bm25_vector(text: str) -> Dict:
    """Generate BM25 sparse vector from text."""
    if not text or not text.strip():
        return {"indices": [], "values": []}
    
    try:
        model = _get_bm25_model()
        embeddings = list(model.embed([text]))
        if not embeddings:
            return {"indices": [], "values": []}
        
        sparse_vector = embeddings[0]
        return {
            "indices": sparse_vector.indices.tolist(),
            "values": sparse_vector.values.tolist(),
        }
    except Exception as exc:
        logger.warning(f"Failed to generate BM25 vector: {exc}")
        return {"indices": [], "values": []}


def embed_query(text: str) -> List[float]:
    client = _get_client()
    trimmed = (text or "").strip()
    if not trimmed:
        raise ValueError("Query must not be empty.")

    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            response = client.models.embed_content(
                model=EMBED_MODEL,
                contents=[trimmed],
                config=genai_types.EmbedContentConfig(
                    output_dimensionality=EMBED_DIM,
                    task_type="retrieval_query",
                ),
            )
            embeddings = response.embeddings or []
            if not embeddings or not embeddings[0].values:
                raise RuntimeError("Empty embedding returned from Gemini.")
            return embeddings[0].values
        except (genai_errors.ClientError, genai_errors.APIError, genai_errors.ServerError) as exc:
            if attempt >= attempts:
                raise RuntimeError(f"Gemini embedding failed: {exc}") from exc
            wait = 2**attempt + random.uniform(0, 1)
            logger.warning("Embedding retry %d/%d due to %s. Sleeping %.1fs", attempt, attempts, exc, wait)
            time.sleep(wait)

    raise RuntimeError("Failed to generate embedding for query.")


@app.get("/search", tags=["search"])
def search(
    query: str = Query(..., description="The search query string"),
    top_k: int = Query(5, ge=1, le=50, description="Number of top results to return"),
    chunk_candidates: int = Query(50, ge=1, le=200, description="Number of chunks to search before deduplication"),
) -> Dict[str, List[Dict]]:
    """
    Hybrid search (dense + sparse):
    1. Generate both semantic (dense) and BM25 (sparse) vectors for query
    2. Search chunks collection with hybrid query
    3. Group by document to find unique documents
    4. Retrieve document metadata for each unique document
    5. Return top K results with document info + best chunk snippet
    """
    try:
        # Generate dense vector (semantic)
        query_vector = embed_query(query)
        
        # Generate sparse vector (BM25 keyword)
        bm25_vector = generate_bm25_vector(query)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Step 1: Hybrid search on chunks collection using prefetch + fusion
    try:
        response = qdrant_client.query_points(
            collection_name=CHUNK_COLLECTION,
            prefetch=[
                qmodels.Prefetch(
                    query=qmodels.SparseVector(
                        indices=bm25_vector["indices"],
                        values=bm25_vector["values"],
                    ),
                    using=BM25_VECTOR_NAME,
                    limit=chunk_candidates,
                ),
                qmodels.Prefetch(
                    query=query_vector,
                    using=CHUNK_VECTOR_NAME,
                    limit=chunk_candidates,
                ),
            ],
            query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
            limit=chunk_candidates,
        )
        chunk_results = response.points if hasattr(response, 'points') else response
    except Exception as exc:
        logger.error(f"Hybrid search failed: {exc}")
        # Fallback to dense-only search
        chunk_results = qdrant_client.search(
            collection_name=CHUNK_COLLECTION,
            query_vector=(CHUNK_VECTOR_NAME, query_vector),
            limit=chunk_candidates,
        )
    
    if not chunk_results:
        return {"results": []}

    # Step 2: Group chunks by docId and keep only the best chunk per document
    doc_best_chunks: Dict[str, Dict] = {}  # docId -> {chunk_info, score}
    
    for chunk in chunk_results:
        chunk_payload = chunk.payload or {}
        doc_id = chunk_payload.get("docId")
        
        if not doc_id:
            continue
        
        # Keep only the best (first/highest scored) chunk per document
        if doc_id not in doc_best_chunks:
            snippet = chunk_payload.get("text", "")
            doc_best_chunks[doc_id] = {
                "docId": doc_id,
                "chunkNo": chunk_payload.get("chunkNo"),
                "snippet": snippet[:512] + ("..." if len(snippet) > 512 else ""),
                "score": chunk.score,
                "fileName": chunk_payload.get("fileName"),
            }
    
    # Step 3: Retrieve document metadata for each unique document
    if not doc_best_chunks:
        return {"results": []}
    
    # Build filter to get all documents at once
    doc_ids = list(doc_best_chunks.keys())
    
    # Retrieve documents by filtering on fileId
    doc_points, _ = qdrant_client.scroll(
        collection_name=DOC_COLLECTION,
        scroll_filter=qmodels.Filter(
            should=[
                qmodels.FieldCondition(
                    key="fileId",
                    match=qmodels.MatchValue(value=doc_id),
                )
                for doc_id in doc_ids
            ]
        ),
        limit=len(doc_ids),
        with_payload=True,
        with_vectors=False,
    )
    
    # Step 4: Combine document metadata with chunk info
    results: List[Dict] = []
    
    for doc_point in doc_points:
        doc_payload = doc_point.payload or {}
        file_id = doc_payload.get("fileId")
        
        if file_id not in doc_best_chunks:
            continue
        
        chunk_info = doc_best_chunks[file_id]
        
        results.append({
            "fileId": file_id,
            "fileName": doc_payload.get("fileName"),
            "drivePath": doc_payload.get("drivePath"),
            "summary": doc_payload.get("summary"),
            "webUrl": doc_payload.get("webUrl"),
            "chunkNo": chunk_info["chunkNo"],
            "snippet": chunk_info["snippet"],
            "score": chunk_info["score"],
        })
    
    # Sort by score (highest first) and return top K
    results.sort(key=lambda item: item["score"], reverse=True)
    return {"results": results[:top_k]}
