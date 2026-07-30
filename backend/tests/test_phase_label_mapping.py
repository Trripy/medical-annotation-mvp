from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import ResearchPhaseLabel, ResearchPhaseSegment
from app.schemas.research_phase import (
    CreateResearchPhaseLabelMappingProfileRequest,
    DuplicateResearchPhaseLabelMappingProfileRequest,
    MergeResearchPhaseMappingClassesRequest,
    UnmergeResearchPhaseMappingTargetRequest,
)
from app.services.phase_label_mapping import (
    create_mapping_profile,
    duplicate_mapping_profile,
    merge_mapping_classes,
    publish_mapping_profile,
    unmerge_mapping_target,
)
from app.services.research_phase_export_service import build_phase_export_filename, build_phase_json_export
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data
from tests.test_research_phase_exports import add_segment, create_annotation_set, update_video


@pytest.fixture()
def phase_mapping_context(tmp_path):
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        yield session_factory, seeded
    finally:
        engine.dispose()


def test_identity_mapping_profile_maps_each_source_label_once(phase_mapping_context) -> None:
    session_factory, seeded = phase_mapping_context
    with session_factory() as db:
        profile = create_mapping_profile(
            db,
            seeded.active_default_protocol_id,
            CreateResearchPhaseLabelMappingProfileRequest(
                name="Cataract LMM",
                initialize_identity_mapping=True,
            ),
        )

    assert profile.source_label_count == 3
    assert profile.target_count == 3
    assert profile.unmapped_label_count == 0
    assert sorted(len(target.source_labels) for target in profile.targets) == [1, 1, 1]


def test_merge_and_unmerge_classes_do_not_modify_original_labels_or_segments(phase_mapping_context) -> None:
    session_factory, seeded = phase_mapping_context
    with session_factory() as db:
        labels_before = db.scalars(select(ResearchPhaseLabel).order_by(ResearchPhaseLabel.id)).all()
        segments_before = db.scalars(select(ResearchPhaseSegment).order_by(ResearchPhaseSegment.id)).all()
        label_snapshot = [(label.id, label.key, label.name) for label in labels_before]
        segment_snapshot = [(segment.id, segment.phase_label_id, segment.start_frame, segment.end_frame_exclusive) for segment in segments_before]
        profile = create_mapping_profile(
            db,
            seeded.active_default_protocol_id,
            CreateResearchPhaseLabelMappingProfileRequest(name="Merge draft"),
        )
        merged = merge_mapping_classes(
            db,
            profile.id,
            MergeResearchPhaseMappingClassesRequest(
                source_label_ids=[
                    seeded.active_default_label_ids["idle"],
                    seeded.active_default_label_ids["viscoelastic"],
                ],
                target_key="idle-or-viscoelastic",
                target_name="Idle/Viscoelastic Injection",
                target_color="#0ea5e9",
            ),
        )

        assert merged.target_count == 2
        merged_target = next(target for target in merged.targets if len(target.source_labels) == 2)
        unmerged = unmerge_mapping_target(
            db,
            merged.id,
            UnmergeResearchPhaseMappingTargetRequest(target_id=merged_target.id),
        )
        labels_after = db.scalars(select(ResearchPhaseLabel).order_by(ResearchPhaseLabel.id)).all()
        segments_after = db.scalars(select(ResearchPhaseSegment).order_by(ResearchPhaseSegment.id)).all()

    assert unmerged.target_count == 3
    assert [(label.id, label.key, label.name) for label in labels_after] == label_snapshot
    assert [(segment.id, segment.phase_label_id, segment.start_frame, segment.end_frame_exclusive) for segment in segments_after] == segment_snapshot


def test_published_profile_is_not_mutable_but_can_be_duplicated(phase_mapping_context) -> None:
    session_factory, seeded = phase_mapping_context
    with session_factory() as db:
        profile = create_mapping_profile(
            db,
            seeded.active_default_protocol_id,
            CreateResearchPhaseLabelMappingProfileRequest(name="Publish me"),
        )
        published = publish_mapping_profile(db, profile.id)
        with pytest.raises(HTTPException):
            merge_mapping_classes(
                db,
                profile.id,
                MergeResearchPhaseMappingClassesRequest(
                    source_label_ids=[
                        seeded.active_default_label_ids["idle"],
                        seeded.active_default_label_ids["viscoelastic"],
                    ],
                    target_key="blocked",
                    target_name="Blocked",
                    target_color="#64748b",
                ),
            )
        duplicate = duplicate_mapping_profile(
            db,
            published.id,
            DuplicateResearchPhaseLabelMappingProfileRequest(name="Publish me draft"),
        )

    assert published.status == "published"
    assert duplicate.status == "draft"
    assert duplicate.target_count == published.target_count


def test_mapped_export_merges_only_adjacent_same_target_segments(phase_mapping_context) -> None:
    session_factory, seeded = phase_mapping_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="mapping_export")
    update_video(session_factory, seeded.video_id, name="前后联合 赵平广 男 57岁_cleaned_trimmed.mp4", frame_count=240)
    segment_a = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=0,
        end_frame_exclusive=50,
        notes="第一段备注",
    )
    segment_b = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["viscoelastic"],
        start_frame=50,
        end_frame_exclusive=100,
        notes="第二段\n多行备注",
    )
    segment_c = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=100,
        end_frame_exclusive=125,
    )
    segment_d = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=130,
        end_frame_exclusive=160,
    )

    with session_factory() as db:
        profile = create_mapping_profile(
            db,
            seeded.active_default_protocol_id,
            CreateResearchPhaseLabelMappingProfileRequest(name="cataract-lmm-merged"),
        )
        profile = merge_mapping_classes(
            db,
            profile.id,
            MergeResearchPhaseMappingClassesRequest(
                source_label_ids=[
                    seeded.active_default_label_ids["idle"],
                    seeded.active_default_label_ids["viscoelastic"],
                ],
                target_key="idle-or-viscoelastic",
                target_name="Idle/Viscoelastic Injection",
                target_color="#0ea5e9",
            ),
        )
        profile = publish_mapping_profile(db, profile.id)
        export = build_phase_json_export(db, annotation_set_id, mapping_profile_id=profile.id)

    assert export.filename == "前后联合 赵平广 男 57岁_cleaned_trimmed__cataract-lmm-merged.json"
    assert [segment["start_frame"] for segment in export.payload["segments"]] == [0, 100, 130]
    assert [segment["end_frame_exclusive"] for segment in export.payload["segments"]] == [100, 125, 160]
    assert export.payload["segments"][0]["source_segment_ids"] == [segment_a, segment_b]
    assert export.payload["segments"][0]["source_segments"] == [
        {
            "segment_id": segment_a,
            "source_label_id": seeded.active_default_label_ids["idle"],
            "source_label_name": "Idle",
            "start_frame": 0,
            "end_frame_exclusive": 50,
            "notes": "第一段备注",
        },
        {
            "segment_id": segment_b,
            "source_label_id": seeded.active_default_label_ids["viscoelastic"],
            "source_label_name": "Viscoelastic Injection",
            "start_frame": 50,
            "end_frame_exclusive": 100,
            "notes": "第二段\n多行备注",
        },
    ]
    assert export.payload["segments"][0]["notes"] == [
        {"source_segment_id": segment_a, "note": "第一段备注"},
        {"source_segment_id": segment_b, "note": "第二段\n多行备注"},
    ]
    assert export.payload["segments"][1]["source_segment_ids"] == [segment_c]
    assert export.payload["segments"][2]["source_segment_ids"] == [segment_d]
    assert export.payload["mapping_statistics"]["frame_conservation_passed"] is True
    assert export.payload["manifest"]["mapping_mode"] == "profile"
    assert "file_path" not in str(export.payload)


@pytest.mark.parametrize(
    ("display_name", "profile_key", "expected"),
    [
        ("case001.MP4", None, "case001.json"),
        ("前后联合 赵平广 男 57岁_cleaned_trimmed.mp4", None, "前后联合 赵平广 男 57岁_cleaned_trimmed.json"),
        ("case001", "cataract-lmm-merged", "case001__cataract-lmm-merged.json"),
        ('bad/name:?".mp4', None, "bad_name___.json"),
        ("\n", None, "research-video-12.json"),
        ("CON.mp4", None, "CON_file.json"),
    ],
)
def test_phase_export_filename_rules(display_name: str, profile_key: str | None, expected: str) -> None:
    assert build_phase_export_filename(
        video_display_name=display_name,
        video_id=12,
        mapping_profile_key=profile_key,
        mapping_mode="profile" if profile_key else "original",
    ) == expected
