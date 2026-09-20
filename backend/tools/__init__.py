"""工具层：LangChain Tools。MVP 仅文档生成器。"""

from backend.tools.document_generator import (
    document_generator,
    render_and_save,
    render_document,
    save_document,
)

__all__ = ["document_generator", "render_and_save", "render_document", "save_document"]
