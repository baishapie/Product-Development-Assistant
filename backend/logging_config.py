"""统一日志配置：把 ``logger.*(..., extra={...})`` 的上下文字段输出到日志行。

默认 Python ``logging`` 不会渲染 ``extra`` 字段，未配置 handler 时还会退化为
只打印 message。这里注册一个 root handler + ``KeyValueFormatter``，把
``agent=... attempt=...`` 等上下文追加到每行末尾。
"""

from __future__ import annotations

import logging

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


def configure_logging(level: int = logging.INFO) -> None:
    """配置 root logger；重复调用是幂等的。"""
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        KeyValueFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    # 保留已有 handler（避免与宿主重复），仅在为空时接管
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(level)
    _configured = True
