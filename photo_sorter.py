# 陈同学影像管理助手 v1.7.9
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
# - 新增闭眼/半眨/翻白眼与曝光检测流程，支持红框预览与批量删除记录

import os, sys, json, time, shutil, platform, subprocess, re, threading, queue, math, csv, io
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime

from types import SimpleNamespace

VERSION = "v1.7.9"
CONFIG_FILE = "photo_sorter_config.json"
CATEGORIES = ["婚礼", "写真", "日常记录", "旅游记录", "商业活动拍摄"]
THEMES = ["暗黑"]
DEFAULT_THEME_KEY = "dark"
LOG_PANEL_WIDTH = 360
COPY_BUFFER_SIZE = 4 * 1024 * 1024

DEFAULT_CONFIG = {
    "last_target_root": "",
    "theme": DEFAULT_THEME_KEY,
    "sash_ratio": 0.55,
    "eye": {
        "ear_closed": 0.20,
        "ear_half": 0.26,
        "roll_margin": 0.18,
        "conf_min": 0.5,
    },
    "exposure": {
        "under_dark_pct": 0.45,
        "under_p75": 60,
        "over_bright_pct": 0.10,
        "over_p99": 254,
    },
    "scan": {
        "ext": [".jpg", ".jpeg"],
        "max_side": 1600,
    },
}

SUPPRESS_RUNTIME_WARNINGS = any(arg in ("-h", "--help") for arg in sys.argv[1:])

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - best effort fallback for limited environments
    psutil = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 psutil，部分磁盘信息功能将受限。", file=sys.stderr)

try:
    from PIL import Image, ExifTags, ImageTk
except Exception:  # pragma: no cover - optional dependency fallback
    Image = None
    ImageTk = None
    ExifTags = SimpleNamespace(TAGS={})
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 Pillow，EXIF 读取功能将受限。", file=sys.stderr)

try:
    import exifread
except Exception:  # pragma: no cover - optional dependency fallback
    exifread = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 exifread，将使用文件修改时间作为拍摄时间。", file=sys.stderr)

try:
    import winsound
    def beep_start(): winsound.MessageBeep(winsound.MB_ICONASTERISK)
    def beep_done():  winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
except Exception:
    def beep_start(): pass
    def beep_done():  pass

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 opencv-python，闭眼/曝光检测功能将不可用。", file=sys.stderr)

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    np = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 numpy，闭眼/曝光检测功能将不可用。", file=sys.stderr)

try:
    import mediapipe as mp  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    mp = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 mediapipe，闭眼/曝光检测功能将不可用。", file=sys.stderr)

try:
    from send2trash import send2trash  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    send2trash = None
    if not SUPPRESS_RUNTIME_WARNINGS:
        print("[警告] 未检测到 send2trash，检测模式将无法安全删除文件。", file=sys.stderr)

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

def is_removable_path(path: str) -> bool:
    try:
        abs_path = os.path.abspath(path)
    except Exception:
        return False
    if os.name == "nt":
        drive = os.path.splitdrive(abs_path)[0]
        if len(drive) == 2 and drive.endswith(":"):
            return get_drive_type_code(drive) == 2
        return False
    if psutil is None:
        return False
    try:
        for part in psutil.disk_partitions(all=False):
            mount = getattr(part, "mountpoint", "")
            if not mount:
                continue
            try:
                if abs_path.startswith(mount):
                    opts = getattr(part, "opts", "") or ""
                    if "removable" in opts or "thumb" in opts:
                        return True
                    break
            except Exception:
                continue
    except Exception:
        pass
    return False

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
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k not in {"eye", "exposure", "scan"}})
            for key in ("eye", "exposure", "scan"):
                section = DEFAULT_CONFIG[key].copy()
                user_section = data.get(key)
                if isinstance(user_section, dict):
                    section.update(user_section)
                cfg[key] = section
    return cfg

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

# ---------- 检测工作流 ----------
class DetectionSession(SimpleNamespace):
    """保存检测过程中的临时状态。"""


CURRENT_DETECTION_SESSION: DetectionSession | None = None


def _ensure_detection_ready():
    if cv2 is None or np is None or mp is None:
        raise RuntimeError("检测功能依赖 opencv-python、numpy 与 mediapipe，请先安装依赖。")
    if send2trash is None:
        raise RuntimeError("检测功能依赖 send2trash 以安全删除文件，请先安装依赖。")


def scan_jpgs(root_dir) -> list[str]:
    cfg = load_config()
    exts = {ext.lower() for ext in cfg.get("scan", {}).get("ext", [".jpg", ".jpeg"])}
    matches: list[str] = []
    for base, _dirs, files in os.walk(root_dir):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in exts:
                matches.append(os.path.join(base, name))
    matches.sort()
    return matches


FACE_MESH_OBJ = None


def _get_face_mesh():
    global FACE_MESH_OBJ
    if FACE_MESH_OBJ is None and mp is not None:
        FACE_MESH_OBJ = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            refine_landmarks=True,
            max_num_faces=1,
            min_detection_confidence=0.5,
        )
    return FACE_MESH_OBJ


_EYE_LANDMARKS_L = [33, 160, 158, 133, 153, 144]
_EYE_LANDMARKS_R = [362, 385, 387, 263, 373, 380]
_IRIS_L = [468, 469, 470, 471, 472]
_IRIS_R = [473, 474, 475, 476, 477]


def _ear_from_landmarks(pts: 'np.ndarray') -> float:
    a = float(np.linalg.norm(pts[1] - pts[5]))
    b = float(np.linalg.norm(pts[2] - pts[4]))
    c = float(np.linalg.norm(pts[0] - pts[3]))
    if c <= 1e-6:
        return 0.0
    return (a + b) / (2.0 * c)


def _iris_position(iris_pts: 'np.ndarray', eye_box) -> tuple[float, float]:
    if iris_pts.size == 0 or not eye_box:
        return (0.5, 0.5)
    cx = float(np.mean(iris_pts[:, 0]))
    cy = float(np.mean(iris_pts[:, 1]))
    x0, y0, w, h = eye_box
    if w <= 0 or h <= 0:
        return (0.5, 0.5)
    return ((cx - x0) / w, (cy - y0) / h)


def detect_eye_state(img_bgr) -> dict:
    if cv2 is None or np is None or mp is None:
        return {
            "state": "unknown",
            "left_eye_box": None,
            "right_eye_box": None,
            "ear_L": 0.0,
            "ear_R": 0.0,
            "confidence": 0.0,
        }

    mesh = _get_face_mesh()
    if mesh is None:
        return {
            "state": "unknown",
            "left_eye_box": None,
            "right_eye_box": None,
            "ear_L": 0.0,
            "ear_R": 0.0,
            "confidence": 0.0,
        }

    h, w = img_bgr.shape[:2]
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    result = mesh.process(rgb)
    if not result.multi_face_landmarks:
        return {
            "state": "unknown",
            "left_eye_box": None,
            "right_eye_box": None,
            "ear_L": 0.0,
            "ear_R": 0.0,
            "confidence": 0.0,
        }

    face = result.multi_face_landmarks[0]
    pts = np.array([(lm.x * w, lm.y * h) for lm in face.landmark], dtype=np.float32)

    left = pts[_EYE_LANDMARKS_L]
    right = pts[_EYE_LANDMARKS_R]

    lbox = (
        float(np.min(left[:, 0])),
        float(np.min(left[:, 1])),
        float(np.max(left[:, 0]) - np.min(left[:, 0])),
        float(np.max(left[:, 1]) - np.min(left[:, 1])),
    )
    rbox = (
        float(np.min(right[:, 0])),
        float(np.min(right[:, 1])),
        float(np.max(right[:, 0]) - np.min(right[:, 0])),
        float(np.max(right[:, 1]) - np.min(right[:, 1])),
    )

    ear_L = float(_ear_from_landmarks(left))
    ear_R = float(_ear_from_landmarks(right))

    iris_L = pts[_IRIS_L]
    iris_R = pts[_IRIS_R]
    iris_pos_L = _iris_position(iris_L, lbox)
    iris_pos_R = _iris_position(iris_R, rbox)

    cfg = load_config()
    eye_cfg = cfg.get("eye", {})
    closed_th = float(eye_cfg.get("ear_closed", 0.20))
    half_th = float(eye_cfg.get("ear_half", 0.26))
    roll_margin = float(eye_cfg.get("roll_margin", 0.18))

    avg_ear = (ear_L + ear_R) / 2.0
    state = "ok"
    if avg_ear < closed_th:
        state = "closed"
    elif avg_ear < half_th:
        state = "half"

    for iris_pos in (iris_pos_L, iris_pos_R):
        if iris_pos[1] < roll_margin or iris_pos[1] > 1.0 - roll_margin:
            state = "roll"
            break

    return {
        "state": state,
        "left_eye_box": lbox,
        "right_eye_box": rbox,
        "ear_L": ear_L,
        "ear_R": ear_R,
        "confidence": 1.0,
        "iris_L": iris_pos_L,
        "iris_R": iris_pos_R,
    }


def assess_exposure(img_bgr) -> dict:
    if np is None:
        return {"under": False, "over": False, "metrics": {}}

    cfg = load_config()
    expo_cfg = cfg.get("exposure", {})
    if cv2 is not None:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = (img_bgr[..., 2] * 0.299 + img_bgr[..., 1] * 0.587 + img_bgr[..., 0] * 0.114).astype(np.float32)
    flat = gray.reshape(-1).astype(np.float32)
    total = max(float(flat.size), 1.0)
    dark_pct = float(np.sum(flat < 20.0) / total)
    bright_pct = float(np.sum(flat > 240.0) / total)
    p75 = float(np.percentile(flat, 75))
    p99 = float(np.percentile(flat, 99))

    under = dark_pct >= float(expo_cfg.get("under_dark_pct", 0.45)) or p75 < float(expo_cfg.get("under_p75", 60))
    over = bright_pct >= float(expo_cfg.get("over_bright_pct", 0.10)) or p99 >= float(expo_cfg.get("over_p99", 254))

    return {
        "under": bool(under),
        "over": bool(over),
        "metrics": {
            "dark_pct": dark_pct,
            "bright_pct": bright_pct,
            "p75": p75,
            "p99": p99,
        },
    }


def render_eye_boxes(img_bgr, boxes, labels) -> 'np.ndarray':
    if cv2 is None:
        return img_bgr
    annotated = img_bgr.copy()
    for box, label in zip(boxes, labels):
        if not box:
            continue
        x, y, w, h = box
        start = (int(x), int(y))
        end = (int(x + w), int(y + h))
        cv2.rectangle(annotated, start, end, (0, 0, 255), 2)
        if label:
            cv2.putText(annotated, label, (int(x), int(y) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1, cv2.LINE_AA)
    return annotated


def process_batch(paths, q_progress):  # 后台线程
    session = CURRENT_DETECTION_SESSION
    if session is None:
        raise RuntimeError("检测会话尚未初始化。")

    cfg = load_config()
    max_side = int(cfg.get("scan", {}).get("max_side", 1600))
    total_bytes = sum(max(os.path.getsize(p), 0) for p in paths if os.path.isfile(p))
    session.total_bytes = total_bytes
    session.start_time = time.time()
    session.delete_records = []

    q_progress.put(("total", total_bytes))

    for path in paths:
        if session.cancel_ev.is_set():
            break
        while session.pause_ev.is_set():
            time.sleep(0.1)

        try:
            file_size = os.path.getsize(path)
        except Exception:
            file_size = 0

        try:
            data = np.fromfile(path, dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR) if cv2 is not None else None
        except Exception:
            img = None

        if img is None:
            q_progress.put(("file", {"path": path, "error": "无法读取"}))
            q_progress.put(("bytes", file_size))
            continue

        h, w = img.shape[:2]
        if max(h, w) > max_side and max_side > 0:
            scale = max_side / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        eye_info = detect_eye_state(img)
        expo_info = assess_exposure(img)

        boxes = [eye_info.get("left_eye_box"), eye_info.get("right_eye_box")]
        state = eye_info.get("state", "unknown")
        if state == "closed":
            labels = ["闭眼", "闭眼"]
        elif state == "half":
            labels = ["半眨", "半眨"]
        elif state == "roll":
            labels = ["翻白眼", "翻白眼"]
        else:
            labels = ["", ""]

        annotated = render_eye_boxes(img, boxes, labels)
        thumb = annotated
        if max(thumb.shape[:2]) > 480:
            ratio = 480 / max(thumb.shape[:2])
            thumb = cv2.resize(thumb, (int(thumb.shape[1] * ratio), int(thumb.shape[0] * ratio)), interpolation=cv2.INTER_AREA)

        thumb_bytes = None
        if cv2 is not None:
            ok, buf = cv2.imencode(".jpg", thumb)
            if ok:
                thumb_bytes = bytes(buf)

        q_progress.put(
            (
                "file",
                {
                    "path": path,
                    "eye": eye_info,
                    "expo": expo_info,
                    "thumb": thumb_bytes,
                },
            )
        )

        if state == "closed":
            if getattr(session, "delete_all_closed", False):
                decision = "yes"
            else:
                prompt_q = queue.Queue()
                q_progress.put(("prompt", {"path": path, "eye": eye_info, "thumb": thumb_bytes, "response": prompt_q}))
                try:
                    decision = prompt_q.get()
                except Exception:
                    decision = "no"
            if decision in ("yes", "all"):
                try:
                    send2trash(path)
                    session.delete_records.append(
                        {
                            "time": datetime.now().isoformat(timespec="seconds"),
                            "path": path,
                            "reason": "闭眼",
                        }
                    )
                    q_progress.put(("deleted", {"path": path}))
                except Exception as exc:
                    q_progress.put(("error", {"path": path, "error": str(exc)}))
            if decision == "all":
                session.delete_all_closed = True

        q_progress.put(("bytes", file_size))

    q_progress.put(("done", {"records": getattr(session, "delete_records", [])}))


def on_detect_result(item):  # 主线程
    session = CURRENT_DETECTION_SESSION
    if session is None:
        return
    results = getattr(session, "results", None)
    if results is None:
        session.results = [item]
    else:
        results.append(item)


def launch_eye_detection(root, info_box):
    global CURRENT_DETECTION_SESSION
    try:
        _ensure_detection_ready()
    except RuntimeError as exc:
        aurora_showwarning("无法启动检测", str(exc), parent=root)
        return

    if CURRENT_DETECTION_SESSION is not None and not getattr(CURRENT_DETECTION_SESSION, "finished", False):
        aurora_showwarning("检测进行中", "已有检测任务运行中，请先完成或取消后再启动新检测。", parent=root)
        return

    folder = filedialog.askdirectory(title="选择待检测文件夹（仅限固定硬盘）")
    if not folder:
        return

    if is_removable_path(folder):
        aurora_showwarning("路径受限", "仅支持固定硬盘/SSD 目录，检测已取消。", parent=root)
        return

    paths = scan_jpgs(folder)
    if not paths:
        aurora_showwarning("未找到 JPG", "所选目录未检测到 JPG/JPEG 文件。", parent=root)
        return

    log_add(info_box, f"检测目录：{folder}")
    log_add(info_box, f"待检测文件数：{len(paths)}")

    session = DetectionSession()
    session.root_dir = folder
    session.pause_ev = threading.Event()
    session.cancel_ev = threading.Event()
    session.queue = queue.Queue()
    session.results = []
    session.delete_all_closed = False
    session.total_bytes = 0
    session.copied_bytes = 0
    session.start_time = time.time()
    session.finished = False
    session.photo_cache = {}
    session.data_map = {}
    session.was_cancelled = False
    session.progress_var = tk.DoubleVar(value=0.0)
    session.percent_var = tk.StringVar(value="进度: 0.0%")
    session.eta_var = tk.StringVar(value="剩余时间：计算中…")
    session.status_var = tk.StringVar(value="待机")

    CURRENT_DETECTION_SESSION = session

    win = tk.Toplevel(root)
    session.window = win
    win.title("闭眼与曝光检测")
    win.minsize(960, 600)
    win.geometry("1180x720")
    win.transient(root)
    apply_theme(win, load_config().get("theme", DEFAULT_THEME_KEY))

    container = ttk.Frame(win, style="AuroraPanel.TFrame", padding=(24, 22))
    container.pack(fill="both", expand=True)
    container.grid_columnconfigure(0, weight=3)
    container.grid_columnconfigure(1, weight=2)
    container.grid_rowconfigure(1, weight=1)

    header = ttk.Frame(container, style="AuroraCard.TFrame", padding=(22, 18))
    header.grid(row=0, column=0, columnspan=2, sticky="ew")
    ttk.Label(header, text=f"检测目录：{folder}", style="AuroraBody.TLabel", anchor="w").pack(anchor="w")
    ttk.Label(header, textvariable=session.status_var, style="AuroraStatus.TLabel", anchor="w").pack(anchor="w", pady=(6, 0))

    left = ttk.Frame(container, style="AuroraCard.TFrame", padding=(22, 20))
    left.grid(row=1, column=0, sticky="nsew", padx=(0, 16))
    left.grid_rowconfigure(2, weight=1)
    left.grid_columnconfigure(0, weight=1)

    pb = ttk.Progressbar(
        left,
        mode="determinate",
        maximum=100,
        variable=session.progress_var,
        style="Aurora.Horizontal.TProgressbar",
    )
    pb.grid(row=0, column=0, columnspan=3, sticky="ew")

    ttk.Label(left, textvariable=session.percent_var, style="AuroraStatus.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
    ttk.Label(left, textvariable=session.eta_var, style="AuroraStatus.TLabel").grid(row=1, column=1, sticky="w", pady=(8, 0))

    btn_frame = ttk.Frame(left, style="AuroraCard.TFrame")
    btn_frame.grid(row=1, column=2, sticky="e", pady=(8, 0))

    pause_btn = ttk.Button(btn_frame, text="暂停", style="AuroraPrimary.TButton", state="disabled")
    pause_btn.grid(row=0, column=0, padx=(0, 12))
    cancel_btn = ttk.Button(btn_frame, text="取消", style="AuroraDanger.TButton", state="disabled")
    cancel_btn.grid(row=0, column=1)

    columns = ("name", "eye", "expo")
    tree = ttk.Treeview(left, columns=columns, show="headings", height=18, selectmode="browse")
    tree.heading("name", text="文件")
    tree.heading("eye", text="眼部状态")
    tree.heading("expo", text="曝光")
    tree.column("name", anchor="w", width=320)
    tree.column("eye", anchor="center", width=110)
    tree.column("expo", anchor="center", width=150)
    tree.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=(18, 0))
    tree_scroll = ttk.Scrollbar(left, orient="vertical", command=tree.yview, style="Aurora.Vertical.TScrollbar")
    tree_scroll.grid(row=2, column=3, sticky="nsw", pady=(18, 0), padx=(12, 0))
    tree.configure(yscrollcommand=tree_scroll.set)

    right = ttk.Frame(container, style="AuroraCard.TFrame", padding=(22, 20))
    right.grid(row=1, column=1, sticky="nsew")
    right.grid_rowconfigure(0, weight=1)
    right.grid_columnconfigure(0, weight=1)
    preview_label = ttk.Label(right, text="选择左侧结果查看预览", style="AuroraStatus.TLabel", anchor="center")
    preview_label.grid(row=0, column=0, sticky="nsew")

    session.tree = tree
    session.preview_label = preview_label
    session.pause_btn = pause_btn
    session.cancel_btn = cancel_btn

    def update_preview(path):
        data = session.data_map.get(path)
        if not data:
            return
        thumb_bytes = data.get("thumb")
        if thumb_bytes is None or Image is None or ImageTk is None:
            preview_label.configure(text=os.path.basename(path), image="")
            preview_label.image = None
            return
        if path not in session.photo_cache:
            try:
                with Image.open(io.BytesIO(thumb_bytes)) as img:
                    session.photo_cache[path] = ImageTk.PhotoImage(img)
            except Exception:
                session.photo_cache[path] = None
        tk_img = session.photo_cache.get(path)
        if tk_img is not None:
            preview_label.configure(image=tk_img, text="")
            preview_label.image = tk_img
        else:
            preview_label.configure(text=os.path.basename(path), image="")
            preview_label.image = None

    def on_select(_event=None):
        sel = tree.selection()
        if not sel:
            return
        path = tree.set(sel[0], "name")
        stored_path = session.item_to_path.get(sel[0])
        update_preview(stored_path or path)

    tree.bind("<<TreeviewSelect>>", on_select)

    session.item_to_path = {}

    def update_progress(delta):
        session.copied_bytes = min(session.total_bytes, session.copied_bytes + max(delta, 0))
        if session.total_bytes > 0:
            percent = min(100.0, (session.copied_bytes / session.total_bytes) * 100.0)
        else:
            percent = 0.0
        session.progress_var.set(percent)
        session.percent_var.set(f"进度: {percent:.1f}%")
        elapsed = max(time.time() - session.start_time, 1e-6)
        if session.copied_bytes <= 0 or session.total_bytes <= 0:
            eta_text = "剩余时间：计算中…"
        else:
            remaining = (session.total_bytes - session.copied_bytes) / max(session.copied_bytes / elapsed, 1e-6)
            eta_text = format_eta(remaining)
        if session.pause_ev.is_set():
            eta_text = "已暂停"
        if session.cancel_ev.is_set():
            eta_text = "取消中…"
        session.eta_var.set(eta_text)

    def refresh_status():
        session.status_var.set(f"已检测 {len(session.results)} 张")

    def handle_file(payload):
        path = payload.get("path")
        if not path:
            return
        on_detect_result(payload)
        session.data_map[path] = payload
        rel_name = os.path.relpath(path, session.root_dir)
        eye = payload.get("eye", {})
        expo = payload.get("expo", {})
        state = eye.get("state", "unknown")
        state_map = {
            "closed": "闭眼",
            "half": "半眨眼",
            "roll": "翻白眼",
            "ok": "正常",
            "unknown": "不可判定",
        }
        expo_text = []
        if expo.get("under"):
            expo_text.append("欠曝")
        if expo.get("over"):
            expo_text.append("过曝")
        expo_str = ",".join(expo_text) if expo_text else "正常"
        iid = tree.insert("", "end", values=(rel_name, state_map.get(state, state), expo_str))
        session.item_to_path[iid] = path
        if len(session.results) == 1:
            tree.selection_set(iid)
            tree.focus(iid)
            update_preview(path)
        refresh_status()

    def handle_prompt(payload):
        if session.delete_all_closed:
            payload.get("response").put("yes")
            return
        decision = aurora_ask_eye_delete(parent=win)
        if decision == "all":
            session.delete_all_closed = True
            payload.get("response").put("all")
        elif decision == "yes":
            payload.get("response").put("yes")
        elif decision == "no":
            payload.get("response").put("no")
        else:
            payload.get("response").put("no")

    def handle_deleted(payload):
        path = payload.get("path")
        if path:
            log_add(info_box, f"已移入回收站：{path}")

    def handle_error(payload):
        msg = payload.get("error") or "检测失败"
        log_add(info_box, f"检测错误：{msg}")

    def finalize(payload):
        global CURRENT_DETECTION_SESSION
        if session.finished:
            return
        session.finished = True
        set_button_state(pause_btn, active=False)
        set_button_state(cancel_btn, active=False, style_active="AuroraDanger.TButton")
        session.progress_var.set(100.0 if not session.was_cancelled else session.progress_var.get())
        if session.was_cancelled or session.cancel_ev.is_set():
            session.status_var.set("检测已取消")
            session.eta_var.set("已取消")
        else:
            session.status_var.set("检测完成")
            session.eta_var.set("完成")
            session.progress_var.set(100.0)
            session.percent_var.set("进度: 100.0%")
        records = payload.get("records") if isinstance(payload, dict) else None
        if records:
            ts_now = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path = os.path.join(session.root_dir, f"eye_detection_deleted_{ts_now}.csv")
            try:
                with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(["time", "path", "reason"])
                    for row in records:
                        writer.writerow([row.get("time"), row.get("path"), row.get("reason")])
                log_add(info_box, f"删除记录已保存：{csv_path}")
            except Exception as exc:
                log_add(info_box, f"保存删除日志失败：{exc}")
        refresh_status()
        session.eta_var.set("完成" if not session.was_cancelled else "已取消")
        CURRENT_DETECTION_SESSION = None

    def pump():
        try:
            while True:
                kind, payload = session.queue.get_nowait()
                if kind == "total":
                    session.total_bytes = payload
                elif kind == "bytes":
                    update_progress(payload)
                elif kind == "file":
                    handle_file(payload)
                elif kind == "prompt":
                    handle_prompt(payload)
                elif kind == "deleted":
                    handle_deleted(payload)
                elif kind == "error":
                    handle_error(payload)
                elif kind == "done":
                    finalize(payload)
        except queue.Empty:
            pass
        if not session.finished:
            root.after(50, pump)

    def toggle_pause():
        if session.finished:
            return
        if not session.pause_ev.is_set():
            session.pause_ev.set()
            session.status_var.set("已暂停")
            session.eta_var.set("已暂停")
            pause_btn.config(text="继续")
            set_button_state(pause_btn, active=True, style_active="AuroraWarning.TButton")
            log_add(info_box, "检测已暂停")
        else:
            session.pause_ev.clear()
            session.status_var.set("检测中…")
            session.eta_var.set("剩余时间：计算中…")
            pause_btn.config(text="暂停")
            set_button_state(pause_btn, active=True, style_active="AuroraPrimary.TButton")
            log_add(info_box, "检测继续执行")

    def do_cancel():
        if session.finished:
            return
        session.was_cancelled = True
        session.cancel_ev.set()
        set_button_state(pause_btn, active=False)
        set_button_state(cancel_btn, active=False, style_active="AuroraDanger.TButton")
        session.status_var.set("取消中…")
        session.eta_var.set("取消中…")
        log_add(info_box, "检测取消中…")

    def close_window():
        if not session.finished:
            session.was_cancelled = True
            session.cancel_ev.set()
        win.destroy()

    pause_btn.configure(command=toggle_pause)
    cancel_btn.configure(command=do_cancel)

    win.protocol("WM_DELETE_WINDOW", close_window)

    set_button_state(pause_btn, active=True, style_active="AuroraPrimary.TButton")
    set_button_state(cancel_btn, active=True, style_active="AuroraDanger.TButton")
    session.status_var.set("检测中…")

    worker = threading.Thread(target=process_batch, args=(paths, session.queue), daemon=True)
    worker.start()
    pump()

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


def aurora_ask_eye_delete(parent=None):
    toplevel = _normalize_parent(parent)
    if not _can_use_modal(toplevel):
        res = messagebox.askquestion(
            "确认删除",
            "检测到闭眼，是否删除？\n（将移入回收站，可撤销）",
            icon="warning",
            type=messagebox.YESNOCANCEL,
            parent=parent,
        )
        if res == "yes":
            return "yes"
        if res == "no":
            return "no"
        return "cancel"

    result = _aurora_modal(
        "确认删除",
        "检测到闭眼，是否删除？\n（将移入回收站，可撤销）",
        level="warning",
        buttons=[
            ("否", "AuroraGhost.TButton", "no"),
            ("是", "AuroraPrimary.TButton", "yes"),
            ("对本次全部", "AuroraWarning.TButton", "all"),
        ],
        parent=toplevel,
        default_index=1,
        close_value="cancel",
    )
    return result

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
    detect_btn,
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
    if detect_btn is not None:
        set_button_state(detect_btn, active=False)

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
            if detect_btn is not None:
                set_button_state(detect_btn, active=True)
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

    try:
        root = tk.Tk()
    except Exception:
        print("[提示] 无法初始化图形界面，自动切换到命令行模式。")
        run_cli(reason="无法初始化图形界面")
        return
    root.title(f"陈同学影像管理助手  {VERSION}")
    root.geometry("1180x760")
    root.minsize(960, 640)
    root.resizable(True, True)

    apply_theme(root, theme_key)

    root.grid_rowconfigure(1, weight=1)
    root.grid_columnconfigure(0, weight=1)
    root.grid_columnconfigure(1, weight=0)

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
    header.columnconfigure(0, weight=1)
    accent = ttk.Frame(header, style="AuroraAccent.TFrame", height=4)
    accent.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 20))
    accent.grid_propagate(False)
    ttk.Label(header, text="照片/视频导入与分类", style="AuroraTitle.TLabel").grid(row=1, column=0, sticky="w")
    ttk.Label(header, text="主题", style="AuroraBodyOnPanel.TLabel").grid(row=1, column=1, sticky="e", padx=(24, 10))
    theme_box = ttk.Combobox(header, state="readonly", values=THEMES, width=8, style="Aurora.TCombobox")
    theme_box.grid(row=1, column=2, sticky="e")
    theme_box.set(THEMES[0])

    main_frame = ttk.Frame(root, style="AuroraPanel.TFrame")
    main_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=36, pady=(0, 28))
    main_frame.grid_columnconfigure(0, weight=1)
    main_frame.grid_columnconfigure(1, weight=0)
    main_frame.grid_rowconfigure(0, weight=1)

    right_col = ttk.Frame(main_frame, style="AuroraPanel.TFrame", width=LOG_PANEL_WIDTH)
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

    left_col = ttk.Frame(main_frame, style="AuroraPanel.TFrame")
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
            detect_btn,
            refresh_star_button_visual,
            state,
            extract_star=extract_star_flag,
        )

    btn_start = ttk.Button(card3, text="开始分类", style="AuroraPrimary.TButton", command=start_action)
    btn_start.grid(row=2, column=0, sticky="w", pady=(18, 0))

    open_btn = ttk.Button(card3, text="打开文件夹", style="AuroraPrimary.TButton", command=open_current_month)
    open_btn.grid(row=2, column=1, sticky="w", padx=(16, 0), pady=(18, 0))

    detect_btn = ttk.Button(
        card3,
        text="闭眼与曝光检测",
        style="AuroraPrimary.TButton",
        command=lambda: launch_eye_detection(root, info_box),
    )
    detect_btn.grid(row=2, column=2, sticky="w", padx=(16, 0), pady=(18, 0))

    pause_btn = ttk.Button(card3, text="暂停", style="AuroraPrimary.TButton", command=on_pause, state="disabled")
    pause_btn.grid(row=2, column=3, sticky="e", padx=(0, 0), pady=(18, 0))

    cancel_btn = ttk.Button(card3, text="取消", style="AuroraPrimary.TButton", command=on_cancel, state="disabled")
    cancel_btn.grid(row=2, column=4, sticky="e", padx=(16, 0), pady=(18, 0))

    set_button_state(btn_start, active=True)
    set_button_state(open_btn, active=True)
    set_button_state(detect_btn, active=True)
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
