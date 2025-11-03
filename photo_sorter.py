# 陈同学影像管理助手 v1.7.8
# 更新点：
# - 开始/完成提示音
# - 复制过程无弹窗；主界面显示进度与速度（MB/s）
# - 进度条按字节比例；速度=累计字节/耗时
# - 保留星标提取、撤销、主题切换、可拖动分割、稳定日志、容量显示修复、版权提示
# - 弹窗统一 Aurora 风格并适配暗黑主题
# - 新增 Aurora 风格文本输入弹窗，统一拍摄名称输入体验
# - 星标提取按钮直接切换状态并记录日志，进度条实时刷新显示百分比，按钮风格保持一致
# - 复制进度改为队列驱动刷新，彻底消除跨线程 UI 调用引发的卡顿
# - 全新动画进度条：真实进度优先，缺失数据时模拟推进，确保界面流畅
# - 进度条新增预计剩余时间显示，随平均速率实时更新
# - 操作按钮样式统一并区分启用、禁用与暂停状态

import os, sys, json, time, shutil, platform, subprocess, re, threading, queue, math
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from types import SimpleNamespace



from app.bootstrap_models import get_current_providers, register_session_builder, rebuild_sessions
from app.providers import cuda_available, load_pref, pick_providers, save_pref

VERSION = "v1.7.8"
CONFIG_FILE = "photo_sorter_config.json"
CATEGORIES = ["婚礼", "写真", "日常记录", "旅游记录", "商业活动拍摄"]
THEMES = ["暗黑"]
DEFAULT_THEME_KEY = "dark"
LOG_PANEL_WIDTH = 360
COPY_BUFFER_SIZE = 4 * 1024 * 1024

SUPPRESS_RUNTIME_WARNINGS = any(arg in ("-h", "--help") for arg in sys.argv[1:])

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - best effort fallback for limited environments
    psutil = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 psutil，部分磁盘信息功能将受限。", file=sys.stderr)

try:
    from PIL import Image, ExifTags, ImageDraw, ImageTk, ImageStat
except Exception:  # pragma: no cover - optional dependency fallback
    Image = None
    ExifTags = SimpleNamespace(TAGS={})
    ImageDraw = None
    ImageTk = None
    ImageStat = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 Pillow，EXIF 读取功能将受限。", file=sys.stderr)

try:
    import exifread
except Exception:  # pragma: no cover - optional dependency fallback
    exifread = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 exifread，将使用文件修改时间作为拍摄时间。", file=sys.stderr)

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    np = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 numpy，部分智能检测功能将受限。", file=sys.stderr)

try:
    import mediapipe as mp  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    mp = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 MediaPipe，无法启用智能闭眼检测。", file=sys.stderr)

try:
    from insightface.app import FaceAnalysis  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    FaceAnalysis = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[提示] 未检测到 insightface，GPU 加速闭眼检测将不可用。", file=sys.stderr)

try:
    import onnxruntime  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    onnxruntime = None

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    np = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 numpy，部分智能检测功能将受限。", file=sys.stderr)

try:
    import mediapipe as mp  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    mp = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 MediaPipe，无法启用智能闭眼检测。", file=sys.stderr)

try:
    from insightface.app import FaceAnalysis  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    FaceAnalysis = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[提示] 未检测到 insightface，GPU 加速闭眼检测将不可用。", file=sys.stderr)

try:
    import onnxruntime  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    onnxruntime = None

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    np = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 numpy，部分智能检测功能将受限。", file=sys.stderr)

try:
    import mediapipe as mp  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    mp = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 MediaPipe，无法启用智能闭眼检测。", file=sys.stderr)

try:
    from insightface.app import FaceAnalysis  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    FaceAnalysis = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[提示] 未检测到 insightface，GPU 加速闭眼检测将不可用。", file=sys.stderr)

try:
    import onnxruntime  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    onnxruntime = None

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    np = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 numpy，部分智能检测功能将受限。", file=sys.stderr)

try:
    import mediapipe as mp  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    mp = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 MediaPipe，无法启用智能闭眼检测。", file=sys.stderr)

try:
    from insightface.app import FaceAnalysis  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    FaceAnalysis = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[提示] 未检测到 insightface，GPU 加速闭眼检测将不可用。", file=sys.stderr)

try:
    import onnxruntime  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    onnxruntime = None

try:
    import winsound
    def beep_start(): winsound.MessageBeep(winsound.MB_ICONASTERISK)
    def beep_done():  winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
except Exception:
    def beep_start(): pass
    def beep_done():  pass

# ---------- 工具 ----------
def ts(): return datetime.now().strftime("%H:%M:%S")

def bytes_to_human(n) -> str:
    try: n = int(n)
    except Exception: return "N/A"
    units = ["B","KB","MB","GB","TB","PB","EB"]
    i = 0; v = float(n)
    while v >= 1024.0 and i < len(units) - 1:
        v /= 1024.0; i += 1
    return f"{v:.2f} {units[i]}"


def format_eta(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "剩余时间：计算中…"
    seconds = max(seconds, 0.0)
    if seconds < 1:
        return "剩余约 0 秒"
    if seconds < 60:
        return f"剩余约 {int(seconds)} 秒"
    if seconds < 3600:
        minutes = math.ceil(seconds / 60.0)
        return f"剩余约 {minutes} 分钟"
    hours = seconds / 3600.0
    if hours >= 10:
        hours = math.ceil(hours)
        return f"剩余约 {int(hours)} 小时"
    return f"剩余约 {hours:.1f} 小时"


def enable_high_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes  # Local import to avoid cost on non-Windows

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def set_tk_scaling(root: tk.Tk) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes  # Local import to avoid cost elsewhere

        hdc = ctypes.windll.user32.GetDC(0)
        if not hdc:
            return
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        if dpi <= 0:
            return
        root.tk.call("tk", "scaling", dpi / 96.0)
    except Exception:
        pass


def get_drive_type_code(letter):
    import ctypes
    try: return ctypes.windll.kernel32.GetDriveTypeW(letter + "\\")
    except Exception: return 0

def drive_type_name(code): return {2:"移动",3:"固定",4:"网络",5:"光驱",6:"RAM"}.get(code,"未知")
def is_system_drive(letter): return letter.upper().startswith(os.environ.get("SystemDrive","C:").upper())
def _disk_partitions(all=True):
    if psutil is not None:
        try:
            return psutil.disk_partitions(all=all)
        except Exception:
            pass

    parts = []
    if os.name == "nt":
        try:
            import string

            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    parts.append(SimpleNamespace(device=drive, mountpoint=drive))
        except Exception:
            pass
    else:
        seen = set()
        try:
            with open("/proc/mounts", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    segs = line.split()
                    if len(segs) < 2:
                        continue
                    device, mountpoint = segs[0], segs[1]
                    if any(mountpoint.startswith(prefix) for prefix in ("/proc", "/sys", "/run", "/dev", "/snap")):
                        continue
                    if mountpoint in seen:
                        continue
                    seen.add(mountpoint)
                    parts.append(SimpleNamespace(device=device, mountpoint=mountpoint))
        except Exception:
            pass
        if not parts:
            parts.append(SimpleNamespace(device="/", mountpoint="/"))
    return parts


def list_drives():
    drives = []
    for part in _disk_partitions(all=True):
        mount = getattr(part, "mountpoint", "")
        device = getattr(part, "device", "")
        if mount and not os.path.exists(mount):
            continue
        if os.name == "nt":
            candidate = device.rstrip("\\") or mount.rstrip("\\")
        else:
            candidate = mount or device
        if not candidate:
            continue
        drives.append(candidate)
    if not drives and os.name != "nt":
        drives.append("/")
    # Preserve order while removing duplicates
    seen = []
    for d in drives:
        if d not in seen:
            seen.append(d)
    return seen

def get_drive_label(letter):
    import ctypes
    try:
        vn=ctypes.create_unicode_buffer(1024); fs=ctypes.create_unicode_buffer(1024)
        sn=ctypes.c_ulong(); mcl=ctypes.c_ulong(); fl=ctypes.c_ulong()
        ctypes.windll.kernel32.GetVolumeInformationW(letter+"\\",vn,1024,ctypes.byref(sn),ctypes.byref(mcl),ctypes.byref(fl),fs,1024)
        name=vn.value.strip()
    except Exception: name=""
    if not name and get_drive_type_code(letter)==2: return "U盘"
    return name or "(无名称)"

def get_drive_usage_bytes(root):
    path = root
    if os.name == "nt":
        if len(path) == 2 and path[1] == ":":
            path = path + "\\"
        elif len(path) == 3 and path[1] == ":" and path[2] in ("/", "\\"):
            path = path[0:2] + "\\"
    if psutil is not None:
        try:
            u = psutil.disk_usage(path)
            return u.total, u.free
        except Exception:
            pass
    total, used, free = shutil.disk_usage(path)
    return total, free

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE,"r",encoding="utf-8") as f:
            cfg = json.load(f)
            theme = cfg.get("theme", DEFAULT_THEME_KEY)
            if theme not in {DEFAULT_THEME_KEY}:
                cfg["theme"] = DEFAULT_THEME_KEY
            if "theme" not in cfg:
                cfg["theme"] = DEFAULT_THEME_KEY
            if "sash_ratio" not in cfg: cfg["sash_ratio"] = 0.55
            return cfg
    return {"last_target_root": "", "theme": DEFAULT_THEME_KEY, "sash_ratio": 0.55}

def save_config(cfg):
    with open(CONFIG_FILE,"w",encoding="utf-8") as f: json.dump(cfg,f,ensure_ascii=False,indent=2)

def is_raw_ext(e): return e in {"cr2","cr3","nef","nrw","arw","srf","sr2","raf","rw2","orf","dng","pef","raw"}
def is_jpg_ext(e): return e in {"jpg","jpeg","jpe"}
def is_video_ext(e): return e in {"mp4"}

# ---------- EXIF / XMP ----------
def _parse_exif_str(s):
    s=s.strip()
    if len(s)>=19 and s[4]==":" and s[7]==":": return datetime.strptime(s[:19],"%Y:%m:%d %H:%M:%S")
    return None

def _exif_dt_from_jpg(p):
    if Image is None:
        return None
    try:
        im=Image.open(p); exif=im._getexif()
        if not exif: return None
        tag={ExifTags.TAGS.get(k,k):v for k,v in exif.items()}
        for k in("DateTimeOriginal","DateTimeDigitized","DateTime"):
            v=tag.get(k)
            if isinstance(v,str):
                dt=_parse_exif_str(v)
                if dt: return dt
    except Exception: pass
    return None

def _exif_dt_from_any(p):
    if exifread is None:
        return None
    try:
        with open(p,"rb") as f: tags=exifread.process_file(f,stop_tag="EXIF DateTimeOriginal",details=False)
        for k in("EXIF DateTimeOriginal","Image DateTime","EXIF DateTimeDigitized"):
            if k in tags:
                dt=_parse_exif_str(str(tags[k]))
                if dt: return dt
    except Exception: pass
    return None

def get_capture_dt(p):
    ext=p.rsplit(".",1)[-1].lower() if "." in p else ""
    if is_jpg_ext(ext): dt=_exif_dt_from_jpg(p) or _exif_dt_from_any(p)
    elif is_raw_ext(ext): dt=_exif_dt_from_any(p)
    else: dt=None
    if dt: return dt
    try: return datetime.fromtimestamp(os.path.getmtime(p))
    except Exception: return datetime.now()

# ---------- 星标检测 ----------
import re
_XMP_RATING_PATTERNS = [
    re.compile(rb"<xmp:Rating>\s*(-?\d+)\s*</xmp:Rating>", re.I),
    re.compile(rb"Rating=\"\s*(-?\d+)\s*\"", re.I),
]

def _find_rating_in_bytes(b: bytes) -> int:
    for pat in _XMP_RATING_PATTERNS:
        m = pat.search(b)
        if m:
            try: return int(m.group(1))
            except Exception: pass
    return 0

def is_starred_file(path: str) -> bool:
    stem, _ = os.path.splitext(path)
    sidecar = stem + ".xmp"
    try:
        if os.path.isfile(sidecar):
            with open(sidecar, "rb") as f:
                rating = _find_rating_in_bytes(f.read(512*1024))
                return rating >= 1
    except Exception:
        pass
    try:
        with open(path, "rb") as f:
            rating = _find_rating_in_bytes(f.read(1024*1024))
            return rating >= 1
    except Exception:
        return False

# ---------- 其它工具 ----------
def unique_path(d,f):
    n,e=os.path.splitext(f); c=os.path.join(d,f); i=1
    while os.path.exists(c):
        c=os.path.join(d,f"{n}({i}){e}"); i+=1
    return c

# ---------- 日志 ----------
def log_init_if_empty(text_widget, line):
    if text_widget is None:
        print(f"[{ts()}] {line}")
        return
    if float(text_widget.index("end-1c"))==1.0:
        text_widget.configure(state="normal")
        text_widget.insert("end", f"[{ts()}] {line}\n")
        text_widget.configure(state="disabled")

def log_add(text_widget, line):
    if text_widget is None:
        print(f"[{ts()}] {line}")
        return
    text_widget.configure(state="normal")
    text_widget.insert("end", f"[{ts()}] {line}\n")
    text_widget.see("end")
    text_widget.configure(state="disabled")


# ---------- 废片检测 ----------
LEFT_EYE_EAR_POINTS = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_EAR_POINTS = [263, 387, 385, 362, 380, 373]
LEFT_EYE_BOUNDARY_POINTS = [33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7]
RIGHT_EYE_BOUNDARY_POINTS = [263, 466, 388, 387, 386, 385, 384, 398, 362, 382, 381, 380, 374, 373, 390, 249]
LEFT_IRIS_POINTS = [468, 469, 470, 471, 472]
RIGHT_IRIS_POINTS = [473, 474, 475, 476, 477]

CLOSED_EAR_THRESHOLD = 0.19
PARTIAL_EAR_THRESHOLD = 0.23


@dataclass
class EyeRegion:
    bbox: Tuple[int, int, int, int]
    issues: List[str] = field(default_factory=list)
    ear: float = 0.0
    side: str = "left"


@dataclass
class DetectionResult:
    path: str
    issues: List[str] = field(default_factory=list)
    closed_eye_count: int = 0
    partial_eye_count: int = 0
    abnormal_eye_count: int = 0
    eye_regions: List[EyeRegion] = field(default_factory=list)
    mean_luminance: float = 0.0
    exposure_issue: Optional[str] = None
    clipped_ratio: float = 0.0


# 兼容早期代码中使用的 PhotoQualityResult 类型名称，防止导入时出现 NameError。
# 废片检测结果结构未发生变化，因此直接复用 DetectionResult。
PhotoQualityResult = DetectionResult


class PhotoWasteDetector:
    def __init__(self, providers: Optional[List[str]] = None) -> None:
        self._face_mesh = None
        self._mesh_lock = threading.Lock()
        self._insightface = None
        self.eye_detection_ready = False
        self.requirements_hint = (
            "安装依赖：pip install mediapipe==0.10.9 opencv-python numpy\n"
            "可选安装 insightface 与 onnxruntime 以启用更精准的人眼检测（CPU 模式）。\n"
            "模型下载：https://huggingface.co/deepinsight/insightface/resolve/main/models/buffalo_l.zip\n"
            "安装后将模型解压到 %APPDATA%/insightface/models 或 ~/.insightface/models。"
        )
        desired = list(providers) if providers else ["CPUExecutionProvider"]
        if not desired:
            desired = ["CPUExecutionProvider"]
        self.providers = desired
        self.current_providers: List[str] = list(self.providers)
        self.available_providers: List[str] = []
        self.refresh_available_providers()
        self._init_models()

    def refresh_available_providers(self) -> List[str]:
        providers: List[str] = []
        if onnxruntime is not None:
            try:
                providers = list(onnxruntime.get_available_providers())
            except Exception:
                providers = []
        self.available_providers = providers
        return providers

    def _init_models(self) -> None:
        self._init_face_mesh()
        self._init_insightface(self.providers)

    def _init_face_mesh(self) -> None:
        if mp is None or np is None:
            return
        try:
            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True,
                refine_landmarks=True,
                max_num_faces=10,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self.eye_detection_ready = True
        except Exception as exc:
            self._face_mesh = None
            self.eye_detection_ready = False
            if not SUPPRESS_RUNTIME_WARNINGS:
                print(f"[警告] 初始化 MediaPipe FaceMesh 失败：{exc}", file=sys.stderr)

    def _init_insightface(self, providers: Optional[List[str]]) -> None:
        if FaceAnalysis is None:
            self.current_providers = list(providers or ["CPUExecutionProvider"])
            return
        try:
            runtime_providers = providers or ["CPUExecutionProvider"]
            engine = FaceAnalysis(name="buffalo_l", providers=runtime_providers)
            engine.prepare(ctx_id=0, det_size=(640, 640))
            self._insightface = engine
            self.current_providers = list(runtime_providers)
        except Exception as exc:
            self._insightface = None
            if not SUPPRESS_RUNTIME_WARNINGS:
                print(f"[提示] InsightFace 初始化失败：{exc}", file=sys.stderr)

    def set_providers(self, providers: List[str]) -> Dict[str, List[str]]:
        desired = ["CPUExecutionProvider"]
        self.providers = list(desired)
        self.current_providers = list(desired)
        if FaceAnalysis is not None and onnxruntime is not None:
            try:
                engine = FaceAnalysis(name="buffalo_l", providers=desired)
                engine.prepare(ctx_id=0, det_size=(640, 640))
                self._insightface = engine
            except Exception as exc:
                raise RuntimeError(f"InsightFace 初始化失败：{exc}") from exc
        return {"providers": list(self.current_providers)}

    def describe_model_inventory(self) -> List[str]:
        messages: List[str] = []
        if FaceAnalysis is None:
            messages.append("insightface 未安装，跳过模型自检。")
            return messages
        candidates: List[Path] = []
        home_model = Path.home() / ".insightface" / "models"
        if home_model.exists():
            candidates.append(home_model)
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            if appdata:
                win_model = Path(appdata) / "insightface" / "models"
                if win_model.exists():
                    candidates.append(win_model)
        if not candidates:
            messages.append("未发现 insightface 模型目录，请按说明下载并解压。")
            return messages
        for path in candidates:
            try:
                onnx_files = [p.name for p in path.rglob("*.onnx")][:3]
            except Exception:
                onnx_files = []
            if onnx_files:
                messages.append(f"模型目录：{path}")
                messages.append(f"示例模型文件：{', '.join(onnx_files)}")
            else:
                messages.append(f"模型目录：{path}（未找到 .onnx 文件）")
        return messages

    def close(self) -> None:
        mesh = self._face_mesh
        if mesh is not None:
            try:
                mesh.close()
            except Exception:
                pass
        self._face_mesh = None
        self.eye_detection_ready = False

    @staticmethod
    def _landmark_to_point(landmark, width: int, height: int) -> Tuple[int, int]:
        return int(landmark.x * width), int(landmark.y * height)

    @staticmethod
    def _eye_aspect_ratio(points: List[Tuple[int, int]]) -> float:
        if len(points) != 6:
            return 0.0
        p1, p2, p3, p4, p5, p6 = points
        def _dist(a, b):
            return math.hypot(a[0] - b[0], a[1] - b[1])

        denom = _dist(p1, p4)
        if denom == 0:
            return 0.0
        ear = (_dist(p2, p6) + _dist(p3, p5)) / (2.0 * denom)
        return ear

    @staticmethod
    def _bounding_box(points: List[Tuple[int, int]], width: int, height: int, padding: int = 4) -> Tuple[int, int, int, int]:
        if not points:
            return 0, 0, width, height
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x0 = max(0, min(xs) - padding)
        y0 = max(0, min(ys) - padding)
        x1 = min(width, max(xs) + padding)
        y1 = min(height, max(ys) + padding)
        return x0, y0, x1, y1

    @staticmethod
    def _iris_issue(box: Tuple[int, int, int, int], iris_points: List[Tuple[int, int]]) -> Optional[str]:
        if not iris_points:
            return None
        x0, y0, x1, y1 = box
        w = max(1, x1 - x0)
        h = max(1, y1 - y0)
        cx = sum(p[0] for p in iris_points) / len(iris_points)
        cy = sum(p[1] for p in iris_points) / len(iris_points)
        rel_x = (cx - x0) / w
        rel_y = (cy - y0) / h
        if rel_y < 0.15 or rel_y > 0.85 or rel_x < 0.12 or rel_x > 0.88:
            return "眼球偏离"
        return None

    def _analyze_face(self, face_landmarks, width: int, height: int, result: DetectionResult) -> None:
        if np is None:
            return
        def _collect_points(indices):
            pts = []
            for idx in indices:
                if idx < len(face_landmarks.landmark):
                    pts.append(self._landmark_to_point(face_landmarks.landmark[idx], width, height))
            return pts

        for side, ear_indices, boundary_indices, iris_indices in (
            ("left", LEFT_EYE_EAR_POINTS, LEFT_EYE_BOUNDARY_POINTS, LEFT_IRIS_POINTS),
            ("right", RIGHT_EYE_EAR_POINTS, RIGHT_EYE_BOUNDARY_POINTS, RIGHT_IRIS_POINTS),
        ):
            eye_points = _collect_points(ear_indices)
            if len(eye_points) != 6:
                continue
            ear = self._eye_aspect_ratio(eye_points)
            boundary_points = _collect_points(boundary_indices)
            iris_points = _collect_points(iris_indices)
            box = self._bounding_box(boundary_points or eye_points, width, height)
            issues: List[str] = []
            if ear <= CLOSED_EAR_THRESHOLD:
                issues.append("闭眼")
                result.closed_eye_count += 1
            elif ear <= PARTIAL_EAR_THRESHOLD:
                issues.append("半眨眼")
                result.partial_eye_count += 1
            iris_issue = self._iris_issue(box, iris_points)
            if iris_issue:
                issues.append(iris_issue)
                result.abnormal_eye_count += 1
            if not issues:
                continue
            result.eye_regions.append(EyeRegion(bbox=box, issues=issues, ear=ear, side=side))
            for issue in issues:
                if issue not in result.issues:
                    result.issues.append(issue)

    def _analyze_exposure(self, image: Image.Image, result: DetectionResult) -> None:
        try:
            if ImageStat is not None:
                stats = ImageStat.Stat(image.convert("L"))
                mean = float(stats.mean[0])
            elif np is not None:
                gray = np.asarray(image.convert("L"))
                mean = float(gray.mean())
            else:
                # 简易平均
                pixels = list(image.convert("L").getdata())
                mean = sum(pixels) / max(1, len(pixels))
        except Exception:
            mean = 0.0
        result.mean_luminance = mean
        exposure_issue = None
        clipped_ratio = 0.0
        try:
            gray = np.asarray(image.convert("L")) if np is not None else None
            if gray is not None:
                dark_ratio = float(np.mean(gray < 40))
                bright_ratio = float(np.mean(gray > 215))
                clipped_ratio = max(dark_ratio, bright_ratio)
                if mean < 55 and dark_ratio > 0.25:
                    exposure_issue = "欠曝"
                elif mean > 200 and bright_ratio > 0.25:
                    exposure_issue = "过曝"
        except Exception:
            exposure_issue = None
            clipped_ratio = 0.0
        if exposure_issue:
            result.exposure_issue = exposure_issue
            if exposure_issue not in result.issues:
                result.issues.append(exposure_issue)
        result.clipped_ratio = clipped_ratio

    def analyze_image(self, path: str) -> Optional[DetectionResult]:
        if Image is None:
            return None
        try:
            with Image.open(path) as im:
                image = im.convert("RGB")
        except Exception:
            return None

        result = DetectionResult(path=path)
        self._analyze_exposure(image, result)

        mesh = self._face_mesh
        if mesh is not None and self.eye_detection_ready and np is not None:
            arr = np.asarray(image)
            with self._mesh_lock:
                mesh_result = mesh.process(arr)
            if mesh_result and mesh_result.multi_face_landmarks:
                for face_landmarks in mesh_result.multi_face_landmarks:
                    self._analyze_face(face_landmarks, image.width, image.height, result)

        if not result.issues:
            return None
        return result


class WasteDetectionUI:
    def __init__(self, root: tk.Tk, frame: ttk.Frame, theme_key: str, on_back) -> None:
        self.root = root
        self.frame = frame
        self.theme_key = theme_key
        self.on_back = on_back
        self.detector = PhotoWasteDetector(["CPUExecutionProvider"])
        self.folder_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="待机")
        self.summary_var = tk.StringVar(value="尚未检测")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_pct_var = tk.StringVar(value="0.0%")
        self.progress_eta_var = tk.StringVar(value="预计剩余时间：估算中…")
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        self._results: Dict[str, DetectionResult] = {}
        self._preview_photo = None
        self._prompt_queue: "queue.Queue[DetectionResult]" = queue.Queue()
        self._prompt_active = False
        self._processed_files = 0
        self._total_files = 0
        self._closed_count = 0
        self._half_count = 0
        self._abnormal_count = 0
        self._under_count = 0
        self._over_count = 0
        self._progress_state: Dict[str, Any] = {}
        self._progress_job: Optional[str] = None

        self._build_ui()
        self.apply_theme(theme_key)
        self._update_detector_hint()
        self._log_provider_status()

    def _build_ui(self) -> None:
        self.frame.grid_columnconfigure(0, weight=3)
        self.frame.grid_columnconfigure(1, weight=2)
        self.frame.grid_rowconfigure(0, weight=1)

        left_col = ttk.Frame(self.frame, style="AuroraPanel.TFrame")
        left_col.grid(row=0, column=0, sticky="nsew")
        left_col.grid_rowconfigure(1, weight=1)
        left_col.grid_columnconfigure(0, weight=1)

        control_card = ttk.Frame(left_col, style="AuroraCard.TFrame", padding=(28, 24))
        control_card.grid(row=0, column=0, sticky="ew")
        control_card.grid_columnconfigure(1, weight=1)
        ttk.Label(control_card, text="废片检测", style="AuroraSection.TLabel").grid(row=0, column=0, sticky="w", columnspan=3)

        ttk.Label(control_card, text="待检测文件夹", style="AuroraBody.TLabel").grid(row=1, column=0, sticky="e", pady=(16, 0))
        entry = ttk.Entry(control_card, textvariable=self.folder_var, width=60, state="readonly", style="Aurora.TEntry")
        entry.grid(row=1, column=1, sticky="ew", pady=(16, 0))
        self.browse_btn = ttk.Button(control_card, text="浏览", style="AuroraPrimary.TButton", command=self.choose_folder)
        self.browse_btn.grid(row=1, column=2, sticky="w", padx=(16, 0), pady=(16, 0))

        self.detector_hint = ttk.Label(
            control_card,
            text="",
            style="AuroraBody.TLabel",
            wraplength=520,
            justify="left",
        )
        self.detector_hint.grid(row=2, column=0, columnspan=3, sticky="w", pady=(18, 0))

        btn_row = ttk.Frame(control_card, style="AuroraCard.TFrame")
        btn_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        for col in range(3):
            btn_row.grid_columnconfigure(col, weight=0)
        btn_row.grid_columnconfigure(2, weight=1)

        self.start_btn = ttk.Button(btn_row, text="开始检测", style="AuroraPrimary.TButton", command=self.start_detection)
        self.start_btn.grid(row=0, column=0, sticky="w")
        self.stop_btn = ttk.Button(btn_row, text="停止", style="AuroraWarning.TButton", command=self.stop_detection, state="disabled")
        self.stop_btn.grid(row=0, column=1, sticky="w", padx=(16, 0))
        self.back_btn = ttk.Button(btn_row, text="返回导入界面", style="AuroraGhost.TButton", command=self._handle_back)
        self.back_btn.grid(row=0, column=2, sticky="e")

        progress_panel = ttk.Frame(control_card, style="AuroraCard.TFrame")
        progress_panel.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(20, 0))
        progress_panel.grid_columnconfigure(0, weight=1)

        self.progress_bar = ttk.Progressbar(
            progress_panel,
            mode="determinate",
            variable=self.progress_var,
            maximum=100.0,
            style="Aurora.Horizontal.TProgressbar",
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew")

        progress_info = ttk.Frame(progress_panel, style="AuroraCard.TFrame")
        progress_info.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        progress_info.grid_columnconfigure(0, weight=0)
        progress_info.grid_columnconfigure(1, weight=1)
        ttk.Label(progress_info, textvariable=self.progress_pct_var, style="AuroraStatus.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(progress_info, textvariable=self.progress_eta_var, style="AuroraStatus.TLabel").grid(row=0, column=1, sticky="e")

        ttk.Label(control_card, textvariable=self.status_var, style="AuroraStatus.TLabel").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(16, 0)
        )
        ttk.Label(control_card, textvariable=self.summary_var, style="AuroraStatus.TLabel").grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

        results_card = ttk.Frame(left_col, style="AuroraCard.TFrame", padding=(28, 24))
        results_card.grid(row=1, column=0, sticky="nsew", pady=(20, 0))
        results_card.grid_rowconfigure(1, weight=1)
        results_card.grid_columnconfigure(0, weight=1)
        results_card.grid_columnconfigure(1, weight=0)
        results_card.grid_columnconfigure(2, weight=0)
        ttk.Label(results_card, text="检测结果", style="AuroraSection.TLabel").grid(row=0, column=0, sticky="w")

        columns = ("filename", "issues", "brightness", "clip", "path")
        self.tree = ttk.Treeview(results_card, columns=columns, show="headings", height=12, selectmode="browse")
        self.tree.heading("filename", text="文件名")
        self.tree.heading("issues", text="问题")
        self.tree.heading("brightness", text="平均亮度")
        self.tree.heading("clip", text="高/低光占比")
        self.tree.column("filename", width=240, anchor="w")
        self.tree.column("issues", width=220, anchor="w")
        self.tree.column("brightness", width=100, anchor="center")
        self.tree.column("clip", width=120, anchor="center")
        self.tree.column("path", width=0, stretch=False)
        self.tree.grid(row=1, column=0, sticky="nsew", pady=(18, 0))

        tree_scroll = ttk.Scrollbar(results_card, orient="vertical", command=self.tree.yview, style="Aurora.Vertical.TScrollbar")
        tree_scroll.grid(row=1, column=1, sticky="ns", pady=(18, 0))
        self.tree.configure(yscrollcommand=tree_scroll.set)

        action_row = ttk.Frame(results_card, style="AuroraCard.TFrame")
        action_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        action_row.grid_columnconfigure(0, weight=0)
        action_row.grid_columnconfigure(1, weight=0)
        action_row.grid_columnconfigure(2, weight=1)

        self.open_btn = ttk.Button(action_row, text="打开所在文件夹", style="AuroraPrimary.TButton", command=self.open_selected)
        self.open_btn.grid(row=0, column=0, sticky="w")
        self.delete_btn = ttk.Button(action_row, text="删除所选照片", style="AuroraDanger.TButton", command=self.delete_selected)
        self.delete_btn.grid(row=0, column=1, sticky="w", padx=(16, 0))

        self.log_text = tk.Text(results_card, height=6, wrap="word", bd=0, relief="flat", state="disabled")
        self.log_text.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(18, 0))
        log_scroll = ttk.Scrollbar(results_card, orient="vertical", command=self.log_text.yview, style="Aurora.Vertical.TScrollbar")
        log_scroll.grid(row=3, column=2, sticky="ns", pady=(18, 0))
        self.log_text.configure(yscrollcommand=log_scroll.set)

        right_card = ttk.Frame(self.frame, style="AuroraCard.TFrame", padding=(28, 24))
        right_card.grid(row=0, column=1, sticky="nsew", padx=(24, 0))
        right_card.grid_rowconfigure(1, weight=1)
        right_card.grid_columnconfigure(0, weight=1)
        ttk.Label(right_card, text="预览", style="AuroraSection.TLabel").grid(row=0, column=0, sticky="w")
        self.preview_canvas = tk.Canvas(right_card, width=360, height=360, highlightthickness=0, bd=0)
        self.preview_canvas.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        self.detail_var = tk.StringVar(value="选择列表中的照片查看预览")
        ttk.Label(right_card, textvariable=self.detail_var, style="AuroraBody.TLabel", wraplength=360, justify="left").grid(
            row=2, column=0, sticky="w", pady=(16, 0)
        )

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        set_button_state(self.stop_btn, active=False, style_active="AuroraWarning.TButton")

    def apply_theme(self, theme_key: str) -> None:
        self.theme_key = theme_key
        set_text_theme(self.log_text, theme_key)
        bg = AURORA_THEME["CARD_HIGHLIGHT"]
        self.preview_canvas.configure(bg=bg)

    def _update_detector_hint(self) -> None:
        if self.detector.eye_detection_ready:
            hint = "检测模块已就绪，可开始分析。"
        else:
            hint = (
                "尚未准备好闭眼检测，请先安装依赖：\n"
                f"{self.detector.requirements_hint}"
            )
        providers = getattr(self.detector, "available_providers", [])
        if providers:
            hint += f"\n已检测到 ONNX Runtime providers：{', '.join(providers)}"
        elif onnxruntime is None:
            hint += "\n(未检测到 onnxruntime，可按需安装 onnxruntime。)"
        if FaceAnalysis is None:
            hint += "\n(未检测到 insightface，可选安装以提升检测准确度。)"
        self.detector_hint.configure(text=hint)

    def _log_provider_status(self) -> None:
        providers = self.detector.refresh_available_providers()
        if onnxruntime is None:
            self._log("未检测到 onnxruntime，默认使用 CPUExecutionProvider。")
        elif providers:
            self._log(f"已检测到的 providers：{', '.join(providers)}")
        else:
            self._log("onnxruntime 未返回可用 providers，已回退到 CPU。")
        current = self.detector.current_providers
        self._log(f"当前推理 providers：{', '.join(current)}")
        for line in self.detector.describe_model_inventory():
            self._log(line)

    def _init_progress_state(self) -> None:
        now = time.time()
        self._progress_state = {
            "alpha": 0.2,
            "rate": 0.0,
            "last_done": 0,
            "last_elapsed": 0.0,
            "total": self._total_files,
            "simulate": True,
            "sim_start": now,
            "sim_value": 0.0,
            "active": True,
        }
        self.progress_var.set(0.0)
        self.progress_pct_var.set("0.0%")
        self.progress_eta_var.set("预计剩余时间：估算中…")
        self._start_progress_loop()

    def _start_progress_loop(self) -> None:
        self._stop_progress_loop()
        if not self._progress_state:
            return
        self._progress_state["active"] = True
        self._progress_job = self.root.after(200, self._progress_loop)

    def _progress_loop(self) -> None:
        if not self._progress_state.get("active"):
            return
        if self._progress_state.get("simulate"):
            now = time.time()
            sim_start = self._progress_state.get("sim_start", now)
            elapsed = max(0.0, now - sim_start)
            current = self._progress_state.get("sim_value", 0.0)
            if elapsed <= 10.0:
                target = min(20.0, (elapsed / 10.0) * 20.0)
            else:
                target = min(95.0, current + 0.4)
            value = max(current, target)
            self._progress_state["sim_value"] = value
            self.progress_var.set(value)
            self.progress_pct_var.set(f"{value:.1f}%")
            self.progress_eta_var.set("预计剩余时间：估算中…")
        self._progress_job = self.root.after(200, self._progress_loop)

    def _stop_progress_loop(self) -> None:
        if self._progress_job is not None:
            try:
                self.root.after_cancel(self._progress_job)
            except Exception:
                pass
            self._progress_job = None
        if self._progress_state:
            self._progress_state["active"] = False
            self._progress_state["simulate"] = False

    def _apply_progress(self, processed: int, elapsed: float) -> None:
        if not self._progress_state:
            return
        total = self._progress_state.get("total", self._total_files)
        self._progress_state["total"] = total
        prev_done = self._progress_state.get("last_done", 0)
        delta_done = processed - prev_done
        prev_elapsed = self._progress_state.get("last_elapsed", 0.0)
        delta_time = max(1e-3, elapsed - prev_elapsed)
        inst_rate = max(0.0, delta_done / delta_time) if delta_done >= 0 else 0.0
        rate = self._progress_state.get("rate", 0.0)
        if inst_rate > 0:
            alpha = self._progress_state.get("alpha", 0.2)
            self._progress_state["rate"] = inst_rate if rate <= 0 else (alpha * inst_rate + (1 - alpha) * rate)
        self._progress_state["last_done"] = processed
        self._progress_state["last_elapsed"] = elapsed
        self._progress_state["simulate"] = False
        pct = 0.0
        if total > 0:
            pct = min(100.0, processed / total * 100.0)
        self.progress_var.set(pct)
        self.progress_pct_var.set(f"{pct:.1f}%")
        rate = self._progress_state.get("rate", 0.0)
        if total > 0 and processed >= total:
            self.progress_eta_var.set("预计剩余时间：00:00:00")
        elif rate > 0 and total:
            remaining = max(0.0, (total - processed) / rate)
            self.progress_eta_var.set(f"预计剩余时间：{self._format_eta(remaining)}")
        else:
            self.progress_eta_var.set("预计剩余时间：估算中…")

    @staticmethod
    def _format_eta(seconds: float) -> str:
        secs = max(0, int(round(seconds)))
        minutes, sec = divmod(secs, 60)
        hour, minute = divmod(minutes, 60)
        return f"{hour:d}:{minute:02d}:{sec:02d}"

    def choose_folder(self) -> None:
        path = filedialog.askdirectory(parent=self.root)
        if not path:
            return
        self.folder_var.set(path)
        self._log(f"已选择检测目录：{path}")

    def _is_removable_path(self, path: str) -> bool:
        if os.name == "nt":
            drive = os.path.splitdrive(os.path.abspath(path))[0]
            if drive:
                try:
                    return get_drive_type_code(drive) == 2
                except Exception:
                    return False
        return False

    def start_detection(self) -> None:
        if self._running:
            return
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            aurora_showwarning("提示", "请先选择有效的文件夹。", parent=self.root)
            return
        if self._is_removable_path(folder):
            aurora_showwarning("提示", "请先将素材复制到电脑硬盘后再检测，避免直接操作存储卡。", parent=self.root)
            return
        files: List[str] = []
        for root_dir, _, filenames in os.walk(folder):
            for name in filenames:
                if name.lower().endswith((".jpg", ".jpeg")):
                    files.append(os.path.join(root_dir, name))
        files.sort()
        if not files:
            aurora_showinfo("提示", "所选目录中未找到 JPG 照片。", parent=self.root)
            return

        self._running = True
        self._stop_event.clear()
        self._results.clear()
        self._prompt_active = False
        while not self._prompt_queue.empty():
            try:
                self._prompt_queue.get_nowait()
            except queue.Empty:
                break
        self.tree.delete(*self.tree.get_children())
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.preview_canvas.delete("all")
        self.detail_var.set("检测中，选中结果可查看预览")
        self._closed_count = 0
        self._half_count = 0
        self._abnormal_count = 0
        self._under_count = 0
        self._over_count = 0
        self._processed_files = 0
        self._total_files = len(files)
        self._init_progress_state()
        self.status_var.set(f"检测中：0/{self._total_files}")
        self._update_summary()
        set_button_state(self.start_btn, active=False)
        set_button_state(self.stop_btn, active=True, style_active="AuroraWarning.TButton")
        self._log(f"开始检测，共 {self._total_files} 张 JPG 照片。")
        current_providers = self.detector.current_providers
        self._log(f"使用推理 providers：{', '.join(current_providers)}")

        def _worker():
            start_perf = time.perf_counter()
            try:
                for idx, path in enumerate(files, start=1):
                    if self._stop_event.is_set():
                        break
                    detection = self.detector.analyze_image(path)
                    self._processed_files = idx
                    elapsed = time.perf_counter() - start_perf
                    self.root.after(0, lambda idx=idx, elapsed=elapsed: self._update_progress(idx, elapsed))
                    if detection:
                        self.root.after(0, lambda det=detection: self._handle_detection(det))
                        if detection.closed_eye_count > 0:
                            self._prompt_queue.put(detection)
                            self.root.after(0, self._schedule_prompt)
                stopped = self._stop_event.is_set()
            finally:
                self.root.after(0, lambda stopped=bool(self._stop_event.is_set()): self._finish_detection(stopped))

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def _update_progress(self, processed: int, elapsed: float) -> None:
        self._apply_progress(processed, elapsed)
        self.status_var.set(f"检测中：{processed}/{self._total_files}")

    def _finish_detection(self, stopped: bool) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_progress_loop()
        set_button_state(self.start_btn, active=True)
        set_button_state(self.stop_btn, active=False, style_active="AuroraWarning.TButton")
        if stopped:
            self.status_var.set(f"已停止，完成 {self._processed_files}/{self._total_files}")
            self._log("检测已停止。")
            self.progress_eta_var.set("预计剩余时间：--:--:--")
        else:
            self.progress_var.set(100.0)
            self.progress_pct_var.set("100.0%")
            self.progress_eta_var.set("预计剩余时间：00:00:00")
            self.status_var.set(f"检测完成，共 {self._total_files} 张")
            self._log("检测完成。")
        self._update_summary()

    def stop_detection(self) -> None:
        if not self._running:
            return
        self._stop_event.set()
        self._log("正在停止检测，请稍候…")

    def _update_summary(self) -> None:
        summary = (
            f"闭眼 {self._closed_count} 张 | 半眨眼 {self._half_count} 张 | "
            f"眼部异常 {self._abnormal_count} 张 | 欠曝 {self._under_count} 张 | 过曝 {self._over_count} 张"
        )
        self.summary_var.set(summary)

    def _handle_detection(self, detection: DetectionResult) -> None:
        issues_text = "、".join(detection.issues)
        brightness_text = f"{detection.mean_luminance:.1f}" if detection.mean_luminance else "--"
        clip_text = f"{detection.clipped_ratio * 100:.1f}%" if detection.clipped_ratio else "0.0%"
        iid = self.tree.insert(
            "",
            "end",
            values=(os.path.basename(detection.path), issues_text, brightness_text, clip_text, detection.path),
        )
        self._results[iid] = detection
        self._log(f"发现问题照片：{detection.path} -> {issues_text}")
        if "闭眼" in detection.issues:
            self._closed_count += 1
        if "半眨眼" in detection.issues:
            self._half_count += 1
        if any(issue in detection.issues for issue in ("眼球偏离",)):
            self._abnormal_count += 1
        if detection.exposure_issue == "欠曝":
            self._under_count += 1
        if detection.exposure_issue == "过曝":
            self._over_count += 1
        self._update_summary()

    def _schedule_prompt(self) -> None:
        if self._prompt_active:
            return
        if self._prompt_queue.empty():
            return
        detection = self._prompt_queue.get()
        self._prompt_active = True

        def _ask():
            message = (
                "检测到闭眼照片：\n"
                f"{detection.path}\n"
                "是否删除这张照片？"
            )
            if aurora_askyesno("删除闭眼照片", message, parent=self.root):
                try:
                    os.remove(detection.path)
                    self._log(f"已删除闭眼照片：{detection.path}")
                    self._remove_detection(detection.path)
                except Exception as exc:
                    aurora_showwarning("删除失败", f"无法删除文件：{exc}", parent=self.root)
            else:
                self._log(f"已保留闭眼照片：{detection.path}")
            self._prompt_active = False
            self.root.after(0, self._schedule_prompt)

        self.root.after(100, _ask)

    def _remove_detection(self, path: str) -> None:
        to_delete = None
        for iid, detection in self._results.items():
            if detection.path == path:
                to_delete = iid
                break
        if to_delete is not None:
            self.tree.delete(to_delete)
            detection = self._results.pop(to_delete)
            if "闭眼" in detection.issues and self._closed_count > 0:
                self._closed_count -= 1
            if "半眨眼" in detection.issues and self._half_count > 0:
                self._half_count -= 1
            if any(issue in detection.issues for issue in ("眼球偏离",)) and self._abnormal_count > 0:
                self._abnormal_count -= 1
            if detection.exposure_issue == "欠曝" and self._under_count > 0:
                self._under_count -= 1
            if detection.exposure_issue == "过曝" and self._over_count > 0:
                self._over_count -= 1
            self._update_summary()

    def on_tree_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        iid = selection[0]
        detection = self._results.get(iid)
        if detection:
            self._show_preview(detection)

    def on_tree_double_click(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        self.open_selected()

    def _show_preview(self, detection: DetectionResult) -> None:
        if Image is None or ImageTk is None:
            self.detail_var.set("当前环境缺少 Pillow，无法生成预览。")
            return
        try:
            with Image.open(detection.path) as im:
                image = im.convert("RGB")
        except Exception as exc:
            self.detail_var.set(f"无法打开图片：{exc}")
            return

        draw = ImageDraw.Draw(image) if ImageDraw is not None else None
        for region in detection.eye_regions:
            if draw is not None:
                draw.rectangle(region.bbox, outline="#FF4D4F", width=4)
                label = "、".join(region.issues)
                if label:
                    text_pos = (region.bbox[0] + 6, region.bbox[1] + 6)
                    draw.text(text_pos, label, fill="#FF4D4F")

        canvas_w = int(self.preview_canvas.winfo_width() or 360)
        canvas_h = int(self.preview_canvas.winfo_height() or 360)
        if canvas_w <= 0:
            canvas_w = 360
        if canvas_h <= 0:
            canvas_h = 360
        scale = min(canvas_w / image.width, canvas_h / image.height, 1.0)
        if scale < 1.0:
            new_size = (int(image.width * scale), int(image.height * scale))
            image = image.resize(new_size, Image.LANCZOS)

        photo = ImageTk.PhotoImage(image)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(canvas_w // 2, canvas_h // 2, image=photo)
        self._preview_photo = photo

        extra = []
        if detection.exposure_issue:
            extra.append(detection.exposure_issue)
        detail = f"{os.path.basename(detection.path)}\n问题：{ '、'.join(detection.issues) }"
        detail += f"\n平均亮度：{detection.mean_luminance:.1f}"
        if extra:
            detail += f"\n曝光：{'、'.join(extra)}"
        self.detail_var.set(detail)

    def open_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        detection = self._results.get(selection[0])
        if not detection:
            return
        folder = os.path.dirname(detection.path)
        if not folder:
            return
        _open_folder(folder)

    def delete_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        iid = selection[0]
        detection = self._results.get(iid)
        if not detection:
            return
        if not aurora_askyesno("删除确认", f"确定删除 {detection.path}?", parent=self.root):
            return
        try:
            os.remove(detection.path)
        except Exception as exc:
            aurora_showwarning("删除失败", f"无法删除文件：{exc}", parent=self.root)
            return
        self._log(f"已删除照片：{detection.path}")
        self._remove_detection(detection.path)

    def _handle_back(self) -> None:
        if self._running:
            if not aurora_askyesno("提示", "检测仍在进行，确定要返回导入界面吗？", parent=self.root):
                return
            self.stop_detection()
        if callable(self.on_back):
            self.on_back()

    def on_hide(self) -> None:
        if self._running:
            self.stop_detection()

    def on_show(self) -> None:
        self._update_detector_hint()

    def _log(self, message: str) -> None:
        log_add(self.log_text, message)

def rollback_files(paths, target_root):
    removed = 0
    root_abs = os.path.abspath(target_root)
    for path in reversed(paths):
        try:
            if os.path.isfile(path):
                os.remove(path)
                removed += 1
        except Exception:
            pass
    prune_candidates = set()
    # 预置常规子目录，确保即使尚未复制文件也能清理空目录
    standard_subdirs = [
        os.path.join(root_abs, "RAW"),
        os.path.join(root_abs, "JPG"),
        os.path.join(root_abs, "VIDEO"),
        os.path.join(root_abs, "已星标照片"),
        os.path.join(root_abs, "已星标照片", "已星标JPG"),
        os.path.join(root_abs, "已星标照片", "已星标RAW"),
    ]
    prune_candidates.update(os.path.abspath(d) for d in standard_subdirs)
    prune_candidates.add(root_abs)

    for path in paths:
        parent = os.path.dirname(os.path.abspath(path))
        while parent and parent.startswith(root_abs):
            prune_candidates.add(parent)
            next_parent = os.path.dirname(parent)
            if next_parent == parent:
                break
            parent = next_parent

    def _safe_rmdir(folder):
        try:
            if os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)
                return True
        except Exception:
            pass
        return False

    for folder in sorted(prune_candidates, key=len, reverse=True):
        _safe_rmdir(folder)

    # 继续向上清理“月/类别/年份”空目录，但不越过导入根目录
    try:
        stop_at = os.path.abspath(os.path.join(root_abs, os.pardir, os.pardir, os.pardir, os.pardir))
    except Exception:
        stop_at = None

    parent = os.path.dirname(root_abs)
    while parent:
        if stop_at is not None:
            try:
                if os.path.commonpath([stop_at, parent]) != stop_at or parent == stop_at:
                    break
            except Exception:
                break
        if not _safe_rmdir(parent):
            break
        parent = os.path.dirname(parent)

    return removed


def remove_daily_folder_tree(target_dir, copy_date):
    removed = []
    try:
        target_root = os.path.abspath(os.path.join(target_dir, "..", "..", "..", ".."))
    except Exception:
        return removed
    if not os.path.isdir(target_root):
        return removed
    month_cn = os.path.join(target_root, f"{copy_date.year}年{copy_date.month:02d}月")
    day_cn = os.path.join(month_cn, f"{copy_date.month:02d}月{copy_date.day:02d}日")
    try:
        if os.path.isdir(day_cn):
            try:
                if os.path.commonpath([target_root, day_cn]) == target_root:
                    shutil.rmtree(day_cn)
            except Exception:
                shutil.rmtree(day_cn, ignore_errors=True)
            if not os.path.isdir(day_cn):
                removed.append(day_cn)
    except Exception:
        pass
    try:
        if os.path.isdir(month_cn) and os.path.commonpath([target_root, month_cn]) == target_root:
            if not os.listdir(month_cn):
                os.rmdir(month_cn)
        if not os.path.isdir(month_cn):
            removed.append(month_cn)
    except Exception:
        pass
    return removed

# ---------- 扫描/计划 ----------
def preflight_scan(src_root):
    counts={"RAW":0,"JPG":0,"VIDEO":0}; sizes={"RAW":0,"JPG":0,"VIDEO":0}
    files={"RAW":[],"JPG":[],"VIDEO":[]}
    for root,_,fs in os.walk(src_root):
        for f in fs:
            ext=f.rsplit('.',1)[-1].lower() if '.' in f else ""
            full=os.path.join(root,f)
            try: sz=os.path.getsize(full)
            except Exception: sz=0
            if is_raw_ext(ext): counts["RAW"]+=1; sizes["RAW"]+=sz; files["RAW"].append(full)
            elif is_jpg_ext(ext): counts["JPG"]+=1; sizes["JPG"]+=sz; files["JPG"].append(full)
            elif is_video_ext(ext): counts["VIDEO"]+=1; sizes["VIDEO"]+=sz; files["VIDEO"].append(full)
    return counts,sizes,files

def build_seq_plan(photo_files,mmdd_str):
    entries=[]
    for p in photo_files:
        ext=p.rsplit(".",1)[-1].lower() if "." in p else ""
        stem=os.path.splitext(os.path.basename(p))[0]
        dt=get_capture_dt(p)
        entries.append({"path":p,"ext":ext,"stem":stem,"dt":dt})
    entries.sort(key=lambda x:(x["dt"],x["stem"],x["ext"]))
    stem_to_idx={}; seq=0; plan=[]
    for e in entries:
        if e["stem"] in stem_to_idx: idx=stem_to_idx[e["stem"]]
        else: seq+=1; idx=seq; stem_to_idx[e["stem"]]=idx
        plan.append((e["path"], f"{mmdd_str}-{idx:04d}", e["ext"]))
    return plan

# ---------- 完成弹窗与撤销 ----------
def _open_folder(p):
    try:
        if platform.system()=="Windows": os.startfile(p)
        elif platform.system()=="Darwin": subprocess.Popen(["open", p])
        else: subprocess.Popen(["xdg-open", p])
    except Exception:
        pass

def show_finish_and_undo(root, target_dir, created_files, copy_date):
    win = tk.Toplevel(root)
    win.title("完成")
    win.resizable(False, False)
    win.transient(root)      # 置于父窗口上方
    win.grab_set()           # 获取焦点

    # 统一应用当前主题（修复暗黑/日间不匹配）
    try:
        theme_key = load_config().get("theme", DEFAULT_THEME_KEY)
    except Exception:
        theme_key = DEFAULT_THEME_KEY
    if theme_key not in {DEFAULT_THEME_KEY}:
        theme_key = DEFAULT_THEME_KEY
    apply_theme(win, theme_key)

    win.grid_rowconfigure(0, weight=1)
    win.grid_columnconfigure(0, weight=1)

    container = ttk.Frame(win, style="AuroraCard.TFrame", padding=(26, 22))
    container.grid(row=0, column=0, sticky="nsew")
    for i in range(3):
        container.grid_columnconfigure(i, weight=1 if i == 0 else 0)

    accent = ttk.Frame(container, style="AuroraAccent.TFrame", height=3)
    accent.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 18))
    accent.grid_propagate(False)

    ttk.Label(container, text="导入完成", style="AuroraSection.TLabel").grid(row=1, column=0, columnspan=3, sticky="w")
    ttk.Label(container, text=f"输出目录：  {target_dir}", style="AuroraBody.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=(12, 0))

    def _open():
        try:
            if platform.system()=="Windows": os.startfile(target_dir)
            elif platform.system()=="Darwin": subprocess.Popen(["open", target_dir])
            else: subprocess.Popen(["xdg-open", target_dir])
        except Exception:
            pass

    def undo():
        removed = 0
        for p in created_files:
            try:
                if os.path.isfile(p):
                    os.remove(p); removed += 1
            except Exception:
                pass
        for sub in ["RAW","JPG","VIDEO","已星标照片","已星标照片\\已星标JPG","已星标照片\\已星标RAW"]:
            d = os.path.join(target_dir, sub)
            try:
                if os.path.isdir(d) and not os.listdir(d): os.rmdir(d)
            except Exception: pass
        try:
            if os.path.isdir(target_dir) and not os.listdir(target_dir): os.rmdir(target_dir)
        except Exception: pass
        extra_removed = remove_daily_folder_tree(target_dir, copy_date)
        msg = f"已删除本次导入生成的 {removed} 个文件。"
        if extra_removed:
            detail = "\n".join(extra_removed)
            msg += f"\n已删除目录：\n{detail}"
        aurora_showinfo("撤销完成", msg, parent=win)
        win.destroy()

    ttk.Button(container, text="打开输出文件夹", style="AuroraPrimary.TButton", command=_open)\
        .grid(row=3, column=0, sticky="w", pady=(22, 0))
    ttk.Button(container, text="撤销本次导入", style="AuroraSecondary.TButton", command=undo)\
        .grid(row=3, column=1, sticky="w", padx=(16, 0), pady=(22, 0))
    ttk.Button(container, text="关闭", style="AuroraGhost.TButton", command=win.destroy)\
        .grid(row=3, column=2, sticky="e", padx=(16, 0), pady=(22, 0))

    # 计算尺寸后居中到父窗口
    win.update_idletasks()
    center_on_parent(win, root)
     # 居中弹出窗口
def center_on_parent(child: tk.Toplevel, parent: tk.Tk):
    """把子窗口居中到父窗口"""
    parent.update_idletasks()
    child.update_idletasks()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    cw, ch = child.winfo_width(), child.winfo_height()
    x = px + max((pw - cw) // 2, 0)
    y = py + max((ph - ch) // 2, 0)
    child.geometry(f"+{x}+{y}")

# ---------- 复制（主界面进度，MB/s，含星标） ----------
def copy_with_progress_seq_and_video(
    src_files,
    dst,
    pb,
    status_label,
    log_file,
    mmdd_str,
    info_box,
    total_bytes,
    extract_star=False,
    progress_hook=None,
    cancel_ev=None,
    pause_ev=None,
    log_func=None,
    on_file_done=None,
):
    created = []
    done = set()
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("完成: "):
                    done.add(line.split("完成: ", 1)[1].split(" -> ", 1)[0].strip())

    photo_files = src_files["RAW"] + src_files["JPG"]
    video_files = src_files["VIDEO"]

    raw_dir = os.path.join(dst, "RAW")
    jpg_dir = os.path.join(dst, "JPG")
    vid_dir = os.path.join(dst, "VIDEO")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(jpg_dir, exist_ok=True)
    os.makedirs(vid_dir, exist_ok=True)

    star_root = os.path.join(dst, "已星标照片")
    star_jpg = os.path.join(star_root, "已星标JPG")
    star_raw = os.path.join(star_root, "已星标RAW")
    if extract_star:
        os.makedirs(star_jpg, exist_ok=True)
        os.makedirs(star_raw, exist_ok=True)

    plan = build_seq_plan(photo_files, mmdd_str)
    final_map = {}

    log = log_func if log_func is not None else (lambda line: log_add(info_box, line))

    bytes_done = 0
    t0 = time.time()
    last_emit = 0.0

    def report_progress(phase, delta, *, force=False):
        nonlocal last_emit
        now = time.time()
        if not force and now - last_emit < 0.05:
            return
        elapsed = max(now - t0, 1e-6)
        speed_mb = bytes_done / elapsed / (1024 * 1024)
        if progress_hook is not None:
            try:
                progress_hook(delta, phase, bytes_done, total_bytes, speed_mb)
            except Exception:
                pass
        last_emit = now

    def check_flow():
        if cancel_ev is not None and cancel_ev.is_set():
            raise KeyboardInterrupt
        if pause_ev is not None:
            while pause_ev.is_set():
                if cancel_ev is not None and cancel_ev.is_set():
                    raise KeyboardInterrupt
                time.sleep(0.1)

    def copy_stream(src_path, dst_path, phase):
        nonlocal bytes_done
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        copied = 0
        try:
            with open(src_path, "rb") as fsrc, open(dst_path, "wb") as fdst:
                while True:
                    check_flow()
                    chunk = fsrc.read(COPY_BUFFER_SIZE)
                    if not chunk:
                        break
                    fdst.write(chunk)
                    copied += len(chunk)
                    bytes_done += len(chunk)
                    report_progress(phase, len(chunk))
            try:
                shutil.copystat(src_path, dst_path)
            except Exception:
                pass
        except KeyboardInterrupt:
            try:
                if os.path.exists(dst_path):
                    os.remove(dst_path)
            except Exception:
                pass
            raise
        except Exception:
            try:
                if os.path.exists(dst_path):
                    os.remove(dst_path)
            except Exception:
                pass
            raise
        report_progress(phase, 0, force=True)
        return copied

    # 照片复制与重命名
    for src, base, ext in plan:
        check_flow()
        if src in done:
            try:
                size = os.path.getsize(src)
                bytes_done += size
            except Exception:
                size = 0
            report_progress("照片", size, force=True)
            continue
        td = raw_dir if is_raw_ext(ext) else jpg_dir
        dst_path = unique_path(td, f"{base}.{ext}")
        try:
            copy_stream(src, dst_path, "照片")
            created.append(dst_path)
            final_map[src] = dst_path
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"完成: {src} -> {os.path.basename(dst_path)}\n")
            if on_file_done is not None:
                on_file_done(dst_path)
            if int(time.time() * 10) % 3 == 0:
                log(f"复制：{os.path.basename(dst_path)}")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"错误: {src} | {e}\n")

    # 视频复制（保留原名）
    for src in video_files:
        check_flow()
        if src in done:
            try:
                size = os.path.getsize(src)
                bytes_done += size
            except Exception:
                size = 0
            report_progress("视频", size, force=True)
            continue
        dst_path = unique_path(vid_dir, os.path.basename(src))
        try:
            copy_stream(src, dst_path, "视频")
            created.append(dst_path)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"完成: {src} -> {os.path.basename(dst_path)}\n")
            if on_file_done is not None:
                on_file_done(dst_path)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"错误: {src} | {e}\n")

    report_progress("收尾", 0, force=True)

    if extract_star:
        log("开始提取星标照片…")
        star_count = 0
        for src, base, ext in plan:
            check_flow()
            try:
                if is_starred_file(src):
                    src_copied_path = final_map.get(src, src)
                    if is_jpg_ext(ext):
                        dst_star = unique_path(star_jpg, os.path.basename(src_copied_path))
                    else:
                        dst_star = unique_path(star_raw, os.path.basename(src_copied_path))
                    shutil.copy2(src_copied_path, dst_star)
                    created.append(dst_star)
                    if on_file_done is not None:
                        on_file_done(dst_star)
                    star_count += 1
            except KeyboardInterrupt:
                raise
            except Exception as e:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"星标复制错误: {src} | {e}\n")
        log(f"星标提取完成，共 {star_count} 个文件")

    return created

def _update(pb,lab,copied,total,start,phase):
    # 仅保留以防调用；本版本不用文件数速率
    pb["value"]= (copied/total*100) if total else 0
    el=max(time.time()-start,1e-6); sp=copied/el; rem=max(total-copied,0); eta=int(rem/sp) if sp>0 else 0
    lab.config(text=f"{phase} {copied}/{total} | 速度 {sp:.2f}/秒 | 预计剩余 {eta} 秒"); lab.update()

# ---------- 主题 ----------
AURORA_THEME = {
    "BG": "#050A16",
    "HEADER_BG": "#0E1626",
    "PANEL_BG": "#0B1322",
    "CARD": "#111E32",
    "CARD_HIGHLIGHT": "#17263C",
    "CARD_BORDER": "#1F2E45",
    "TEXT": "#F4F7FB",
    "SUB": "#8EA3C0",
    "STATUS": "#94A3B8",
    "ACCENT": "#38BDF8",
    "ACCENT_HOVER": "#0EA5E9",
    "ACCENT_ACTIVE": "#0284C7",
    "ACCENT_LINE": "#60A5FA",
    "INPUT_BG": "#15243A",
    "INPUT_FG": "#E2E8F0",
    "INPUT_BORDER": "#1F3450",
    "TROUGH": "#102036",
    "SCROLLBAR_BG": "#0D182B",
    "SCROLLBAR_FG": "#1D3554"
}


def _font(size, weight="normal"):
    if weight == "bold":
        return ("Microsoft YaHei UI", size, "bold")
    return ("Microsoft YaHei UI", size)


def apply_theme(root, theme_key, info_text_widget=None):
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    P = AURORA_THEME

    root.configure(bg=P["BG"])
    try:
        root.option_add("*TCombobox*Listbox.background", P["CARD"])
        root.option_add("*TCombobox*Listbox.foreground", P["TEXT"])
        root.option_add("*TCombobox*Listbox.selectBackground", P["ACCENT"])
        root.option_add("*TCombobox*Listbox.selectForeground", "#061427")
    except Exception:
        pass

    style.configure("TPanedwindow", background=P["PANEL_BG"], bordercolor=P["PANEL_BG"], relief="flat")
    style.configure("TPanedwindow.Pane", background=P["PANEL_BG"])

    style.configure("AuroraHeader.TFrame", background=P["HEADER_BG"], borderwidth=0, relief="flat")
    style.configure("AuroraPanel.TFrame", background=P["PANEL_BG"], borderwidth=0, relief="flat")
    style.configure("AuroraCard.TFrame", background=P["CARD"], borderwidth=1, relief="flat", bordercolor=P["CARD_BORDER"])
    style.configure("AuroraAccent.TFrame", background=P["ACCENT_LINE"])

    style.configure("AuroraTitle.TLabel", background=P["HEADER_BG"], foreground=P["TEXT"], font=_font(20, "bold"))
    style.configure("AuroraSection.TLabel", background=P["CARD"], foreground=P["TEXT"], font=_font(15, "bold"))
    style.configure("AuroraBody.TLabel", background=P["CARD"], foreground=P["TEXT"], font=_font(12))
    style.configure("AuroraBodyOnPanel.TLabel", background=P["HEADER_BG"], foreground=P["TEXT"], font=_font(12))
    style.configure("AuroraSubtle.TLabel", background=P["CARD"], foreground=P["SUB"], font=_font(11))
    style.configure("AuroraStatus.TLabel", background=P["CARD"], foreground=P["STATUS"], font=_font(11))
    style.configure("AuroraFooter.TLabel", background=P["BG"], foreground=P["SUB"], font=_font(10))

    button_base = dict(
        background=P["ACCENT"],
        foreground="#051225",
        font=_font(12, "bold"),
        padding=(22, 10),
        borderwidth=0,
        focusthickness=0,
        focuscolor=P["ACCENT_ACTIVE"],
    )
    button_map = dict(
        background=[("pressed", P["ACCENT_ACTIVE"]), ("active", P["ACCENT_HOVER"])],
        foreground=[("pressed", "#E6F6FF"), ("active", "#F0F9FF")],
    )

    style.configure("AuroraPrimary.TButton", **button_base)
    style.map("AuroraPrimary.TButton", **button_map)

    for name in ("AuroraSecondary.TButton", "AuroraGhost.TButton", "Danger.TButton"):
        style.configure(name, **button_base)
        style.map(name, **button_map)

    style.configure(
        "AuroraDisabled.TButton",
        background="#1C283D",
        foreground="#5F7394",
        font=_font(12, "bold"),
        padding=(22, 10),
        borderwidth=0,
        focusthickness=0,
    )
    style.map("AuroraDisabled.TButton", background=[("active", "#1C283D"), ("pressed", "#1C283D")], foreground=[("active", "#5F7394")])

    style.configure(
        "AuroraWarning.TButton",
        background="#F59E0B",
        foreground="#0A0F1C",
        font=_font(12, "bold"),
        padding=(22, 10),
        borderwidth=0,
        focusthickness=0,
    )
    style.map(
        "AuroraWarning.TButton",
        background=[("active", "#FFB020"), ("pressed", "#C27803")],
        foreground=[("active", "#0A0F1C"), ("pressed", "#020307")],
    )

    style.configure(
        "AuroraSuccess.TButton",
        background="#4CAF50",
        foreground="#F8FAFC",
        font=_font(12, "bold"),
        padding=(22, 10),
        borderwidth=0,
        focusthickness=0,
    )
    style.map(
        "AuroraSuccess.TButton",
        background=[("active", "#67C566"), ("pressed", "#2F7C31")],
        foreground=[("pressed", "#E8FCE8"), ("active", "#F8FFFA")],
    )

    style.configure(
        "AuroraDanger.TButton",
        background="#F87171",
        foreground="#0F172A",
        font=_font(12, "bold"),
        padding=(22, 10),
        borderwidth=0,
        focusthickness=0,
    )
    style.map(
        "AuroraDanger.TButton",
        background=[("active", "#FB7185"), ("pressed", "#B91C1C")],
        foreground=[("active", "#0F172A"), ("pressed", "#FDF2F2")],
    )

    style.configure("Aurora.Horizontal.TProgressbar", troughcolor=P["TROUGH"], bordercolor=P["TROUGH"], background=P["ACCENT"], darkcolor=P["ACCENT_ACTIVE"], lightcolor=P["ACCENT"], thickness=10)

    style.configure("Aurora.TCombobox", fieldbackground=P["INPUT_BG"], background=P["INPUT_BG"], foreground=P["INPUT_FG"], bordercolor=P["INPUT_BORDER"], arrowcolor=P["SUB"])
    style.map(
        "Aurora.TCombobox",
        fieldbackground=[("readonly", P["INPUT_BG"]), ("active", P["INPUT_BG"])],
        foreground=[("readonly", P["INPUT_FG"])],
        background=[("readonly", P["INPUT_BG"])],
        arrowcolor=[("active", P["ACCENT"]), ("readonly", P["SUB"])],
    )

    style.configure("Aurora.TEntry", fieldbackground=P["INPUT_BG"], foreground=P["INPUT_FG"], bordercolor=P["INPUT_BORDER"], padding=(12, 8))
    style.map(
        "Aurora.TEntry",
        fieldbackground=[("focus", P["INPUT_BG"])],
        bordercolor=[("focus", P["ACCENT_LINE"])],
        foreground=[("disabled", P["SUB"])],
    )

    style.configure("Aurora.TCheckbutton", background=P["CARD"], foreground=P["TEXT"], font=_font(11))
    style.map("Aurora.TCheckbutton", background=[("active", P["CARD_HIGHLIGHT"])], foreground=[("disabled", P["SUB"])])

    style.configure("Aurora.Vertical.TScrollbar", background=P["CARD"], troughcolor=P["SCROLLBAR_BG"], bordercolor=P["CARD"], darkcolor=P["CARD"], lightcolor=P["CARD"], arrowsize=12)
    style.map(
        "Aurora.Vertical.TScrollbar",
        background=[("active", P["CARD_HIGHLIGHT"]), ("pressed", P["ACCENT_ACTIVE"])],
        arrowcolor=[("active", P["ACCENT"])],
    )

    if info_text_widget is not None:
        info_text_widget.configure(
            bg=AURORA_THEME["CARD_HIGHLIGHT"],
            fg=AURORA_THEME["TEXT"],
            insertbackground=AURORA_THEME["ACCENT"],
            highlightthickness=0,
            relief="flat",
            selectbackground=AURORA_THEME["ACCENT"],
            selectforeground="#071425",
        )


def set_text_theme(widget, theme_key):
    widget.configure(
        bg=AURORA_THEME["CARD_HIGHLIGHT"],
        fg=AURORA_THEME["TEXT"],
        insertbackground=AURORA_THEME["ACCENT"],
        selectbackground=AURORA_THEME["ACCENT"],
        selectforeground="#071425",
        highlightthickness=0,
        relief="flat",
        padx=16,
        pady=14,
    )


def set_button_state(button: ttk.Button, *, active: bool = True, style_active: str = "AuroraPrimary.TButton", style_disabled: str = "AuroraDisabled.TButton", cursor_active: str = "hand2") -> None:
    if active:
        button.config(state="normal", style=style_active, cursor=cursor_active)
    else:
        button.config(state="disabled", style=style_disabled, cursor="arrow")


def _normalize_parent(widget):
    if widget is None:
        widget = tk._default_root
    if widget is None:
        return None
    try:
        return widget.winfo_toplevel()
    except Exception:
        return None


def _can_use_modal(widget):
    if widget is None:
        return False
    try:
        return bool(widget.winfo_exists())
    except Exception:
        return False


def _aurora_modal(title, message, *, level="info", buttons, parent=None, default_index=0, close_value=None, width=460):
    toplevel = _normalize_parent(parent)
    if not _can_use_modal(toplevel):
        return None

    win = tk.Toplevel(toplevel)
    win.withdraw()
    win.title(title)
    win.resizable(False, False)
    win.transient(toplevel)
    win.grab_set()
    win.attributes("-topmost", True)

    apply_theme(win, DEFAULT_THEME_KEY)
    win.configure(bg=AURORA_THEME["HEADER_BG"])

    palette = {
        "info": AURORA_THEME["ACCENT_LINE"],
        "warning": "#F97316",
        "danger": "#F87171",
    }
    accent_color = palette.get(level, AURORA_THEME["ACCENT_LINE"])

    accent = tk.Frame(win, bg=accent_color, height=4, bd=0, highlightthickness=0)
    accent.pack(fill="x")

    container = ttk.Frame(win, style="AuroraCard.TFrame", padding=(28, 24))
    container.pack(fill="both", expand=True)

    title_label = ttk.Label(container, text=title, style="AuroraSection.TLabel")
    title_label.pack(anchor="w")

    body_label = ttk.Label(
        container,
        text=message,
        style="AuroraBody.TLabel",
        wraplength=width,
        justify="left",
    )
    body_label.pack(anchor="w", pady=(12, 0))

    btn_frame = ttk.Frame(container, style="AuroraCard.TFrame")
    btn_frame.pack(anchor="e", pady=(26, 6))

    result = {"value": close_value}

    def close_with(value):
        result["value"] = value
        win.destroy()

    def on_close():
        result["value"] = close_value
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    default_btn = None
    for idx, (text, style_name, value) in enumerate(buttons):
        btn = ttk.Button(btn_frame, text=text, style=style_name, command=lambda v=value: close_with(v))
        if idx < len(buttons) - 1:
            btn.pack(side="right", padx=(12, 0))
        else:
            btn.pack(side="right")
        if idx == default_index:
            default_btn = btn

    if default_btn is not None:
        default_btn.focus_set()
        win.bind("<Return>", lambda _event: close_with(buttons[default_index][2]))
    win.bind("<Escape>", lambda _event: on_close())

    win.update_idletasks()
    if toplevel is not None:
        toplevel.update_idletasks()
        pw, ph = toplevel.winfo_width(), toplevel.winfo_height()
        px, py = toplevel.winfo_rootx(), toplevel.winfo_rooty()
        cw, ch = win.winfo_width(), win.winfo_height()
        x = px + max((pw - cw) // 2, 0)
        y = py + max((ph - ch) // 2, 0)
        win.geometry(f"+{x}+{y}")

    win.deiconify()
    win.wait_window()
    return result["value"]


def aurora_askstring(title, prompt, *, parent=None, initialvalue=""):
    toplevel = _normalize_parent(parent)
    if not _can_use_modal(toplevel):
        return simpledialog.askstring(title, prompt, parent=parent, initialvalue=initialvalue)

    win = tk.Toplevel(toplevel)
    win.withdraw()
    win.title(title)
    win.resizable(False, False)
    win.transient(toplevel)
    win.grab_set()
    win.attributes("-topmost", True)

    apply_theme(win, DEFAULT_THEME_KEY)
    win.configure(bg=AURORA_THEME["HEADER_BG"])

    accent = tk.Frame(win, bg=AURORA_THEME["ACCENT_LINE"], height=4, bd=0, highlightthickness=0)
    accent.pack(fill="x")

    container = ttk.Frame(win, style="AuroraCard.TFrame", padding=(28, 24))
    container.pack(fill="both", expand=True)

    title_label = ttk.Label(container, text=title, style="AuroraSection.TLabel")
    title_label.pack(anchor="w")

    body_label = ttk.Label(container, text=prompt, style="AuroraBody.TLabel", wraplength=440, justify="left")
    body_label.pack(anchor="w", pady=(12, 0))

    entry = tk.Entry(container, font=_font(12))
    entry.insert(0, initialvalue or "")
    entry.configure(
        bg=AURORA_THEME["INPUT_BG"],
        fg=AURORA_THEME["INPUT_FG"],
        insertbackground=AURORA_THEME["ACCENT"],
        relief="flat",
        highlightthickness=1,
        highlightbackground=AURORA_THEME["INPUT_BORDER"],
        highlightcolor=AURORA_THEME["ACCENT_LINE"],
        selectbackground=AURORA_THEME["ACCENT"],
        selectforeground="#071425",
        insertwidth=2,
    )
    entry.pack(fill="x", pady=(18, 0))

    result = {"value": None}

    def submit():
        result["value"] = entry.get()
        win.destroy()

    def cancel():
        result["value"] = None
        win.destroy()

    btn_frame = ttk.Frame(container, style="AuroraCard.TFrame")
    btn_frame.pack(anchor="e", pady=(24, 6))

    btn_cancel = ttk.Button(btn_frame, text="取消", style="AuroraGhost.TButton", command=cancel)
    btn_cancel.pack(side="right", padx=(12, 0))

    btn_ok = ttk.Button(btn_frame, text="确认", style="AuroraPrimary.TButton", command=submit)
    btn_ok.pack(side="right")

    win.protocol("WM_DELETE_WINDOW", cancel)
    win.bind("<Escape>", lambda _event: cancel())
    win.bind("<Return>", lambda _event: submit())

    win.update_idletasks()
    if toplevel is not None:
        toplevel.update_idletasks()
        pw, ph = toplevel.winfo_width(), toplevel.winfo_height()
        px, py = toplevel.winfo_rootx(), toplevel.winfo_rooty()
        cw, ch = win.winfo_width(), win.winfo_height()
        x = px + max((pw - cw) // 2, 0)
        y = py + max((ph - ch) // 2, 0)
        win.geometry(f"+{x}+{y}")

    win.deiconify()
    entry.focus_set()
    entry.select_range(0, tk.END)
    win.wait_window()
    return result["value"]


def aurora_showinfo(title, message, parent=None):
    toplevel = _normalize_parent(parent)
    if not _can_use_modal(toplevel):
        messagebox.showinfo(title, message, parent=parent)
        return
    _aurora_modal(
        title,
        message,
        level="info",
        buttons=[("确定", "AuroraPrimary.TButton", True)],
        parent=toplevel,
        default_index=0,
    )


def aurora_showwarning(title, message, parent=None):
    toplevel = _normalize_parent(parent)
    if not _can_use_modal(toplevel):
        messagebox.showwarning(title, message, parent=parent)
        return
    _aurora_modal(
        title,
        message,
        level="warning",
        buttons=[("我知道了", "AuroraPrimary.TButton", True)],
        parent=toplevel,
        default_index=0,
    )


def aurora_askyesno(title, message, parent=None):
    toplevel = _normalize_parent(parent)
    if not _can_use_modal(toplevel):
        return messagebox.askyesno(title, message, parent=parent)
    return bool(
        _aurora_modal(
            title,
            message,
            level="info",
            buttons=[
                ("取消", "AuroraGhost.TButton", False),
                ("继续", "AuroraPrimary.TButton", True),
            ],
            parent=toplevel,
            default_index=1,
            close_value=False,
        )
    )


def aurora_askretrycancel(title, message, parent=None):
    toplevel = _normalize_parent(parent)
    if not _can_use_modal(toplevel):
        return messagebox.askretrycancel(title, message, parent=parent)
    return bool(
        _aurora_modal(
            title,
            message,
            level="warning",
            buttons=[
                ("取消", "AuroraGhost.TButton", False),
                ("重试", "AuroraPrimary.TButton", True),
            ],
            parent=toplevel,
            default_index=1,
            close_value=False,
        )
    )


class WasteDetectionView:
    """Secondary UI for closed-eye & exposure detection."""

    def __init__(self, parent, root, theme_key, on_back):
        self.parent = parent
        self.root = root
        self.theme_key = theme_key
        self.on_back = on_back
        self.frame = ttk.Frame(parent, style="AuroraPanel.TFrame")
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)

        self.folder_var = tk.StringVar()
        self.status_var = tk.StringVar(value="待机")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_text_var = tk.StringVar(value="0 / 0")
        self.preview_message_var = tk.StringVar(value="选择结果后显示预览")

        self._queue = queue.Queue()
        self._thread = None
        self._cancel_event = threading.Event()
        self._analyzer = None
        self._results = []
        self._result_by_item = {}
        self._current_folder = None
        self._preview_image = None

        self._build_ui()
        self.apply_theme(theme_key)

    # ---------- UI Building ----------
    def _build_ui(self):
        container = ttk.Frame(self.frame, style="AuroraPanel.TFrame")
        container.grid(row=0, column=0, sticky="nsew", padx=36, pady=(0, 28))
        container.grid_rowconfigure(1, weight=1)
        container.grid_columnconfigure(0, weight=3)
        container.grid_columnconfigure(1, weight=2)

        # Controls card
        control_card = ttk.Frame(container, style="AuroraCard.TFrame", padding=(28, 26))
        control_card.grid(row=0, column=0, columnspan=2, sticky="ew")
        control_card.grid_columnconfigure(1, weight=1)
        ttk.Label(control_card, text="闭眼/曝光检测", style="AuroraSection.TLabel").grid(
            row=0, column=0, sticky="w", columnspan=3
        )

        ttk.Label(control_card, text="检测目录", style="AuroraBody.TLabel").grid(
            row=1, column=0, sticky="e", padx=(0, 12), pady=(14, 0)
        )
        entry = ttk.Entry(control_card, textvariable=self.folder_var, width=60, style="Aurora.TEntry")
        entry.grid(row=1, column=1, sticky="ew", pady=(14, 0))
        ttk.Button(
            control_card,
            text="浏览",
            style="AuroraGhost.TButton",
            command=self._choose_folder,
        ).grid(row=1, column=2, padx=(14, 0), pady=(14, 0))

        self.start_btn = ttk.Button(
            control_card,
            text="开始检测",
            style="AuroraPrimary.TButton",
            command=self._start_detection,
        )
        self.start_btn.grid(row=2, column=0, sticky="w", pady=(18, 0))

        self.stop_btn = ttk.Button(
            control_card,
            text="停止",
            style="AuroraDanger.TButton",
            command=self._stop_detection,
            state="disabled",
        )
        self.stop_btn.grid(row=2, column=1, sticky="w", padx=(18, 0), pady=(18, 0))

        ttk.Button(
            control_card,
            text="返回导入界面",
            style="AuroraGhost.TButton",
            command=self._back_to_import,
        ).grid(row=2, column=2, sticky="e", pady=(18, 0))

        progress = ttk.Progressbar(
            control_card,
            mode="determinate",
            maximum=100,
            variable=self.progress_var,
            style="Aurora.Horizontal.TProgressbar",
        )
        progress.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(22, 0))
        ttk.Label(control_card, textvariable=self.progress_text_var, style="AuroraStatus.TLabel").grid(
            row=3, column=2, sticky="e", pady=(22, 0)
        )
        ttk.Label(control_card, textvariable=self.status_var, style="AuroraStatus.TLabel").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(16, 0)
        )

        # Results card
        results_card = ttk.Frame(container, style="AuroraCard.TFrame", padding=(28, 24))
        results_card.grid(row=1, column=0, sticky="nsew", pady=(20, 0))
        results_card.grid_rowconfigure(1, weight=1)
        results_card.grid_columnconfigure(0, weight=1)
        ttk.Label(results_card, text="检测结果", style="AuroraSection.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        columns = ("file", "eyes", "exposure", "confidence")
        self.tree = ttk.Treeview(
            results_card,
            columns=columns,
            show="headings",
            height=10,
        )
        self.tree.heading("file", text="文件")
        self.tree.heading("eyes", text="眼部异常")
        self.tree.heading("exposure", text="曝光")
        self.tree.heading("confidence", text="置信度")
        self.tree.column("file", width=260, anchor="w")
        self.tree.column("eyes", width=160, anchor="w")
        self.tree.column("exposure", width=100, anchor="center")
        self.tree.column("confidence", width=90, anchor="center")
        self.tree.grid(row=1, column=0, sticky="nsew", pady=(18, 0))

        vsb = ttk.Scrollbar(results_card, orient="vertical", command=self.tree.yview, style="Aurora.Vertical.TScrollbar")
        vsb.grid(row=1, column=1, sticky="ns", padx=(16, 0), pady=(18, 0))
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.tag_configure("eyes", foreground="#F87171")
        self.tree.tag_configure("exposure", foreground="#F97316")

        btn_row = ttk.Frame(results_card, style="AuroraCard.TFrame")
        btn_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=0)
        btn_row.columnconfigure(2, weight=0)

        self.delete_btn = ttk.Button(
            btn_row,
            text="删除选中", style="AuroraDanger.TButton", command=self._delete_selected, state="disabled"
        )
        self.delete_btn.grid(row=0, column=2, padx=(16, 0))

        ttk.Button(
            btn_row,
            text="打开所在文件夹",
            style="AuroraPrimary.TButton",
            command=self._open_selected_folder,
        ).grid(row=0, column=1, padx=(16, 0))

        self.open_file_btn = ttk.Button(
            btn_row,
            text="预览原图",
            style="AuroraPrimary.TButton",
            command=self._open_original,
            state="disabled",
        )
        self.open_file_btn.grid(row=0, column=0, sticky="w")

        # Preview card
        preview_card = ttk.Frame(container, style="AuroraCard.TFrame", padding=(28, 24))
        preview_card.grid(row=1, column=1, sticky="nsew", padx=(20, 0), pady=(20, 0))
        preview_card.grid_rowconfigure(1, weight=1)
        preview_card.grid_columnconfigure(0, weight=1)
        ttk.Label(preview_card, text="预览", style="AuroraSection.TLabel").grid(row=0, column=0, sticky="w")

        self.preview_canvas = tk.Canvas(
            preview_card,
            width=420,
            height=320,
            highlightthickness=0,
            bd=0,
        )
        self.preview_canvas.grid(row=1, column=0, sticky="nsew", pady=(18, 0))

        ttk.Label(preview_card, textvariable=self.preview_message_var, style="AuroraStatus.TLabel").grid(
            row=2, column=0, sticky="w", pady=(16, 0)
        )

        # Info/instructions card
        info_card = ttk.Frame(container, style="AuroraCard.TFrame", padding=(28, 24))
        info_card.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(20, 0))
        info_card.grid_rowconfigure(1, weight=1)
        info_card.grid_columnconfigure(0, weight=1)
        ttk.Label(info_card, text="建议与说明", style="AuroraSection.TLabel").grid(row=0, column=0, sticky="w")

        self.info_box = tk.Text(info_card, height=6, wrap="word", bd=0, relief="flat", state="normal")
        self.info_box.insert(
            "end",
            "• 仅对选中目录内的 JPG/JPEG 文件进行检测，且不会自动删除；删除操作需人工确认。\n"
            "• 推荐在电脑硬盘路径运行，不要直接在存储卡上操作，本界面会阻止对移动介质执行批量删除。\n"
            "• 初次使用请安装依赖：pip install mediapipe==0.10.9 opencv-python onnxruntime numpy pillow。\n"
            "• 若电脑具备 NVIDIA GPU，可执行 pip install onnxruntime-gpu insightface，并在 ~/.insightface/models/ 目录放置 antelopev2 模型。\n"
            "  模型下载：https://github.com/deepinsight/insightface/releases/download/antelopev2/antelopev2.zip，解压后保持子目录结构。\n"
            "• 也可使用 CPU 版本（pip install onnxruntime insightface），识别速度较慢但占用低；本界面默认自动检测 mediapipe 并支持 GPU/CPU 回退。\n"
            "• 欠曝/过曝判定依据平均亮度与高低光比例，可在检测后通过预览红框确认眼部区域。\n"
        )
        self.info_box.configure(state="disabled")
        self.info_box.grid(row=1, column=0, sticky="nsew", pady=(16, 0))

        info_sb = ttk.Scrollbar(info_card, orient="vertical", command=self.info_box.yview, style="Aurora.Vertical.TScrollbar")
        info_sb.grid(row=1, column=1, sticky="ns", pady=(16, 0))
        self.info_box.configure(yscrollcommand=info_sb.set)

        self.log_box = tk.Text(info_card, height=6, wrap="word", bd=0, relief="flat", state="disabled")
        self.log_box.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
        info_card.grid_rowconfigure(2, weight=1)
        log_sb = ttk.Scrollbar(info_card, orient="vertical", command=self.log_box.yview, style="Aurora.Vertical.TScrollbar")
        log_sb.grid(row=2, column=1, sticky="ns", pady=(18, 0))
        self.log_box.configure(yscrollcommand=log_sb.set)

    # ---------- Theme & Utility ----------
    def apply_theme(self, theme_key):
        self.theme_key = theme_key
        if hasattr(self, "info_box"):
            set_text_theme(self.info_box, theme_key)
        if hasattr(self, "log_box"):
            set_text_theme(self.log_box, theme_key)
        if self.preview_canvas is not None:
            bg = AURORA_THEME["CARD_HIGHLIGHT"]
            self.preview_canvas.configure(background=bg)

    def show(self):
        self.frame.tkraise()
        self.status_var.set("待机")
        self._append_log("已进入闭眼检测界面")

    def _append_log(self, line: str):
        log_add(self.log_box, line)

    def _choose_folder(self):
        initial = self.folder_var.get() or os.path.expanduser("~")
        folder = filedialog.askdirectory(title="选择需要检测的硬盘目录", initialdir=initial)
        if folder:
            if self._is_removable_drive(folder):
                aurora_showwarning("提示", "检测目标必须位于电脑硬盘，请先复制到硬盘后再进行检测。", parent=self.root)
                return
            self.folder_var.set(folder)
            self._current_folder = folder
            self._append_log(f"选定目录：{folder}")

    def _is_removable_drive(self, path: str) -> bool:
        if os.name == "nt":
            drive, _ = os.path.splitdrive(os.path.abspath(path))
            if drive:
                code = get_drive_type_code(drive)
                return code == 2
        return False

    def _set_running(self, running: bool):
        set_button_state(self.start_btn, active=not running)
        set_button_state(self.stop_btn, active=running, style_active="AuroraDanger.TButton")
        if running:
            self.stop_btn.config(state="normal")
        else:
            self.stop_btn.config(state="disabled")

    def _start_detection(self):
        if self._thread and self._thread.is_alive():
            return
        folder = self.folder_var.get().strip()
        if not folder:
            aurora_showwarning("提示", "请先选择需要检测的目录。", parent=self.root)
            return
        if not os.path.isdir(folder):
            aurora_showwarning("提示", "目录不存在，请重新选择。", parent=self.root)
            return
        if self._is_removable_drive(folder):
            aurora_showwarning("提示", "请勿直接在存储卡上操作，请复制到硬盘后再检测。", parent=self.root)
            return

        try:
            self._analyzer = PhotoQualityAnalyzer()
        except AnalyzerUnavailableError as exc:
            aurora_showwarning("缺少依赖", str(exc), parent=self.root)
            return
        except Exception as exc:
            aurora_showwarning("初始化失败", f"初始化检测模型失败：{exc}", parent=self.root)
            return

        self._results.clear()
        self._result_by_item.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._preview_image = None
        self.preview_canvas.delete("all")
        self.preview_message_var.set("检测进行中…")
        self.progress_var.set(0.0)
        self.progress_text_var.set("0 / 0")
        self.status_var.set("正在初始化检测…")
        self._append_log("开始检测闭眼/曝光问题…")

        self._queue = queue.Queue()
        self._cancel_event.clear()
        self._set_running(True)

        def worker():
            total_flagged = 0
            try:
                def progress_cb(idx, total, path, analysis):
                    if self._cancel_event.is_set():
                        return
                    self._queue.put(("progress", idx, total))
                    if analysis is not None and analysis.has_issue:
                        self._queue.put(("issue", analysis))

                results = self._analyzer.analyze_folder(
                    folder,
                    include_normal=False,
                    cancel_event=self._cancel_event,
                    progress_cb=progress_cb,
                )
                total_flagged = len(results)
                if self._cancel_event.is_set():
                    self._queue.put(("cancelled",))
                else:
                    self._queue.put(("done", total_flagged))
            except Exception as exc:
                self._queue.put(("error", str(exc)))
            finally:
                try:
                    if self._analyzer:
                        self._analyzer.close()
                except Exception:
                    pass

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()
        self._pump_queue()

    def _pump_queue(self):
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "progress":
                    _, idx, total = item
                    if total:
                        self.progress_var.set(max(0.0, min(100.0, idx / total * 100)))
                        self.progress_text_var.set(f"{idx} / {total}")
                    self.status_var.set(f"检测中…({idx}/{total})")
                elif kind == "issue":
                    analysis = item[1]
                    self._add_result(analysis)
                elif kind == "done":
                    flagged = item[1]
                    self.status_var.set(f"检测完成，发现 {flagged} 张异常照片")
                    self._append_log(f"检测完成，共发现 {flagged} 张可能需要关注的照片。")
                    if flagged:
                        self._ask_delete_all()
                    self._set_running(False)
                    self.preview_message_var.set("选择结果查看预览")
                elif kind == "cancelled":
                    self.status_var.set("已取消")
                    self.preview_message_var.set("检测已取消")
                    self._append_log("用户取消检测")
                    self._set_running(False)
                elif kind == "error":
                    msg = item[1]
                    self.status_var.set("检测失败")
                    self.preview_message_var.set("检测失败")
                    self._append_log(f"检测失败：{msg}")
                    aurora_showwarning("检测失败", msg, parent=self.root)
                    self._set_running(False)
        except queue.Empty:
            pass
        if self._thread and self._thread.is_alive():
            self.frame.after(120, self._pump_queue)

    def _add_result(self, analysis: PhotoQualityResult):
        self._results.append(analysis)
        tags = []
        if analysis.eye_issues:
            tags.append("eyes")
        if analysis.exposure_issue and analysis.exposure_issue.status != "正常":
            tags.append("exposure")
        eye_conf = max((issue.confidence for issue in analysis.eye_issues), default=0.0)
        expo_conf = analysis.exposure_issue.confidence if analysis.exposure_issue else 0.0
        conf_text = f"眼{eye_conf:.2f}/光{expo_conf:.2f}" if (eye_conf or expo_conf) else "--"
        item = self.tree.insert(
            "",
            "end",
            values=(analysis.rel_path, analysis.closed_eye_summary, analysis.exposure_issue.status if analysis.exposure_issue else "--", conf_text),
            tags=tags,
        )
        self._result_by_item[item] = analysis
        self.delete_btn.config(state="normal")

    def _stop_detection(self):
        if self._thread and self._thread.is_alive():
            self._cancel_event.set()
            self.status_var.set("取消中…")
            self._append_log("正在取消检测…")

    def _on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            self.preview_canvas.delete("all")
            self.preview_message_var.set("选择结果后显示预览")
            self.open_file_btn.config(state="disabled")
            return
        item = sel[0]
        analysis = self._result_by_item.get(item)
        if analysis is None:
            return
        self.open_file_btn.config(state="normal")
        self.preview_message_var.set(f"{analysis.rel_path}")
        self._render_preview(analysis)

    def _render_preview(self, analysis: PhotoQualityResult):
        self.preview_canvas.delete("all")
        if Image is None or ImageDraw is None or ImageTk is None:
            self.preview_message_var.set("需要安装 Pillow 才能预览")
            return
        try:
            image = Image.open(analysis.path)
        except Exception as exc:
            self.preview_message_var.set(f"无法打开图片：{exc}")
            return
        image = image.convert("RGB")
        draw = ImageDraw.Draw(image)
        scale = max(1, image.width // 450)
        for issue in analysis.eye_issues:
            draw.rectangle(issue.bbox, outline=(255, 80, 80), width=scale)
            draw.text((issue.bbox[0] + 4, issue.bbox[1] + 4), issue.status, fill=(255, 80, 80))
        if analysis.exposure_issue and analysis.exposure_issue.status != "正常":
            draw.rectangle((12, 12, 12 + 220, 60), outline=(255, 208, 0), width=scale)
            draw.text((20, 20), f"曝光：{analysis.exposure_issue.status}", fill=(255, 208, 0))
        preview = ImageOps.contain(image, (420, 320)) if ImageOps else image
        self._preview_image = ImageTk.PhotoImage(preview)
        self.preview_canvas.create_image(210, 160, image=self._preview_image)

    def _open_original(self):
        sel = self.tree.selection()
        if not sel:
            return
        analysis = self._result_by_item.get(sel[0])
        if analysis:
            try:
                if sys.platform.startswith("win"):
                    os.startfile(analysis.path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", analysis.path])
                else:
                    subprocess.Popen(["xdg-open", analysis.path])
            except Exception as exc:
                aurora_showwarning("打开失败", f"无法打开文件：{exc}", parent=self.root)

    def _open_selected_folder(self):
        sel = self.tree.selection()
        if not sel:
            return
        analysis = self._result_by_item.get(sel[0])
        if not analysis:
            return
        folder = os.path.dirname(analysis.path)
        if not folder:
            return
        _open_folder(folder)

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        paths = []
        for item in sel:
            analysis = self._result_by_item.get(item)
            if analysis:
                paths.append(analysis.path)
        if not paths:
            return
        if not aurora_askyesno("删除确认", f"确认删除选中的 {len(paths)} 张照片？操作不可撤销。", parent=self.root):
            return
        removed = 0
        for item in list(sel):
            analysis = self._result_by_item.get(item)
            if not analysis:
                continue
            try:
                if os.path.isfile(analysis.path):
                    os.remove(analysis.path)
                    removed += 1
            except Exception as exc:
                self._append_log(f"删除失败：{analysis.rel_path} | {exc}")
                continue
            self.tree.delete(item)
            self._result_by_item.pop(item, None)
        self._append_log(f"已删除 {removed} 张照片。")
        if not self.tree.get_children():
            self.delete_btn.config(state="disabled")

    def _ask_delete_all(self):
        flagged = [analysis for analysis in self._results if analysis.eye_issues]
        if not flagged:
            return
        if aurora_askyesno(
            "批量删除确认",
            f"检测到 {len(flagged)} 张可能闭眼或视线异常的照片，是否立即全部删除？",
            parent=self.root,
        ):
            for analysis in flagged:
                try:
                    if os.path.isfile(analysis.path):
                        os.remove(analysis.path)
                except Exception as exc:
                    self._append_log(f"批量删除失败：{analysis.rel_path} | {exc}")
            self._append_log("批量删除完成。刷新列表。")
            self._refresh_after_deletion()

    def _refresh_after_deletion(self):
        for item, analysis in list(self._result_by_item.items()):
            if not os.path.isfile(analysis.path):
                self.tree.delete(item)
                self._result_by_item.pop(item, None)
        if not self.tree.get_children():
            self.delete_btn.config(state="disabled")

    def _back_to_import(self):
        if callable(self.on_back):
            self.on_back()

# ---------- 列表刷新 ----------
def refresh_sources(info_box, combo_src, auto_pick=False):
    all_drives=list_drives()
    removable=[]; src_vals=[]
    for d in all_drives:
        tname=drive_type_name(get_drive_type_code(d))
        if get_drive_type_code(d)==2: removable.append(d)
        tag="(系统)" if is_system_drive(d) else ""
        src_vals.append(f"{d}  |  名称: {get_drive_label(d)}  |  类型: {tname}{tag}")
    combo_src["values"]=src_vals
    if auto_pick and removable:
        pick=removable[0]
        for i,s in enumerate(src_vals):
            if s.startswith(pick): combo_src.current(i); break
    log_init_if_empty(info_box,"日志已启动")
    if removable: log_add(info_box, f"发现移动盘：{', '.join(removable)}")
    else: log_add(info_box, "未检测到移动盘")

def refresh_dests(info_box, combo_dst):
    vals=[]
    for part in _disk_partitions(all=False):
        mount = getattr(part, "mountpoint", "")
        device = getattr(part, "device", "")
        if os.name == "nt":
            letter = device.rstrip("\\") or mount.rstrip("\\")
            if not letter:
                continue
            if get_drive_type_code(letter) != 3:
                continue
            label = get_drive_label(letter)
            usage_key = letter
        else:
            letter = mount or device
            if not letter:
                continue
            label = os.path.basename(letter) or letter
            usage_key = letter
        try:
            total,free=get_drive_usage_bytes(usage_key)
        except Exception:
            continue
        vals.append(f"{letter} {label}（{bytes_to_human(free)} / {bytes_to_human(total)}）")
    combo_dst["values"]=vals
    log_add(info_box, "已刷新目标固定磁盘列表" if vals else "未检测到目标固定磁盘")

# ---------- 复制入口 ----------
def start_copy(
    src_drive,
    dst_letter,
    cfg,
    root,
    category,
    info_box,
    btn_start,
    status_lbl,
    pause_btn,
    cancel_btn,
    star_btn,
    star_refresh_cb,
    state,
    extract_star=False,
):
    if state.is_copying:
        log_add(info_box, "已有任务正在进行，请稍后。")
        return

    if not category:
        aurora_showwarning("提示", "请先选择拍摄类型。", parent=root)
        return

    dtype = drive_type_name(get_drive_type_code(src_drive))
    log_add(info_box, f"素材盘：{src_drive}（{get_drive_label(src_drive)} | {dtype}）")
    if is_system_drive(src_drive):
        if not aurora_askyesno("高风险确认", f"{src_drive} 是系统盘，不建议作为素材盘源。继续？", parent=root):
            return
        if not aurora_askyesno("二次确认", "再次确认从系统盘作为相机源复制？", parent=root):
            return
    elif get_drive_type_code(src_drive) != 2:
        if not aurora_askyesno("固定磁盘警告", f"{src_drive} 为固定盘，通常应选移动盘。继续？", parent=root):
            return

    shoot_name = aurora_askstring("本次拍摄名称", "输入拍摄地点或主题（可中文）：", parent=root, initialvalue="")
    if not shoot_name:
        return

    total_b, free_b = get_drive_usage_bytes(src_drive)
    log_add(info_box, f"素材盘容量：{bytes_to_human(total_b)} | 剩余：{bytes_to_human(free_b)}")
    log_add(info_box, "开始预检源文件…")
    counts, sizes, files = preflight_scan(src_drive)
    total_files = counts["RAW"] + counts["JPG"] + counts["VIDEO"]
    total_size = sizes["RAW"] + sizes["JPG"] + sizes["VIDEO"]
    log_add(
        info_box,
        f"预检完成 RAW:{counts['RAW']} JPG:{counts['JPG']} VIDEO:{counts['VIDEO']} 合计:{total_files} | 体积 {bytes_to_human(total_size)}",
    )

    if not aurora_askyesno(
        "确认复制",
        "预检完成：\n"
        f"RAW：{counts['RAW']}（{bytes_to_human(sizes['RAW'])}）\n"
        f"JPG：{counts['JPG']}（{bytes_to_human(sizes['JPG'])}）\n"
        f"VIDEO：{counts['VIDEO']}（{bytes_to_human(sizes['VIDEO'])}）\n"
        f"合计：{total_files}（{bytes_to_human(total_size)}）\n\n"
        "将复制到：年/拍摄类型/“MM月”/“MM.DD_拍摄名”/（RAW,JPG,VIDEO，及可选已星标照片）\n"
        "照片重命名：MMDD-0001 起；视频保留原名。",
        parent=root,
    ):
        log_add(info_box, "用户取消复制")
        return

    if dst_letter:
        if os.name == "nt" and not dst_letter.endswith("\\"):
            target_root = dst_letter + "\\"
        else:
            target_root = dst_letter
    else:
        target_root = cfg.get("last_target_root", "")
        if not os.path.exists(target_root):
            target_root = filedialog.askdirectory(title="选择目标硬盘文件夹（建议为外置硬盘根目录）")
            if not target_root:
                return
    cfg["last_target_root"] = target_root
    save_config(cfg)
    if os.path.splitdrive(target_root)[0].upper() == os.path.splitdrive(src_drive)[0].upper():
        if not aurora_askyesno("风险提示", "目标盘与素材盘相同盘符，建议不同物理盘。继续？", parent=root):
            return

    today = datetime.now()
    year_dir = os.path.join(target_root, str(today.year))
    cat_dir = os.path.join(year_dir, category)
    month_dir = os.path.join(cat_dir, f"{today.month:02d}月")
    day_folder = f"{today.month:02d}.{today.day:02d}_{shoot_name}"
    target_dir = os.path.join(month_dir, day_folder)
    os.makedirs(target_dir, exist_ok=True)
    month_cn_dir = os.path.join(target_root, f"{today.year}年{today.month:02d}月")
    day_cn_dir = os.path.join(month_cn_dir, f"{today.month:02d}月{today.day:02d}日")
    try:
        os.makedirs(day_cn_dir, exist_ok=True)
    except Exception:
        pass
    log_add(info_box, f"目标目录：{target_dir}")

    try:
        usage_key = dst_letter or target_root
        _, dst_free = get_drive_usage_bytes(usage_key)
        if dst_free < total_size:
            log_add(info_box, f"目标剩余 {bytes_to_human(dst_free)} < 需要 {bytes_to_human(total_size)}")
            if not aurora_askretrycancel(
                "空间不足",
                f"目标剩余 {bytes_to_human(dst_free)}，预计需要 {bytes_to_human(total_size)}。清理后重试。",
                parent=root,
            ):
                return
    except Exception:
        pass

    log_file = os.path.join(target_dir, "copy_log.txt")
    mmdd_str = f"{today.month:02d}{today.day:02d}"

    progress_start_fn = getattr(state, "progress_start", None)
    progress_stop_fn = getattr(state, "progress_stop_done", None)
    progress_reset_fn = getattr(state, "progress_cancel_reset", None)

    if callable(progress_reset_fn):
        progress_reset_fn()
    status_lbl.config(text="准备复制…")
    if state.progress_eta_var is not None:
        state.progress_eta_var.set("剩余时间：计算中…")
        state.last_eta_text = "剩余时间：计算中…"

    beep_start()
    log_add(info_box, "开始复制…")

    set_button_state(btn_start, active=False)
    set_button_state(pause_btn, active=False)
    pause_btn.config(text="暂停")
    set_button_state(cancel_btn, active=False, style_active="AuroraDanger.TButton")
    set_button_state(star_btn, active=False)

    state.is_copying = True
    state.is_paused = False
    state.cancel_ev.clear()
    state.pause_ev.clear()
    state.copied_paths.clear()
    state.total_bytes = total_size
    state.copied_bytes = 0
    state.progress_phase = "准备复制…"
    state.progress_speed = 0.0
    while True:
        try:
            state.progress_queue.get_nowait()
        except queue.Empty:
            break

    if callable(progress_start_fn):
        progress_start_fn(total_size)

    def safe_log(message):
        root.after(0, lambda m=message: log_add(info_box, m))

    def progress_cb(delta_bytes, phase, done_bytes, total, speed_mb):
        state.progress_queue.put(("progress", delta_bytes, done_bytes, total, phase, speed_mb))

    def on_file_done(path):
        state.copied_paths.append(path)

    def worker():
        created = []
        cancelled = False
        error = None
        manifest_path = None
        removed_dirs = []
        try:
            created = copy_with_progress_seq_and_video(
                files,
                target_dir,
                None,
                None,
                log_file,
                mmdd_str,
                None,
                total_bytes=total_size,
                extract_star=extract_star,
                progress_hook=progress_cb,
                cancel_ev=state.cancel_ev,
                pause_ev=state.pause_ev,
                log_func=safe_log,
                on_file_done=on_file_done,
            )
        except KeyboardInterrupt:
            cancelled = True
        except Exception as exc:
            error = exc

        if state.cancel_ev.is_set():
            cancelled = True

        if cancelled or error is not None:
            removed = rollback_files(list(state.copied_paths), target_dir)
            removed_dirs.extend(remove_daily_folder_tree(target_dir, today))
        else:
            removed = 0
            ts2 = datetime.now().strftime("%Y%m%d_%H%M%S")
            manifest_path = os.path.join(target_dir, f"import_manifest_{ts2}.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "version": VERSION,
                        "created_at": ts2,
                        "source_drive": src_drive,
                        "target_dir": target_dir,
                        "files": created,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

        def finalize():
            state.is_copying = False
            state.is_paused = False
            state.pause_ev.clear()
            state.cancel_ev.clear()
            state.copied_paths.clear()
            state.total_bytes = 0
            state.copied_bytes = 0
            state.progress_phase = "待机"
            state.progress_speed = 0.0

            set_button_state(btn_start, active=True)
            set_button_state(pause_btn, active=False)
            pause_btn.config(text="暂停")
            set_button_state(cancel_btn, active=False, style_active="AuroraDanger.TButton")
            set_button_state(star_btn, active=True)
            if star_refresh_cb is not None:
                try:
                    star_refresh_cb()
                except Exception:
                    pass

            if cancelled:
                if callable(progress_reset_fn):
                    progress_reset_fn()
                status_lbl.config(text="已取消")
                log_add(info_box, "已取消并回滚")
                if state.progress_eta_var is not None:
                    state.progress_eta_var.set("已取消")
                    state.last_eta_text = "已取消"
                if removed:
                    log_add(info_box, f"已清理 {removed} 个文件")
                if removed_dirs:
                    for d in removed_dirs:
                        log_add(info_box, f"已删除目录：{d}")
            elif error is not None:
                if callable(progress_reset_fn):
                    progress_reset_fn()
                status_lbl.config(text="复制失败")
                log_add(info_box, f"复制失败：{error}")
                if state.progress_eta_var is not None:
                    state.progress_eta_var.set("复制失败")
                    state.last_eta_text = "复制失败"
                if removed:
                    log_add(info_box, f"已清理 {removed} 个文件")
                if removed_dirs:
                    for d in removed_dirs:
                        log_add(info_box, f"已删除目录：{d}")
                aurora_showwarning("复制失败", f"发生错误：{error}", parent=root)
            else:
                if callable(progress_stop_fn):
                    progress_stop_fn()
                status_lbl.config(text="复制完成")
                log_add(info_box, f"复制完成 共 {len(created)} 个目标文件")
                if manifest_path:
                    log_add(info_box, f"清单已保存：{manifest_path}")
                beep_done()
                show_finish_and_undo(root, target_dir, created, today)

        root.after(0, finalize)

    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()

    set_button_state(pause_btn, active=True)
    pause_btn.config(text="暂停")
    set_button_state(cancel_btn, active=True, style_active="AuroraDanger.TButton")

# ---------- CLI 模式 ----------
def _prompt_directory(prompt, allow_create=False):
    while True:
        try:
            raw = input(prompt).strip().strip('"')
        except EOFError:
            return None
        if not raw:
            print("输入不能为空，请重新输入。")
            continue
        path = os.path.abspath(raw)
        if os.path.isdir(path):
            return path
        if allow_create:
            try:
                os.makedirs(path, exist_ok=True)
                return path
            except Exception as exc:
                print(f"创建目录失败：{exc}")
        print("目录不存在，请重新输入。")


def run_cli(reason=None):
    if reason:
        msg = f"[提示] {reason}，已切换到命令行模式。按 Ctrl+C 可随时中断。"
    else:
        msg = "[提示] 已切换到命令行模式。按 Ctrl+C 可随时中断。"
    print(msg)

    try:
        src_root = None
        while src_root is None:
            src_root = _prompt_directory("请输入素材所在的文件夹路径：")
            if src_root is None:
                print("未获得有效路径，已退出。")
                return
            counts, sizes, files = preflight_scan(src_root)
            total_files = counts["RAW"] + counts["JPG"] + counts["VIDEO"]
            total_size = sizes["RAW"] + sizes["JPG"] + sizes["VIDEO"]
            if total_files == 0:
                print("该目录内未检测到可处理的照片或视频，请重新选择。")
                src_root = None

        dst_root = _prompt_directory("请输入导入目标根目录（例如备份硬盘）：", allow_create=True)
        if dst_root is None:
            print("未获得有效目标目录，已退出。")
            return

        print("可选拍摄类型：")
        for idx, name in enumerate(CATEGORIES, 1):
            print(f"  {idx}. {name}")
        while True:
            try:
                sel = input("请选择拍摄类型（输入序号，默认 1）：").strip()
            except EOFError:
                print("未获得输入，已退出。")
                return
            if not sel:
                category = CATEGORIES[0]
                break
            if sel.isdigit() and 1 <= int(sel) <= len(CATEGORIES):
                category = CATEGORIES[int(sel)-1]
                break
            print("输入无效，请重新输入。")

        default_name = os.path.basename(os.path.normpath(src_root)) or "作品"
        try:
            shoot_name = input(f"请输入拍摄主题（默认：{default_name}）：").strip()
        except EOFError:
            print("未获得输入，已退出。")
            return
        if not shoot_name:
            shoot_name = default_name

        try:
            star_answer = input("是否提取星标照片？(y/N)：").strip().lower()
        except EOFError:
            star_answer = ""
        extract_star = star_answer in {"y", "yes", "是"}

        print("\n预检结果：")
        print(f"  RAW: {counts['RAW']} 张，共 {bytes_to_human(sizes['RAW'])}")
        print(f"  JPG: {counts['JPG']} 张，共 {bytes_to_human(sizes['JPG'])}")
        print(f"  VIDEO: {counts['VIDEO']} 个，共 {bytes_to_human(sizes['VIDEO'])}")
        total_size = sizes["RAW"] + sizes["JPG"] + sizes["VIDEO"]
        print(f"  总计：{total_files} 个文件，约 {bytes_to_human(total_size)}")

        today = datetime.now()
        year_dir = os.path.join(dst_root, f"{today.year}")
        cat_dir = os.path.join(year_dir, category)
        month_dir = os.path.join(cat_dir, f"{today.month:02d}月")
        day_folder = f"{today.month:02d}.{today.day:02d}_{shoot_name}"
        target_dir = os.path.join(month_dir, day_folder)
        os.makedirs(target_dir, exist_ok=True)

        try:
            usage_key = dst_root
            _, dst_free = get_drive_usage_bytes(usage_key)
        except Exception:
            dst_free = None
        if dst_free is not None and dst_free < total_size:
            print(f"[警告] 目标磁盘剩余 {bytes_to_human(dst_free)}，低于预计需要的 {bytes_to_human(total_size)}。")
            try:
                cont = input("是否继续？(y/N)：").strip().lower()
            except EOFError:
                cont = ""
            if cont not in {"y", "yes", "是"}:
                print("用户取消导入。")
                return

        print(f"\n导入目标目录：{target_dir}")
        log_file = os.path.join(target_dir, "copy_log.txt")
        mmdd_str = f"{today.month:02d}{today.day:02d}"

        print("开始复制，请稍候…")
        beep_start()

        last_emit = 0.0

        def progress_hook(delta_bytes, phase, done_bytes, total_bytes, speed_mb):
            nonlocal last_emit
            now = time.time()
            if now - last_emit < 0.5 and done_bytes < total_bytes:
                return
            pct = (done_bytes / total_bytes * 100) if total_bytes else 0.0
            print(f"[{ts()}] {phase} {pct:5.1f}% | {bytes_to_human(done_bytes)} / {bytes_to_human(total_bytes)} | 速度 {speed_mb:.2f} MB/s", end="\r" if done_bytes < total_bytes else "\n")
            last_emit = now

        created = []
        try:
            created = copy_with_progress_seq_and_video(
                files, target_dir, None, None, log_file, mmdd_str, None,
                total_bytes=total_size, extract_star=extract_star, progress_hook=progress_hook
            )
        except KeyboardInterrupt:
            print("\n用户中断，正在清理未完成的复制文件…")
            for p in created:
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass
            return

        print("\n复制完成！")
        beep_done()
        print(f"本次共生成 {len(created)} 个文件。")

        ts2 = datetime.now().strftime("%Y%m%d_%H%M%S")
        manifest_path = os.path.join(target_dir, f"import_manifest_{ts2}.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({
                "version": VERSION,
                "created_at": ts2,
                "source": src_root,
                "target_dir": target_dir,
                "category": category,
                "files": created,
                "extract_star": extract_star,
            }, f, ensure_ascii=False, indent=2)
        print(f"导入清单已保存：{manifest_path}")
        print("感谢使用命令行模式。")
    except KeyboardInterrupt:
        print("\n用户取消操作。")


# ---------- UI（分割窗可拖动） ----------
def main_ui():
    cfg = load_config()
    theme_key = cfg.get("theme", DEFAULT_THEME_KEY)
    if theme_key not in {DEFAULT_THEME_KEY}:
        theme_key = DEFAULT_THEME_KEY

    enable_high_dpi_awareness()
    try:
        root = tk.Tk()
    except Exception:
        print("[提示] 无法初始化图形界面，自动切换到命令行模式。")
        run_cli(reason="无法初始化图形界面")
        return
    set_tk_scaling(root)
    root.title(f"陈同学影像管理助手  {VERSION}")
    root.geometry("1180x760")
    root.minsize(960, 640)
    root.resizable(True, True)

    apply_theme(root, theme_key)

    root.grid_rowconfigure(1, weight=1)
    root.grid_columnconfigure(0, weight=1)

    state = SimpleNamespace(
        cancel_ev=threading.Event(),
        pause_ev=threading.Event(),
        is_copying=False,
        is_paused=False,
        copied_paths=[],
        progress_queue=queue.Queue(),
        total_bytes=0,
        copied_bytes=0,
        progress_phase="待机",
        progress_speed=0.0,
        anim_cur=0.0,
        anim_tgt=0.0,
        anim_running=False,
        last_real_update=time.monotonic(),
        last_sim_bump=time.monotonic(),
        progress_value_var=None,
        progress_pct_var=None,
        progress_eta_var=None,
        last_eta_text="剩余时间：--",
        progress_start_time=0.0,
    )

    header = ttk.Frame(root, style="AuroraHeader.TFrame", padding=(32, 26))
    header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=36, pady=(28, 16))
    header.grid_columnconfigure(0, weight=1)
    header.grid_columnconfigure(3, weight=0)
    accent = ttk.Frame(header, style="AuroraAccent.TFrame", height=4)
    accent.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 20))
    accent.grid_propagate(False)
    ttk.Label(header, text="照片/视频导入与分类", style="AuroraTitle.TLabel").grid(row=1, column=0, sticky="w")
    ttk.Label(header, text="主题", style="AuroraBodyOnPanel.TLabel").grid(row=1, column=1, sticky="e", padx=(24, 10))
    theme_box = ttk.Combobox(header, state="readonly", values=THEMES, width=8, style="Aurora.TCombobox")
    theme_box.grid(row=1, column=2, sticky="e")
    theme_box.set(THEMES[0])

    detect_btn = ttk.Button(header, text="检测废片", style="AuroraPrimary.TButton")
    detect_btn.grid(row=1, column=3, sticky="e", padx=(18, 0))

    content_container = ttk.Frame(root, style="AuroraPanel.TFrame")
    content_container.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=36, pady=(0, 28))
    content_container.grid_rowconfigure(0, weight=1)
    content_container.grid_columnconfigure(0, weight=1)

    import_frame = ttk.Frame(content_container, style="AuroraPanel.TFrame")
    import_frame.grid(row=0, column=0, sticky="nsew")
    import_frame.grid_columnconfigure(0, weight=1)
    import_frame.grid_columnconfigure(1, weight=0)
    import_frame.grid_rowconfigure(0, weight=1)

    waste_frame = ttk.Frame(content_container, style="AuroraPanel.TFrame")
    waste_frame.grid(row=0, column=0, sticky="nsew")
    waste_frame.grid_remove()

    waste_ui = WasteDetectionUI(root, waste_frame, theme_key, on_back=lambda: None)

    def goto_import():
        waste_ui.on_hide()
        waste_frame.grid_remove()
        import_frame.grid()
        detect_btn.config(text="检测废片", command=goto_waste)

    def goto_waste():
        import_frame.grid_remove()
        waste_frame.grid()
        waste_ui.on_show()
        detect_btn.config(text="返回导入界面", command=goto_import)

    detect_btn.config(command=goto_waste)
    waste_ui.on_back = goto_import

    right_col = ttk.Frame(import_frame, style="AuroraPanel.TFrame", width=LOG_PANEL_WIDTH)
    right_col.grid(row=0, column=1, sticky="ns")
    right_col.grid_propagate(False)
    right_col.grid_rowconfigure(0, weight=1)

    log_card = ttk.Frame(right_col, style="AuroraCard.TFrame", padding=(28, 24))
    log_card.grid(row=0, column=0, sticky="nsew")
    log_card.grid_rowconfigure(1, weight=1)
    log_card.grid_columnconfigure(0, weight=1)
    ttk.Label(log_card, text="信息", style="AuroraSection.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 16))
    info_box = tk.Text(log_card, height=10, wrap="word", bd=0, relief="flat", state="disabled")
    set_text_theme(info_box, theme_key)
    info_box.grid(row=1, column=0, sticky="nsew")
    sb = ttk.Scrollbar(log_card, command=info_box.yview, orient="vertical", style="Aurora.Vertical.TScrollbar")
    sb.grid(row=1, column=1, sticky="ns", padx=(16, 0))
    info_box.configure(yscrollcommand=sb.set)

    left_col = ttk.Frame(import_frame, style="AuroraPanel.TFrame")
    left_col.grid(row=0, column=0, sticky="nsew")
    left_col.grid_columnconfigure(0, weight=1)

    card1 = ttk.Frame(left_col, style="AuroraCard.TFrame", padding=(28, 26))
    card1.grid(row=0, column=0, sticky="ew")
    card1.grid_columnconfigure(1, weight=1)
    card1.grid_columnconfigure(2, weight=0)
    card1.grid_columnconfigure(3, weight=0)
    ttk.Label(card1, text="导入设置", style="AuroraSection.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 16), columnspan=5)

    ttk.Label(card1, text="选择素材盘", style="AuroraBody.TLabel").grid(row=1, column=0, sticky="e", padx=(0, 12))
    combo_src = ttk.Combobox(card1, state="readonly", width=70, style="Aurora.TCombobox")
    combo_src.grid(row=1, column=1, sticky="ew")
    ttk.Button(card1, text="刷新", style="AuroraGhost.TButton",
               command=lambda: refresh_sources(info_box, combo_src, auto_pick=True)).grid(row=1, column=2, padx=(14, 0))

    ttk.Label(card1, text="拷入到", style="AuroraBody.TLabel").grid(row=2, column=0, sticky="e", padx=(0, 12), pady=(14, 0))
    combo_dst = ttk.Combobox(card1, state="readonly", width=50, style="Aurora.TCombobox")
    combo_dst.grid(row=2, column=1, sticky="ew", pady=(14, 0))
    ttk.Button(card1, text="刷新", style="AuroraGhost.TButton",
               command=lambda: refresh_dests(info_box, combo_dst)).grid(row=2, column=2, padx=(14, 0), pady=(14, 0))

    ttk.Label(card1, text="拍摄类型", style="AuroraBody.TLabel").grid(row=3, column=0, sticky="e", padx=(0, 12), pady=(14, 0))
    combo_cat = ttk.Combobox(card1, state="readonly", values=CATEGORIES, width=20, style="Aurora.TCombobox")
    combo_cat.grid(row=3, column=1, sticky="w", pady=(14, 0))
    combo_cat.current(0)

    extract_star_enabled = False

    def refresh_star_button_visual():
        suffix = "√" if extract_star_enabled else "×"
        star_btn.config(text=f"提取星标照片 {suffix}")
        if str(star_btn["state"]) == "normal":
            style_name = "AuroraSuccess.TButton" if extract_star_enabled else "AuroraPrimary.TButton"
            star_btn.config(style=style_name)

    def toggle_star():
        nonlocal extract_star_enabled
        extract_star_enabled = not extract_star_enabled
        refresh_star_button_visual()
        log_add(info_box, "已启用星标提取" if extract_star_enabled else "已关闭星标提取")

    star_btn = ttk.Button(
        card1,
        text="提取星标照片 ×",
        style="AuroraPrimary.TButton",
        command=toggle_star,
    )
    star_btn.grid(row=3, column=2, sticky="w", padx=(18, 0), pady=(14, 0))

    set_button_state(star_btn, active=True)
    refresh_star_button_visual()

    card3 = ttk.Frame(left_col, style="AuroraCard.TFrame", padding=(28, 24))
    card3.grid(row=1, column=0, sticky="ew", pady=(20, 0))
    card3.grid_columnconfigure(0, weight=1)
    card3.grid_columnconfigure(1, weight=0)
    card3.grid_columnconfigure(2, weight=1)
    card3.grid_columnconfigure(3, weight=0)
    card3.grid_columnconfigure(4, weight=0)
    card3.grid_columnconfigure(5, weight=0)
    progress_value_var = tk.DoubleVar(value=0.0)
    pb_main = ttk.Progressbar(
        card3,
        mode="determinate",
        maximum=100,
        variable=progress_value_var,
        style="Aurora.Horizontal.TProgressbar",
    )
    pb_main.grid(row=0, column=0, columnspan=4, sticky="ew")
    progress_pct_var = tk.StringVar(value="进度: 0.0%")
    ttk.Label(card3, textvariable=progress_pct_var, style="AuroraStatus.TLabel").grid(
        row=0, column=4, sticky="e", padx=(16, 0)
    )
    eta_var = tk.StringVar(value="剩余时间：--")
    ttk.Label(card3, textvariable=eta_var, style="AuroraStatus.TLabel").grid(
        row=0, column=5, sticky="w", padx=(16, 0)
    )
    status_lbl = ttk.Label(card3, text="待机", style="AuroraStatus.TLabel")
    status_lbl.grid(row=1, column=0, columnspan=5, sticky="w", pady=(12, 0))

    state.progress_value_var = progress_value_var
    state.progress_pct_var = progress_pct_var
    state.progress_eta_var = eta_var

    def progress_start(total_bytes):
        state.anim_cur = 0.0
        state.anim_tgt = 0.0
        state.anim_running = True
        state.total_bytes = total_bytes
        state.copied_bytes = 0
        now = time.monotonic()
        state.last_real_update = now
        state.last_sim_bump = now
        state.progress_start_time = now
        progress_value_var.set(0.0)
        progress_pct_var.set("进度: 0.0%")
        state.last_eta_text = "剩余时间：计算中…"
        if state.progress_eta_var is not None:
            state.progress_eta_var.set("剩余时间：计算中…")

    def progress_set_real(copied, total):
        if not state.anim_running:
            return
        now = time.monotonic()
        if total > 0 and copied >= total:
            state.last_real_update = now
            progress_stop_done()
            return
        if total > 0:
            percent = max(0.0, min(100.0, (copied / total) * 100.0))
            target = min(99.0, percent)
        else:
            target = min(99.0, state.anim_tgt + 0.5)
        state.anim_tgt = max(0.0, target)
        state.last_real_update = now

    def progress_bump_sim(pace=0.3, cap=99.0):
        if not state.anim_running:
            return
        if state.anim_tgt >= cap:
            return
        state.anim_tgt = min(cap, state.anim_tgt + pace)
        state.last_sim_bump = time.monotonic()

    def progress_stop_done():
        state.anim_running = True
        state.anim_tgt = 100.0
        state.last_real_update = time.monotonic()
        if state.progress_eta_var is not None:
            state.progress_eta_var.set("完成")
            state.last_eta_text = "完成"

    def progress_cancel_reset():
        state.anim_running = False
        state.anim_tgt = 0.0
        state.anim_cur = 0.0
        state.total_bytes = 0
        state.copied_bytes = 0
        progress_value_var.set(0.0)
        progress_pct_var.set("进度: 0.0%")
        state.last_real_update = time.monotonic()
        state.last_sim_bump = state.last_real_update
        state.progress_start_time = 0.0
        state.last_eta_text = "剩余时间：--"
        if state.progress_eta_var is not None:
            state.progress_eta_var.set("剩余时间：--")

    def progress_tick():
        target = state.anim_tgt
        current = state.anim_cur
        if abs(target - current) > 0.01:
            step = max(0.2, abs(target - current) * 0.25)
            if current < target:
                current = min(current + step, target)
            else:
                current = max(current - step, target)
            state.anim_cur = current
        else:
            state.anim_cur = target
        progress_value_var.set(state.anim_cur)
        progress_pct_var.set(f"进度: {state.anim_cur:.1f}%")
        root.after(50, progress_tick)

    state.progress_start = progress_start
    state.progress_stop_done = progress_stop_done
    state.progress_cancel_reset = progress_cancel_reset

    def pump_progress():
        drained = 0
        last_phase = None
        last_speed = None
        last_done = None
        last_total = None
        had_real_update = False
        try:
            while True:
                item = state.progress_queue.get_nowait()
                if not isinstance(item, tuple) or not item:
                    continue
                kind = item[0]
                if kind == "progress" and len(item) == 6:
                    _, delta, done_bytes, total_bytes, phase, speed_mb = item
                    drained += max(delta, 0)
                    last_phase = phase
                    last_speed = speed_mb
                    last_done = max(done_bytes, 0)
                    last_total = max(total_bytes, 0)
        except queue.Empty:
            pass

        if last_total is not None:
            state.total_bytes = last_total
        if last_phase is not None:
            state.progress_phase = last_phase
        if last_speed is not None:
            state.progress_speed = last_speed

        if last_done is not None:
            state.copied_bytes = last_done
            had_real_update = True
        elif drained:
            state.copied_bytes = max(0, state.copied_bytes + drained)
            had_real_update = True

        if had_real_update:
            progress_set_real(state.copied_bytes, state.total_bytes)

        now = time.monotonic()
        eta_text = None
        if state.anim_running and state.is_copying and not state.is_paused:
            if had_real_update:
                state.last_sim_bump = now
            elif (now - state.last_real_update) > 0.4 and (now - state.last_sim_bump) > 0.4:
                progress_bump_sim()

        if state.is_copying:
            total = state.total_bytes
            done = min(state.copied_bytes, total) if total else state.copied_bytes
            current_phase = state.progress_phase or "进度"
            status_lbl.config(
                text=f"{current_phase} | {bytes_to_human(done)} / {bytes_to_human(total)} | 速度 {state.progress_speed:.2f} MB/s"
            )
            if state.is_paused:
                eta_text = "已暂停"
            elif state.cancel_ev.is_set():
                eta_text = "取消中…"
            else:
                remaining = max(state.total_bytes - state.copied_bytes, 0)
                elapsed = now - state.progress_start_time if state.progress_start_time else 0.0
                if remaining <= 0:
                    eta_text = "完成"
                elif elapsed > 0 and state.copied_bytes > 0:
                    avg_speed = state.copied_bytes / elapsed
                    if last_speed is None and avg_speed > 0:
                        state.progress_speed = avg_speed / (1024 * 1024)
                    if avg_speed > 0:
                        eta_text = format_eta(remaining / avg_speed)
                    else:
                        eta_text = "剩余时间：计算中…"
                else:
                    eta_text = "剩余时间：计算中…"

        if eta_text is not None and state.progress_eta_var is not None:
            if eta_text != state.last_eta_text:
                state.progress_eta_var.set(eta_text)
                state.last_eta_text = eta_text

        root.after(50, pump_progress)

    progress_tick()
    pump_progress()

    def on_pause():
        if not state.is_copying:
            return
        if not state.is_paused:
            state.pause_ev.set()
            state.is_paused = True
            pause_btn.config(text="继续")
            set_button_state(pause_btn, active=True, style_active="AuroraWarning.TButton")
            status_lbl.config(text="已暂停")
            if state.progress_eta_var is not None:
                state.progress_eta_var.set("已暂停")
                state.last_eta_text = "已暂停"
            log_add(info_box, "已暂停")
        else:
            state.pause_ev.clear()
            state.is_paused = False
            pause_btn.config(text="暂停")
            set_button_state(pause_btn, active=True, style_active="AuroraPrimary.TButton")
            status_lbl.config(text="继续执行")
            if state.progress_eta_var is not None:
                state.progress_eta_var.set("剩余时间：计算中…")
                state.last_eta_text = "剩余时间：计算中…"
            log_add(info_box, "继续执行")

    def on_cancel():
        if not state.is_copying:
            return
        if not aurora_askyesno(
            "确认取消",
            "还没复制完，是否取消？\n（取消会撤回本次所有未复制完成的文件）",
            parent=root,
        ):
            return
        set_button_state(cancel_btn, active=False, style_active="AuroraDanger.TButton")
        set_button_state(pause_btn, active=False)
        state.cancel_ev.set()
        status_lbl.config(text="取消中…")
        if state.progress_eta_var is not None:
            state.progress_eta_var.set("取消中…")
            state.last_eta_text = "取消中…"
        log_add(info_box, "取消中…")

    def open_current_month():
        cfg_local = load_config()
        dst_value = combo_dst.get().strip()
        if dst_value:
            base = dst_value.split(" ", 1)[0].strip()
            if os.name == "nt" and base and not base.endswith("\\"):
                target_root = base + "\\"
            else:
                target_root = base
        else:
            target_root = cfg_local.get("last_target_root", "")
        if not target_root:
            aurora_showwarning("提示", "请先选择目标硬盘或配置目标目录。", parent=root)
            return
        today = datetime.now()
        category = combo_cat.get().strip() or CATEGORIES[0]
        primary = os.path.join(target_root, str(today.year), category, f"{today.month:02d}月")
        alt = os.path.join(target_root, f"{today.year}年{today.month:02d}月")
        chosen = None
        for candidate in (primary, alt):
            if os.path.isdir(candidate):
                chosen = candidate
                break
        if chosen is None:
            chosen = primary
            try:
                os.makedirs(chosen, exist_ok=True)
            except Exception as exc:
                aurora_showwarning("打开失败", f"无法创建目录：{exc}", parent=root)
                return
        log_add(info_box, f"打开目录：{chosen}")
        _open_folder(chosen)

    def start_action():
        if state.is_copying:
            return
        sv = combo_src.get()
        if not sv:
            aurora_showwarning("提示", "请先选择素材盘。", parent=root)
            return
        src_drive = sv.split("|", 1)[0].strip()
        dst_letter = combo_dst.get().split(" ", 1)[0].strip().rstrip("\\") if combo_dst.get() else ""
        extract_star_flag = extract_star_enabled
        start_copy(
            src_drive,
            dst_letter,
            load_config(),
            root,
            combo_cat.get().strip(),
            info_box,
            btn_start,
            status_lbl,
            pause_btn,
            cancel_btn,
            star_btn,
            refresh_star_button_visual,
            state,
            extract_star=extract_star_flag,
        )

    btn_start = ttk.Button(card3, text="开始", style="AuroraPrimary.TButton", command=start_action)
    btn_start.grid(row=2, column=0, sticky="w", pady=(18, 0))

    open_btn = ttk.Button(card3, text="打开文件夹", style="AuroraPrimary.TButton", command=open_current_month)
    open_btn.grid(row=2, column=1, sticky="w", padx=(16, 0), pady=(18, 0))

    pause_btn = ttk.Button(card3, text="暂停", style="AuroraPrimary.TButton", command=on_pause, state="disabled")
    pause_btn.grid(row=2, column=3, sticky="e", padx=(0, 0), pady=(18, 0))

    cancel_btn = ttk.Button(card3, text="取消", style="AuroraPrimary.TButton", command=on_cancel, state="disabled")
    cancel_btn.grid(row=2, column=4, sticky="e", padx=(16, 0), pady=(18, 0))

    set_button_state(btn_start, active=True)
    set_button_state(open_btn, active=True)
    set_button_state(pause_btn, active=False)
    pause_btn.config(text="暂停")
    set_button_state(cancel_btn, active=False, style_active="AuroraDanger.TButton")

    footer = ttk.Label(root, text="此软件完全免费，请勿倒卖！ by: 抖音@摄影师陈同学", style="AuroraFooter.TLabel", anchor="center")
    footer.grid(row=2, column=0, columnspan=2, pady=(0, 18))

    def on_theme_change(event=None):
        cfg2 = load_config()
        cfg2["theme"] = DEFAULT_THEME_KEY
        save_config(cfg2)
        apply_theme(root, DEFAULT_THEME_KEY, info_text_widget=info_box)
        set_text_theme(info_box, DEFAULT_THEME_KEY)
        waste_ui.apply_theme(DEFAULT_THEME_KEY)

    theme_box.bind("<<ComboboxSelected>>", on_theme_change)

    refresh_sources(info_box, combo_src, auto_pick=True)

    root.mainloop()


def print_usage():
    print("""用法:
  python photo_sorter.py [选项]

选项:
  -h, --help    显示此帮助信息并退出。
  --cli         强制使用命令行模式。
  --gui         即使在检测到可能的无显示环境时也尝试启动图形界面。

默认行为:
  若存在图形显示环境则启动图形界面，否则自动回退到命令行模式。
""")


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if any(arg in ("-h", "--help") for arg in argv):
        print_usage()
        return 0

    recognized = {"--cli", "--gui"}
    unknown = [arg for arg in argv if arg not in recognized]
    if unknown:
        print(f"[错误] 未识别的参数：{' '.join(unknown)}")
        print_usage()
        return 1

    force_cli = "--cli" in argv
    force_gui = "--gui" in argv

    if force_cli and force_gui:
        print("[错误] --cli 与 --gui 不能同时使用。")
        print_usage()
        return 1

    if force_cli:
        run_cli(reason="根据命令行参数 --cli")
        return 0

    headless = (os.name != "nt" and not os.environ.get("DISPLAY"))
    if headless and not force_gui:
        run_cli(reason="检测到无图形显示环境")
        return 0

    main_ui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
