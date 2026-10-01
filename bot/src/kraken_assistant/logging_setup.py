"""Logs INFO/WARNING/ERROR, console + fichier, avec masquage systématique des secrets."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from .config import Settings

_HEADER_RE = re.compile(r"(API-Key|API-Sign|APIKey|Authent|Authorization|token)(['\"]?\s*[:=]\s*['\"]?)([^'\"\s,}]+)",
                        re.IGNORECASE)


class SecretRedactor(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if len(s) >= 6]

    def redact(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "***")
        return _HEADER_RE.sub(r"\1\2***", text)

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        red = self.redact(msg)
        if red != msg:
            record.msg, record.args = red, ()
        return True


def setup_logging(settings: Settings) -> None:
    root = logging.getLogger()
    if getattr(root, "_ka_configured", False):
        return
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    redactor = SecretRedactor(settings.secret_values())
    console = logging.StreamHandler()
    fileh = RotatingFileHandler(settings.log_dir / "assistant.log", maxBytes=2_000_000, backupCount=5,
                                encoding="utf-8")
    for h in (console, fileh):
        h.setFormatter(fmt)
        h.addFilter(redactor)
        root.addHandler(h)
    root.setLevel(settings.log_level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx logue les URLs, pas utile
    root._ka_configured = True  # type: ignore[attr-defined]
