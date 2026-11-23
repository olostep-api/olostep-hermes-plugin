"""Hermes plugin entry point for Olostep.

Hermes' git-clone plugin loader imports this file; the implementation lives in
the ``olostep_hermes`` package next to it. Putting this directory on sys.path
lets that package import the same way under the loader, pytest and a plain checkout.
"""

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from olostep_hermes import register  # noqa: E402

__all__ = ["register"]
