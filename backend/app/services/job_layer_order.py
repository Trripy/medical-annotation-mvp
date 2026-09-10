"""Job-scoped helpers for generating annotation z-order values.

The rule never participates in rendering or export directly.  It only updates the
persisted Annotation.z_order values that existing consumers already understand.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Annotation, Job, JobLayerOrderRule, JobLayerOrderRuleItem, Label


@dataclass(frozen=True)
class LayerOrderPreview:
    image_count: int
    annotation_count: int
    changed_image_count: int
    changed_annotation_count: int


def job_layer_order_labels(db: Session, job: Job) -> list[Label]:
    """Return exactly the labels the Job can currently use, in UI order."""
    labels = list(db.scalars(select(Label).where(Label.job_id == job.id).order_by(Label.sort_order, Label.id)).all())
    if labels:
        return labels
    if job.project_id is None:
        return []
    return list(
        db.scalars(select(Label).where(Label.project_id == job.project_id).order_by(Label.sort_order, Label.id)).all()
    )


def spatial_job_label_ids(db: Session, job: Job) -> set[int]:
    return {label.id for label in job_layer_order_labels(db, job) if label.shape_type != "classification"}


def get_job_layer_rule(db: Session, job_id: int) -> JobLayerOrderRule | None:
    return db.scalar(
        select(JobLayerOrderRule)
        .where(JobLayerOrderRule.job_id == job_id)
        .options(selectinload(JobLayerOrderRule.items))
    )


def front_to_back_label_ids(rule: JobLayerOrderRule) -> list[int]:
    return [item.label_id for item in sorted(rule.items, key=lambda item: (item.position, item.id))]


def validate_front_to_back_label_ids(db: Session, job: Job, label_ids: list[int]) -> None:
    if len(label_ids) != len(set(label_ids)):
        raise ValueError("Layer rule contains duplicate labels")
    available = spatial_job_label_ids(db, job)
    if set(label_ids) != available:
        raise ValueError("Layer rule must include every spatial label available to this job")


def upsert_job_layer_rule(
    db: Session,
    job: Job,
    *,
    label_ids: list[int],
    auto_apply: bool,
) -> JobLayerOrderRule:
    validate_front_to_back_label_ids(db, job, label_ids)
    rule = get_job_layer_rule(db, job.id)
    if rule is None:
        rule = JobLayerOrderRule(job_id=job.id, auto_apply=auto_apply)
        db.add(rule)
        db.flush()
    else:
        rule.auto_apply = auto_apply
        rule.items.clear()
        db.flush()
    rule.items = [JobLayerOrderRuleItem(label_id=label_id, position=position) for position, label_id in enumerate(label_ids)]
    db.flush()
    return rule


def _front_to_back_annotations(annotations: list[Annotation]) -> list[Annotation]:
    return sorted(annotations, key=lambda annotation: (-annotation.z_order, annotation.id))


def _ordered_for_rule(annotations: list[Annotation], priority: dict[int, int]) -> list[Annotation]:
    current_front_to_back = _front_to_back_annotations(annotations)
    original_index = {annotation.id: index for index, annotation in enumerate(current_front_to_back)}
    # A stable sort preserves same-label order as well as unconfigured fallback order.
    return sorted(
        current_front_to_back,
        key=lambda annotation: (priority.get(annotation.label_id, len(priority)), original_index[annotation.id]),
    )


def _next_z_orders(annotations: list[Annotation], priority: dict[int, int]) -> dict[int, int]:
    front_to_back = _ordered_for_rule(annotations, priority)
    return {annotation.id: index for index, annotation in enumerate(reversed(front_to_back))}


def preview_job_layer_order(db: Session, job: Job, label_ids: list[int]) -> LayerOrderPreview:
    validate_front_to_back_label_ids(db, job, label_ids)
    annotations = list(
        db.scalars(
            select(Annotation)
            .where(Annotation.job_id == job.id, Annotation.shape_type != "classification")
            .order_by(Annotation.image_id, Annotation.z_order, Annotation.id)
        ).all()
    )
    return _preview_annotations(annotations, label_ids)


def _preview_annotations(annotations: list[Annotation], label_ids: list[int]) -> LayerOrderPreview:
    priority = {label_id: position for position, label_id in enumerate(label_ids)}
    by_image: dict[int, list[Annotation]] = defaultdict(list)
    for annotation in annotations:
        by_image[annotation.image_id].append(annotation)
    changed_image_count = 0
    changed_annotation_count = 0
    for image_annotations in by_image.values():
        target = _next_z_orders(image_annotations, priority)
        changed = sum(annotation.z_order != target[annotation.id] for annotation in image_annotations)
        if changed:
            changed_image_count += 1
            changed_annotation_count += changed
    return LayerOrderPreview(
        image_count=len(by_image),
        annotation_count=len(annotations),
        changed_image_count=changed_image_count,
        changed_annotation_count=changed_annotation_count,
    )


def apply_job_layer_order_to_annotations(db: Session, job: Job, label_ids: list[int]) -> LayerOrderPreview:
    """Apply a Job rule atomically within the caller's transaction."""
    preview = preview_job_layer_order(db, job, label_ids)
    priority = {label_id: position for position, label_id in enumerate(label_ids)}
    annotations = list(
        db.scalars(
            select(Annotation)
            .where(Annotation.job_id == job.id, Annotation.shape_type != "classification")
            .order_by(Annotation.image_id, Annotation.z_order, Annotation.id)
        ).all()
    )
    by_image: dict[int, list[Annotation]] = defaultdict(list)
    for annotation in annotations:
        by_image[annotation.image_id].append(annotation)
    for image_annotations in by_image.values():
        for annotation in image_annotations:
            annotation.z_order = _next_z_orders(image_annotations, priority)[annotation.id]
    db.flush()
    return preview


def apply_job_layer_rule_to_image(db: Session, job: Job, image_id: int) -> bool:
    """Normalize one image after a create or label-change only when enabled."""
    rule = get_job_layer_rule(db, job.id)
    if rule is None or not rule.auto_apply:
        return False
    priority = {item.label_id: item.position for item in rule.items}
    annotations = list(
        db.scalars(
            select(Annotation)
            .where(
                Annotation.job_id == job.id,
                Annotation.image_id == image_id,
                Annotation.shape_type != "classification",
            )
            .order_by(Annotation.z_order, Annotation.id)
        ).all()
    )
    # A newly introduced label is intentionally left on the legacy path until the
    # user explicitly saves an expanded rule containing it.
    if not annotations or any(annotation.label_id not in priority for annotation in annotations):
        return False
    target = _next_z_orders(annotations, priority)
    changed = False
    for annotation in annotations:
        if annotation.z_order != target[annotation.id]:
            annotation.z_order = target[annotation.id]
            changed = True
    if changed:
        db.flush()
    return changed
