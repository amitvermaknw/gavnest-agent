"""
HOA document analyzer — the viral feature.

What it does:
  User uploads 80-200 page HOA document.
  Gavvy surfaces:
    - Special assessments (one-time fees the buyer inherits)
    - Reserve fund health (is the HOA financially solvent?)
    - Rental restrictions (can you rent it out?)
    - Pet restrictions
    - Litigation history
    - Move-in/move-out fees
    - Upcoming rule changes

Architecture:
  1. Receive PDF bytes
  2. Extract text with pypdf
  3. Chunk into ~800 token segments with overlap
  4. Embed chunks with OpenAI text-embedding-3-small
  5. Store chunks + embeddings in Firestore for this uid+property
  6. Query: embed the question, find top-k chunks by cosine similarity
  7. Pass top chunks to LLM for synthesis

Storage:
  Firestore: hoa_docs/{uid}/{property_id}/chunks/{chunk_id}
  Each chunk: {text, embedding, page_num, chunk_index}

Note: For MVP we do in-memory similarity search (no vector DB needed).
BigQuery VECTOR_SEARCH upgrade path is documented at the bottom.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any
from langchain_core.messages import HumanMessage
import pypdf
import io

import httpx

from app.graph.llm import get_llm
from app.config import get_setting


# ── Chunking config
CHUNK_SIZE    = 800    # tokens (approx — we use chars/4 as proxy)
CHUNK_OVERLAP = 100
TOP_K         = 5      # top chunks to send to LLM

# Questions Gavvy always asks about an HOA document
HOA_ANALYSIS_QUESTIONS = [
    "Are there any special assessments currently levied or planned?",
    "What is the reserve fund balance and is it adequately funded?",
    "Are there any rental restrictions or rental caps?",
    "What are the pet restrictions?",
    "Is there any pending or active litigation involving the HOA?",
    "What are the move-in or move-out fees?",
    "Are there any upcoming rule changes or amendments?",
]


async def analyze_hoa_document(
    pdf_bytes: bytes,
    uid: str,
    property_address: str,
) -> dict:
    """
    Main entry point — analyzes an HOA PDF and returns structured findings.

    Args:
        pdf_bytes:         raw PDF bytes from file upload
        uid:               Firebase user ID
        property_address:  used as document identifier for Firestore storage

    Returns:
        {
            "property": "...",
            "findings": [
                {"topic": "Special Assessments", "answer": "...", "risk": "high"},
                ...
            ],
            "summary": "...",
            "pages_analyzed": 42,
            "chunks_indexed": 87,
        }
    """
    settings = get_setting()

    # ── Step 1: extract text from PDF 
    pages = _extract_text_from_pdf(pdf_bytes)
    full_text = "\n\n".join([p["text"] for p in pages])
    total_pages = len(pages)

    # ── Step 2: chunk the text
    chunks = _chunk_text(full_text)

    # ── Step 3: embed all chunks 
    embeddings = await _embed_chunks([c["text"] for c in chunks], settings)

    # Attach embeddings to chunks
    for i, chunk in enumerate(chunks):
        chunk["embedding"] = embeddings[i]

    # ── Step 4: persist chunks to Firestore 
    property_id = _make_property_id(property_address)
    await _save_chunks_to_firestore(uid, property_id, chunks)

    # ── Step 5: answer each HOA question via RAG 
    llm = get_llm()
    findings = []

    for question in HOA_ANALYSIS_QUESTIONS:
        # Embed the question
        q_embedding = await _embed_single(question, settings)

        # Find top-k most relevant chunks
        top_chunks = _top_k_chunks(q_embedding, chunks, k=TOP_K)
        context = "\n\n---\n\n".join([c["text"] for c in top_chunks])

        # Ask LLM
        from langchain_core.messages import SystemMessage, HumanMessage
        response = await llm.ainvoke([
            SystemMessage(content=(
                "You are analyzing an HOA document for a home buyer. "
                "Answer the question using only the provided document excerpts. "
                "If the information is not found, say 'Not mentioned in document.' "
                "Be specific — quote dollar amounts, dates, and vote counts when present. "
                "Classify risk as: high, medium, low, or not_found."
                "Respond in JSON: {\"answer\": \"...\", \"risk\": \"...\"}"
            )),
            HumanMessage(content=(
                f"Document excerpts:\n{context}\n\n"
                f"Question: {question}"
            )),
        ])

        try:
            parsed = json.loads(response.content)
        except Exception:
            parsed = {"answer": response.content, "risk": "unknown"}

        topic = question.replace("Are there any ", "").replace("What is the ", "").replace("What are the ", "").replace("Is there any ", "").replace("?", "").strip().title()

        findings.append({
            "topic":    topic,
            "question": question,
            "answer":   parsed.get("answer", ""),
            "risk":     parsed.get("risk", "unknown"),
        })

    # Step 6: generate overall summary 
    high_risk = [f for f in findings if f["risk"] == "high"]
    summary_prompt = (
        f"HOA Analysis Summary for {property_address}:\n\n"
        + "\n".join([f"- {f['topic']}: {f['answer']}" for f in findings])
        + f"\n\nWrite a 3-sentence plain-English summary for a first-time home buyer. "
        f"Highlight any high-risk findings. Be direct and factual."
    )

    
    summary_resp = await llm.ainvoke([HumanMessage(content=summary_prompt)])

    return {
        "property":       property_address,
        "findings":       findings,
        "summary":        summary_resp.content,
        "high_risk_count": len(high_risk),
        "pages_analyzed": total_pages,
        "chunks_indexed": len(chunks),
        "source":         "HOA document provided by user",
    }


# Text extraction 

def _extract_text_from_pdf(pdf_bytes: bytes) -> list[dict]:
    """Extract text page by page using pypdf."""
    try:
        
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append({"page_num": i + 1, "text": text.strip()})
        return pages
    except Exception as e:
        raise RuntimeError(f"PDF extraction failed: {e}") from e


# Chunking 
def _chunk_text(text: str) -> list[dict]:
    """Split text into overlapping chunks of ~CHUNK_SIZE tokens."""
    char_size    = CHUNK_SIZE * 4       # ~4 chars per token
    char_overlap = CHUNK_OVERLAP * 4
    chunks = []
    start = 0
    idx = 0

    while start < len(text):
        end = min(start + char_size, len(text))
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append({"chunk_index": idx, "text": chunk_text})
            idx += 1
        start += char_size - char_overlap

    return chunks


# Embeddings 

async def _embed_chunks(texts: list[str], settings) -> list[list[float]]:
    """Embed a batch of texts using OpenAI text-embedding-3-small."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={"model": "text-embedding-3-small", "input": texts},
        )
        resp.raise_for_status()
    data = resp.json()
    return [item["embedding"] for item in data["data"]]


async def _embed_single(text: str, settings) -> list[float]:
    """Embed a single text string."""
    results = await _embed_chunks([text], settings)
    return results[0]


# Similarity search 

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _top_k_chunks(
    query_embedding: list[float],
    chunks: list[dict],
    k: int = TOP_K,
) -> list[dict]:
    """Return top-k chunks by cosine similarity to the query embedding."""
    scored = [
        (c, _cosine_similarity(query_embedding, c["embedding"]))
        for c in chunks
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in scored[:k]]


# ── Firestore persistence

def _make_property_id(address: str) -> str:
    """Stable document ID from address string."""
    return hashlib.md5(address.lower().strip().encode()).hexdigest()[:12]


async def _save_chunks_to_firestore(
    uid: str,
    property_id: str,
    chunks: list[dict],
) -> None:
    """
    Persist chunks to Firestore for later re-querying.
    Skips silently if Firestore unavailable.

    Path: hoa_docs/{uid}/{property_id}/chunks/{chunk_index}
    """
    try:
        from google.cloud import firestore
        import asyncio
        db = firestore.AsyncClient()
        base = (
            db.collection("hoa_docs")
              .document(uid)
              .collection(property_id)
        )
        # Write in batches of 10 to avoid rate limits
        batch_size = 10
        for i in range(0, len(chunks), batch_size):
            batch = db.batch()
            for chunk in chunks[i:i + batch_size]:
                ref = base.document(str(chunk["chunk_index"]))
                # Store text + embedding (embedding needed for future re-queries)
                batch.set(ref, {
                    "chunk_index": chunk["chunk_index"],
                    "text":        chunk["text"],
                    "embedding":   chunk["embedding"],
                })
            await batch.commit()

        print(f"[HOA_ANALYZER] Saved {len(chunks)} chunks to Firestore")
    except Exception as e:
        print(f"[HOA_ANALYZER] Firestore save skipped: {e}")


#  BigQuery upgrade path (Weekend 6 / post-MVP) 
# When HOA doc volume grows, replace in-memory similarity with:
#   SELECT base.chunk_index, base.text
#   FROM VECTOR_SEARCH(
#     TABLE hoa_chunks,
#     'embedding',
#     (SELECT embedding FROM query_embedding),
#     top_k => 5,
#     distance_type => 'COSINE'
#   )
# This keeps the same interface — just swap _top_k_chunks() implementation.