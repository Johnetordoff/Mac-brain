import sys

if sys.version_info[:2] != (3, 14):
    raise RuntimeError(
        "Mac Brain requires CPython 3.14.x exactly. Update Python before running Mac Brain."
    )

__version__ = "0.7.0"
