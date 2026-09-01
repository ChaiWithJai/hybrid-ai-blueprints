"""edgekit — the shared platform under every edge/mobile demo.

The violet_rails transplant, runnable: namespaces installed from
bundle.json, EdgeResources with JSON properties, client actions executed
on create through a registry, and an offline-first sync queue. Standard
library only, per repository convention.
"""

from .provider import BonsaiProvider, FixtureProvider, get_provider
from .store import FamilyStore
from .actions import ActionRegistry
from .harness import Gate, run_gates, write_evidence

__all__ = [
    "BonsaiProvider",
    "FixtureProvider",
    "get_provider",
    "FamilyStore",
    "ActionRegistry",
    "Gate",
    "run_gates",
    "write_evidence",
]
