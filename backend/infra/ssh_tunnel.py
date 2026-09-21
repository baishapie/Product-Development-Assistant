"""SSH 本地端口转发：把远端 PostgreSQL 端口映射到本地。

仅当 ``SSH_ENABLED=true`` 时启用；用于数据库只能经跳板机访问的场景。
``sshtunnel`` 为延迟导入，未安装/未启用时不产生依赖。
"""

from __future__ import annotations

import logging
from typing import Any

from backend.config import Settings

logger = logging.getLogger(__name__)


class SSHTunnel:
    """管理一条 SSH 隧道（本地端口 -> PG_HOST:PG_PORT）。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._server: Any = None

    def start(self) -> tuple[str, int]:
        """建立隧道，返回本地 (host, port)。"""
        from sshtunnel import SSHTunnelForwarder

        s = self._settings
        logger.info(
            "ssh tunnel: connecting",
            extra={
                "ssh_host": s.ssh_host,
                "ssh_port": s.ssh_port,
                "ssh_user": s.ssh_user,
                "remote": f"{s.pg_host}:{s.pg_port}",
            },
        )
        self._server = SSHTunnelForwarder(
            (s.ssh_host, s.ssh_port),
            ssh_username=s.ssh_user or None,
            ssh_pkey=str(s.ssh_key_path),
            ssh_private_key_password=s.ssh_key_passphrase or None,
            remote_bind_address=(s.pg_host, s.pg_port),
            local_bind_address=(s.ssh_local_bind_host, s.ssh_local_bind_port),
        )
        self._server.start()
        logger.info(
            "ssh tunnel: established",
            extra={
                "local_host": self._server.local_bind_host,
                "local_port": self._server.local_bind_port,
                "remote": f"{s.pg_host}:{s.pg_port}",
            },
        )
        return self._server.local_bind_host, self._server.local_bind_port

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.stop()
            except Exception:  # noqa: BLE001 - 关闭失败不影响退出
                logger.warning("failed to stop ssh tunnel", exc_info=True)
            self._server = None
            logger.info("ssh tunnel: stopped")

    def is_active(self) -> bool:
        return bool(self._server is not None and getattr(self._server, "is_active", False))
