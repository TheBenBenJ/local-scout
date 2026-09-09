"""Scout : le modèle local déblaie, l'orchestrateur ne voit qu'un dossier borné.

Inverse du MCP local-agent (15 outils, orchestration à chaque expand).
Ici la boucle d'outils reste locale. Un seul texte plafonné sort.
"""

from .engine import ScoutResult, run_scout

__all__ = ["ScoutResult", "run_scout"]
