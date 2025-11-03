from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

try:  # Optional dependency, mirror runtime behavior in main app
    import onnxruntime as ort  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    ort = None  # type: ignore

CFG = Path.home() / ".ctxphoto" / "config.json"
CFG.parent.mkdir(parents=True, exist_ok=True)

_DEFAULT_PREF: Dict[str, Any] = {"prefer_cuda": True}


def load_pref() -> Dict[str, Any]:
    if CFG.exists():
        try:
            data = json.loads(CFG.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**_DEFAULT_PREF, **data}
        except Exception:
            pass
    return dict(_DEFAULT_PREF)


def save_pref(data: Dict[str, Any]) -> None:
    payload = {**_DEFAULT_PREF, **data}
    CFG.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cuda_available() -> bool:
    if ort is None:
        return False
    try:
        return "CUDAExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


def pick_providers(prefer_cuda: bool) -> List[str]:
    providers: List[str] = ["CPUExecutionProvider"]
    if not prefer_cuda:
        return providers
    if not cuda_available():
        return providers
    return ["CUDAExecutionProvider", "CPUExecutionProvider"]
