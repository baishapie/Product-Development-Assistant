"""统一日志配置：控制台 + 文件（滚动）。

- ``KeyValueFormatter`` 把 ``logger.*(..., extra={...})`` 的上下文字段以 ``key=value``
  追加到日志行；请用单行值（如 JSON 字符串），避免多行破坏格式。
- 输出到控制台与 ``{log_dir}/app.log``（RotatingFileHandler，默认 10MB × 5）。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# LogRecord 内置字段（这些不当作 extra 输出）
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()) | {
    "message",
    "asctime",
    "taskName",
}

_configured = False


class KeyValueFormatter(logging.Formatter):
    """标准格式 + ``key=value`` 形式追加 ``extra`` 字段。"""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED and not key.startswith("_")
        }
        if not extras:
            return base
        suffix = " ".join(f"{key}={value}" for key, value in extras.items())
        return f"{base} {suffix}"


def configure_logging(
    level: str | int = logging.INFO,
    log_dir: str | Path | None = None,
    to_file: bool = True,
) -> None:
    """配置 root logger（控制台 + 文件）；重复调用是幂等的。"""
    global _configured
    if _configured:
        return

    if isinstance(level, str):
        level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    formatter = KeyValueFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if to_file:
        directory = Path(log_dir) if log_dir else Path("./logs")
        directory.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                directory / "app.log",
                maxBytes=10_000_000,
                backupCount=5,
                encoding="utf-8",
            )
        )
    for handler in handlers:
        handler.setFormatter(formatter)

    root = logging.getLogger()
    if not root.handlers:
        for handler in handlers:
            root.addHandler(handler)
    root.setLevel(level)
    _configured = True
