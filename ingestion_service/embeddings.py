from __future__ import annotations

import logging
import random
import time
from enum import Enum
from threading import Lock
from typing import List, Sequence

import google.genai as genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
import requests
import json

import config

logger = logging.getLogger("ingestion.embeddings")

_CLIENT_LOCK = Lock()
_CLIENT: genai.Client | None = None


class EmbeddingTask(str, Enum):
    DOCUMENT = "retrieval_document"
    QUERY = "retrieval_query"


def _get_client() -> genai.Client:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = genai.Client(api_key=config.GEMINI_API_KEY)
    return _CLIENT


def ensure_embeddings_ready() -> None:
    """Ensure the Gemini client can be initialised."""
    _get_client()


def ensure_summarizer_ready() -> None:
    """Ensure the summarizer client can be initialised based on configured provider."""
    if config.SUMMARY_PROVIDER == "OPENROUTER":
        if not config.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY is not configured.")
    else:
        _get_client()


def embed_texts(
    texts: Sequence[str],
    *,
    task: EmbeddingTask = EmbeddingTask.DOCUMENT,
) -> List[List[float]]:
    if not texts:
        return []

    client = _get_client()
    vectors: List[List[float]] = []
    batch_size = config.EMBED_BATCH_SIZE

    for start in range(0, len(texts), batch_size):
        batch = [t or "" for t in texts[start : start + batch_size]]
        attempts = config.EMBED_MAX_RETRIES
        for attempt in range(1, attempts + 1):
            try:
                response = client.models.embed_content(
                    model=config.EMBED_MODEL,
                    contents=batch,
                    config=genai_types.EmbedContentConfig(
                        output_dimensionality=config.EMBED_DIM,
                        task_type=task.value,
                    ),
                )
                embeddings = response.embeddings or []
                if len(embeddings) != len(batch):
                    raise RuntimeError("Embedding response size mismatch.")
                vectors.extend([embed.values or [] for embed in embeddings])
                break
            except genai_errors.ClientError as exc:
                if attempt >= attempts:
                    raise
                wait = 1 + attempt * 2
                logger.warning("Embedding client error (attempt %d/%d): %s", attempt, attempts, exc)
                time.sleep(wait)
            except Exception as exc:  # noqa: BLE001
                if attempt >= attempts:
                    raise
                wait = 2 ** attempt + random.uniform(0, 1)
                logger.warning("Embedding error (attempt %d/%d): %s", attempt, attempts, exc)
                time.sleep(wait)

    return vectors


def summarise_document(text: str) -> str:
    # Check if summary generation is disabled
    if config.SKIP_SUMMARY:
        logger.debug("Summary generation skipped (SKIP_SUMMARY=true), returning '-'")
        return "-"
    
    if config.SUMMARY_PROVIDER == "OPENROUTER":
        return _summarise_with_openrouter(text)
    else:
        return _summarise_with_gemini(text)


def _summarise_with_gemini(text: str) -> str:
    """Summarise document using Google Gemini API."""
    logger.debug("Summary generation enabled, calling Gemini API...")
    client = _get_client()
    candidate_text = text[:30000]
    prompt = (
        "Analisis dokumen berikut dan susun ringkasan berbahasa Indonesia dengan struktur berikut:\n\n"
        "1. Paragraf Pembuka: Jelaskan secara garis besar apa isi dokumen ini dan tujuannya\n"
        "2. Detail: Sajikan poin-poin penting seperti jenis dokumen, pihak terkait, tanggal, "
        "angka penting, dan pokok isi dengan format markdown (bullet points, headings, dll jika relevan)\n\n"
        f"TEKS DOKUMEN:\n{candidate_text}\n"
    )

    parts = [genai_types.Part(text=prompt)]
    content = genai_types.Content(role="user", parts=parts)
    attempts = config.SUMMARY_MAX_RETRIES

    for attempt in range(1, attempts + 1):
        try:
            response = client.models.generate_content(
                model=config.SUMMARY_MODEL,
                contents=[content],
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=2048,
                    safety_settings=[
                        genai_types.SafetySetting(
                            category=genai_types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                            threshold=genai_types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                        genai_types.SafetySetting(
                            category=genai_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                            threshold=genai_types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                        genai_types.SafetySetting(
                            category=genai_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                            threshold=genai_types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                        genai_types.SafetySetting(
                            category=genai_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                            threshold=genai_types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                    ],
                ),
            )

            if response.prompt_feedback and response.prompt_feedback.block_reason:
                logger.warning("Summary blocked by safety system: %s", response.prompt_feedback.block_reason)
                return config.SUMMARY_FALLBACK_TEXT

            candidate = response.candidates[0] if response.candidates else None
            if not candidate or candidate.finish_reason == genai_types.FinishReason.SAFETY:
                logger.warning("Summary generation interrupted due to safety.")
                return config.SUMMARY_FALLBACK_TEXT

            if not candidate.content or not candidate.content.parts:
                if not config.SKIP_SUMMARY:
                    logger.warning("Summary generation returned empty content.")
                return config.SUMMARY_FALLBACK_TEXT

            parts = candidate.content.parts
            summary = " ".join(part.text for part in parts if part.text).strip()
            if not summary:
                return config.SUMMARY_FALLBACK_TEXT

            return summary

        except (genai_errors.ClientError, genai_errors.ServerError, genai_errors.APIError) as exc:
            if attempt >= attempts:
                logger.warning("Summary generation failed after %d attempts: %s", attempts, exc)
                return config.SUMMARY_FALLBACK_TEXT
            wait = 2 ** attempt + random.uniform(0, 1)
            logger.warning("Summary generation error (attempt %d/%d): %s", attempt, attempts, exc)
            time.sleep(wait)

    return config.SUMMARY_FALLBACK_TEXT


def _summarise_with_openrouter(text: str) -> str:
    """Summarise document using OpenRouter API with raw requests."""
    logger.debug("Summary generation enabled, calling OpenRouter API...")
    candidate_text = text[:30000]
    prompt = (
        "Analisis dokumen berikut dan susun ringkasan berbahasa Indonesia dengan struktur berikut:\n\n"
        "1. Paragraf Pembuka: Jelaskan secara garis besar apa isi dokumen ini dan tujuannya\n"
        "2. Detail: Sajikan poin-poin penting seperti jenis dokumen, pihak terkait, tanggal, "
        "angka penting, dan pokok isi dengan format markdown (bullet points, headings, dll jika relevan)\n\n"
        f"TEKS DOKUMEN:\n{candidate_text}\n"
    )

    attempts = config.SUMMARY_MAX_RETRIES

    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://document-search.local",
                    "X-Title": "Document Search Stack",
                },
                data=json.dumps({
                    "model": config.OPENROUTER_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                        }
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2048,
                }),
                timeout=30,
            )

            if response.status_code != 200:
                error_msg = f"OpenRouter API error {response.status_code}"
                if response.status_code >= 400 and response.status_code < 500:
                    logger.warning("OpenRouter client error: %s", error_msg)
                    if attempt >= attempts:
                        return config.SUMMARY_FALLBACK_TEXT
                    wait = 2 ** attempt + random.uniform(0, 1)
                    logger.warning("Summary generation error (attempt %d/%d): %s", attempt, attempts, error_msg)
                    time.sleep(wait)
                    continue
                else:
                    raise RuntimeError(error_msg)

            data = response.json()
            
            if not data.get("choices") or not data["choices"][0].get("message"):
                logger.warning("Summary generation returned empty content from OpenRouter.")
                return config.SUMMARY_FALLBACK_TEXT

            summary = data["choices"][0]["message"].get("content", "").strip()
            if not summary:
                return config.SUMMARY_FALLBACK_TEXT

            return summary

        except requests.exceptions.RequestException as exc:
            if attempt >= attempts:
                logger.warning("Summary generation failed after %d attempts: %s", attempts, exc)
                return config.SUMMARY_FALLBACK_TEXT
            wait = 2 ** attempt + random.uniform(0, 1)
            logger.warning("Summary generation error (attempt %d/%d): %s", attempt, attempts, exc)
            time.sleep(wait)
        except Exception as exc:  # noqa: BLE001
            if attempt >= attempts:
                logger.warning("Summary generation failed after %d attempts: %s", attempts, exc)
                return config.SUMMARY_FALLBACK_TEXT
            wait = 2 ** attempt + random.uniform(0, 1)
            logger.warning("Summary generation error (attempt %d/%d): %s", attempt, attempts, exc)
            time.sleep(wait)

    return config.SUMMARY_FALLBACK_TEXT
