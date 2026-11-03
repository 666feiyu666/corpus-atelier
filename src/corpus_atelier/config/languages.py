"""Interface languages offered by the product.

These constants live in the configuration layer so that preferences, settings,
and the translation catalogue share one source without depending on each other.
"""

from __future__ import annotations


DEFAULT_LANGUAGE = "zh-CN"
SUPPORTED_LANGUAGES = ("zh-CN", "en")
LANGUAGE_LABELS = {
    "zh-CN": "简体中文",
    "en": "English",
}
