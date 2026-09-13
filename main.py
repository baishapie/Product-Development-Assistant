"""项目启动入口：``python main.py``（内部启动 FastAPI + 前端页面）。

用法：
    python main.py                # http://127.0.0.1:8000
    python main.py --port 8001    # 指定端口
    python main.py --reload       # 开发模式自动重载
"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="main.py", description="启动 ProductMind AI Web 服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码变更自动重载")
    args = parser.parse_args()

    print(f"ProductMind AI 启动中：http://{args.host}:{args.port}   (接口文档：/docs)")
    uvicorn.run("backend.api.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
