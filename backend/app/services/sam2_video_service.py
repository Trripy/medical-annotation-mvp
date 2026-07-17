from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import threading
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image as PILImage

from app.core.config import settings
from app.services.sam2_service import (
    DEFAULT_SAM2_MODEL_NAME,
    SAM2_MODEL_REGISTRY,
    Sam2PredictionError,
    Sam2UnavailableError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Sam2VideoFrame:
    image_id: int
    frame_index: int
    filename: str
    file_path: str
    width: int
    height: int


@dataclass
class Sam2TrackVideoFrameResult:
    image_id: int
    frame_index: int
    filename: str
    points: list[list[float]] | None
    score: float | None
    area: float | None
    status: str
    propagation_direction: str
    detail: str | None = None


@dataclass
class Sam2TrackVideoResult:
    start_frame_index: int
    end_frame_index: int
    backward_end_frame_index: int | None
    forward_end_frame_index: int | None
    direction: str
    model_name: str
    results: list[Sam2TrackVideoFrameResult]
    review_frames: list[int]
    warnings: list[str]


@dataclass(frozen=True)
class Sam2TrackingRunSpec:
    propagation_direction: str
    frames: list[Sam2VideoFrame]
    resolved_end_frame_index: int


class Sam2VideoService:
    def __init__(self) -> None:
        self._predictor: Any | None = None
        self._torch: Any | None = None
        self._device = "cpu"
        self._dtype = "float32"
        self._active_model_name: str | None = None
        self._lock = threading.Lock()
        self.load_error: str | None = None

    @property
    def ready(self) -> bool:
        return self._predictor is not None and self.load_error is None

    def load(self, model_name: str | None = None) -> None:
        target_model_name = model_name or self._active_model_name or DEFAULT_SAM2_MODEL_NAME
        if self._predictor is not None and self._active_model_name == target_model_name:
            return

        with self._lock:
            if self._predictor is not None and self._active_model_name == target_model_name:
                return

            repo_root, checkpoint, model_cfg = self._resolve_model(target_model_name)
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))

            try:
                import torch
                from sam2.build_sam import build_sam2_video_predictor
            except Exception as exc:  # pragma: no cover - depends on optional runtime deps
                self.load_error = f"SAM2 video dependencies are not available: {exc}"
                raise Sam2UnavailableError(self.load_error) from exc

            requested_device = settings.sam2_device
            cuda_available = torch.cuda.is_available()
            next_device = requested_device
            if requested_device == "auto":
                next_device = "cuda" if cuda_available else "cpu"
            if next_device == "cuda" and not cuda_available:
                logger.warning("CUDA is not available for SAM2 video tracking. Falling back to CPU.")
                next_device = "cpu"

            self._torch = torch
            self._device = next_device
            self._dtype = self._select_autocast_dtype(torch)

            try:
                self._release_predictor()
                self._predictor = build_sam2_video_predictor(
                    model_cfg,
                    str(checkpoint),
                    device=self._device,
                )
                self._active_model_name = target_model_name
                self.load_error = None
                logger.warning(
                    "SAM2 video model loaded model=%s checkpoint=%s config=%s device=%s dtype=%s",
                    target_model_name,
                    checkpoint,
                    model_cfg,
                    self._device,
                    self._dtype,
                )
            except Exception as exc:  # pragma: no cover - model load depends on local weights
                self.load_error = f"SAM2 video model failed to load: {exc}"
                raise Sam2UnavailableError(self.load_error) from exc

    def track_video(
        self,
        *,
        frames: list[Sam2VideoFrame],
        start_image_id: int,
        start_frame_index: int | None,
        polygon_points: list[list[float]],
        direction: str,
        end_frame_index: int | None,
        backward_end_frame_index: int | None,
        forward_end_frame_index: int | None,
        review_interval: int,
        model_name: str,
        polygon_epsilon: float,
        min_mask_area: float,
        mask_threshold: float,
        max_hole_area: float,
    ) -> Sam2TrackVideoResult:
        self.load(model_name)
        if not self.ready:
            raise Sam2UnavailableError(self.load_error or "SAM2 video model is not loaded")
        if len(polygon_points) < 3:
            raise Sam2PredictionError("Polygon must have at least 3 points.")
        if not frames:
            raise Sam2PredictionError("No frames are available for SAM2 video tracking.")

        cv2, np = self._load_post_processing_dependencies()
        start_idx = self._find_start_frame_index(frames, start_image_id)
        start_frame = frames[start_idx]
        if start_frame_index is not None and start_frame.frame_index != start_frame_index:
            raise Sam2PredictionError("Start frame index does not match the selected image.")

        tracking_runs = self._build_tracking_run_specs(
            frames=frames,
            start_idx=start_idx,
            direction=direction,
            end_frame_index=end_frame_index,
            backward_end_frame_index=backward_end_frame_index,
            forward_end_frame_index=forward_end_frame_index,
        )

        rough_mask = self._rasterize_polygon_mask(
            polygon_points,
            width=start_frame.width,
            height=start_frame.height,
            cv2=cv2,
            np=np,
        )
        source_points = [[float(point[0]), float(point[1])] for point in polygon_points]
        review_frames = self._build_review_frames(tracking_runs, review_interval)
        warnings: list[str] = []
        results_by_image_id: dict[int, Sam2TrackVideoFrameResult] = {
            start_frame.image_id: Sam2TrackVideoFrameResult(
                image_id=start_frame.image_id,
                frame_index=start_frame.frame_index,
                filename=start_frame.filename,
                points=source_points,
                score=None,
                area=float(rough_mask.astype(bool).sum()),
                status="source",
                propagation_direction="source",
            )
        }

        successful_runs = 0
        first_run_error: Sam2PredictionError | None = None
        for tracking_run in tracking_runs:
            try:
                run_results, run_warnings = self._track_frame_range(
                    tracking_run=tracking_run,
                    rough_mask=rough_mask,
                    cv2=cv2,
                    np=np,
                    polygon_epsilon=polygon_epsilon,
                    min_mask_area=min_mask_area,
                    mask_threshold=mask_threshold,
                    max_hole_area=max_hole_area,
                )
            except Sam2PredictionError as exc:
                if first_run_error is None:
                    first_run_error = exc
                if len(tracking_runs) == 1:
                    raise
                warnings.append(
                    f"{tracking_run.propagation_direction.capitalize()} tracking failed: {exc}"
                )
                continue

            successful_runs += 1
            warnings.extend(run_warnings)
            for result in run_results:
                results_by_image_id[result.image_id] = result

        if successful_runs == 0 and tracking_runs:
            raise first_run_error or Sam2PredictionError("SAM2 video tracking failed.")

        results = sorted(
            results_by_image_id.values(),
            key=lambda result: (result.frame_index, result.image_id),
        )
        resolved_backward_end_frame_index = self._resolved_end_frame_index_for_direction(tracking_runs, "backward")
        resolved_forward_end_frame_index = self._resolved_end_frame_index_for_direction(tracking_runs, "forward")
        if direction == "backward":
            resolved_end_frame_index = (
                resolved_backward_end_frame_index
                if resolved_backward_end_frame_index is not None
                else start_frame.frame_index
            )
        elif direction == "forward":
            resolved_end_frame_index = (
                resolved_forward_end_frame_index
                if resolved_forward_end_frame_index is not None
                else start_frame.frame_index
            )
        else:
            if resolved_forward_end_frame_index is not None:
                resolved_end_frame_index = resolved_forward_end_frame_index
            elif resolved_backward_end_frame_index is not None:
                resolved_end_frame_index = resolved_backward_end_frame_index
            else:
                resolved_end_frame_index = start_frame.frame_index

        return Sam2TrackVideoResult(
            start_frame_index=start_frame.frame_index,
            end_frame_index=resolved_end_frame_index,
            backward_end_frame_index=resolved_backward_end_frame_index,
            forward_end_frame_index=resolved_forward_end_frame_index,
            direction=direction,
            model_name=self._active_model_name or model_name,
            results=results,
            review_frames=review_frames,
            warnings=warnings,
        )

    def _find_start_frame_index(self, frames: list[Sam2VideoFrame], start_image_id: int) -> int:
        for index, frame in enumerate(frames):
            if frame.image_id == start_image_id:
                return index
        raise Sam2PredictionError("Start image is not part of the selected job.")

    def _build_tracking_run_specs(
        self,
        *,
        frames: list[Sam2VideoFrame],
        start_idx: int,
        direction: str,
        end_frame_index: int | None,
        backward_end_frame_index: int | None,
        forward_end_frame_index: int | None,
    ) -> list[Sam2TrackingRunSpec]:
        start_frame = frames[start_idx]
        tracking_runs: list[Sam2TrackingRunSpec] = []

        if direction == "forward":
            forward_run = self._select_tracking_frames(
                frames=frames,
                start_idx=start_idx,
                propagation_direction="forward",
                end_frame_index=end_frame_index,
            )
            if len(forward_run.frames) <= 1:
                raise Sam2PredictionError("Cannot track forward from the last frame.")
            tracking_runs.append(forward_run)
        elif direction == "backward":
            backward_run = self._select_tracking_frames(
                frames=frames,
                start_idx=start_idx,
                propagation_direction="backward",
                end_frame_index=end_frame_index,
            )
            if len(backward_run.frames) <= 1:
                raise Sam2PredictionError("Cannot track backward from the first frame.")
            tracking_runs.append(backward_run)
        elif direction == "both":
            backward_run = self._select_tracking_frames(
                frames=frames,
                start_idx=start_idx,
                propagation_direction="backward",
                end_frame_index=backward_end_frame_index,
            )
            forward_run = self._select_tracking_frames(
                frames=frames,
                start_idx=start_idx,
                propagation_direction="forward",
                end_frame_index=forward_end_frame_index,
            )
            if len(backward_run.frames) > 1:
                tracking_runs.append(backward_run)
            if len(forward_run.frames) > 1:
                tracking_runs.append(forward_run)
        else:
            raise Sam2PredictionError(f"Unsupported tracking direction: {direction}")

        if not tracking_runs:
            raise Sam2PredictionError("No additional frames are available in the selected tracking range.")

        return tracking_runs

    def _select_tracking_frames(
        self,
        *,
        frames: list[Sam2VideoFrame],
        start_idx: int,
        propagation_direction: str,
        end_frame_index: int | None,
    ) -> Sam2TrackingRunSpec:
        if end_frame_index is None:
            raise Sam2PredictionError("Tracking range is missing an end frame.")

        start_frame = frames[start_idx]
        if propagation_direction == "forward":
            if end_frame_index < start_frame.frame_index:
                raise Sam2PredictionError("End frame must be after the selected start frame.")

            last_available_frame_index = frames[-1].frame_index
            resolved_end_frame_index = min(end_frame_index, last_available_frame_index)
            tracking_frames = [
                frame
                for frame in frames[start_idx:]
                if frame.frame_index <= resolved_end_frame_index
            ]
        elif propagation_direction == "backward":
            if end_frame_index > start_frame.frame_index:
                raise Sam2PredictionError("End frame must be before the selected start frame.")

            first_available_frame_index = frames[0].frame_index
            resolved_end_frame_index = max(end_frame_index, first_available_frame_index)
            tracking_frames = [
                frame
                for frame in frames[: start_idx + 1]
                if frame.frame_index >= resolved_end_frame_index
            ]
            tracking_frames = list(reversed(tracking_frames))
        else:
            raise Sam2PredictionError(f"Unsupported propagation direction: {propagation_direction}")

        if not tracking_frames:
            raise Sam2PredictionError("No frames are available in the selected tracking range.")

        return Sam2TrackingRunSpec(
            propagation_direction=propagation_direction,
            frames=tracking_frames,
            resolved_end_frame_index=tracking_frames[-1].frame_index,
        )

    def _build_review_frames(
        self,
        tracking_runs: list[Sam2TrackingRunSpec],
        review_interval: int,
    ) -> list[int]:
        review_frames: set[int] = set()
        for tracking_run in tracking_runs:
            if len(tracking_run.frames) <= 1:
                continue

            run_review_frames = [
                frame.frame_index
                for index, frame in enumerate(tracking_run.frames[1:], start=1)
                if index % review_interval == 0
            ]
            final_frame_index = tracking_run.frames[-1].frame_index
            if final_frame_index != tracking_run.frames[0].frame_index and final_frame_index not in run_review_frames:
                run_review_frames.append(final_frame_index)
            review_frames.update(run_review_frames)
        return sorted(review_frames)

    def _resolved_end_frame_index_for_direction(
        self,
        tracking_runs: list[Sam2TrackingRunSpec],
        propagation_direction: str,
    ) -> int | None:
        for tracking_run in tracking_runs:
            if tracking_run.propagation_direction == propagation_direction:
                return tracking_run.resolved_end_frame_index
        return None

    def _track_frame_range(
        self,
        *,
        tracking_run: Sam2TrackingRunSpec,
        rough_mask: Any,
        cv2: Any,
        np: Any,
        polygon_epsilon: float,
        min_mask_area: float,
        mask_threshold: float,
        max_hole_area: float,
    ) -> tuple[list[Sam2TrackVideoFrameResult], list[str]]:
        self._validate_frame_sizes(tracking_run.frames)
        warnings: list[str] = []
        results: list[Sam2TrackVideoFrameResult] = []

        with tempfile.TemporaryDirectory(prefix="sam2_video_job_") as temp_dir:
            self._prepare_tracking_directory(tracking_run.frames, temp_dir)

            try:
                propagated_results = self._run_tracking(
                    temp_dir=temp_dir,
                    rough_mask=rough_mask,
                    frame_count=len(tracking_run.frames),
                )
            except Sam2PredictionError:
                raise
            except Exception as exc:
                raise Sam2PredictionError(f"SAM2 video tracking failed: {exc}") from exc

            for local_frame_idx, _obj_ids, video_res_masks in propagated_results:
                if local_frame_idx <= 0:
                    continue

                frame = tracking_run.frames[local_frame_idx]
                try:
                    mask_scores = self._extract_first_mask(video_res_masks)
                    mask = mask_scores > mask_threshold
                    mask = self._fill_small_holes(mask, cv2, np, max_hole_area)
                    points, _num_contours, mask_area = self._mask_to_polygon(
                        mask,
                        cv2,
                        np,
                        polygon_epsilon,
                        min_mask_area,
                    )
                    results.append(
                        Sam2TrackVideoFrameResult(
                            image_id=frame.image_id,
                            frame_index=frame.frame_index,
                            filename=frame.filename,
                            points=points,
                            score=None,
                            area=mask_area,
                            status="tracked",
                            propagation_direction=tracking_run.propagation_direction,
                        )
                    )
                except Sam2PredictionError as exc:
                    detail = str(exc)
                    warnings.append(f"Frame {frame.frame_index}: {detail}")
                    results.append(
                        Sam2TrackVideoFrameResult(
                            image_id=frame.image_id,
                            frame_index=frame.frame_index,
                            filename=frame.filename,
                            points=None,
                            score=None,
                            area=None,
                            status="failed",
                            propagation_direction=tracking_run.propagation_direction,
                            detail=detail,
                        )
                    )

        return results, warnings

    def _validate_frame_sizes(self, frames: list[Sam2VideoFrame]) -> None:
        first_width = frames[0].width
        first_height = frames[0].height
        if first_width <= 0 or first_height <= 0:
            raise Sam2PredictionError("All frames in the tracking range must have the same image size.")

        for frame in frames[1:]:
            if frame.width != first_width or frame.height != first_height:
                raise Sam2PredictionError("All frames in the tracking range must have the same image size.")

    def _prepare_tracking_directory(self, frames: list[Sam2VideoFrame], target_dir: str) -> None:
        for index, frame in enumerate(frames):
            source = Path(frame.file_path)
            if not source.is_file():
                raise Sam2PredictionError(f"Image file not found for frame {frame.frame_index}.")

            target = Path(target_dir) / f"{index:06d}.jpg"
            suffix = source.suffix.lower()
            if suffix in {".jpg", ".jpeg"}:
                try:
                    os.symlink(source, target)
                    continue
                except OSError:
                    shutil.copy2(source, target)
                    continue

            with PILImage.open(source) as image:
                image.convert("RGB").save(target, format="JPEG", quality=95)

    def _run_tracking(self, *, temp_dir: str, rough_mask: Any, frame_count: int) -> list[tuple[int, Any]]:
        offload_video_to_cpu = self._device == "mps"
        with self._lock:
            with self._torch.inference_mode():
                with self._autocast_context():
                    inference_state = self._predictor.init_state(
                        temp_dir,
                        offload_video_to_cpu=offload_video_to_cpu,
                    )
                    self._predictor.add_new_mask(
                        inference_state=inference_state,
                        frame_idx=0,
                        obj_id=1,
                        mask=rough_mask.astype(bool),
                    )
                    return list(
                        self._predictor.propagate_in_video(
                            inference_state,
                            start_frame_idx=0,
                            max_frame_num_to_track=frame_count,
                            reverse=False,
                        )
                    )

    def _extract_first_mask(self, video_res_masks: Any) -> Any:
        mask_tensor = video_res_masks
        if getattr(mask_tensor, "dim", None) is None:
            raise Sam2PredictionError("SAM2 returned an invalid tracking mask.")
        if mask_tensor.dim() == 4:
            mask_tensor = mask_tensor[0, 0]
        elif mask_tensor.dim() == 3:
            mask_tensor = mask_tensor[0]
        if mask_tensor.dim() != 2:
            raise Sam2PredictionError("SAM2 returned an invalid tracking mask.")
        return mask_tensor.detach().cpu().numpy()

    def _mask_to_polygon(
        self,
        mask: Any,
        cv2: Any,
        np: Any,
        polygon_epsilon: float,
        min_mask_area: float,
    ) -> tuple[list[list[float]], int, float]:
        mask_uint8 = mask.astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            raise Sam2PredictionError("SAM2 returned an empty mask")

        usable_contours = [contour for contour in contours if cv2.contourArea(contour) >= min_mask_area]
        if not usable_contours:
            raise Sam2PredictionError("SAM2 returned no contour above min_mask_area")

        contour = max(usable_contours, key=cv2.contourArea)
        mask_area = float(mask.astype(bool).sum())
        epsilon_ratio = polygon_epsilon if polygon_epsilon is not None else settings.sam2_polygon_epsilon_ratio
        epsilon = max(1.0, epsilon_ratio * cv2.arcLength(contour, True))
        approx = cv2.approxPolyDP(contour, epsilon, True)
        if len(approx) < 3:
            approx = cv2.convexHull(contour)
        if len(approx) < 3:
            raise Sam2PredictionError("SAM2 mask could not be converted to polygon")

        height, width = mask_uint8.shape[:2]
        points: list[list[float]] = []
        for raw_point in approx[:, 0, :]:
            x = float(max(0, min(width, raw_point[0])))
            y = float(max(0, min(height, raw_point[1])))
            points.append([x, y])
        return points, len(usable_contours), mask_area

    def _fill_small_holes(self, mask: Any, cv2: Any, np: Any, max_hole_area: float) -> Any:
        if max_hole_area <= 0:
            return mask

        mask_uint8 = mask.astype(np.uint8) * 255
        inverted = cv2.bitwise_not(mask_uint8)
        contours, _ = cv2.findContours(inverted, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        height, width = mask_uint8.shape[:2]

        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            touches_border = x <= 0 or y <= 0 or x + w >= width or y + h >= height
            if touches_border:
                continue
            if cv2.contourArea(contour) <= max_hole_area:
                cv2.drawContours(mask_uint8, [contour], -1, 255, thickness=-1)

        return mask_uint8.astype(bool)

    def _rasterize_polygon_mask(
        self,
        points: list[list[float]],
        *,
        width: int,
        height: int,
        cv2: Any,
        np: Any,
    ) -> Any:
        if width <= 0 or height <= 0:
            raise Sam2PredictionError("Image dimensions are invalid for SAM2 video tracking.")

        mask = np.zeros((height, width), dtype=np.uint8)
        normalized_points = []
        for point in points:
            if len(point) != 2:
                continue
            x = int(round(float(point[0])))
            y = int(round(float(point[1])))
            normalized_points.append([
                max(0, min(width - 1, x)),
                max(0, min(height - 1, y)),
            ])

        if len(normalized_points) < 3:
            raise Sam2PredictionError("Polygon must have at least 3 points.")

        polygon = np.asarray(normalized_points, dtype=np.float32)
        if cv2.contourArea(polygon) <= 0:
            raise Sam2PredictionError("Polygon must enclose a non-zero area.")

        cv2.fillPoly(mask, [polygon.astype(np.int32)], 1)
        return mask

    def _load_post_processing_dependencies(self) -> tuple[Any, Any]:
        try:
            import cv2
            import numpy as np
        except Exception as exc:  # pragma: no cover - depends on optional runtime deps
            raise Sam2UnavailableError(f"SAM2 post-processing dependencies are not available: {exc}") from exc
        return cv2, np

    def _select_autocast_dtype(self, torch: Any) -> str:
        if self._device != "cuda":
            return "float32"

        try:
            if torch.cuda.is_bf16_supported():
                return "bfloat16"
        except Exception:
            pass
        return "float16"

    def _autocast_context(self) -> Any:
        if self._device != "cuda" or self._torch is None:
            return nullcontext()
        dtype = self._torch.bfloat16 if self._dtype == "bfloat16" else self._torch.float16
        return self._torch.autocast("cuda", dtype=dtype)

    def _resolve_model(self, model_name: str) -> tuple[Path, Path, str]:
        spec = SAM2_MODEL_REGISTRY.get(model_name)
        if spec is None:
            raise Sam2UnavailableError(f"Unsupported SAM2 model: {model_name}")

        repo_root = Path(settings.sam2_repo_root)
        if not repo_root.exists():
            raise Sam2UnavailableError(f"SAM2 repo not found: {repo_root}")

        checkpoint = repo_root / spec["checkpoint"]
        if not checkpoint.is_file():
            raise Sam2UnavailableError(f"Model checkpoint not found: {checkpoint}")

        model_cfg = spec["config"]
        config_path = repo_root / "sam2" / model_cfg
        if not config_path.is_file():
            raise Sam2UnavailableError(f"Model config not found: {config_path}")

        return repo_root, checkpoint, model_cfg

    def _release_predictor(self) -> None:
        if self._predictor is None:
            return

        self._predictor = None
        self._active_model_name = None
        if self._torch is not None and self._device == "cuda":
            try:
                self._torch.cuda.empty_cache()
            except Exception:
                pass


sam2_video_service = Sam2VideoService()


def get_sam2_video_service() -> Sam2VideoService:
    return sam2_video_service
