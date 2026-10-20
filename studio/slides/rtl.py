"""Right-to-left script detection (Arabic, Persian, Urdu)."""
import re

_RTL = re.compile("[֐-׿؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


def is_rtl(text):
    return bool(_RTL.search(str(text or "")))
