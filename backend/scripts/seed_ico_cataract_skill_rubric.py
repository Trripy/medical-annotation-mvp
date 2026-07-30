from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal, engine
from app.models import (
    ResearchSkillAssessment,
    ResearchSkillCriterion,
    ResearchSkillEvidence,
    ResearchSkillRubric,
    ResearchSkillScore,
)
from app.models.user import User
from app.schemas.research_skill import (
    CreateResearchSkillCriterionRequest,
    CreateResearchSkillRubricRequest,
    UpdateResearchSkillCriterionRequest,
    UpdateResearchSkillRubricRequest,
)
from app.services.research_skill_service import (
    activate_skill_rubric,
    create_skill_criterion,
    create_skill_rubric,
    update_skill_criterion,
    update_skill_rubric,
)
from scripts.data.ico_cataract_skill_rubric_zh_cn import CRITERIA, RUBRIC, RUBRIC_NAME, RUBRIC_VERSION


@dataclass(frozen=True)
class SeedResult:
    action: str
    rubric_id: int | None
    status: str | None
    expected_fingerprint: str
    database_fingerprint: str | None
    match: bool
    database_writes: int


def canonical_expected_payload() -> dict[str, Any]:
    return {
        "name": RUBRIC["name"],
        "version": RUBRIC["version"],
        "description": RUBRIC["description"],
        "phase_protocol_id": RUBRIC["phase_protocol_id"],
        "criteria": [
            _canonical_criterion_payload(criterion)
            for criterion in sorted(CRITERIA, key=lambda item: item["display_order"])
        ],
    }


def fingerprint_payload(payload: dict[str, Any]) -> str:
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def expected_fingerprint() -> str:
    return fingerprint_payload(canonical_expected_payload())


def rubric_to_payload(rubric: ResearchSkillRubric) -> dict[str, Any]:
    return {
        "name": rubric.name,
        "version": rubric.version,
        "description": rubric.description,
        "phase_protocol_id": rubric.phase_protocol_id,
        "criteria": [
            _canonical_criterion_payload(
                {
                    "key": criterion.key,
                    "name": criterion.name,
                    "description": criterion.description,
                    "scope": criterion.scope,
                    "score_type": criterion.score_type,
                    "min_value": criterion.min_value,
                    "max_value": criterion.max_value,
                    "step": criterion.step,
                    "options_json": criterion.options_json,
                    "required": criterion.required,
                    "allow_na": criterion.allow_na,
                    "weight": criterion.weight,
                    "display_order": criterion.display_order,
                    "is_active": criterion.is_active,
                    "phase_label_ids": [link.phase_label_id for link in criterion.phase_label_links],
                }
            )
            for criterion in sorted(rubric.criteria, key=lambda item: item.display_order)
        ],
    }


def database_fingerprint(rubric: ResearchSkillRubric) -> str:
    return fingerprint_payload(rubric_to_payload(rubric))


def load_rubric(db: Session) -> ResearchSkillRubric | None:
    return db.scalar(
        select(ResearchSkillRubric)
        .options(
            selectinload(ResearchSkillRubric.criteria).selectinload(ResearchSkillCriterion.phase_label_links),
        )
        .where(ResearchSkillRubric.name == RUBRIC_NAME, ResearchSkillRubric.version == RUBRIC_VERSION)
    )


def seed_ico_cataract_skill_rubric(
    db: Session,
    *,
    creator_username: str,
    apply: bool,
    activate: bool,
) -> SeedResult:
    validate_embedded_rubric_data()
    before_counts = _mutation_counts(db)
    creator = db.scalar(select(User).where(User.username == creator_username))
    if creator is None:
        raise RuntimeError(f"Creator user not found: {creator_username}")

    expected = expected_fingerprint()
    existing = load_rubric(db)
    if existing is None:
        if not apply:
            return SeedResult("would_create", None, None, expected, None, False, 0)
        created = create_skill_rubric(
            db,
            CreateResearchSkillRubricRequest(
                name=RUBRIC["name"],
                version=RUBRIC["version"],
                description=RUBRIC["description"],
                phase_protocol_id=RUBRIC["phase_protocol_id"],
                username=creator_username,
            ),
        )
        existing = load_rubric(db)
        if existing is None:
            raise RuntimeError(f"Rubric was not found after creation: {created.id}")
        for criterion in CRITERIA:
            create_skill_criterion(db, existing.id, CreateResearchSkillCriterionRequest(**criterion))
        existing = _refresh_rubric(db, existing.id)
        if activate:
            activate_skill_rubric(db, existing.id)
            existing = _refresh_rubric(db, existing.id)
        action = "created"
    elif existing.status == "draft":
        diff = compare_rubric(existing)
        if diff["extra_keys"]:
            raise RuntimeError(f"Draft rubric has extra criterion keys: {', '.join(diff['extra_keys'])}")
        if not apply:
            action = "would_update" if diff["differences"] or diff["missing_keys"] else "would_activate"
            return SeedResult(action, existing.id, existing.status, expected, database_fingerprint(existing), False, 0)
        update_skill_rubric(
            db,
            existing.id,
            UpdateResearchSkillRubricRequest(
                name=RUBRIC["name"],
                description=RUBRIC["description"],
                clear_phase_protocol=True,
            ),
        )
        existing = _refresh_rubric(db, existing.id)
        upsert_draft_criteria(db, existing)
        existing = _refresh_rubric(db, existing.id)
        if activate:
            activate_skill_rubric(db, existing.id)
            existing = _refresh_rubric(db, existing.id)
        action = "updated"
    elif existing.status == "active":
        actual = database_fingerprint(existing)
        if actual != expected:
            raise RuntimeError("Active iCO rubric exists but does not match embedded data; refusing to modify.")
        return SeedResult("already_exists", existing.id, existing.status, expected, actual, True, 0)
    elif existing.status == "archived":
        raise RuntimeError("Archived iCO rubric exists; refusing to reactivate or overwrite.")
    else:
        raise RuntimeError(f"Unsupported rubric status: {existing.status}")

    final = _refresh_rubric(db, existing.id)
    actual = database_fingerprint(final)
    if actual != expected:
        raise RuntimeError("Database fingerprint does not match expected iCO rubric fingerprint after import.")
    after_counts = _mutation_counts(db)
    _assert_no_assessment_score_evidence_writes(before_counts, after_counts)
    return SeedResult(action, final.id, final.status, expected, actual, True, after_counts["criteria"] - before_counts["criteria"] + max(after_counts["rubrics"] - before_counts["rubrics"], 0))


def upsert_draft_criteria(db: Session, rubric: ResearchSkillRubric) -> None:
    existing_by_key = {criterion.key: criterion for criterion in rubric.criteria}
    expected_by_key = {criterion["key"]: criterion for criterion in CRITERIA}
    extra_keys = sorted(set(existing_by_key) - set(expected_by_key))
    if extra_keys:
        raise RuntimeError(f"Draft rubric has extra criterion keys: {', '.join(extra_keys)}")
    for expected in CRITERIA:
        existing = existing_by_key.get(expected["key"])
        if existing is None:
            create_skill_criterion(db, rubric.id, CreateResearchSkillCriterionRequest(**expected))
            continue
        immutable_fields = ("key", "scope", "score_type")
        immutable_diff = [
            field
            for field in immutable_fields
            if getattr(existing, field) != expected[field]
        ]
        if immutable_diff:
            raise RuntimeError(f"Draft criterion {existing.key} has incompatible fields: {', '.join(immutable_diff)}")
        update_skill_criterion(
            db,
            existing.id,
            UpdateResearchSkillCriterionRequest(
                name=expected["name"],
                description=expected["description"],
                min_value=expected["min_value"],
                max_value=expected["max_value"],
                step=expected["step"],
                options_json=expected["options_json"],
                required=expected["required"],
                allow_na=expected["allow_na"],
                weight=expected["weight"],
                display_order=expected["display_order"],
                is_active=expected["is_active"],
                phase_label_ids=[],
            ),
        )


def compare_rubric(rubric: ResearchSkillRubric) -> dict[str, Any]:
    expected_by_key = {criterion["key"]: criterion for criterion in CRITERIA}
    existing_by_key = {criterion.key: criterion for criterion in rubric.criteria}
    differences: list[str] = []
    if rubric.description != RUBRIC["description"]:
        differences.append("rubric.description")
    if rubric.phase_protocol_id != RUBRIC["phase_protocol_id"]:
        differences.append("rubric.phase_protocol_id")
    for key in sorted(set(expected_by_key) & set(existing_by_key)):
        actual = _canonical_criterion_payload(
            {
                "key": existing_by_key[key].key,
                "name": existing_by_key[key].name,
                "description": existing_by_key[key].description,
                "scope": existing_by_key[key].scope,
                "score_type": existing_by_key[key].score_type,
                "min_value": existing_by_key[key].min_value,
                "max_value": existing_by_key[key].max_value,
                "step": existing_by_key[key].step,
                "options_json": existing_by_key[key].options_json,
                "required": existing_by_key[key].required,
                "allow_na": existing_by_key[key].allow_na,
                "weight": existing_by_key[key].weight,
                "display_order": existing_by_key[key].display_order,
                "is_active": existing_by_key[key].is_active,
                "phase_label_ids": [link.phase_label_id for link in existing_by_key[key].phase_label_links],
            }
        )
        expected = _canonical_criterion_payload(expected_by_key[key])
        if actual != expected:
            differences.append(f"criterion.{key}")
    return {
        "missing_keys": sorted(set(expected_by_key) - set(existing_by_key)),
        "extra_keys": sorted(set(existing_by_key) - set(expected_by_key)),
        "differences": differences,
    }


def validate_embedded_rubric_data() -> None:
    keys = [criterion["key"] for criterion in CRITERIA]
    names = [criterion["name"] for criterion in CRITERIA]
    if len(CRITERIA) != 20:
        raise RuntimeError("Embedded iCO rubric must contain 20 criteria.")
    if len(set(keys)) != len(keys):
        raise RuntimeError("Embedded iCO criterion keys must be unique.")
    if len(set(names)) != len(names):
        raise RuntimeError("Embedded iCO criterion names must be unique.")
    if [criterion["display_order"] for criterion in CRITERIA] != list(range(20)):
        raise RuntimeError("Embedded iCO display_order must be 0 through 19.")
    for criterion in CRITERIA:
        values = [option["value"] for option in criterion["options_json"]]
        if values != ["0", "2", "3", "4", "5"]:
            raise RuntimeError(f"Invalid options for criterion {criterion['key']}: {values}")
        if "1" in set(values):
            raise RuntimeError(f"Criterion {criterion['key']} must not contain a 1 point option.")
        for score in ("0 分", "2 分", "3 分", "4 分", "5 分"):
            if score not in criterion["description"]:
                raise RuntimeError(f"Criterion {criterion['key']} description missing {score}.")


def _canonical_criterion_payload(criterion: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": criterion["key"],
        "name": criterion["name"],
        "description": criterion["description"],
        "scope": criterion["scope"],
        "score_type": criterion["score_type"],
        "min_value": criterion.get("min_value"),
        "max_value": criterion.get("max_value"),
        "step": criterion.get("step"),
        "options_json": criterion["options_json"],
        "required": bool(criterion["required"]),
        "allow_na": bool(criterion["allow_na"]),
        "weight": criterion.get("weight"),
        "display_order": criterion["display_order"],
        "is_active": bool(criterion["is_active"]),
        "phase_label_ids": sorted(criterion.get("phase_label_ids") or []),
    }


def _refresh_rubric(db: Session, rubric_id: int) -> ResearchSkillRubric:
    db.expire_all()
    rubric = db.scalar(
        select(ResearchSkillRubric)
        .options(
            selectinload(ResearchSkillRubric.criteria).selectinload(ResearchSkillCriterion.phase_label_links),
        )
        .where(ResearchSkillRubric.id == rubric_id)
    )
    if rubric is None:
        raise RuntimeError(f"Rubric not found: {rubric_id}")
    return rubric


def _mutation_counts(db: Session) -> dict[str, int]:
    return {
        "rubrics": db.scalar(select(func.count(ResearchSkillRubric.id))) or 0,
        "criteria": db.scalar(select(func.count(ResearchSkillCriterion.id))) or 0,
        "assessments": db.scalar(select(func.count(ResearchSkillAssessment.id))) or 0,
        "scores": db.scalar(select(func.count(ResearchSkillScore.id))) or 0,
        "evidence": db.scalar(select(func.count(ResearchSkillEvidence.id))) or 0,
    }


def _assert_no_assessment_score_evidence_writes(before: dict[str, int], after: dict[str, int]) -> None:
    for key in ("assessments", "scores", "evidence"):
        if after[key] != before[key]:
            raise RuntimeError(f"Unexpected {key} count change: {before[key]} -> {after[key]}")


def seed_ico_cataract_skill_rubric_via_api(
    api_base: str,
    *,
    creator_username: str,
    apply: bool,
    activate: bool,
) -> SeedResult:
    validate_embedded_rubric_data()
    api = ResearchSkillApiClient(api_base)
    expected = expected_fingerprint()
    existing = api.find_rubric()
    if existing is None:
        if not apply:
            return SeedResult("would_create", None, None, expected, None, False, 0)
        rubric = api.create_rubric(
            {
                "name": RUBRIC["name"],
                "version": RUBRIC["version"],
                "description": RUBRIC["description"],
                "phase_protocol_id": RUBRIC["phase_protocol_id"],
                "username": creator_username,
            }
        )
        for criterion in CRITERIA:
            api.create_criterion(rubric["id"], criterion)
        if activate:
            rubric = api.activate_rubric(rubric["id"])["rubric"]
        else:
            rubric = api.get_rubric(rubric["id"])
        actual = fingerprint_payload(_api_rubric_to_payload(rubric))
        if actual != expected:
            raise RuntimeError("API-imported rubric fingerprint does not match embedded iCO rubric data.")
        return SeedResult("created", rubric["id"], rubric["status"], expected, actual, True, 21 if activate else 20)
    if existing["status"] == "draft":
        detail = api.get_rubric(existing["id"])
        diff = compare_api_rubric(detail)
        if diff["extra_keys"]:
            raise RuntimeError(f"Draft rubric has extra criterion keys: {', '.join(diff['extra_keys'])}")
        if not apply:
            action = "would_update" if diff["differences"] or diff["missing_keys"] else "would_activate"
            return SeedResult(action, detail["id"], detail["status"], expected, fingerprint_payload(_api_rubric_to_payload(detail)), False, 0)
        api.update_rubric(
            detail["id"],
            {
                "name": RUBRIC["name"],
                "description": RUBRIC["description"],
                "clear_phase_protocol": True,
            },
        )
        detail = api.get_rubric(detail["id"])
        existing_by_key = {criterion["key"]: criterion for criterion in detail.get("criteria", [])}
        for criterion in CRITERIA:
            existing_criterion = existing_by_key.get(criterion["key"])
            if existing_criterion is None:
                api.create_criterion(detail["id"], criterion)
                continue
            immutable_diff = [
                field
                for field in ("key", "scope", "score_type")
                if existing_criterion.get(field) != criterion[field]
            ]
            if immutable_diff:
                raise RuntimeError(f"Draft criterion {criterion['key']} has incompatible fields: {', '.join(immutable_diff)}")
            api.update_criterion(
                existing_criterion["id"],
                {
                    "name": criterion["name"],
                    "description": criterion["description"],
                    "min_value": criterion["min_value"],
                    "max_value": criterion["max_value"],
                    "step": criterion["step"],
                    "options_json": criterion["options_json"],
                    "required": criterion["required"],
                    "allow_na": criterion["allow_na"],
                    "weight": criterion["weight"],
                    "display_order": criterion["display_order"],
                    "is_active": criterion["is_active"],
                    "phase_label_ids": [],
                },
            )
        detail = api.get_rubric(detail["id"])
        if activate:
            detail = api.activate_rubric(detail["id"])["rubric"]
        actual = fingerprint_payload(_api_rubric_to_payload(detail))
        if actual != expected:
            raise RuntimeError("API-updated rubric fingerprint does not match embedded iCO rubric data.")
        return SeedResult("updated", detail["id"], detail["status"], expected, actual, True, 0)
    if existing["status"] == "active":
        detail = api.get_rubric(existing["id"])
        actual = fingerprint_payload(_api_rubric_to_payload(detail))
        if actual != expected:
            raise RuntimeError("Active iCO rubric exists but does not match embedded data; refusing to modify.")
        return SeedResult("already_exists", detail["id"], detail["status"], expected, actual, True, 0)
    if existing["status"] == "archived":
        raise RuntimeError("Archived iCO rubric exists; refusing to reactivate or overwrite.")
    raise RuntimeError(f"Unsupported rubric status: {existing['status']}")


class ResearchSkillApiClient:
    def __init__(self, api_base: str) -> None:
        self.api_base = api_base.rstrip("/")

    def find_rubric(self) -> dict[str, Any] | None:
        query = urlencode({"include_archived": "true"})
        rubrics = self._request("GET", f"/skill-rubrics?{query}")
        for rubric in rubrics:
            if rubric.get("name") == RUBRIC_NAME and rubric.get("version") == RUBRIC_VERSION:
                return rubric
        return None

    def get_rubric(self, rubric_id: int) -> dict[str, Any]:
        return self._request("GET", f"/skill-rubrics/{rubric_id}")

    def create_rubric(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/skill-rubrics", payload)

    def update_rubric(self, rubric_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"/skill-rubrics/{rubric_id}", payload)

    def create_criterion(self, rubric_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/skill-rubrics/{rubric_id}/criteria", payload)

    def update_criterion(self, criterion_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"/skill-criteria/{criterion_id}", payload)

    def activate_rubric(self, rubric_id: int) -> dict[str, Any]:
        return self._request("POST", f"/skill-rubrics/{rubric_id}/activate")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.api_base}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"API {method} {path} failed with {exc.code}: {error_body}") from exc
        return json.loads(body) if body else None


def compare_api_rubric(rubric: dict[str, Any]) -> dict[str, Any]:
    expected_by_key = {criterion["key"]: criterion for criterion in CRITERIA}
    existing_by_key = {criterion["key"]: criterion for criterion in rubric.get("criteria", [])}
    differences: list[str] = []
    if rubric.get("description") != RUBRIC["description"]:
        differences.append("rubric.description")
    if rubric.get("phase_protocol_id") != RUBRIC["phase_protocol_id"]:
        differences.append("rubric.phase_protocol_id")
    for key in sorted(set(expected_by_key) & set(existing_by_key)):
        if _canonical_criterion_payload(_api_criterion_to_payload(existing_by_key[key])) != _canonical_criterion_payload(expected_by_key[key]):
            differences.append(f"criterion.{key}")
    return {
        "missing_keys": sorted(set(expected_by_key) - set(existing_by_key)),
        "extra_keys": sorted(set(existing_by_key) - set(expected_by_key)),
        "differences": differences,
    }


def _api_rubric_to_payload(rubric: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": rubric.get("name"),
        "version": rubric.get("version"),
        "description": rubric.get("description"),
        "phase_protocol_id": rubric.get("phase_protocol_id"),
        "criteria": [
            _canonical_criterion_payload(_api_criterion_to_payload(criterion))
            for criterion in sorted(rubric.get("criteria", []), key=lambda item: item["display_order"])
        ],
    }


def _api_criterion_to_payload(criterion: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": criterion.get("key"),
        "name": criterion.get("name"),
        "description": criterion.get("description"),
        "scope": criterion.get("scope"),
        "score_type": criterion.get("score_type"),
        "min_value": criterion.get("min_value"),
        "max_value": criterion.get("max_value"),
        "step": criterion.get("step"),
        "options_json": criterion.get("options_json"),
        "required": criterion.get("required"),
        "allow_na": criterion.get("allow_na"),
        "weight": criterion.get("weight"),
        "display_order": criterion.get("display_order"),
        "is_active": criterion.get("is_active"),
        "phase_label_ids": criterion.get("phase_label_ids") or [],
    }


def _database_target() -> str:
    url = str(engine.url)
    return str(engine.url.set(password="***")) if engine.url.password else url


def _print_result(result: SeedResult, *, creator_username: str, dry_run: bool, target: str | None = None) -> None:
    print(f"database_target={target or _database_target()}")
    print(f"creator_username={creator_username}")
    print(f"dry_run={dry_run}")
    print(f"action={result.action}")
    print(f"rubric_id={result.rubric_id}")
    print(f"rubric_status={result.status}")
    print(f"planned_rubric={RUBRIC_NAME} v{RUBRIC_VERSION}")
    print(f"planned_criteria_count={len(CRITERIA)}")
    print("planned_option_values=0,2,3,4,5")
    print(f"expected_fingerprint={result.expected_fingerprint}")
    print(f"database_fingerprint={result.database_fingerprint}")
    print(f"match={str(result.match).lower()}")
    print(f"database_writes={result.database_writes}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed the Chinese iCO cataract skill rubric into the Skill Assessment system.")
    parser.add_argument("--creator-username", default="zhangyuzhu")
    parser.add_argument("--api-base", default=None, help="Optional backend API base URL, for example http://127.0.0.1:8000/api/research.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect only. This is the default unless --apply is set.")
    parser.add_argument("--apply", action="store_true", help="Write the rubric and criteria when needed.")
    parser.add_argument("--activate", action="store_true", help="Activate the rubric after import.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dry_run = not args.apply or args.dry_run
    try:
        if args.api_base:
            result = seed_ico_cataract_skill_rubric_via_api(
                args.api_base,
                creator_username=args.creator_username,
                apply=not dry_run,
                activate=args.activate,
            )
            _print_result(result, creator_username=args.creator_username, dry_run=dry_run, target=args.api_base.rstrip("/"))
            return 0
        with SessionLocal() as db:
            result = seed_ico_cataract_skill_rubric(
                db,
                creator_username=args.creator_username,
                apply=not dry_run,
                activate=args.activate,
            )
            _print_result(result, creator_username=args.creator_username, dry_run=dry_run)
        return 0
    except (HTTPException, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
