from __future__ import annotations

import logging
import sys
import threading
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image as PILImage

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SAM2_MODEL_NAME = "sam2_hiera_large"
SAM2_MODEL_REGISTRY = {
    "sam2_hiera_tiny": {
        "checkpoint": "checkpoints/sam2.1_hiera_tiny.pt",
        "config": "configs/sam2.1/sam2.1_hiera_t.yaml",
    },
    "sam2_hiera_small": {
        "checkpoint": "checkpoints/sam2.1_hiera_small.pt",
        "config": "configs/sam2.1/sam2.1_hiera_s.yaml",
    },
    "sam2_hiera_base_plus": {
        "checkpoint": "checkpoints/sam2.1_hiera_base_plus.pt",
        "config": "configs/sam2.1/sam2.1_hiera_b+.yaml",
    },
    "sam2_hiera_large": {
        "checkpoint": "checkpoints/sam2.1_hiera_large.pt",
        "config": "configs/sam2.1/sam2.1_hiera_l.yaml",
    },
}


@dataclass
class Sam2PredictionResult:
    points: list[list[float]]
    score: float
    model_name: str
    candidate: str
    polygon_epsilon: float
    mask_threshold: float
    max_hole_area: float
    num_contours: int
    mask_area: float


class Sam2UnavailableError(RuntimeError):
    pass


class Sam2PredictionError(RuntimeError):
    pass


class Sam2Service:
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
                from sam2.build_sam import build_sam2
                from sam2.sam2_image_predictor import SAM2ImagePredictor
            except Exception as exc:  # pragma: no cover - depends on optional runtime deps
                self.load_error = f"SAM2 dependencies are not available: {exc}"
                raise Sam2UnavailableError(self.load_error) from exc

            requested_device = settings.sam2_device
            cuda_available = torch.cuda.is_available()
            next_device = requested_device
            if requested_device == "auto":
                next_device = "cuda" if cuda_available else "cpu"
            if next_device == "cuda" and not cuda_available:
                logger.warning("CUDA is not available for SAM2. Falling back to CPU.")
                next_device = "cpu"
            self._torch = torch
            self._device = next_device
            self._dtype = self._select_autocast_dtype(torch)

            try:
                self._release_predictor()
                sam2_model = build_sam2(
                    model_cfg,
                    str(checkpoint),
                    device=self._device,
                )
                self._predictor = SAM2ImagePredictor(
                    sam2_model,
                    mask_threshold=settings.sam2_mask_threshold,
                    max_hole_area=settings.sam2_max_hole_area,
                    max_sprinkle_area=settings.sam2_max_sprinkle_area,
                )
                self._active_model_name = target_model_name
                self.load_error = None
                logger.warning(
                    "SAM2 model loaded model=%s checkpoint=%s config=%s device=%s dtype=%s",
                    target_model_name,
                    checkpoint,
                    model_cfg,
                    self._device,
                    self._dtype,
                )
            except Exception as exc:  # pragma: no cover - model load depends on local weights
                self.load_error = f"SAM2 model failed to load: {exc}"
                raise Sam2UnavailableError(self.load_error) from exc

    def predict(
        self,
        image_path: str,
        model_name: str,
        point_coords: list[list[float]],
        point_labels: list[int],
        box: list[float] | None,
        multimask_output: bool,
        candidate: str,
        polygon_epsilon: float,
        min_mask_area: float,
        mask_threshold: float,
        max_hole_area: float,
    ) -> Sam2PredictionResult:
        self.load(model_name)
        if not self.ready:
            raise Sam2UnavailableError(self.load_error or "SAM2 model is not loaded")

        if len(point_coords) != len(point_labels):
            raise Sam2PredictionError("point_coords and point_labels length mismatch")
        if not point_coords and box is None:
            raise Sam2PredictionError("At least one point or one box prompt is required")

        try:
            import cv2
            import numpy as np
        except Exception as exc:  # pragma: no cover - depends on optional runtime deps
            raise Sam2UnavailableError(f"SAM2 post-processing dependencies are not available: {exc}") from exc

        image_file = Path(image_path)
        if not image_file.is_file():
            raise Sam2PredictionError("Image file not found")

        with PILImage.open(image_file) as image:
            image_array = np.array(image.convert("RGB"))

        point_coords_array = np.array(point_coords, dtype=np.float32) if point_coords else None
        point_labels_array = np.array(point_labels, dtype=np.int32) if point_labels else None
        box_array = np.array(box, dtype=np.float32) if box is not None else None

        with self._lock:
            with self._torch.inference_mode():
                with self._autocast_context():
                    self._predictor.set_image(image_array)
                    masks, scores, _ = self._predictor.predict(
                        point_coords=point_coords_array,
                        point_labels=point_labels_array,
                        box=box_array,
                        multimask_output=multimask_output,
                        return_logits=True,
                    )

        best_index = self._select_candidate_index(scores, candidate, np)
        mask_logits = masks[best_index]
        mask = mask_logits > mask_threshold
        mask = self._fill_small_holes(mask, cv2, np, max_hole_area)
        score = float(scores[best_index])
        points, num_contours, mask_area = self._mask_to_polygon(mask, cv2, np, polygon_epsilon, min_mask_area)
        return Sam2PredictionResult(
            points=points,
            score=score,
            model_name=self._active_model_name or model_name,
            candidate=candidate,
            polygon_epsilon=polygon_epsilon,
            mask_threshold=mask_threshold,
            max_hole_area=max_hole_area,
            num_contours=num_contours,
            mask_area=mask_area,
        )

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

            area = cv2.contourArea(contour)
            if area <= max_hole_area:
                cv2.drawContours(mask_uint8, [contour], -1, 255, thickness=-1)

        return mask_uint8.astype(bool)

    def _select_candidate_index(self, scores: Any, candidate: str, np: Any) -> int:
        if candidate == "best":
            return int(np.argmax(scores))

        index = int(candidate)
        if index < 0 or index >= len(scores):
            raise Sam2PredictionError(f"SAM2 candidate {index} is not available")
        return index

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

    def _model_name(self, checkpoint: Path, config: str) -> str:
        value = f"{checkpoint.name} {config}".lower()
        if "hiera_t" in value or "tiny" in value:
            return "sam2_hiera_tiny"
        if "hiera_s" in value or "small" in value:
            return "sam2_hiera_small"
        if "hiera_b+" in value or "base_plus" in value:
            return "sam2_hiera_base_plus"
        if "hiera_l" in value or "large" in value:
            return "sam2_hiera_large"
        return checkpoint.stem


sam2_service = Sam2Service()


def get_sam2_service() -> Sam2Service:
    return sam2_service
