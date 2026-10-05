"""
3D Reel Studio — AI Audio Transcription Integration & Unit Tests
Phase 6: AI Audio Transcription & Timestamps
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from openai import AuthenticationError, RateLimitError, APIConnectionError
import httpx

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.project import Project, MediaFile, Transcript, TranscriptSegment
from app.services.storage import get_base_storage_dir


class MockSegment:
    """Mock segment representing OpenAI verbose_json segment response."""
    def __init__(self, sequence: int, start: float, end: float, text: str, words=None):
        self.id = sequence
        self.seek = 0
        self.start = start
        self.end = end
        self.text = text
        self.tokens = []
        self.temperature = 0.0
        self.avg_logprob = -0.15
        self.compression_ratio = 1.2
        self.no_speech_prob = 0.01
        self.words = words or []


class MockWord:
    """Mock word representing OpenAI verbose_json word timestamp."""
    def __init__(self, word: str, start: float, end: float):
        self.word = word
        self.start = start
        self.end = end


class MockVerboseTranscription:
    """Mock response object from OpenAI client.audio.transcriptions.create."""
    def __init__(self, text: str, language: str = "english", segments=None, words=None):
        self.text = text
        self.language = language
        self.duration = 4.75
        self.segments = segments or []
        self.words = words or []


@pytest.fixture
def project_with_audio(client: TestClient):
    """
    Creates a test project with a valid extracted audio file.
    """
    # 1. Create project
    create_resp = client.post("/api/v1/projects", json={"name": "Transcription Test Project"})
    assert create_resp.status_code == 201
    project_id = create_resp.json()["project"]["id"]

    # 2. Create physical audio file
    base_storage = get_base_storage_dir()
    audio_dir = base_storage / "projects" / project_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_file_path = audio_dir / "sample_test_audio.mp3"
    audio_file_path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00MOCK_MP3_AUDIO_STREAM_BYTES_FOR_TESTING")

    # 3. Create MediaFile record
    db = SessionLocal()
    try:
        media_record = MediaFile(
            id="MEDIA-AUDIO-TEST-001",
            project_id=project_id,
            file_type="extracted_audio",
            original_filename="sample_audio.mp3",
            stored_filename="sample_test_audio.mp3",
            file_path=f"projects/{project_id}/audio/sample_test_audio.mp3",
            mime_type="audio/mpeg",
            file_size=len(audio_file_path.read_bytes()),
            sha256_hash="mocksha256hashforaudiotest",
        )
        db.add(media_record)
        db.commit()
    finally:
        db.close()

    yield {"project_id": project_id, "media_id": "MEDIA-AUDIO-TEST-001", "audio_path": audio_file_path}

    # Cleanup
    db = SessionLocal()
    try:
        proj = db.query(Project).filter(Project.id == project_id).first()
        if proj:
            db.delete(proj)
            db.commit()
    finally:
        db.close()


def test_successful_audio_transcription(client: TestClient, project_with_audio: dict):
    """
    Scenario 1 & 2: Valid extracted audio transcribes successfully and returns structured transcript.
    """
    project_id = project_with_audio["project_id"]
    media_id = project_with_audio["media_id"]

    mock_words_seg0 = [
        MockWord("Hello", 0.52, 1.10),
        MockWord("everyone", 1.15, 2.31),
    ]
    mock_words_seg1 = [
        MockWord("Welcome", 2.32, 2.90),
        MockWord("to", 2.91, 3.10),
        MockWord("my", 3.11, 3.40),
        MockWord("channel", 3.41, 4.75),
    ]

    mock_segments = [
        MockSegment(0, 0.52, 2.31, "Hello everyone", mock_words_seg0),
        MockSegment(1, 2.32, 4.75, "Welcome to my channel", mock_words_seg1),
    ]

    mock_resp = MockVerboseTranscription(
        text="Hello everyone Welcome to my channel",
        language="english",
        segments=mock_segments,
    )

    with patch.object(settings, "OPENAI_API_KEY", "sk-mock-key-for-unit-testing"), \
         patch("app.services.transcription.OpenAI") as mock_openai_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.audio.transcriptions.create.return_value = mock_resp
        mock_openai_cls.return_value = mock_client_instance

        resp = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/transcribe")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    transcript = data["transcript"]
    assert transcript["project_id"] == project_id
    assert transcript["audio_media_id"] == media_id
    assert transcript["language"] == "english"
    assert transcript["full_text"] == "Hello everyone Welcome to my channel"
    assert len(transcript["segments"]) == 2

    # Scenario 3: Check timestamped segments and word timestamps
    seg0 = transcript["segments"][0]
    assert seg0["sequence"] == 0
    assert seg0["start_time"] == pytest.approx(0.52)
    assert seg0["end_time"] == pytest.approx(2.31)
    assert seg0["text"] == "Hello everyone"
    assert seg0["words"] is not None
    assert len(seg0["words"]) == 2
    assert seg0["words"][0]["word"] == "Hello"

    seg1 = transcript["segments"][1]
    assert seg1["sequence"] == 1
    assert seg1["start_time"] == pytest.approx(2.32)
    assert seg1["end_time"] == pytest.approx(4.75)
    assert seg1["text"] == "Welcome to my channel"


def test_transcription_missing_api_key(client: TestClient, project_with_audio: dict):
    """
    Scenario 4: Transcription fails with 400 when OPENAI_API_KEY is not configured.
    """
    project_id = project_with_audio["project_id"]
    media_id = project_with_audio["media_id"]

    with patch.object(settings, "OPENAI_API_KEY", None):
        resp = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/transcribe")

    assert resp.status_code == 400
    data = resp.json()
    assert data["success"] is False
    assert data["error"]["code"] == "MISSING_OPENAI_API_KEY"
    assert "OPENAI_API_KEY" in data["error"]["message"]


def test_transcription_invalid_project(client: TestClient):
    """
    Scenario 5: 404 when project does not exist.
    """
    with patch.object(settings, "OPENAI_API_KEY", "sk-mock-key"):
        resp = client.post("/api/v1/projects/PROJ-NONEXISTENT/media/MEDIA-123/transcribe")

    assert resp.status_code == 404
    data = resp.json()
    assert data["success"] is False
    assert data["error"]["code"] in ("PROJECT_NOT_FOUND", "NOT_FOUND")


def test_transcription_invalid_media(client: TestClient, project_with_audio: dict):
    """
    Scenario 6: 404 when media does not exist in project.
    """
    project_id = project_with_audio["project_id"]
    with patch.object(settings, "OPENAI_API_KEY", "sk-mock-key"):
        resp = client.post(f"/api/v1/projects/{project_id}/media/MEDIA-NONEXISTENT/transcribe")

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "MEDIA_NOT_FOUND"


def test_transcription_wrong_media_type(client: TestClient, project_with_audio: dict):
    """
    Scenario 7: 400 when media is not extracted audio (e.g., source_video or face_reference).
    """
    project_id = project_with_audio["project_id"]
    db = SessionLocal()
    try:
        video_media = MediaFile(
            id="MEDIA-VIDEO-TEST-002",
            project_id=project_id,
            file_type="source_video",
            original_filename="sample.mp4",
            stored_filename="stored.mp4",
            file_path=f"projects/{project_id}/source/stored.mp4",
            mime_type="video/mp4",
            file_size=1024,
        )
        db.add(video_media)
        db.commit()
    finally:
        db.close()

    with patch.object(settings, "OPENAI_API_KEY", "sk-mock-key"):
        resp = client.post(f"/api/v1/projects/{project_id}/media/MEDIA-VIDEO-TEST-002/transcribe")

    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "INVALID_MEDIA_TYPE"


def test_transcription_missing_physical_file(client: TestClient, project_with_audio: dict):
    """
    Scenario 8: 404 when physical audio file is missing on disk.
    """
    project_id = project_with_audio["project_id"]
    audio_path = project_with_audio["audio_path"]
    # Temporarily remove physical file
    if audio_path.exists():
        audio_path.unlink()

    with patch.object(settings, "OPENAI_API_KEY", "sk-mock-key"):
        resp = client.post(f"/api/v1/projects/{project_id}/media/MEDIA-AUDIO-TEST-001/transcribe")

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "AUDIO_FILE_NOT_FOUND"


def test_transcription_openai_auth_failure(client: TestClient, project_with_audio: dict):
    """
    Scenario 9: 401 when OpenAI authentication fails.
    """
    project_id = project_with_audio["project_id"]
    media_id = project_with_audio["media_id"]

    req = httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")
    res = httpx.Response(401, request=req)
    auth_error = AuthenticationError(message="Incorrect API key provided.", response=res, body={"error": {"message": "Invalid key"}})

    with patch.object(settings, "OPENAI_API_KEY", "sk-invalid-key"), \
         patch("app.services.transcription.OpenAI") as mock_openai_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.audio.transcriptions.create.side_effect = auth_error
        mock_openai_cls.return_value = mock_client_instance

        resp = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/transcribe")

    assert resp.status_code == 401
    data = resp.json()
    assert data["success"] is False
    assert data["error"]["code"] == "OPENAI_AUTH_ERROR"


def test_transcription_rate_limit_handling(client: TestClient, project_with_audio: dict):
    """
    Scenario 10: 429 when OpenAI rate limit or quota is exceeded.
    """
    project_id = project_with_audio["project_id"]
    media_id = project_with_audio["media_id"]

    req = httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")
    res = httpx.Response(429, request=req)
    rate_error = RateLimitError(message="Rate limit exceeded.", response=res, body={"error": {"message": "Rate limit"}})

    with patch.object(settings, "OPENAI_API_KEY", "sk-mock-key"), \
         patch("app.services.transcription.OpenAI") as mock_openai_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.audio.transcriptions.create.side_effect = rate_error
        mock_openai_cls.return_value = mock_client_instance

        resp = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/transcribe")

    assert resp.status_code == 429
    data = resp.json()
    assert data["success"] is False
    assert data["error"]["code"] == "OPENAI_RATE_LIMIT"


def test_transcription_db_persistence_and_retrieval(client: TestClient, project_with_audio: dict):
    """
    Scenario 11 & 12: Transcripts persist correctly to SQLite and are returned by GET /api/v1/projects/{project_id}.
    """
    project_id = project_with_audio["project_id"]
    media_id = project_with_audio["media_id"]

    mock_segments = [
        MockSegment(0, 0.0, 1.5, "First line of song"),
        MockSegment(1, 1.5, 3.2, "Second line of song"),
    ]
    mock_resp = MockVerboseTranscription(
        text="First line of song Second line of song",
        language="en",
        segments=mock_segments,
    )

    with patch.object(settings, "OPENAI_API_KEY", "sk-mock-key"), \
         patch("app.services.transcription.OpenAI") as mock_openai_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.audio.transcriptions.create.return_value = mock_resp
        mock_openai_cls.return_value = mock_client_instance

        transcribe_resp = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/transcribe")

    assert transcribe_resp.status_code == 200
    transcript_id = transcribe_resp.json()["transcript"]["id"]

    # 1. Direct DB verification
    db = SessionLocal()
    try:
        t_row = db.query(Transcript).filter(Transcript.id == transcript_id).first()
        assert t_row is not None
        assert t_row.project_id == project_id
        assert t_row.audio_media_id == media_id
        assert t_row.language == "en"
        assert t_row.full_text == "First line of song Second line of song"

        segments_in_db = db.query(TranscriptSegment).filter(TranscriptSegment.transcript_id == transcript_id).all()
        assert len(segments_in_db) == 2
        assert segments_in_db[0].text == "First line of song"
        assert segments_in_db[1].text == "Second line of song"
    finally:
        db.close()

    # 2. Project detail retrieval verification
    get_resp = client.get(f"/api/v1/projects/{project_id}")
    assert get_resp.status_code == 200
    proj_data = get_resp.json()["project"]
    assert "transcripts" in proj_data
    assert len(proj_data["transcripts"]) >= 1
    found_transcript = next((t for t in proj_data["transcripts"] if t["id"] == transcript_id), None)
    assert found_transcript is not None
    assert found_transcript["full_text"] == "First line of song Second line of song"
    assert len(found_transcript["segments"]) == 2
