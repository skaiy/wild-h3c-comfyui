"""Wild H3C: MiniMax H3 video generation on Apple Silicon (h3.c C/Metal engine)."""

from .nodes import H3Extension, comfy_entrypoint

__all__ = ["comfy_entrypoint", "H3Extension"]
