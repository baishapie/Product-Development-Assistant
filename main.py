"""项目启动入口：``python main.py``（启动 FastAPI + 前端页面）。

服务参数由配置提供，可用环境变量覆盖：``HOST`` / ``PORT`` / ``RELOAD``
（默认 ``127.0.0.1:8000``，见 ``.env.example``）。
"""

from __future__ import annotations

import uvicorn

from backend.config import get_settings
from backend.logging_config import configure_logging


def main() -> None:
    configure_logging()
    settings = get_settings()

    # 开发热重载时排除缓存/产物目录，减少文件监视开销
    reload_excludes = [
        ".git",
        "__pycache__",
        "output",
        "docs",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
    ]

    print(f"ProductMind AI 启动中：http://{settings.host}:{settings.port}   (接口文档：/docs)")
    uvicorn.run(
        "backend.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        reload_excludes=reload_excludes,
    )


if __name__ == "__main__":
    main()
