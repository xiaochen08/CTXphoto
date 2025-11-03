from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Iterable, List, Tuple

_ProviderList = List[str]
_Builder = Callable[[Iterable[str]], Any]

_lock = threading.Lock()
_builders: Dict[str, _Builder] = {}
_sessions: Dict[str, Any] = {}
_current_providers: _ProviderList = ["CPUExecutionProvider"]


class _SessionRegistry:
    def register(self, name: str, builder: _Builder) -> None:
        with _lock:
            _builders[name] = builder

    def get(self, name: str) -> Any:
        with _lock:
            return _sessions.get(name)

    def providers(self) -> _ProviderList:
        return get_current_providers()


ort_session = _SessionRegistry()


def register_session_builder(name: str, builder: _Builder) -> None:
    ort_session.register(name, builder)


def rebuild_sessions(providers: Iterable[str]) -> List[Tuple[str, Exception]]:
    errors: List[Tuple[str, Exception]] = []
    provider_list = list(providers)
    with _lock:
        new_sessions: Dict[str, Any] = {}
        for name, builder in _builders.items():
            try:
                new_sessions[name] = builder(provider_list)
            except Exception as exc:  # pragma: no cover - depends on runtime env
                errors.append((name, exc))
        if not errors:
            _sessions.clear()
            _sessions.update(new_sessions)
            _current_providers.clear()
            _current_providers.extend(provider_list or ["CPUExecutionProvider"])
    return errors


def get_current_providers() -> _ProviderList:
    with _lock:
        return list(_current_providers)
