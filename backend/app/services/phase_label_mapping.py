from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Iterable, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ResearchPhaseAnnotationSet,
    ResearchPhaseLabel,
    ResearchPhaseLabelMappingProfile,
    ResearchPhaseLabelMappingRule,
    ResearchPhaseLabelMappingTarget,
    ResearchPhaseProtocol,
)
from app.schemas.research_phase import (
    CreateResearchPhaseLabelMappingProfileRequest,
    DuplicateResearchPhaseLabelMappingProfileRequest,
    MergeResearchPhaseMappingClassesRequest,
    ResearchPhaseLabelMappingProfileDetail,
    ResearchPhaseLabelMappingProfileSummary,
    ResearchPhaseLabelMappingSourceLabelResponse,
    ResearchPhaseLabelMappingTargetResponse,
    ResearchPhaseSegmentResponse,
    UnmergeResearchPhaseMappingTargetRequest,
    UpdateResearchPhaseLabelMappingProfileRequest,
)

PHASE_MAPPING_STATUS_DRAFT = "draft"
PHASE_MAPPING_STATUS_PUBLISHED = "published"
PHASE_MAPPING_STATUS_ARCHIVED = "archived"
SAFE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
T = TypeVar("T")


@dataclass(frozen=True)
class MappedPhaseSegment:
    target_id: int
    target_key: str
    target_name: str
    target_color: str
    start_frame: int
    end_frame_exclusive: int
    source_segment_ids: list[int]
    source_label_ids: list[int]
    source_label_names: list[str]
    source_segments: list[dict[str, Any]]


def list_mapping_profiles(
    db: Session,
    protocol_id: int,
    *,
    include_archived: bool = False,
) -> list[ResearchPhaseLabelMappingProfileSummary]:
    _get_protocol(db, protocol_id)
    statement = _profile_select().where(ResearchPhaseLabelMappingProfile.protocol_id == protocol_id)
    if not include_archived:
        statement = statement.where(ResearchPhaseLabelMappingProfile.status != PHASE_MAPPING_STATUS_ARCHIVED)
    profiles = db.scalars(statement.order_by(ResearchPhaseLabelMappingProfile.created_at.desc())).unique().all()
    return [_profile_to_summary(profile) for profile in profiles]


def create_mapping_profile(
    db: Session,
    protocol_id: int,
    payload: CreateResearchPhaseLabelMappingProfileRequest,
) -> ResearchPhaseLabelMappingProfileDetail:
    protocol = _get_protocol(db, protocol_id)
    profile = ResearchPhaseLabelMappingProfile(
        protocol_id=protocol.id,
        name=payload.name.strip(),
        description=payload.description,
        version=payload.version,
        status=PHASE_MAPPING_STATUS_DRAFT,
        created_by_id=payload.created_by_id,
    )
    db.add(profile)
    db.flush()
    if payload.initialize_identity_mapping:
        _create_identity_mapping_targets(db, profile, protocol.labels)
    db.commit()
    return get_mapping_profile(db, profile.id)


def get_mapping_profile(db: Session, profile_id: int) -> ResearchPhaseLabelMappingProfileDetail:
    profile = _get_profile(db, profile_id)
    return _profile_to_detail(profile)


def update_mapping_profile(
    db: Session,
    profile_id: int,
    payload: UpdateResearchPhaseLabelMappingProfileRequest,
) -> ResearchPhaseLabelMappingProfileDetail:
    profile = _get_profile(db, profile_id)
    _require_draft(profile)
    if payload.name is not None:
        profile.name = payload.name.strip()
    if payload.description is not None:
        profile.description = payload.description
    db.commit()
    return get_mapping_profile(db, profile.id)


def merge_mapping_classes(
    db: Session,
    profile_id: int,
    payload: MergeResearchPhaseMappingClassesRequest,
) -> ResearchPhaseLabelMappingProfileDetail:
    profile = _get_profile(db, profile_id)
    _require_draft(profile)
    source_label_ids = _deduplicate_ids(payload.source_label_ids)
    if len(source_label_ids) < 2:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Select at least two source labels.")
    _validate_target_key(payload.target_key)
    if any(target.key == payload.target_key for target in profile.targets):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Target key already exists in this profile.")

    source_labels = _get_source_labels_for_profile(db, profile, source_label_ids)
    max_order = max((target.order_index for target in profile.targets), default=-1)
    target = ResearchPhaseLabelMappingTarget(
        profile_id=profile.id,
        key=payload.target_key,
        name=payload.target_name.strip(),
        color=payload.target_color,
        order_index=max_order + 1,
    )
    db.add(target)
    db.flush()

    rules_by_label_id = {rule.source_label_id: rule for rule in profile.rules}
    previous_target_ids = set()
    for label in source_labels:
        rule = rules_by_label_id.get(label.id)
        if rule is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Mapping profile is incomplete.")
        previous_target_ids.add(rule.target_id)
        rule.target_id = target.id

    db.flush()
    _delete_unreferenced_targets(db, profile.id, previous_target_ids)
    db.commit()
    return get_mapping_profile(db, profile.id)


def unmerge_mapping_target(
    db: Session,
    profile_id: int,
    payload: UnmergeResearchPhaseMappingTargetRequest,
) -> ResearchPhaseLabelMappingProfileDetail:
    profile = _get_profile(db, profile_id)
    _require_draft(profile)
    target = next((candidate for candidate in profile.targets if candidate.id == payload.target_id), None)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping target not found.")
    target_rules = [rule for rule in profile.rules if rule.target_id == target.id]
    if len(target_rules) <= 1:
        return _profile_to_detail(profile)

    max_order = max((candidate.order_index for candidate in profile.targets), default=-1)
    for offset, rule in enumerate(sorted(target_rules, key=lambda item: item.source_label.display_order)):
        label = rule.source_label
        identity_target = ResearchPhaseLabelMappingTarget(
            profile_id=profile.id,
            key=label.key,
            name=label.name,
            color=label.color,
            order_index=max_order + offset + 1,
        )
        db.add(identity_target)
        db.flush()
        rule.target_id = identity_target.id
    db.flush()
    db.execute(delete(ResearchPhaseLabelMappingTarget).where(ResearchPhaseLabelMappingTarget.id == target.id))
    db.commit()
    return get_mapping_profile(db, profile.id)


def publish_mapping_profile(db: Session, profile_id: int) -> ResearchPhaseLabelMappingProfileDetail:
    profile = _get_profile(db, profile_id)
    _require_draft(profile)
    validate_mapping_profile(profile)
    profile.status = PHASE_MAPPING_STATUS_PUBLISHED
    db.commit()
    return get_mapping_profile(db, profile.id)


def duplicate_mapping_profile(
    db: Session,
    profile_id: int,
    payload: DuplicateResearchPhaseLabelMappingProfileRequest,
) -> ResearchPhaseLabelMappingProfileDetail:
    source = _get_profile(db, profile_id)
    duplicate = ResearchPhaseLabelMappingProfile(
        protocol_id=source.protocol_id,
        name=payload.name.strip(),
        description=payload.description,
        version=source.version + 1,
        status=PHASE_MAPPING_STATUS_DRAFT,
        created_by_id=source.created_by_id,
    )
    db.add(duplicate)
    db.flush()
    target_id_map: dict[int, int] = {}
    for target in source.targets:
        copied_target = ResearchPhaseLabelMappingTarget(
            profile_id=duplicate.id,
            key=target.key,
            name=target.name,
            color=target.color,
            order_index=target.order_index,
        )
        db.add(copied_target)
        db.flush()
        target_id_map[target.id] = copied_target.id
    for rule in source.rules:
        db.add(
            ResearchPhaseLabelMappingRule(
                profile_id=duplicate.id,
                source_label_id=rule.source_label_id,
                target_id=target_id_map[rule.target_id],
            )
        )
    db.commit()
    return get_mapping_profile(db, duplicate.id)


def archive_mapping_profile(db: Session, profile_id: int) -> ResearchPhaseLabelMappingProfileDetail:
    profile = _get_profile(db, profile_id)
    if profile.status == PHASE_MAPPING_STATUS_DRAFT:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Draft profiles can be deleted, not archived.")
    profile.status = PHASE_MAPPING_STATUS_ARCHIVED
    db.commit()
    return get_mapping_profile(db, profile.id)


def validate_mapping_profile(profile: ResearchPhaseLabelMappingProfile) -> None:
    labels = list(profile.protocol.labels)
    rules = list(profile.rules)
    targets = list(profile.targets)
    label_ids = {label.id for label in labels}
    rule_label_ids = [rule.source_label_id for rule in rules]
    if len(rule_label_ids) != len(set(rule_label_ids)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A source label is mapped more than once.")
    if set(rule_label_ids) != label_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Mapping profile must cover every source label exactly once.")
    target_ids = {target.id for target in targets}
    for rule in rules:
        if rule.target_id not in target_ids:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Mapping rule references an invalid target.")
    used_target_ids = {rule.target_id for rule in rules}
    if used_target_ids != target_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Every mapping target must have at least one source label.")
    if any(not target.name.strip() for target in targets):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Mapping target names cannot be blank.")


def resolve_mapping_rules(
    db: Session,
    profile_id: int,
    *,
    protocol_id: int | None = None,
    require_published: bool = False,
) -> ResearchPhaseLabelMappingProfile:
    profile = _get_profile(db, profile_id)
    if protocol_id is not None and profile.protocol_id != protocol_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Mapping profile does not belong to this protocol.")
    if require_published and profile.status != PHASE_MAPPING_STATUS_PUBLISHED:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only published mapping profiles can be used for export.")
    validate_mapping_profile(profile)
    return profile


def map_phase_segments(
    segments: Iterable[ResearchPhaseSegmentResponse],
    profile: ResearchPhaseLabelMappingProfile,
    *,
    frame_count: int,
) -> list[MappedPhaseSegment]:
    rule_by_label_id = {rule.source_label_id: rule for rule in profile.rules}
    target_by_id = {target.id: target for target in profile.targets}
    mapped: list[MappedPhaseSegment] = []
    for segment in sorted(segments, key=lambda item: (item.start_frame, item.id)):
        end_frame = segment.end_frame_exclusive if segment.end_frame_exclusive is not None else frame_count
        if end_frame <= segment.start_frame:
            continue
        rule = rule_by_label_id.get(segment.phase_label_id)
        if rule is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A segment label is not mapped.")
        target = target_by_id[rule.target_id]
        mapped.append(
            MappedPhaseSegment(
                target_id=target.id,
                target_key=target.key,
                target_name=target.name,
                target_color=target.color,
                start_frame=segment.start_frame,
                end_frame_exclusive=end_frame,
                source_segment_ids=[segment.id],
                source_label_ids=[segment.phase_label_id],
                source_label_names=[segment.phase_label.name],
                source_segments=[
                    {
                        "segment_id": segment.id,
                        "source_label_id": segment.phase_label_id,
                        "source_label_name": segment.phase_label.name,
                        "start_frame": segment.start_frame,
                        "end_frame_exclusive": end_frame,
                        "notes": segment.notes,
                    }
                ],
            )
        )
    return mapped


def merge_adjacent_mapped_segments(segments: Iterable[MappedPhaseSegment]) -> list[MappedPhaseSegment]:
    merged: list[MappedPhaseSegment] = []
    for segment in sorted(segments, key=lambda item: (item.start_frame, item.end_frame_exclusive, item.target_key)):
        previous = merged[-1] if merged else None
        if previous is not None and previous.target_id == segment.target_id and previous.end_frame_exclusive == segment.start_frame:
            merged[-1] = MappedPhaseSegment(
                target_id=previous.target_id,
                target_key=previous.target_key,
                target_name=previous.target_name,
                target_color=previous.target_color,
                start_frame=previous.start_frame,
                end_frame_exclusive=segment.end_frame_exclusive,
                source_segment_ids=previous.source_segment_ids + segment.source_segment_ids,
                source_label_ids=_unique_preserving_order(previous.source_label_ids + segment.source_label_ids),
                source_label_names=_unique_preserving_order(previous.source_label_names + segment.source_label_names),
                source_segments=previous.source_segments + segment.source_segments,
            )
            continue
        merged.append(segment)
    return merged


def calculate_mapping_statistics(
    source_segments: Iterable[ResearchPhaseSegmentResponse],
    mapped_segments: Iterable[MappedPhaseSegment],
    *,
    frame_count: int,
) -> dict[str, Any]:
    source_frames = sum(
        max(0, (segment.end_frame_exclusive if segment.end_frame_exclusive is not None else frame_count) - segment.start_frame)
        for segment in source_segments
    )
    mapped_frames = sum(max(0, segment.end_frame_exclusive - segment.start_frame) for segment in mapped_segments)
    return {
        "source_annotated_frames": source_frames,
        "mapped_annotated_frames": mapped_frames,
        "frame_conservation_passed": source_frames == mapped_frames,
    }


def build_mapping_export_manifest(
    profile: ResearchPhaseLabelMappingProfile | None,
    *,
    video_id: int,
    video_display_name: str,
    annotation_set: ResearchPhaseAnnotationSet,
) -> dict[str, Any]:
    base = {
        "export_type": "research_phase_annotations",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "video_id": video_id,
        "video_display_name": video_display_name,
        "annotation_set_id": annotation_set.id,
        "source_protocol_id": annotation_set.protocol_id,
        "source_protocol_name": annotation_set.protocol.name,
        "mapping_mode": "original" if profile is None else "profile",
        "frame_interval_semantics": "[start_frame, end_frame_exclusive)",
        "adjacent_mapped_segments_merged": profile is not None,
    }
    if profile is None:
        return {
            **base,
            "mapping_profile_id": None,
            "mapping_profile_name": None,
            "mapping_profile_key": None,
            "mapping_profile_version": None,
            "mapping_profile_status": None,
            "target_classes": [],
            "source_to_target_rules": [],
        }
    return {
        **base,
        "mapping_profile_id": profile.id,
        "mapping_profile_name": profile.name,
        "mapping_profile_key": profile_key(profile),
        "mapping_profile_version": profile.version,
        "mapping_profile_status": profile.status,
        "target_classes": [
            {
                "id": target.id,
                "key": target.key,
                "name": target.name,
                "color": target.color,
                "order_index": target.order_index,
            }
            for target in profile.targets
        ],
        "source_to_target_rules": [
            {
                "source_label_id": rule.source_label_id,
                "source_label_key": rule.source_label.key,
                "source_label_name": rule.source_label.name,
                "target_id": rule.target_id,
                "target_key": rule.target.key,
                "target_name": rule.target.name,
            }
            for rule in sorted(profile.rules, key=lambda item: item.source_label.display_order)
        ],
    }


def profile_key(profile: ResearchPhaseLabelMappingProfile) -> str:
    return _slugify_key(profile.name) or f"profile-{profile.id}"


def _create_identity_mapping_targets(
    db: Session,
    profile: ResearchPhaseLabelMappingProfile,
    labels: Iterable[ResearchPhaseLabel],
) -> None:
    for label in sorted(labels, key=lambda item: (item.display_order, item.id)):
        target = ResearchPhaseLabelMappingTarget(
            profile_id=profile.id,
            key=label.key,
            name=label.name,
            color=label.color,
            order_index=label.display_order,
        )
        db.add(target)
        db.flush()
        db.add(
            ResearchPhaseLabelMappingRule(
                profile_id=profile.id,
                source_label_id=label.id,
                target_id=target.id,
            )
        )


def _profile_select() -> Select[tuple[ResearchPhaseLabelMappingProfile]]:
    return select(ResearchPhaseLabelMappingProfile).options(
        selectinload(ResearchPhaseLabelMappingProfile.protocol).selectinload(ResearchPhaseProtocol.labels),
        selectinload(ResearchPhaseLabelMappingProfile.targets).selectinload(ResearchPhaseLabelMappingTarget.rules).selectinload(ResearchPhaseLabelMappingRule.source_label),
        selectinload(ResearchPhaseLabelMappingProfile.rules).selectinload(ResearchPhaseLabelMappingRule.source_label),
        selectinload(ResearchPhaseLabelMappingProfile.rules).selectinload(ResearchPhaseLabelMappingRule.target),
    )


def _get_profile(db: Session, profile_id: int) -> ResearchPhaseLabelMappingProfile:
    profile = db.scalars(_profile_select().where(ResearchPhaseLabelMappingProfile.id == profile_id)).unique().one_or_none()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase label mapping profile not found.")
    return profile


def _get_protocol(db: Session, protocol_id: int) -> ResearchPhaseProtocol:
    protocol = db.get(ResearchPhaseProtocol, protocol_id)
    if protocol is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase protocol not found.")
    return protocol


def _require_draft(profile: ResearchPhaseLabelMappingProfile) -> None:
    if profile.status != PHASE_MAPPING_STATUS_DRAFT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft mapping profiles can be modified.")


def _validate_target_key(target_key: str) -> None:
    if not SAFE_KEY_PATTERN.match(target_key):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Target key contains unsupported characters.")


def _deduplicate_ids(ids: Iterable[int]) -> list[int]:
    unique: list[int] = []
    seen: set[int] = set()
    for value in ids:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _get_source_labels_for_profile(
    db: Session,
    profile: ResearchPhaseLabelMappingProfile,
    source_label_ids: list[int],
) -> list[ResearchPhaseLabel]:
    labels = db.scalars(
        select(ResearchPhaseLabel)
        .where(ResearchPhaseLabel.protocol_id == profile.protocol_id)
        .where(ResearchPhaseLabel.id.in_(source_label_ids))
        .order_by(ResearchPhaseLabel.display_order, ResearchPhaseLabel.id)
    ).all()
    if {label.id for label in labels} != set(source_label_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="All source labels must belong to the profile protocol.")
    return labels


def _delete_unreferenced_targets(db: Session, profile_id: int, candidate_target_ids: set[int]) -> None:
    for target_id in candidate_target_ids:
        rule_count = db.scalar(
            select(func.count(ResearchPhaseLabelMappingRule.id)).where(
                ResearchPhaseLabelMappingRule.profile_id == profile_id,
                ResearchPhaseLabelMappingRule.target_id == target_id,
            )
        )
        if rule_count == 0:
            db.execute(delete(ResearchPhaseLabelMappingTarget).where(ResearchPhaseLabelMappingTarget.id == target_id))


def _profile_to_summary(profile: ResearchPhaseLabelMappingProfile) -> ResearchPhaseLabelMappingProfileSummary:
    source_label_count = len(profile.protocol.labels)
    target_count = len(profile.targets)
    mapped_label_ids = {rule.source_label_id for rule in profile.rules}
    merged_group_count = sum(1 for target in profile.targets if len(target.rules) > 1)
    return ResearchPhaseLabelMappingProfileSummary(
        id=profile.id,
        protocol_id=profile.protocol_id,
        name=profile.name,
        description=profile.description,
        version=profile.version,
        status=profile.status,
        created_by_id=profile.created_by_id,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        source_label_count=source_label_count,
        target_count=target_count,
        merged_group_count=merged_group_count,
        unmapped_label_count=max(0, source_label_count - len(mapped_label_ids)),
    )


def _profile_to_detail(profile: ResearchPhaseLabelMappingProfile) -> ResearchPhaseLabelMappingProfileDetail:
    summary = _profile_to_summary(profile)
    target_responses = []
    for target in sorted(profile.targets, key=lambda item: (item.order_index, item.id)):
        source_labels = sorted((rule.source_label for rule in target.rules), key=lambda item: (item.display_order, item.id))
        target_responses.append(
            ResearchPhaseLabelMappingTargetResponse(
                id=target.id,
                profile_id=target.profile_id,
                key=target.key,
                name=target.name,
                color=target.color,
                order_index=target.order_index,
                source_labels=[
                    ResearchPhaseLabelMappingSourceLabelResponse(
                        id=label.id,
                        key=label.key,
                        name=label.name,
                        color=label.color,
                        display_order=label.display_order,
                    )
                    for label in source_labels
                ],
            )
        )
    return ResearchPhaseLabelMappingProfileDetail(
        **summary.model_dump(mode="python"),
        targets=target_responses,
    )


def _slugify_key(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-._")
    return normalized[:80]


def _unique_preserving_order(values: Iterable[T]) -> list[T]:
    unique: list[T] = []
    for value in values:
        if value in unique:
            continue
        unique.append(value)
    return unique
