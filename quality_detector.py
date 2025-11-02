"""High level quality detection utilities for photo_sorter GUI."""
from __future__ import annotations

import os
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None  # type: ignore

try:
    import mediapipe as mp  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    mp = None  # type: ignore


JPG_EXTENSIONS = {"jpg", "jpeg", "jpe"}


class AnalyzerUnavailableError(RuntimeError):
    """Raised when the analyzer cannot be constructed due to missing deps."""


@dataclass
class EyeIssue:
    bbox: Tuple[int, int, int, int]
    status: str
    confidence: float


@dataclass
class ExposureIssue:
    status: str
    confidence: float
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class PhotoQualityResult:
    path: str
    rel_path: str
    eye_issues: List[EyeIssue] = field(default_factory=list)
    exposure_issue: Optional[ExposureIssue] = None

    @property
    def has_issue(self) -> bool:
        exposure_flag = bool(self.exposure_issue and self.exposure_issue.status != "正常")
        return bool(self.eye_issues or exposure_flag)

    @property
    def closed_eye_summary(self) -> str:
        if not self.eye_issues:
            return "无"
        labels = []
        for issue in self.eye_issues:
            labels.append(issue.status)
        return ",".join(labels)


def _read_image_bgr(path: str) -> Optional[np.ndarray]:
    if cv2 is None:
        return None
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        return image
    except Exception:
        return None


def _normalized_to_pixel(landmark, width: int, height: int) -> Tuple[float, float]:
    return float(landmark.x * width), float(landmark.y * height)


LEFT_EYE_IDX = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_IDX = [362, 385, 387, 263, 373, 380]
LEFT_IRIS_IDX = [468, 469, 470, 471]
RIGHT_IRIS_IDX = [473, 474, 475, 476]


def _eye_aspect_ratio(points: np.ndarray) -> float:
    if points.shape[0] < 6:
        return 0.0
    a = np.linalg.norm(points[1] - points[5])
    b = np.linalg.norm(points[2] - points[4])
    c = np.linalg.norm(points[0] - points[3])
    if c <= 1e-6:
        return 0.0
    return float((a + b) / (2.0 * c))


def _iris_offset(eye_points: np.ndarray, iris_points: np.ndarray) -> Tuple[float, float]:
    if eye_points.shape[0] < 6 or iris_points.shape[0] == 0:
        return 0.5, 0.5
    min_xy = eye_points.min(axis=0)
    max_xy = eye_points.max(axis=0)
    span = np.maximum(max_xy - min_xy, 1e-6)
    iris_center = iris_points.mean(axis=0)
    normalized = (iris_center - min_xy) / span
    return float(normalized[0]), float(normalized[1])


def _rect_from_points(points: np.ndarray, image_shape: Tuple[int, int, int], padding: float = 0.1) -> Tuple[int, int, int, int]:
    h, w = image_shape[:2]
    min_xy = points.min(axis=0)
    max_xy = points.max(axis=0)
    width_height = max_xy - min_xy
    min_xy = min_xy - width_height * padding
    max_xy = max_xy + width_height * padding
    x1 = int(max(0, math.floor(min_xy[0])))
    y1 = int(max(0, math.floor(min_xy[1])))
    x2 = int(min(w, math.ceil(max_xy[0])))
    y2 = int(min(h, math.ceil(max_xy[1])))
    return x1, y1, x2, y2


def _analyze_exposure(image: np.ndarray) -> ExposureIssue:
    if image.ndim == 3 and image.shape[2] == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if cv2 is not None else image.mean(axis=2)
    else:
        gray = image if image.ndim == 2 else image[..., 0]
    gray = gray.astype(np.float32)

    mean_val = float(np.mean(gray))
    std_val = float(np.std(gray))
    dark_ratio = float(np.mean(gray <= 35))
    shadow_ratio = float(np.mean(gray <= 15))
    bright_ratio = float(np.mean(gray >= 220))
    highlight_ratio = float(np.mean(gray >= 245))

    status = "正常"
    confidence = 1.0
    if mean_val < 70 and bright_ratio < 0.1:
        strength = (70 - mean_val) / 70 + shadow_ratio * 0.8
        confidence = float(min(1.0, max(0.2, strength)))
        status = "欠曝"
    elif mean_val > 190 and dark_ratio < 0.08:
        strength = (mean_val - 190) / 65 + highlight_ratio * 0.9
        confidence = float(min(1.0, max(0.2, strength)))
        status = "过曝"

    return ExposureIssue(
        status=status,
        confidence=confidence,
        metrics={
            "mean": mean_val,
            "std": std_val,
            "shadow_ratio": shadow_ratio,
            "highlight_ratio": highlight_ratio,
        },
    )


class PhotoQualityAnalyzer:
    """Performs waste shot detection (closed eyes, exposure issues)."""

    def __init__(self, *, prefer_gpu: bool = False):
        if mp is None:
            raise AnalyzerUnavailableError(
                "未检测到 mediapipe，请先安装 mediapipe（pip install mediapipe）。"
            )
        self._face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            refine_landmarks=True,
            max_num_faces=6,
        )
        self._prefer_gpu = prefer_gpu

    def close(self) -> None:
        try:
            if self._face_mesh:
                self._face_mesh.close()
        except Exception:
            pass

    # Mediapipe returns normalized coords; convert to numpy arrays for processing.
    def _extract_eye_issue(self, image: np.ndarray, landmarks, width: int, height: int) -> List[EyeIssue]:
        issues: List[EyeIssue] = []
        lm_array = []
        for lm in landmarks.landmark:
            lm_array.append(_normalized_to_pixel(lm, width, height))
        lm_array = np.array(lm_array, dtype=np.float32)

        def gather(indices: List[int]) -> np.ndarray:
            pts = lm_array[indices]
            return pts

        left_eye = gather(LEFT_EYE_IDX)
        right_eye = gather(RIGHT_EYE_IDX)
        left_iris = gather(LEFT_IRIS_IDX)
        right_iris = gather(RIGHT_IRIS_IDX)

        for eye_points, iris_points, label in (
            (left_eye, left_iris, "左眼"),
            (right_eye, right_iris, "右眼"),
        ):
            ear = _eye_aspect_ratio(eye_points)
            iris_x, iris_y = _iris_offset(eye_points, iris_points)
            status = None
            confidence = 0.0
            if ear < 0.17:
                status = f"{label}闭眼"
                confidence = float(min(1.0, (0.17 - ear) / 0.08 + 0.3))
            elif ear < 0.23:
                status = f"{label}半眨眼"
                confidence = float(min(1.0, (0.23 - ear) / 0.05 + 0.2))
            elif iris_y < 0.22 or iris_y > 0.78 or iris_x < 0.18 or iris_x > 0.82:
                status = f"{label}视线异常"
                deviation = max(abs(iris_y - 0.5), abs(iris_x - 0.5))
                confidence = float(min(1.0, deviation * 1.6))

            if status:
                bbox = _rect_from_points(eye_points, image.shape, padding=0.25)
                issues.append(EyeIssue(bbox=bbox, status=status, confidence=confidence))
        return issues

    def analyze_image(self, path: str, *, rel_path: Optional[str] = None) -> Optional[PhotoQualityResult]:
        image = _read_image_bgr(path)
        if image is None:
            return None
        height, width = image.shape[:2]
        rgb_image = image[:, :, ::-1]
        result = self._face_mesh.process(rgb_image)
        eye_issues: List[EyeIssue] = []
        if result and result.multi_face_landmarks:
            for face_landmarks in result.multi_face_landmarks:
                eye_issues.extend(self._extract_eye_issue(image, face_landmarks, width, height))
        exposure_issue = _analyze_exposure(image)
        rel = rel_path or os.path.basename(path)
        analysis = PhotoQualityResult(
            path=path,
            rel_path=rel,
            eye_issues=eye_issues,
            exposure_issue=exposure_issue,
        )
        return analysis

    def analyze_folder(
        self,
        folder: str,
        *,
        include_normal: bool = False,
        cancel_event: Optional["threading.Event"] = None,
        progress_cb: Optional[Callable[[int, int, str, Optional[PhotoQualityResult]], None]] = None,
    ) -> List[PhotoQualityResult]:
        all_files: List[str] = []
        for root, _dirs, files in os.walk(folder):
            for name in files:
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext in JPG_EXTENSIONS:
                    all_files.append(os.path.join(root, name))
        all_files.sort()
        total = len(all_files)
        results: List[PhotoQualityResult] = []
        for idx, file_path in enumerate(all_files, start=1):
            if cancel_event is not None and cancel_event.is_set():
                break
            rel_path = os.path.relpath(file_path, folder)
            analysis = self.analyze_image(file_path, rel_path=rel_path)
            if analysis is not None:
                if include_normal or analysis.has_issue:
                    results.append(analysis)
            if progress_cb:
                progress_cb(idx, total, file_path, analysis)
        return results


__all__ = [
    "AnalyzerUnavailableError",
    "EyeIssue",
    "ExposureIssue",
    "PhotoQualityAnalyzer",
    "PhotoQualityResult",
]
