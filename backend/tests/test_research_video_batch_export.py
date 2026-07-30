from __future__ import annotations

import json
from zipfile import ZipFile

import pytest
from fastapi import HTTPException

from app.schemas.research import (
    ResearchVideoBatchExportItemRequest,
    ResearchVideoBatchExportRequest,
    ResearchVideoBatchPhaseExportRequest,
)
from app.schemas.research_phase import CreateResearchPhaseLabelMappingProfileRequest, MergeResearchPhaseMappingClassesRequest
from app.services.phase_label_mapping import create_mapping_profile, merge_mapping_classes, publish_mapping_profile
from app.services.research_video_checklist import build_video_batch_export, preview_video_batch_export, remove_batch_export_file
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data


def test_batch_export_preview_rejects_empty_and_foreign_annotation_set(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        with session_factory() as db:
            empty = preview_video_batch_export(db, ResearchVideoBatchExportRequest(items=[]))
            invalid = preview_video_batch_export(
                db,
                ResearchVideoBatchExportRequest(
                    items=[
                        ResearchVideoBatchExportItemRequest(
                            video_id=9999,
                            include_trim_info=False,
                            phase_exports=[ResearchVideoBatchPhaseExportRequest(annotation_set_id=seeded.set_reader_id)],
                        )
                    ]
                ),
            )

        assert empty.invalid_items
        assert invalid.invalid_items
    finally:
        engine.dispose()


def test_batch_export_zip_contains_only_selected_json_csv_and_manifest(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        payload = ResearchVideoBatchExportRequest(
            batch_name="白内障阶段标签第一批",
            items=[
                ResearchVideoBatchExportItemRequest(
                    video_id=seeded.video_id,
                    include_trim_info=True,
                    phase_exports=[ResearchVideoBatchPhaseExportRequest(annotation_set_id=seeded.set_reviewer_id)],
                )
            ],
        )
        with session_factory() as db:
            preview = preview_video_batch_export(db, payload)
            export_file = build_video_batch_export(db, payload)

        assert preview.video_count == 1
        assert preview.trim_export_count == 1
        assert preview.phase_export_count == 1
        assert export_file.filename == "白内障阶段标签第一批.zip"
        assert "filename*" in export_file.headers["Content-Disposition"]
        with ZipFile(export_file.path) as archive:
            names = archive.namelist()
            assert "manifest.json" in names
            assert "summary.csv" in names
            assert any(name.endswith("/trim.json") for name in names)
            assert any(name.endswith(".json") and "/phase/" in name for name in names)
            assert not any(name.endswith(".mp4") for name in names)
            assert not any("file_path" in archive.read(name).decode("utf-8", errors="ignore") for name in names if name.endswith(".json"))
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            assert manifest["video_count"] == 1
            summary = archive.read("summary.csv")
            assert summary.startswith(b"\xef\xbb\xbf")
        remove_batch_export_file(export_file.path)
        assert not export_file.path.exists()
    finally:
        engine.dispose()


def test_batch_export_reuses_mapped_phase_export_and_rejects_draft_profiles(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        with session_factory() as db:
            draft = create_mapping_profile(
                db,
                seeded.active_default_protocol_id,
                CreateResearchPhaseLabelMappingProfileRequest(name="Draft map"),
            )
            draft_preview = preview_video_batch_export(
                db,
                ResearchVideoBatchExportRequest(
                    items=[
                        ResearchVideoBatchExportItemRequest(
                            video_id=seeded.video_id,
                            phase_exports=[ResearchVideoBatchPhaseExportRequest(annotation_set_id=seeded.set_reviewer_id, mapping_profile_id=draft.id)],
                        )
                    ]
                ),
            )
            merged = merge_mapping_classes(
                db,
                draft.id,
                MergeResearchPhaseMappingClassesRequest(
                    source_label_ids=[
                        seeded.active_default_label_ids["idle"],
                        seeded.active_default_label_ids["viscoelastic"],
                    ],
                    target_key="idle-viscoelastic",
                    target_name="Idle/Viscoelastic",
                    target_color="#0ea5e9",
                ),
            )
            published = publish_mapping_profile(db, merged.id)
            payload = ResearchVideoBatchExportRequest(
                items=[
                    ResearchVideoBatchExportItemRequest(
                        video_id=seeded.video_id,
                        phase_exports=[ResearchVideoBatchPhaseExportRequest(annotation_set_id=seeded.set_reviewer_id, mapping_profile_id=published.id)],
                    )
                ]
            )
            export_file = build_video_batch_export(db, payload)

        assert draft_preview.invalid_items
        with ZipFile(export_file.path) as archive:
            phase_names = [name for name in archive.namelist() if "/phase/" in name]
            assert phase_names
            payload_json = json.loads(archive.read(phase_names[0]).decode("utf-8"))
            assert payload_json["manifest"]["mapping_mode"] == "profile"
            assert payload_json["mapping_statistics"]["frame_conservation_passed"] is True
        remove_batch_export_file(export_file.path)
    finally:
        engine.dispose()


def test_batch_export_raises_422_when_invalid_items_are_exported(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seed_phase_data(session_factory)
    try:
        with session_factory() as db:
            with pytest.raises(HTTPException) as exc_info:
                build_video_batch_export(
                    db,
                    ResearchVideoBatchExportRequest(
                        items=[
                            ResearchVideoBatchExportItemRequest(
                                video_id=12345,
                                include_trim_info=True,
                            )
                        ]
                    ),
                )
        assert exc_info.value.status_code == 422
    finally:
        engine.dispose()
