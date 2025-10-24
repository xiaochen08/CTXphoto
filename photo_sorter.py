# 陈同学影像管理助手 v1.7.3
# 更新点：
# - 开始/完成提示音
# - 复制过程无弹窗；主界面显示进度与速度（MB/s）
# - 进度条按字节比例；速度=累计字节/耗时
# - 保留星标提取、撤销、主题切换、可拖动分割、稳定日志、容量显示修复、版权提示
# - 弹窗统一 Aurora 风格并适配暗黑主题
# - 新增 Aurora 风格文本输入弹窗，统一拍摄名称输入体验
# - 进度条升级为圆角凹槽并新增百分比显示，支持快速打开当月目录与星标按钮状态提示

import os, sys, json, time, shutil, platform, subprocess, re, threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime

from types import SimpleNamespace

VERSION = "v1.7.3"
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
    from PIL import Image, ExifTags
except Exception:  # pragma: no cover - optional dependency fallback
    Image = None
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
    for path in paths:
        parent = os.path.dirname(path)
        while parent and parent.startswith(root_abs):
            prune_candidates.add(parent)
            next_parent = os.path.dirname(parent)
            if next_parent == parent:
                break
            parent = next_parent
    for folder in sorted(prune_candidates, key=len, reverse=True):
        try:
            if os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)
        except Exception:
            pass
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

    def emit_progress(phase, *, force=False):
        nonlocal last_emit
        now = time.time()
        if not force and now - last_emit < 0.1 and total_bytes and bytes_done < total_bytes:
            return
        elapsed = max(time.time() - t0, 1e-6)
        speed_mb = bytes_done / elapsed / (1024 * 1024)
        pct = (bytes_done / total_bytes * 100) if total_bytes else 0
        if pb is not None:
            pb["value"] = min(max(pct, 0), 100)
        if status_label is not None:
            status_label.config(
                text=f"{phase} | {bytes_to_human(bytes_done)} / {bytes_to_human(total_bytes)} | 速度 {speed_mb:.2f} MB/s"
            )
            try:
                status_label.update_idletasks()
            except Exception:
                pass
        if progress_hook is not None:
            try:
                progress_hook(phase, bytes_done, total_bytes, speed_mb)
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
                    emit_progress(phase)
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
        emit_progress(phase, force=True)
        return copied

    # 照片复制与重命名
    for src, base, ext in plan:
        check_flow()
        if src in done:
            try:
                bytes_done += os.path.getsize(src)
            except Exception:
                pass
            emit_progress("照片")
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
                bytes_done += os.path.getsize(src)
            except Exception:
                pass
            emit_progress("视频")
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

    emit_progress("收尾", force=True)

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


class AuroraProgressBar(ttk.Frame):
    def __init__(self, master, height=14, **kwargs):
        super().__init__(master, **kwargs)
        self._height = height
        self._radius = height / 2
        self._value = 0.0
        self._width = 0
        self.canvas = tk.Canvas(
            self,
            height=height,
            bd=0,
            highlightthickness=0,
            relief="flat",
            bg=AURORA_THEME["CARD"],
        )
        self.canvas.pack(fill="both", expand=True)
        self._trough = None
        self._bar = None
        self._shine = None
        self.bind("<Configure>", self._on_resize)

    def _rounded_points(self, x1, y1, x2, y2, radius):
        r = max(0.0, min(radius, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
        if r <= 0:
            return [x1, y1, x2, y1, x2, y2, x1, y2]
        return [
            x1 + r,
            y1,
            x2 - r,
            y1,
            x2,
            y1,
            x2,
            y1 + r,
            x2,
            y2 - r,
            x2,
            y2,
            x2 - r,
            y2,
            x1 + r,
            y2,
            x1,
            y2,
            x1,
            y2 - r,
            x1,
            y1 + r,
            x1,
            y1,
        ]

    def _draw_trough(self):
        if self._trough is not None:
            self.canvas.delete(self._trough)
        points = self._rounded_points(2, 2, self._width - 2, self._height - 2, self._radius)
        self._trough = self.canvas.create_polygon(
            *points,
            smooth=True,
            splinesteps=36,
            fill=AURORA_THEME["TROUGH"],
            outline=AURORA_THEME["CARD_BORDER"],
            width=1,
        )

    def _ensure_bar(self):
        if self._bar is None:
            self._bar = self.canvas.create_polygon(0, 0, 0, 0, fill=AURORA_THEME["ACCENT"], outline="", smooth=True)
        if self._shine is None:
            self._shine = self.canvas.create_polygon(0, 0, 0, 0, fill=AURORA_THEME["ACCENT_HOVER"], outline="", smooth=True, stipple="gray25")

    def _set_bar_width(self, width):
        self._ensure_bar()
        if width <= 0:
            self.canvas.itemconfigure(self._bar, state="hidden")
            self.canvas.itemconfigure(self._shine, state="hidden")
            return
        effective = max(0.0, min(width, self._width - 4))
        r = min(self._radius, effective / 2.0)
        points = self._rounded_points(2, 2, 2 + effective, self._height - 2, r)
        self.canvas.coords(self._bar, *points)
        self.canvas.coords(self._shine, *points)
        self.canvas.itemconfigure(self._bar, state="normal")
        self.canvas.itemconfigure(self._shine, state="normal")

    def set_value(self, value):
        self._value = max(0.0, min(100.0, float(value)))
        if self._width <= 0:
            return
        fill_width = (self._width - 4) * (self._value / 100.0)
        self._set_bar_width(fill_width)

    def reset(self):
        self.set_value(0.0)

    def _on_resize(self, event):
        new_width = max(event.width, 20)
        if abs(new_width - self._width) < 1:
            return
        self._width = new_width
        self.canvas.config(width=new_width)
        self._draw_trough()
        self.set_value(self._value)


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

    style.configure("AuroraPrimary.TButton", background=P["ACCENT"], foreground="#051225", font=_font(12, "bold"), padding=(22, 10), borderwidth=0, focusthickness=0, focuscolor=P["ACCENT_ACTIVE"])
    style.map(
        "AuroraPrimary.TButton",
        background=[("pressed", P["ACCENT_ACTIVE"]), ("active", P["ACCENT_HOVER"])],
        foreground=[("pressed", "#E6F6FF"), ("active", "#F0F9FF")],
    )

    style.configure("AuroraSecondary.TButton", background=P["CARD_HIGHLIGHT"], foreground=P["TEXT"], font=_font(12), padding=(18, 10), borderwidth=0, focusthickness=0)
    style.map(
        "AuroraSecondary.TButton",
        background=[("pressed", P["ACCENT_ACTIVE"]), ("active", P["CARD_BORDER"])],
        foreground=[("pressed", "#F8FAFC")],
    )

    style.configure(
        "Danger.TButton",
        background="#B91C1C",
        foreground="#F8FAFC",
        font=_font(12, "bold"),
        padding=(18, 10),
        borderwidth=0,
        focusthickness=0,
    )
    style.map(
        "Danger.TButton",
        background=[("active", "#DC2626"), ("pressed", "#7F1D1D")],
        foreground=[("pressed", "#FEE2E2")],
    )

    style.configure("AuroraGhost.TButton", background=P["HEADER_BG"], foreground=P["TEXT"], font=_font(11), padding=(16, 8), borderwidth=0, focusthickness=0)
    style.map(
        "AuroraGhost.TButton",
        background=[("active", P["CARD_BORDER"]), ("pressed", P["ACCENT_ACTIVE"])],
        foreground=[("pressed", "#F8FAFC")],
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
    pb_main,
    status_lbl,
    pause_btn,
    cancel_btn,
    star_btn,
    state,
    progress_var=None,
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

    pb_main.reset()
    if progress_var is not None:
        progress_var.set("进度：0%")
    status_lbl.config(text="准备复制…")
    root.update_idletasks()

    beep_start()
    log_add(info_box, "开始复制…")

    btn_start.configure(state="disabled")
    pause_btn.config(state="disabled", text="暂停")
    cancel_btn.config(state="disabled")
    star_btn.config(state="disabled")

    state.is_copying = True
    state.is_paused = False
    state.cancel_ev.clear()
    state.pause_ev.clear()
    state.copied_paths.clear()

    def safe_log(message):
        root.after(0, lambda m=message: log_add(info_box, m))

    def progress_cb(phase, done_bytes, total, speed_mb):
        def _update():
            if not state.is_copying:
                return
            pct = (done_bytes / total * 100) if total else (100 if phase == "收尾" else 0)
            pct = max(0.0, min(100.0, pct))
            pb_main.set_value(pct)
            if progress_var is not None:
                progress_var.set(f"进度：{pct:.0f}%")
            status_lbl.config(
                text=f"{phase} | {bytes_to_human(done_bytes)} / {bytes_to_human(total)} | 速度 {speed_mb:.2f} MB/s"
            )
        root.after(0, _update)

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

            btn_start.configure(state="normal")
            pause_btn.config(state="disabled", text="暂停")
            cancel_btn.config(state="disabled")
            star_btn.config(state="normal")

            if cancelled:
                pb_main.reset()
                if progress_var is not None:
                    progress_var.set("进度：0%")
                status_lbl.config(text="已取消")
                log_add(info_box, "已取消并回滚")
                if removed:
                    log_add(info_box, f"已清理 {removed} 个文件")
                if removed_dirs:
                    for d in removed_dirs:
                        log_add(info_box, f"已删除目录：{d}")
            elif error is not None:
                pb_main.reset()
                if progress_var is not None:
                    progress_var.set("进度：0%")
                status_lbl.config(text="复制失败")
                log_add(info_box, f"复制失败：{error}")
                if removed:
                    log_add(info_box, f"已清理 {removed} 个文件")
                if removed_dirs:
                    for d in removed_dirs:
                        log_add(info_box, f"已删除目录：{d}")
                aurora_showwarning("复制失败", f"发生错误：{error}", parent=root)
            else:
                pb_main.set_value(100)
                if progress_var is not None:
                    progress_var.set("进度：100%")
                status_lbl.config(text="复制完成")
                log_add(info_box, f"复制完成 共 {len(created)} 个目标文件")
                if manifest_path:
                    log_add(info_box, f"清单已保存：{manifest_path}")
                beep_done()
                show_finish_and_undo(root, target_dir, created, today)

        root.after(0, finalize)

    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()

    pause_btn.config(state="normal", text="暂停")
    cancel_btn.config(state="normal")

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

        def progress_hook(phase, done_bytes, total_bytes, speed_mb):
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

    star_enabled = tk.BooleanVar(value=False)

    def toggle_star():
        new_state = not star_enabled.get()
        star_enabled.set(new_state)
        star_btn.config(text=f"提取星标照片 {'√' if new_state else '×'}")
        log_add(info_box, "已开启星标提取" if new_state else "已关闭星标提取")

    star_btn = ttk.Button(
        card1,
        text="提取星标照片 ×",
        style="AuroraSecondary.TButton",
        command=toggle_star,
        width=16,
    )
    star_btn.grid(row=3, column=2, sticky="w", padx=(18, 0), pady=(14, 0))

    card3 = ttk.Frame(left_col, style="AuroraCard.TFrame", padding=(28, 24))
    card3.grid(row=1, column=0, sticky="ew", pady=(20, 0))
    card3.grid_columnconfigure(0, weight=1)
    card3.grid_columnconfigure(1, weight=0)
    card3.grid_columnconfigure(2, weight=1)
    card3.grid_columnconfigure(3, weight=0)
    card3.grid_columnconfigure(4, weight=0)
    pb_main = AuroraProgressBar(card3)
    pb_main.grid(row=0, column=0, columnspan=4, sticky="ew")
    progress_pct_var = tk.StringVar(value="进度：0%")
    ttk.Label(card3, textvariable=progress_pct_var, style="AuroraStatus.TLabel").grid(
        row=0, column=4, sticky="e", padx=(16, 0)
    )
    status_lbl = ttk.Label(card3, text="待机", style="AuroraStatus.TLabel")
    status_lbl.grid(row=1, column=0, columnspan=5, sticky="w", pady=(12, 0))

    def on_pause():
        if not state.is_copying:
            return
        if not state.is_paused:
            state.pause_ev.set()
            state.is_paused = True
            pause_btn.config(text="继续")
            status_lbl.config(text="已暂停")
            log_add(info_box, "已暂停")
        else:
            state.pause_ev.clear()
            state.is_paused = False
            pause_btn.config(text="暂停")
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
        cancel_btn.config(state="disabled")
        pause_btn.config(state="disabled")
        state.cancel_ev.set()
        status_lbl.config(text="取消中…")
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
        start_copy(
            src_drive,
            dst_letter,
            load_config(),
            root,
            combo_cat.get().strip(),
            info_box,
            btn_start,
            pb_main,
            status_lbl,
            pause_btn,
            cancel_btn,
            star_btn,
            state,
            progress_pct_var,
            extract_star=star_enabled.get(),
        )

    btn_start = ttk.Button(card3, text="开始分类", style="AuroraPrimary.TButton", command=start_action)
    btn_start.grid(row=2, column=0, sticky="w", pady=(18, 0))

    open_btn = ttk.Button(card3, text="打开文件夹", style="AuroraSecondary.TButton", command=open_current_month)
    open_btn.grid(row=2, column=1, sticky="w", padx=(16, 0), pady=(18, 0))

    pause_btn = ttk.Button(card3, text="暂停", style="AuroraSecondary.TButton", command=on_pause, state="disabled")
    pause_btn.grid(row=2, column=3, sticky="e", padx=(0, 0), pady=(18, 0))

    cancel_btn = ttk.Button(card3, text="取消", style="Danger.TButton", command=on_cancel, state="disabled")
    cancel_btn.grid(row=2, column=4, sticky="e", padx=(16, 0), pady=(18, 0))

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
