# 陈同学影像管理助手 v1.7.0
# 更新点：
# - 开始/完成提示音
# - 复制过程无弹窗；主界面显示进度与速度（MB/s）
# - 进度条按字节比例；速度=累计字节/耗时
# - 保留星标提取、撤销、主题切换、可拖动分割、稳定日志、容量显示修复、版权提示

import os, sys, json, time, shutil, platform, subprocess, re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime

from types import SimpleNamespace

VERSION = "v1.7.0"
CONFIG_FILE = "photo_sorter_config.json"
CATEGORIES = ["婚礼", "写真", "日常记录", "旅游记录", "商业活动拍摄"]
THEMES = ["日间", "暗黑"]

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - best effort fallback for limited environments
    psutil = None
    print("[警告] 未检测到 psutil，部分磁盘信息功能将受限。", file=sys.stderr)

try:
    from PIL import Image, ExifTags
except Exception:  # pragma: no cover - optional dependency fallback
    Image = None
    ExifTags = SimpleNamespace(TAGS={})
    print("[警告] 未检测到 Pillow，EXIF 读取功能将受限。", file=sys.stderr)

try:
    import exifread
except Exception:  # pragma: no cover - optional dependency fallback
    exifread = None
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
            if "theme" not in cfg: cfg["theme"] = "light"
            if "sash_ratio" not in cfg: cfg["sash_ratio"] = 0.55
            return cfg
    return {"last_target_root": "", "theme": "light", "sash_ratio": 0.55}

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
    if float(text_widget.index("end-1c"))==1.0:
        text_widget.configure(state="normal")
        text_widget.insert("end", f"[{ts()}] {line}\n")
        text_widget.configure(state="disabled")

def log_add(text_widget, line):
    text_widget.configure(state="normal")
    text_widget.insert("end", f"[{ts()}] {line}\n")
    text_widget.see("end")
    text_widget.configure(state="disabled")

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

def show_finish_and_undo(root, target_dir, created_files):
    win = tk.Toplevel(root)
    win.title("完成")
    win.resizable(False, False)
    win.transient(root)      # 置于父窗口上方
    win.grab_set()           # 获取焦点

    # 统一应用当前主题（修复暗黑/日间不匹配）
    try:
        theme_key = load_config().get("theme", "light")
    except Exception:
        theme_key = "light"
    apply_theme(win, theme_key)

    pad = {"padx": 16, "pady": 8}
    ttk.Label(win, text="导入完成", style="WeChatTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", **pad)
    ttk.Label(win, text=f"输出目录：  {target_dir}", style="WeChatBody.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", **pad)

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
        messagebox.showinfo("撤销完成", f"已删除本次导入生成的 {removed} 个文件。")
        win.destroy()

    ttk.Button(win, text="打开输出文件夹", style="WeChatPrimary.TButton", command=_open)\
        .grid(row=2, column=0, sticky="w", padx=16, pady=(10,16))
    ttk.Button(win, text="撤销本次导入", style="WeChatSecondary.TButton", command=undo)\
        .grid(row=2, column=1, sticky="w", padx=8,  pady=(10,16))
    ttk.Button(win, text="关闭", style="WeChatSecondary.TButton", command=win.destroy)\
        .grid(row=2, column=2, sticky="e", padx=16, pady=(10,16))

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
def copy_with_progress_seq_and_video(src_files, dst, pb, status_label, log_file, mmdd_str, info_box, total_bytes, extract_star=False):
    created=[]; done=set()
    if os.path.exists(log_file):
        with open(log_file,"r",encoding="utf-8") as f:
            for line in f:
                if line.startswith("完成: "):
                    done.add(line.split("完成: ",1)[1].split(" -> ",1)[0].strip())

    photo_files=src_files["RAW"]+src_files["JPG"]; video_files=src_files["VIDEO"]

    raw_dir=os.path.join(dst,"RAW"); jpg_dir=os.path.join(dst,"JPG"); vid_dir=os.path.join(dst,"VIDEO")
    os.makedirs(raw_dir,exist_ok=True); os.makedirs(jpg_dir,exist_ok=True); os.makedirs(vid_dir,exist_ok=True)

    star_root = os.path.join(dst, "已星标照片")
    star_jpg  = os.path.join(star_root, "已星标JPG")
    star_raw  = os.path.join(star_root, "已星标RAW")
    if extract_star:
        os.makedirs(star_jpg, exist_ok=True); os.makedirs(star_raw, exist_ok=True)

    plan=build_seq_plan(photo_files,mmdd_str)
    final_map = {}

    bytes_done = 0
    t0 = time.time()

    def _upd(label, phase):
        elapsed = max(time.time()-t0, 1e-6)
        speed_mb = bytes_done / elapsed / (1024*1024)
        pct = (bytes_done/total_bytes*100) if total_bytes>0 else 0
        pb["value"] = min(max(pct,0),100)
        label.config(text=f"{phase} | {bytes_to_human(bytes_done)} / {bytes_to_human(total_bytes)} | 速度 {speed_mb:.2f} MB/s")
        label.update()

    # 照片复制与重命名
    for src,base,ext in plan:
        if src in done:
            _upd(status_label, "照片")
            continue
        td=raw_dir if is_raw_ext(ext) else jpg_dir
        dst_path=unique_path(td,f"{base}.{ext}")
        try:
            size = 0
            try: size = os.path.getsize(src)
            except Exception: size = 0
            shutil.copy2(src,dst_path); created.append(dst_path); final_map[src] = dst_path
            with open(log_file,"a",encoding="utf-8") as f: f.write(f"完成: {src} -> {os.path.basename(dst_path)}\n")
            bytes_done += size
            if int(time.time()*10)%3==0:  # 轻量更新频率
                log_add(info_box,f"复制：{os.path.basename(dst_path)}")
        except Exception as e:
            with open(log_file,"a",encoding="utf-8") as f: f.write(f"错误: {src} | {e}\n")
        _upd(status_label, "照片")

    # 视频复制（保留原名）
    for src in video_files:
        if src in done:
            _upd(status_label, "视频"); continue
        dst_path=unique_path(vid_dir,os.path.basename(src))
        try:
            size = 0
            try: size = os.path.getsize(src)
            except Exception: size = 0
            shutil.copy2(src,dst_path); created.append(dst_path)
            with open(log_file,"a",encoding="utf-8") as f: f.write(f"完成: {src} -> {os.path.basename(dst_path)}\n")
            bytes_done += size
        except Exception as e:
            with open(log_file,"a",encoding="utf-8") as f: f.write(f"错误: {src} | {e}\n")
        _upd(status_label, "视频")

    # 进度条就绪到 100%
    _upd(status_label, "收尾")

    # 星标复制不计入总进度，只追加日志
    if extract_star:
        log_add(info_box, "开始提取星标照片…")
        star_count = 0
        for src, base, ext in plan:
            try:
                if is_starred_file(src):
                    src_copied_path = final_map.get(src, src)
                    if is_jpg_ext(ext):
                        dst_star = unique_path(star_jpg, os.path.basename(src_copied_path))
                    else:
                        dst_star = unique_path(star_raw, os.path.basename(src_copied_path))
                    shutil.copy2(src_copied_path, dst_star)
                    created.append(dst_star)
                    star_count += 1
            except Exception as e:
                with open(log_file,"a",encoding="utf-8") as f: f.write(f"星标复制错误: {src} | {e}\n")
        log_add(info_box, f"星标提取完成，共 {star_count} 个文件")

    return created

def _update(pb,lab,copied,total,start,phase):
    # 仅保留以防调用；本版本不用文件数速率
    pb["value"]= (copied/total*100) if total else 0
    el=max(time.time()-start,1e-6); sp=copied/el; rem=max(total-copied,0); eta=int(rem/sp) if sp>0 else 0
    lab.config(text=f"{phase} {copied}/{total} | 速度 {sp:.2f}/秒 | 预计剩余 {eta} 秒"); lab.update()

# ---------- 主题 ----------
THEME_PALETTES = {
    "light": {"BG":"#F7F7F7","CARD":"#FFFFFF","TEXT":"#111111","SUB":"#6B6B6B","BORDER":"#E6E6E6","GREEN":"#07C160","GREEN_DARK":"#05924C","INPUT_BG":"#FFFFFF","INPUT_FG":"#111111"},
    "dark":  {"BG":"#141414","CARD":"#1F1F1F","TEXT":"#EDEDED","SUB":"#A3A3A3","BORDER":"#2A2A2A","GREEN":"#07C160","GREEN_DARK":"#05924C","INPUT_BG":"#1F1F1F","INPUT_FG":"#EDEDED"}
}

def apply_theme(root, theme_key, info_text_widget=None):
    style = ttk.Style()
    try: style.theme_use("clam")
    except Exception: pass
    P = THEME_PALETTES["dark" if theme_key=="dark" else "light"]

    root.configure(bg=P["BG"])
    style.configure("WeChatTitle.TLabel", background=P["BG"], foreground=P["TEXT"], font=("SimHei",18))
    style.configure("WeChatH2.TLabel",    background=P["BG"], foreground=P["TEXT"], font=("SimHei",14))
    style.configure("WeChatBody.TLabel",  background=P["BG"], foreground=P["TEXT"], font=("SimHei",12))
    style.configure("WeChatSubtle.TLabel",background=P["BG"], foreground=P["SUB"],  font=("SimHei",11))
    style.configure("WeChatFrame.TFrame", background=P["BG"])
    style.configure("WeChatCard.TFrame",  background=P["CARD"], relief="flat")
    style.configure("WeChatPrimary.TButton", background=P["GREEN"], foreground="#FFFFFF", font=("SimHei",12), padding=6, borderwidth=0)
    style.map("WeChatPrimary.TButton", background=[("active", P["GREEN_DARK"])])
    style.configure("WeChatSecondary.TButton", background="#2b2b2b" if theme_key=="dark" else "#EDEDED", foreground=P["TEXT"], font=("SimHei",12), padding=6, borderwidth=0)
    style.map("WeChatSecondary.TButton", background=[("active", "#3a3a3a" if theme_key=="dark" else "#E0E0E0")])
    style.configure("WeChat.Horizontal.TProgressbar", troughcolor=P["BORDER"], background=P["GREEN"], bordercolor=P["BORDER"], lightcolor=P["GREEN"], darkcolor=P["GREEN"])
    style.configure("TCombobox", fieldbackground=P["INPUT_BG"], background=P["INPUT_BG"], foreground=P["TEXT"], bordercolor=P["BORDER"], arrowcolor=P["TEXT"])
    style.map("TCombobox", fieldbackground=[("readonly", P["INPUT_BG"])], foreground=[("readonly", P["TEXT"])], background=[("readonly", P["INPUT_BG"])])

    if info_text_widget is not None:
        info_text_widget.configure(bg=P["CARD"], fg=P["TEXT"], insertbackground=P["TEXT"])

def set_text_theme(widget, theme_key):
    P = THEME_PALETTES["dark" if theme_key=="dark" else "light"]
    widget.configure(bg=P["CARD"], fg=P["TEXT"], insertbackground=P["TEXT"])

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
def start_copy(src_drive,dst_letter,cfg,root,category,info_box,btn_start, pb_main, status_lbl, extract_star=False):
    if not category:
        messagebox.showwarning("提示","请先选择拍摄类型。"); return
    dtype=drive_type_name(get_drive_type_code(src_drive))
    log_add(info_box,f"素材盘：{src_drive}（{get_drive_label(src_drive)} | {dtype}）")
    if is_system_drive(src_drive):
        if not messagebox.askyesno("高风险确认",f"{src_drive} 是系统盘，不建议作为素材盘源。继续？"): return
        if not messagebox.askyesno("二次确认","再次确认从系统盘作为相机源复制？"): return
    elif get_drive_type_code(src_drive)!=2:
        if not messagebox.askyesno("固定磁盘警告",f"{src_drive} 为固定盘，通常应选移动盘。继续？"): return

    shoot_name=simpledialog.askstring("本次拍摄名称","输入拍摄地点或主题（可中文）：",parent=root)
    if not shoot_name: return

    total_b,free_b=get_drive_usage_bytes(src_drive)
    log_add(info_box,f"素材盘容量：{bytes_to_human(total_b)} | 剩余：{bytes_to_human(free_b)}")
    log_add(info_box,"开始预检源文件…")
    counts,sizes,files=preflight_scan(src_drive)
    total_files=counts["RAW"]+counts["JPG"]+counts["VIDEO"]
    total_size =sizes["RAW"] +sizes["JPG"] +sizes["VIDEO"]
    log_add(info_box,f"预检完成 RAW:{counts['RAW']} JPG:{counts['JPG']} VIDEO:{counts['VIDEO']} 合计:{total_files} | 体积 {bytes_to_human(total_size)}")

    if not messagebox.askyesno("确认复制",
        "预检完成：\n"
        f"RAW：{counts['RAW']}（{bytes_to_human(sizes['RAW'])}）\n"
        f"JPG：{counts['JPG']}（{bytes_to_human(sizes['JPG'])}）\n"
        f"VIDEO：{counts['VIDEO']}（{bytes_to_human(sizes['VIDEO'])}）\n"
        f"合计：{total_files}（{bytes_to_human(total_size)}）\n\n"
        "将复制到：年/拍摄类型/“MM月”/“MM.DD_拍摄名”/（RAW,JPG,VIDEO，及可选已星标照片）\n"
        "照片重命名：MMDD-0001 起；视频保留原名。"):
        log_add(info_box,"用户取消复制"); return

    if dst_letter:
        if os.name == "nt" and not dst_letter.endswith("\\"):
            target_root = dst_letter + "\\"
        else:
            target_root = dst_letter
    else:
        target_root=cfg.get("last_target_root","")
        if not os.path.exists(target_root):
            target_root=filedialog.askdirectory(title="选择目标硬盘文件夹（建议为外置硬盘根目录）")
            if not target_root: return
    cfg["last_target_root"]=target_root; save_config(cfg)
    if os.path.splitdrive(target_root)[0].upper()==os.path.splitdrive(src_drive)[0].upper():
        if not messagebox.askyesno("风险提示","目标盘与素材盘相同盘符，建议不同物理盘。继续？"): return

    today=datetime.now()
    year_dir=os.path.join(target_root,str(today.year))
    cat_dir=os.path.join(year_dir,category)
    month_dir=os.path.join(cat_dir,f"{today.month:02d}月")
    day_folder=f"{today.month:02d}.{today.day:02d}_{shoot_name}"
    target_dir=os.path.join(month_dir,day_folder); os.makedirs(target_dir,exist_ok=True)
    log_add(info_box,f"目标目录：{target_dir}")

    try:
        usage_key = dst_letter or target_root
        _,dst_free=get_drive_usage_bytes(usage_key)
        if dst_free<total_size:
            log_add(info_box,f"目标剩余 {bytes_to_human(dst_free)} < 需要 {bytes_to_human(total_size)}")
            if not messagebox.askretrycancel("空间不足",
                f"目标剩余 {bytes_to_human(dst_free)}，预计需要 {bytes_to_human(total_size)}。清理后重试。"):
                return
    except Exception: pass

    log_file=os.path.join(target_dir,"copy_log.txt")
    mmdd_str=f"{today.month:02d}{today.day:02d}"

    # —— 主界面进度初始化 —— #
    pb_main["value"] = 0
    status_lbl.config(text="准备复制…")
    root.update_idletasks()

    # 开始提示音
    beep_start()
    log_add(info_box,"开始复制…")

    btn_start.configure(state="disabled")
    try:
        created=copy_with_progress_seq_and_video(
            files, target_dir, pb_main, status_lbl, log_file, mmdd_str, info_box,
            total_bytes=total_size, extract_star=extract_star
        )
    finally:
        btn_start.configure(state="normal")

    log_add(info_box,f"复制完成 共 {len(created)} 个目标文件")
    status_lbl.config(text="复制完成")

    ts2=datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(target_dir,f"import_manifest_{ts2}.json"),"w",encoding="utf-8") as f:
        json.dump({"version":VERSION,"created_at":ts2,"source_drive":src_drive,"target_dir":target_dir,"files":created},
                  f,ensure_ascii=False,indent=2)

    # 完成提示音 + 撤销窗口
    beep_done()
    show_finish_and_undo(root, target_dir, created)

# ---------- UI（分割窗可拖动） ----------
def main_ui():
    if os.name != "nt" and not os.environ.get("DISPLAY"):
        print("[错误] 未检测到图形显示环境，无法启动 Tkinter 界面。", file=sys.stderr)
        return

    cfg = load_config()
    theme_key = cfg.get("theme","light")
    sash_ratio = float(cfg.get("sash_ratio", 0.55))

    root = tk.Tk()
    root.title(f"陈同学影像管理助手  {VERSION}")
    root.geometry("1000x720")
    root.minsize(860, 600)
    root.resizable(True, True)

    apply_theme(root, theme_key)

    # 顶部栏
    header = ttk.Frame(root, style="WeChatFrame.TFrame")
    header.grid(row=0, column=0, sticky="ew", padx=0, pady=(10,0))
    ttk.Label(header, text="照片/视频导入与分类", style="WeChatTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(20,10))

    ttk.Label(header, text="主题", style="WeChatBody.TLabel").grid(row=0, column=1, sticky="e")
    theme_box = ttk.Combobox(header, state="readonly", values=THEMES, width=6)
    theme_box.grid(row=0, column=2, sticky="w", padx=(6,0))
    theme_box.set("日间" if theme_key=="light" else "暗黑")

    # 分割窗
    paned = ttk.Panedwindow(root, orient="vertical")
    paned.grid(row=1, column=0, sticky="nsew", padx=20, pady=(10,6))
    root.grid_rowconfigure(1, weight=1)
    root.grid_columnconfigure(0, weight=1)

    top_frame = ttk.Frame(paned, style="WeChatFrame.TFrame")
    bottom_frame = ttk.Frame(paned, style="WeChatFrame.TFrame")
    paned.add(top_frame, weight=3)
    paned.add(bottom_frame, weight=5)

    # 顶部：设置
    card1 = ttk.Frame(top_frame, style="WeChatCard.TFrame", padding=16)
    card1.grid(row=0, column=0, sticky="ew")
    card1.grid_columnconfigure(1, weight=1)
    ttk.Label(card1, text="导入设置", style="WeChatH2.TLabel").grid(row=0, column=0, sticky="w", pady=(0,6), columnspan=5)

    ttk.Label(card1, text="选择素材盘", style="WeChatBody.TLabel").grid(row=1, column=0, sticky="e", padx=(0,8))
    combo_src = ttk.Combobox(card1, state="readonly", width=70); combo_src.grid(row=1, column=1, sticky="ew")
    ttk.Button(card1, text="刷新", style="WeChatSecondary.TButton",
               command=lambda: refresh_sources(info_box, combo_src, auto_pick=True)).grid(row=1, column=2, padx=(8,0))

    ttk.Label(card1, text="拷入到", style="WeChatBody.TLabel").grid(row=2, column=0, sticky="e", padx=(0,8), pady=(8,0))
    combo_dst = ttk.Combobox(card1, state="readonly", width=50); combo_dst.grid(row=2, column=1, sticky="w", pady=(8,0))
    ttk.Button(card1, text="刷新", style="WeChatSecondary.TButton",
               command=lambda: refresh_dests(info_box, combo_dst)).grid(row=2, column=2, padx=(8,0), pady=(8,0))

    ttk.Label(card1, text="拍摄类型", style="WeChatBody.TLabel").grid(row=3, column=0, sticky="e", padx=(0,8), pady=(8,0))
    combo_cat = ttk.Combobox(card1, state="readonly", values=CATEGORIES, width=20); combo_cat.grid(row=3, column=1, sticky="w", pady=(8,0))
    combo_cat.current(0)

    star_var = tk.BooleanVar(value=False)
    chk_star = ttk.Checkbutton(card1, text="提取星标照片", variable=star_var)
    chk_star.grid(row=3, column=2, sticky="w", padx=(12,0), pady=(8,0))

    # 顶部：操作 + 进度
    card3 = ttk.Frame(top_frame, style="WeChatCard.TFrame", padding=16)
    card3.grid(row=1, column=0, sticky="ew", pady=(10,0))
    pb_main = ttk.Progressbar(card3, style="WeChat.Horizontal.TProgressbar", orient="horizontal", length=560, mode="determinate")
    pb_main.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0,8))
    status_lbl = ttk.Label(card3, text="待机", style="WeChatSubtle.TLabel")
    status_lbl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0,6))

    def start_action():
        sv = combo_src.get()
        if not sv:
            messagebox.showwarning("提示","请先选择素材盘。"); return
        src_drive = sv.split("|",1)[0].strip()
        dst_letter = combo_dst.get().split(" ",1)[0].strip().rstrip("\\") if combo_dst.get() else ""
        start_copy(src_drive, dst_letter, load_config(), root, combo_cat.get().strip(),
                   info_box, btn_start, pb_main, status_lbl, extract_star=star_var.get())

    btn_start = ttk.Button(card3, text="开始分类", style="WeChatPrimary.TButton", command=start_action)
    btn_start.grid(row=2, column=0, padx=(0,8))
    ttk.Button(card3, text="退出", style="WeChatSecondary.TButton", command=root.destroy).grid(row=2, column=1)

    # 底部：日志
    card2 = ttk.Frame(bottom_frame, style="WeChatCard.TFrame", padding=16)
    card2.grid(row=0, column=0, sticky="nsew")
    bottom_frame.grid_rowconfigure(0, weight=1)
    bottom_frame.grid_columnconfigure(0, weight=1)

    ttk.Label(card2, text="信息", style="WeChatH2.TLabel").grid(row=0, column=0, sticky="w", pady=(0,6))
    info_box = tk.Text(card2, height=10, wrap="word", bd=0, relief="flat", state="disabled")
    set_text_theme(info_box, theme_key)
    info_box.grid(row=1, column=0, sticky="nsew")
    card2.grid_rowconfigure(1, weight=1)
    card2.grid_columnconfigure(0, weight=1)
    sb = ttk.Scrollbar(card2, command=info_box.yview); sb.grid(row=1, column=1, sticky="ns")
    info_box.configure(yscrollcommand=sb.set)

    # 主题切换
    def on_theme_change(event=None):
        sel = theme_box.get()
        key = "light" if sel == "日间" else "dark"
        cfg2 = load_config(); cfg2["theme"] = key; save_config(cfg2)
        apply_theme(root, key, info_text_widget=info_box); set_text_theme(info_box, key)
    theme_box.bind("<<ComboboxSelected>>", on_theme_change)

    # 初始化扫描
    refresh_sources(info_box, combo_src, auto_pick=True)

    # 版权
    def _copyright_popup():
        msg = ("此软件完全免费，请勿倒卖！\nby: 抖音 @摄影师陈同学\nCopyright © 2025")
        messagebox.showinfo("版权声明", msg)
    root.after(500, _copyright_popup)
    footer = ttk.Label(root, text="此软件完全免费，请勿倒卖！ by: 抖音@摄影师陈同学", style="WeChatSubtle.TLabel", anchor="center")
    footer.grid(row=2, column=0, pady=(2,8))

    # 分割比例恢复/保存
    def apply_sash_ratio_later():
        try:
            root.update_idletasks()
            total_h = paned.winfo_height()
            if total_h <= 0:
                root.after(100, apply_sash_ratio_later); return
            pos = int(total_h * float(load_config().get("sash_ratio", 0.55)))
            try:
                paned.sashpos(0, max(120, min(total_h-160, pos)))
            except Exception:
                pass
        except Exception:
            pass
    root.after(300, apply_sash_ratio_later)

    def remember_sash(event=None):
        try:
            root.update_idletasks()
            total_h = paned.winfo_height()
            pos = paned.sashpos(0)
            ratio = round(pos / max(total_h, 1), 4)
            cfg3 = load_config(); cfg3["sash_ratio"] = max(0.15, min(0.85, ratio))
            save_config(cfg3)
        except Exception:
            pass
    paned.bind("<ButtonRelease-1>", remember_sash)
    root.bind("<Configure>", lambda e: root.after(50, remember_sash))

    root.mainloop()

if __name__=="__main__":
    main_ui()
