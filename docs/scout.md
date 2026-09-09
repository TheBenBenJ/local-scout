# Scout

L'orchestrateur n'enchaîne plus Jira / OCR / expand. Le 9B (et surtout les
extracteurs déterministes) ramassent Jira, pièces, Confluence et rg. Un dossier
≤ 12 000 caractères sort.

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

MCP (Cursor / Claude Code) : `scout` et `scout_ping` uniquement.

```
scout(mission="Diagnostiquer LYSI-6476 …", ticket="LYSI-6476")
```

CLI :

```bash
~/.local-scout/bin/local-scout --ticket LYSI-6476
~/.local-scout/bin/local-scout --ticket LYSI-6476 --no-llm
~/.local-scout/bin/local-scout bench --ticket LYSI-6476 --out temp/scout/bench
~/.local-scout/bin/local-scout doctor
```

Sortie : `temp/scout/<clé>/dossier.md` dans le dépôt cible.

## Mesure Cursor (LYSI-6476, 9 sept 2026)

Deux chats neufs, même modèle, puis le même diagnostic 15 lignes.

| Phase | Sans scout | Dossier déjà là | Économie |
| --- | ---: | ---: | ---: |
| Terrain | 422,7 k | 60,5 k | 362,2 k |
| Analyse | 380,3 k | 267,8 k | 112,5 k |
| Session | 803,0 k | 328,3 k | **474,7 k (59 %)** |

Ce n'est pas un `/analyse` recette. Le 9B et les PNG restent hors facture Cursor
quand on part du dossier.

## Compteurs internes

`raw_chars` / `ledger.text_chars` : texte des sources.
`visible_chars` : longueur du dossier. `markdown()` ne les confond plus.
Les octets PNG : `ledger.image_bytes`. Un % d'interception locale n'est pas
un delta de cartes Cursor.
