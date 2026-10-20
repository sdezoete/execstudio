"""PowerPoint generation. Uses python-pptx when installed, otherwise the standard-library writer."""
from pathlib import Path

from ..config import ROOT

try:
    import pptx as _pptx  # noqa: F401
    from . import pptx_engine
    ENGINE = "python-pptx " + _pptx.__version__
except ImportError:  # python-pptx not installed: fall back to the built-in writer
    pptx_engine = None
    ENGINE = "built-in"

from . import xml_engine  # noqa: E402

TEMPLATE_DIR = ROOT / "data" / "templates"


def template_path(tpl):
    name = (tpl or {}).get("file")
    if not name:
        return None
    path = (TEMPLATE_DIR / name).resolve()
    if not path.is_relative_to(TEMPLATE_DIR.resolve()) or not path.exists():
        return None
    return path


def build(title, slides, meta, tpl):
    if pptx_engine is not None:
        return pptx_engine.build(title, slides, meta, tpl, template_path(tpl))
    return xml_engine.build(title, slides, meta, tpl)


def status():
    return {"engine": ENGINE, "advanced": pptx_engine is not None}
