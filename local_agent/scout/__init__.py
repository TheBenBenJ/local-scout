"""Scout: the local model does the groundwork, the orchestrator only sees a bounded dossier.

The reverse of the local-agent MCP (15 tools, orchestration on every expand).
Here the tool loop stays local. A single capped text comes out.
"""

from .engine import ScoutResult, run_scout

__all__ = ["ScoutResult", "run_scout"]
