"""
3D Reel Studio — Audio Transcription Service
Phase 6: AI Audio Transcription & Timestamps
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from openai import OpenAI, AuthenticationError, RateLimitError, APIConnectionError, APIStatusError, APIError

from app.core.config import settings
from app.core.logging import logger


class TranscriptionServiceError(Exception):
    """Custom exception raised during transcription processing."""
    def __init__(self, message: str, error_code: str = "TRANSCRIPTION_ERROR", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code


@dataclass
class WordTimestampData:
    word: str
    start_time: float
    end_time: float


@dataclass
class SegmentData:
    sequence: int
    start_time: float
    end_time: float
    text: str
    words: Optional[List[WordTimestampData]] = None


@dataclass
class TranscriptionResult:
    language: Optional[str]
    full_text: str
    segments: List[SegmentData]


def get_openai_client(api_key: Optional[str] = None) -> OpenAI:
    """
    Instantiates an OpenAI client with configured API key.
    Raises HTTPException if API key is not configured.
    """
    effective_key = api_key or settings.OPENAI_API_KEY
    if not effective_key or not effective_key.strip():
        logger.error("Transcription requested but OPENAI_API_KEY is not configured.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MISSING_OPENAI_API_KEY",
                "message": "OPENAI_API_KEY is not configured on the server. Please set OPENAI_API_KEY in your environment.",
            },
        )
    return OpenAI(api_key=effective_key.strip())


def transcribe_audio_file(
    audio_path: Path,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    openai_client: Optional[OpenAI] = None,
) -> TranscriptionResult:
    """
    Transcribes an extracted audio file using OpenAI's transcription API.
    Preserves detected language, full transcript text, and timestamped segments.
    """
    # 1. Validate physical audio file existence and size
    if not audio_path.exists() or not audio_path.is_file():
        logger.error(f"Audio file not found on disk at requested path.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "AUDIO_FILE_NOT_FOUND",
                "message": "Physical audio file is missing on the server disk.",
            },
        )

    file_size = audio_path.stat().st_size
    if file_size == 0:
        logger.error("Audio file is 0 bytes (empty audio).")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EMPTY_AUDIO_FILE",
                "message": "Audio file is empty (0 bytes) and cannot be transcribed.",
            },
        )

    # 2. Get client & model
    client = openai_client or get_openai_client(api_key=api_key)
    target_model = model or settings.OPENAI_TRANSCRIPTION_MODEL or "whisper-1"

    logger.info(f"Starting audio transcription with model='{target_model}', file_size={file_size} bytes")

    # 3. Call OpenAI Transcription API
    try:
        with open(audio_path, "rb") as audio_file:
            # We request verbose_json to receive full segment timestamps & detected language
            response = client.audio.transcriptions.create(
                file=audio_file,
                model=target_model,
                response_format="verbose_json",
                timestamp_granularities=["segment", "word"],
            )
    except AuthenticationError as auth_err:
        logger.error(f"OpenAI authentication failed: {auth_err}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "OPENAI_AUTH_ERROR",
                "message": "OpenAI API authentication failed. Verify that your OPENAI_API_KEY is valid.",
            },
        )
    except RateLimitError as rate_err:
        logger.warning(f"OpenAI rate limit hit: {rate_err}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "OPENAI_RATE_LIMIT",
                "message": "OpenAI API rate limit or quota exceeded. Please try again later.",
            },
        )
    except APIConnectionError as conn_err:
        logger.error(f"OpenAI connection error: {conn_err}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "OPENAI_CONNECTION_ERROR",
                "message": "Failed to connect to OpenAI transcription services. Please check network connectivity.",
            },
        )
    except (APIStatusError, APIError) as api_err:
        logger.error(f"OpenAI API status error: {api_err}")
        status_code = getattr(api_err, "status_code", 502)
        if not isinstance(status_code, int) or status_code < 400:
            status_code = 502
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": "OPENAI_API_ERROR",
                "message": "OpenAI transcription service encountered an error.",
            },
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        logger.error(f"Unexpected error during transcription: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "TRANSCRIPTION_FAILED",
                "message": "Audio transcription process encountered an unexpected internal error.",
            },
        )

    # 4. Parse & normalize response
    full_text = getattr(response, "text", "") or ""
    language = getattr(response, "language", None)

    # If response is a dict (mock or custom)
    if isinstance(response, dict):
        full_text = response.get("text", full_text)
        language = response.get("language", language)
        raw_segments = response.get("segments", [])
        raw_words = response.get("words", [])
    else:
        raw_segments = getattr(response, "segments", None) or []
        raw_words = getattr(response, "words", None) or []

    parsed_segments: List[SegmentData] = []

    if raw_segments:
        for seq, seg in enumerate(raw_segments):
            if isinstance(seg, dict):
                start = float(seg.get("start", 0.0))
                end = float(seg.get("end", 0.0))
                text = str(seg.get("text", "")).strip()
                seg_words_raw = seg.get("words")
            else:
                start = float(getattr(seg, "start", 0.0))
                end = float(getattr(seg, "end", 0.0))
                text = str(getattr(seg, "text", "")).strip()
                seg_words_raw = getattr(seg, "words", None)

            words_list: Optional[List[WordTimestampData]] = None
            if seg_words_raw and isinstance(seg_words_raw, list):
                words_list = []
                for w in seg_words_raw:
                    if isinstance(w, dict):
                        w_word = str(w.get("word", "")).strip()
                        w_start = float(w.get("start", 0.0))
                        w_end = float(w.get("end", 0.0))
                    else:
                        w_word = str(getattr(w, "word", "")).strip()
                        w_start = float(getattr(w, "start", 0.0))
                        w_end = float(getattr(w, "end", 0.0))
                    words_list.append(WordTimestampData(word=w_word, start_time=w_start, end_time=w_end))

            parsed_segments.append(
                SegmentData(
                    sequence=seq,
                    start_time=start,
                    end_time=end,
                    text=text,
                    words=words_list,
                )
            )
    elif full_text.strip():
        # Fallback if API returned plain text without segment boundaries
        parsed_segments.append(
            SegmentData(
                sequence=0,
                start_time=0.0,
                end_time=0.0,
                text=full_text.strip(),
                words=None,
            )
        )

    logger.info(f"Audio transcription succeeded: {len(parsed_segments)} segments, language='{language}'")
    return TranscriptionResult(
        language=language,
        full_text=full_text,
        segments=parsed_segments,
    )
