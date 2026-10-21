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


def build(title, slides, meta, tpl, template_bytes=None, template_is_potx=False):
    if pptx_engine is not None:
        return pptx_engine.build(title, slides, meta, tpl, template_path(tpl), template_bytes, template_is_potx)
    return xml_engine.build(title, slides, meta, tpl)  # no capability to honour an uploaded template without python-pptx


def supports_custom_template():
    return pptx_engine is not None


def validate_uploaded_template(data, is_potx):
    """Raises ValueError if the file can't be opened as a PowerPoint template. Call once, at
    upload time; theme_colors() below is cheap and safe to call again on every export."""
    if pptx_engine is None:
        raise ValueError("python-pptx is not installed on the server.")
    pptx_engine.open_template_bytes(data, is_potx)


def theme_colors(data):
    return pptx_engine.theme_colors(data) if pptx_engine is not None else {}


def status():
    return {"engine": ENGINE, "advanced": pptx_engine is not None}
