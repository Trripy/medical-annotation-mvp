from __future__ import annotations

import hashlib
import json
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.models import ResearchVideo, ResearchVideoAnnotation, ResearchVideoFrame, ResearchVideoLabel
from app.services.research_video_trim import (
    ResearchVideoTrimError,
    get_linked_video_data,
    minimum_keep_frames,
    trim_research_video,
    validate_trim_range,
    _run_ffmpeg_trim,
    _video_encoder_args,
)


FFMPEG = Path("/data1/zhangyuzhu/code/autoannotate/conda_envs/sam/bin/ffmpeg")


@pytest.fixture()
def trim_db_context(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    original_local_storage_root = settings.local_storage_root
    original_ffmpeg = settings.research_video_ffmpeg_binary
    settings.local_storage_root = str(tmp_path / "storage")
    settings.research_video_ffmpeg_binary = str(FFMPEG)
    try:
        yield SessionLocal, Path(settings.local_storage_root)
    finally:
        settings.local_storage_root = original_local_storage_root
        settings.research_video_ffmpeg_binary = original_ffmpeg
        Base.metadata.drop_all(engine)
        engine.dispose()


def _make_synthetic_video(path: Path, *, seconds: int = 3, fps: int = 25, audio: bool = False) -> None:
    if not FFMPEG.is_file():
        pytest.skip("ffmpeg is not available in the test environment")
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(FFMPEG),
        "-hide_banner",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={seconds}:size=160x120:rate={fps}",
    ]
    if audio:
        command.extend(["-f", "lavfi", "-i", f"sine=frequency=1000:duration={seconds}", "-shortest"])
    command.extend(["-c:v", "mpeg4", "-q:v", "2", "-pix_fmt", "yuv420p"])
    if audio:
        command.extend(["-c:a", "aac"])
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True, text=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _probe_video(path: Path) -> dict:
    completed = subprocess.run(
        [
            str(FFMPEG.with_name("ffprobe")),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,nb_frames",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)["streams"][0]


def _create_source_video(session_factory: sessionmaker, storage_root: Path, *, audio: bool = False) -> ResearchVideo:
    source_path = storage_root / "raw" / ("source_audio.mp4" if audio else "source.mp4")
    _make_synthetic_video(source_path, audio=audio)
    with session_factory() as db:
        video = ResearchVideo(
            name="Source",
            original_filename=source_path.name,
            file_path=str(source_path),
            width=160,
            height=120,
            fps=25.0,
            frame_count=75,
            duration_ms=3000,
            status="ready",
        )
        db.add(video)
        db.flush()
        label = ResearchVideoLabel(video_id=video.id, name="default", color="#22c55e", shape_type="polygon", sort_order=0)
        db.add(label)
        db.flush()
        for index in range(75):
            db.add(
                ResearchVideoFrame(
                    video_id=video.id,
                    frame_index=index,
                    timestamp_ms=index * 40,
                    filename=f"{index:06d}.jpg",
                    file_path=str(storage_root / str(video.id) / "frames" / f"{index:06d}.jpg"),
                    width=160,
                    height=120,
                )
            )
        db.commit()
        db.refresh(video)
        return video


def test_trim_range_validation_rejects_invalid_short_and_full_ranges(trim_db_context) -> None:
    session_factory, storage_root = trim_db_context
    source = _create_source_video(session_factory, storage_root)

    with pytest.raises(ResearchVideoTrimError):
        validate_trim_range(source, -1, 20)
    with pytest.raises(ResearchVideoTrimError):
        validate_trim_range(source, 20, 20)
    with pytest.raises(ResearchVideoTrimError):
        validate_trim_range(source, 0, source.frame_count)
    with pytest.raises(ResearchVideoTrimError):
        validate_trim_range(source, 10, 20)
    assert minimum_keep_frames(source) == 25


def test_trim_requires_acknowledgement_when_frame_annotations_exist(trim_db_context) -> None:
    session_factory, storage_root = trim_db_context
    source = _create_source_video(session_factory, storage_root)
    original_hash = _sha256(Path(source.file_path))

    with session_factory() as db:
        video = db.get(ResearchVideo, source.id)
        label = video.labels[0]
        frame = video.frames[0]
        db.add(
            ResearchVideoAnnotation(
                video_id=video.id,
                frame_id=frame.id,
                frame_index=0,
                label_id=label.id,
                shape_type="rectangle",
                points=[[0, 0], [10, 10]],
                visible=True,
                z_order=0,
            )
        )
        db.commit()
        linked = get_linked_video_data(db, source.id)
        assert linked.frame_annotation_count == 1
        with pytest.raises(ResearchVideoTrimError):
            trim_research_video(
                db=db,
                source_video=video,
                start_frame=10,
                end_frame_exclusive=60,
                display_name="trimmed.mp4",
                acknowledge_annotations_not_copied=False,
                storage_root=storage_root,
            )

    assert _sha256(Path(source.file_path)) == original_hash


def test_trim_creates_new_video_with_exact_frame_count_and_no_annotations(trim_db_context) -> None:
    session_factory, storage_root = trim_db_context
    source = _create_source_video(session_factory, storage_root)
    original_hash = _sha256(Path(source.file_path))

    with session_factory() as db:
        source_video = db.get(ResearchVideo, source.id)
        trimmed, warnings = trim_research_video(
            db=db,
            source_video=source_video,
            start_frame=25,
            end_frame_exclusive=60,
            display_name="../unsafe/name.mov",
            acknowledge_annotations_not_copied=True,
            storage_root=storage_root,
        )
        assert warnings == []
        assert trimmed.id != source.id
        assert trimmed.status == "ready"
        assert trimmed.origin_type == "trimmed"
        assert trimmed.source_video_id == source.id
        assert trimmed.trim_start_frame == 25
        assert trimmed.trim_end_frame_exclusive == 60
        assert trimmed.frame_count == 35
        assert len(trimmed.frames) == 35
        assert trimmed.original_filename == "name.mp4"
        assert Path(trimmed.file_path).is_file()
        probed = _probe_video(Path(trimmed.file_path))
        assert probed["codec_name"] == "h264"
        assert probed["pix_fmt"] == "yuv420p"
        assert Path(trimmed.file_path) != Path(source.file_path)
        assert Path(trimmed.thumbnail_path).is_file()
        assert db.query(ResearchVideoAnnotation).filter(ResearchVideoAnnotation.video_id == trimmed.id).count() == 0

    assert _sha256(Path(source.file_path)) == original_hash


def test_trim_audio_source_succeeds_and_keeps_exact_frame_count(trim_db_context) -> None:
    session_factory, storage_root = trim_db_context
    source = _create_source_video(session_factory, storage_root, audio=True)

    with session_factory() as db:
        trimmed, _warnings = trim_research_video(
            db=db,
            source_video=db.get(ResearchVideo, source.id),
            start_frame=25,
            end_frame_exclusive=55,
            display_name="audio_trimmed.mp4",
            acknowledge_annotations_not_copied=True,
            storage_root=storage_root,
        )
        assert trimmed.frame_count == 30
        assert trimmed.duration_ms == 1200
        assert Path(trimmed.file_path).is_file()


def test_video_encoder_args_uses_only_supported_h264_encoders(monkeypatch) -> None:
    def fake_run(command, **_kwargs):
        assert command[-1] == "-encoders"
        return SimpleNamespace(returncode=0, stdout="V....D libopenh264\nV.S..D mpeg4\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _video_encoder_args(str(FFMPEG)) == ["-c:v", "libopenh264", "-b:v", "6M"]


def test_video_encoder_args_rejects_when_h264_encoder_is_unavailable(monkeypatch) -> None:
    def fake_run(command, **_kwargs):
        assert command[-1] == "-encoders"
        return SimpleNamespace(returncode=0, stdout="V.S..D mpeg4\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ResearchVideoTrimError, match="No supported H.264 encoder"):
        _video_encoder_args(str(FFMPEG))


def test_ffmpeg_select_filter_uses_exclusive_end_minus_one(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.services.research_video_trim._source_has_audio", lambda *_args: False)
    monkeypatch.setattr("app.services.research_video_trim._video_encoder_args", lambda *_args: ["-c:v", "libopenh264", "-b:v", "6M"])
    monkeypatch.setattr("app.services.research_video_trim._validate_trimmed_container", lambda **_kwargs: None)
    monkeypatch.setattr(subprocess, "run", fake_run)

    _run_ffmpeg_trim(
        ffmpeg_binary=str(FFMPEG),
        source_path=tmp_path / "source.mp4",
        part_path=tmp_path / "out.mp4.part",
        start_frame=10,
        end_frame_exclusive=30,
        fps=25.0,
    )

    ffmpeg_command = commands[0]
    assert ffmpeg_command[ffmpeg_command.index("-vf") + 1] == "select=between(n\\,10\\,29),setpts=PTS-STARTPTS"
