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

Un appel par mission. Diagnostiquer depuis le dossier. Relire seulement
les paths marqués tronqués, `re-read_allowed`, ou les ids demandés en
drill-down. `sources` est une liste fermée : un fichier = ce fichier,
un dossier = son index. PDF : objets Annot d'abord, jamais un OCR du
document « au cas où ». Ticket Jira seulement si `ticket` est fourni.

Schémas de source : `repo://`, `jira://`, `confluence://`, `image://`,
`log://<chemin>` (fichier local, échecs + contexte gardés, bruit répétitif
dédupliqué), `ci://gitlab/<projet>/<job_id>` (trace de job GitLab, même
filtrage que `log://`, crédentiels dans `.claude/.env.local` : `GITLAB_URL`,
`GITLAB_TOKEN`, `GITLAB_PROJECT_ID`), `git://<motif>` (branches locales dont
le nom ou l'historique porte le motif, avec leur statut de fusion vers
main/master/develop — ramassage seulement, pas d'avis sur la bonne branche).

OCR d'abord pour les captures. Avec `use_llm=true` et un modèle qui déclare la
vision, jusqu'à 3 captures par mission dont l'OCR ne suffit pas (transcript
vide, ou la mission évoque un trou de layout : en-tête fusionné, filtre,
bouton disabled) reçoivent une seconde passe vision, layout seulement — les
chiffres restent ceux de l'OCR.

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
Prompts terrain 6160 / 6417 / 6553 + grille : [`session-prompts.md`](session-prompts.md).

## Ce que l'analyse des sessions a changé (2 oct 2026)

Dix appels `scout` relevés dans les transcripts Claude Code du 14/09 au 01/10 : dans les dix,
l'orchestrateur a rechargé le ticket ou rouvert les PNG juste après. Causes corrigées :

- corps du ticket coupé à 600 caractères / 8 lignes alors que le dossier n'utilisait qu'un
  tiers de son plafond : le corps passe maintenant en entier tant que le budget le permet ;
- ni commentaires, ni liens, ni priorité, ni champs personnalisés : ils sont rendus, les champs
  nommés dans la mission d'abord (« vide dans Jira » s'ils le sont) ;
- section Code hors sujet (motifs d'un ticket de planification codés en dur) : la recherche
  d'écran part des URL et symboles du ticket, et ne tourne pas pour une mission « Extraire… » ;
- `ready: false` systématique faute de page Confluence, cherchée avec les verbes de la consigne :
  une mission d'extraction n'exige ni page ni écran, et la requête part du titre du ticket ;
- OCR réduit à quelques lignes filtrées par mots-clés : transcript dans l'ordre de lecture,
  borné par image, intégral dans `temp/scout/<clé>/ocr/<image>.txt` ;
- image passée en chemin absolu marquée « non extraite » ; Jira « non configuré » depuis un
  worktree git (le `.env.local` du checkout principal est maintenant lu).

Ce qui est coupé est nommé dans `re-read_allowed` avec un fichier texte sur disque
(`temp/scout/<clé>/tickets/<clé>.md`) : le drill-down lit ce fichier.

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
