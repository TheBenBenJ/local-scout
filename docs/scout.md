# Scout

L'orchestrateur n'enchaîne plus Jira / OCR / expand. Les extracteurs
déterministes ramassent Jira, pièces, Confluence et rg. Un dossier ≤ 12 000
caractères sort. Le 9B n'est appelé que si on le demande (`use_llm` côté MCP,
absence de `--no-llm` côté CLI).

Dépôt : https://github.com/TheBenBenJ/local-scout

## Pourquoi

Le MCP à 14 outils (`local_task`, `local_expand`, …) interceptait le brut **par appel**.
Sur une discussion, chaque tour renvoyait les schémas + l'historique des paquets.
Mesure LYSI-6476 « avec local-agent » : +2,2 M tokens Cursor.

## Install

```bash
git clone https://github.com/TheBenBenJ/local-scout ~/.local-scout
~/.local-scout/install.sh
```

MCP : `scout` et `scout_ping` uniquement. `scout` est déterministe par défaut.
`--out` n'existe que sur la CLI.

```
scout(mission="Diagnostiquer LYSI-6476 …", ticket="LYSI-6476")
```

CLI :

```bash
~/.local-scout/bin/local-scout --ticket LYSI-6476 --no-llm
~/.local-scout/bin/local-scout --ticket LYSI-6476
~/.local-scout/bin/local-scout doctor
```

Sortie disque : `temp/scout/<clé>/dossier.md` dans le dépôt cible (debug).
Le chemin n'est pas renvoyé dans la réponse MCP.

Protocole de session A/B/C : [`session-bench.md`](session-bench.md).

## Mesure Cursor (LYSI-6476, 9 sept 2026)

Dans **une** session mesurée, diagnostiquer depuis un dossier scout **déjà écrit
sur disque** a utilisé 59 % de moins d'usage reporté que la récupération directe
(Jira HTTP + cinq PNG). Ce n'est pas « local-scout économise 59 % des tokens »
en général : le chat pas cher n'a pas appelé `scout`. Ce n'est pas un `/analyse`
recette.

| Phase | Sans scout | Dossier déjà là | Économie |
| --- | ---: | ---: | ---: |
| Terrain | 422,7 k | 60,5 k | 362,2 k |
| Analyse | 380,3 k | 267,8 k | 112,5 k |
| Session | 803,0 k | 328,3 k | **474,7 k (59 %)** |

## Compteurs internes

`raw_chars` / `ledger.text_chars` : texte des sources, sur disque.
`visible_chars` : longueur du dossier, sur disque. Pas dans la réponse MCP.
Les octets PNG : `ledger.image_bytes`. Un % d'interception locale n'est pas
un delta de cartes Cursor.
