from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import jobs as jobs_api
from app.db.base import Base
from app.models import Annotation, Image, Job, Label, Project, User
from app.schemas.annotation import AnnotationSaveRequest
from app.schemas.job import JobLayerOrderRulePayload


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)()


def _job(db: Session, name: str) -> tuple[Job, Image, list[Label]]:
    project = Project(name=f"{name} project", owner=User(username=f"{name}-owner", email=f"{name}@example.com"))
    job = Job(name=name, project=project)
    labels = [
        Label(job=job, name="back", color="#111111", shape_type="polygon", sort_order=0),
        Label(job=job, name="front", color="#222222", shape_type="polygon", sort_order=1),
        Label(job=job, name="class", color="#333333", shape_type="classification", sort_order=2),
    ]
    image = Image(job=job, project=project, filename=f"{name}.png", file_path=f"/{name}.png", thumbnail_path=f"/{name}.png")
    db.add_all([job, *labels, image])
    db.commit()
    return job, image, labels


def test_rule_is_job_scoped_and_applies_stably() -> None:
    db = _db()
    try:
        job_a, image, labels_a = _job(db, "a")
        job_b, _other_image, labels_b = _job(db, "b")
        a_back, a_front, a_class = labels_a
        b_back, b_front, _ = labels_b
        rows = [
            Annotation(job_id=job_a.id, image_id=image.id, label_id=a_back.id, shape_type="polygon", points=[[0, 0], [1, 0], [1, 1]], z_order=4),
            Annotation(job_id=job_a.id, image_id=image.id, label_id=a_front.id, shape_type="polygon", points=[[0, 0], [1, 0], [1, 1]], z_order=1),
            Annotation(job_id=job_a.id, image_id=image.id, label_id=a_front.id, shape_type="polygon", points=[[0, 0], [1, 0], [1, 1]], z_order=3),
            Annotation(job_id=job_a.id, image_id=image.id, label_id=a_class.id, shape_type="classification", points=[], z_order=99),
            Annotation(job_id=job_b.id, image_id=image.id, label_id=b_back.id, shape_type="polygon", points=[[0, 0], [1, 0], [1, 1]], z_order=7),
            Annotation(job_id=job_b.id, image_id=image.id, label_id=b_front.id, shape_type="polygon", points=[[0, 0], [1, 0], [1, 1]], z_order=8),
        ]
        db.add_all(rows)
        db.commit()

        preview = jobs_api.preview_job_layer_order_rule(
            job_a.id, JobLayerOrderRulePayload(front_to_back_label_ids=[a_front.id, a_back.id]), db
        )
        assert preview.annotation_count == 3
        assert db.get(Annotation, rows[0].id).z_order == 4

        result = jobs_api.save_job_layer_order_rule(
            job_a.id,
            JobLayerOrderRulePayload(front_to_back_label_ids=[a_front.id, a_back.id], apply_existing=True),
            db,
        )
        assert result.applied_existing is True
        db.refresh(rows[0]); db.refresh(rows[1]); db.refresh(rows[2]); db.refresh(rows[3]); db.refresh(rows[4]); db.refresh(rows[5])
        assert [rows[0].z_order, rows[1].z_order, rows[2].z_order] == [0, 1, 2]
        assert rows[3].z_order == 99
        assert [rows[4].z_order, rows[5].z_order] == [7, 8]
    finally:
        db.close()


def test_delete_rule_keeps_existing_order_and_auto_apply_is_opt_in() -> None:
    db = _db()
    try:
        job, image, labels = _job(db, "single")
        back, front, _ = labels
        jobs_api.save_job_layer_order_rule(
            job.id, JobLayerOrderRulePayload(front_to_back_label_ids=[front.id, back.id], auto_apply=True), db
        )
        saved = jobs_api.save_image_annotations(
            job.id,
            image.id,
            AnnotationSaveRequest.model_validate({
                "apply_layer_rule": True,
                "annotations": [
                    {"label_id": back.id, "shape_type": "polygon", "points": [[0, 0], [1, 0], [1, 1]], "z_order": 1},
                    {"label_id": front.id, "shape_type": "polygon", "points": [[0, 0], [1, 0], [1, 1]], "z_order": 0},
                ],
            }),
            db,
        )
        assert [item.label_id for item in sorted(saved, key=lambda item: item.z_order)] == [back.id, front.id]
        before = [item.z_order for item in saved]
        jobs_api.delete_job_layer_order_rule(job.id, db)
        assert [db.get(Annotation, item.id).z_order for item in saved] == before
    finally:
        db.close()
