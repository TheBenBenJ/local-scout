# Prompts de conversation + bench terrain

Cinq chats **neufs**, dépôt **LYSI** (pas `~/.local-scout`). MCP `user-local-scout` version **1.8.x** (`scout_ping`). `use_llm=false`. Un appel `scout` par chat.

Le score automatique porte sur le **dossier**, pas sur les cartes Cursor. Les Usage rows se remplissent à la main, comme dans [`session-bench.md`](session-bench.md).

## Imprimer / noter

```bash
# Prompt collable
~/.local-scout/bin/local-scout bench --print-prompt LYSI-6160
~/.local-scout/bin/local-scout bench --print-prompt LYSI-6417-pdf
~/.local-scout/bin/local-scout bench --print-prompt LYSI-6417-dir
~/.local-scout/bin/local-scout bench --print-prompt LYSI-6553-c1
~/.local-scout/bin/local-scout bench --print-prompt LYSI-6553-c2

# Grille sur le dépôt client (Jira réel, --no-llm)
cd /chemin/vers/lysi
~/.local-scout/bin/local-scout bench --cases --repo . --out temp/scout/bench-terrain

# Noter un dossier.md produit dans un chat
~/.local-scout/bin/local-scout bench --score-dossier temp/scout/LYSI-6553/dossier.md --case LYSI-6553-c2 --repo .
```

Cas : `LYSI-6160`, `LYSI-6417-pdf`, `LYSI-6417-dir`, `LYSI-6553-c1`, `LYSI-6553-c2`.

## Comment jouer un chat

1. Nouveau chat, workspace = dépôt LYSI.
2. Coller **un** des prompts ci-dessous (ou la sortie de `--print-prompt`).
3. Vérifier `scout_ping` → `version: 1.8.0` (ou plus).
4. L’agent appelle `scout` **une fois**, diagnostique depuis le dossier.
5. Tout Read/curl Jira/PNG hors `re-read_allowed` = **scout miss** (fallback).
6. Remplir la ligne Usage + la grille. Noter le dossier : `--score-dossier`.

Qualité diagnostic (A et C) : 0 faux, 1 partiel, 2 juste mais preuves minces, 3 juste avec assez de preuves.

| Chat | input | output | cache r | cache w | tools | durée | qualité 0–3 | fallbacks | bench % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 6160 | | | | | | | | | |
| 6417-pdf | | | | | | | | | |
| 6417-dir | | | | | | | | | |
| 6553-c1 | | | | | | | | | |
| 6553-c2 | | | | | | | | | |

`C < A` n’est **pas** le critère ici : on mesure si le dossier 1.8 tient les écarts terrain. Un chat A (MCP off) reste optionnel, ticket par ticket, si tu veux un delta Usage.

---

## LYSI-6160 — revue e-reporting

Échec d’origine : `lib/…/IopoleConnector.php` réécrit en `src/…` → « fichier nommé absent » ; extraits sur le mauvais type ; « Ne pas relire » alors que le fichier était tronqué.

```text
Nouveau chat. Dépôt LYSI (pas ~/.local-scout). MCP user-local-scout ON. Relancer le serveur si la version n'est pas 1.8.x.

Tu es l'orchestrateur. Scout est un FILTRE de sources lourdes. Il ne diagnostique pas.
Un seul appel `scout`. use_llm=false. Ne pas curl Jira, ne pas Read le connecteur en entier.

Revue de code LYSI-6160 : e-reporting quotidien, lots SIREN.
Ne corrige pas. Qualifie ensuite.

Appelle exactement :

scout(
  mission="Revue de code LYSI-6160 e-reporting quotidien lots SIREN. Extraire le handler quotidien, createAndSubmitLotsOn + continue si le lot existe, findValideesParticulierSansLotOn, routing messenger.yaml.",
  ticket="LYSI-6160",
  sources=["lib/facture-electronique-bundle/src/Iopole/Connector/IopoleConnector.php"],
  use_llm=false
)

Depuis le dossier :
- Trancher / qualifier. Relire seulement les paths marqués tronqués ou re-read_allowed.
- Vérifier au grep les comptages. Ne pas conclure à l'absence sans Locations.

Fin de chat — scorecard (oui/non) :
- chemin lib/facture-electronique-bundle conservé, pas « fichier nommé absent »
- EreportingQuotidienMessageHandler, createAndSubmitLotsOn, continue, findValideesParticulierSansLotOn, messenger.yaml
- pas de section Trous inventée ; troncature annoncée si le fichier n'est pas intégral
- 0 fallback Read/curl hors Trous
```

---

## LYSI-6417 — Annot PDF (fichier)

Échec d’origine : pas d’extracteur Annot, OCR des PNG voisins, Jira sans `ticket=`.

```text
Nouveau chat. Dépôt LYSI. MCP user-local-scout ON, version 1.8.x.

Tu es l'orchestrateur. Scout filtre. use_llm=false. Un seul appel.
Ne pas OCR le PDF comme une capture. Ne pas OCR les PNG du même dossier.
Ne pas fetch Jira : ticket= n'est pas fourni.

Mission : extraire les commentaires jaunes (Annot Highlight) du PDF de revue LYSI-6417.
Ne pas diagnostiquer le métier. Lister les annots (auteur, page, /Contents).

Appelle exactement :

scout(
  mission="Commentaires jaunes de REVIEW-Synthese-fonctionnelle-040926.pdf (LYSI-6417). Extraire les Annot Highlight, pas l'OCR du PDF.",
  sources=["temp/64XX/6417/contexte/pieces_jointes/REVIEW-Synthese-fonctionnelle-040926.pdf"],
  use_llm=false
)

Si le chemin exact n'existe pas, passe le chemin réel du même fichier (basename identique), pas le dossier parent.

Depuis le dossier : recopie les annots. Pas de Jira. Pas de screenshot voisin.

Fin de chat — scorecard :
- ready_for_diagnosis true s'il y a des Annot, false sinon avec Trous
- Highlight /Contents présents ; chemin PDF fidèle
- pas d'OCR voisin, pas de dump ticket
- 0 Read PNG, 0 curl Jira
```

---

## LYSI-6417 — dossier = index (chat séparé)

```text
Nouveau chat. Dépôt LYSI. MCP user-local-scout ON.

Même mission LYSI-6417, mais `sources` est le DOSSIER, pas le PDF.
Scout doit indexer, pas extraire les Annot. ready_for_diagnosis: false, section Trous, re-read_allowed vers le PDF.

scout(
  mission="Commentaires jaunes du dossier pieces_jointes LYSI-6417. Extraire les Annot du PDF.",
  sources=["temp/64XX/6417/contexte/pieces_jointes"],
  use_llm=false
)

Si le dossier a bougé, passe le dossier qui contient REVIEW-Synthese-fonctionnelle-040926.pdf.

Scorecard :
- index avec le nom du PDF
- ready false ; Trous / re-read_allowed vers le fichier PDF
- pas d'OCR des PNG du dossier
```

---

## LYSI-6553 — appel 1 (ticket + écran)

Échec d’origine : « Trous : aucun » alors que Confluence, l’écran `render` et le typage `salarieId` manquaient ; ChantierController sorti pour un `use()` ; OCR roman.

```text
Nouveau chat. Dépôt LYSI. MCP user-local-scout ON, version 1.8.x.

Tu es l'orchestrateur. Scout filtre. use_llm=false. Un seul appel pour CET échange.
Ne pas diagnostiquer à la place du dossier. Ne pas curl search/jql. Ne pas Read des PNG.

Diagnostiquer LYSI-6553 (durée planifiée / compteur / jauge à 0, planning polyvalents).
Ne pas corriger. Qualifier ensuite.

Appelle exactement :

scout(
  mission="Diagnostiquer LYSI-6553 : durée planifiée, compteur ou jauge à 0 sur le planning des polyvalents. Rassembler ticket, captures, écran (contrôleur qui render), page Confluence du domaine, UUID d'URL typés. Ne pas conclure à l'absence sans Trous.",
  ticket="LYSI-6553",
  use_llm=false
)

Depuis le dossier :
- L'écran attendu est PlanificationBonsTravauxController (render planification_bt / dureePlanifiee), pas un autre contrôleur qui use() PlanificationBonsService.
- Chaque UUID d'URL : valeur | :paramètreDeRoute | entité. Si :salarieId → ce n'est pas l'id de planification.
- Captures : tableau court + « OCR bruit ». Pas de roman OCR.
- « Trous : aucun » seulement si ticket + Confluence + écran render + UUID typés.
- Mesurer encore (SQL, grep, rejeu) toi-même. Scout ne compte pas (« N journées », « 71 plannings »).

Fin de chat — scorecard :
- ## Ticket compact (type, statut, ≤ 8 lignes, UUID typés)
- écran TravauxController, pas ChantierController comme écran
- Confluence (titre+pageId+citation) OU Trous « non cherchée »
- pas ready_for_diagnosis true si un trou bloquant n'est pas dans Trous
- 0 curl Jira, 0 Read PNG
```

---

## LYSI-6553 — appel 2 (liés + JQL)

Échec d’origine : `sources` rempli → aucun JQL ; Claude a dû curl `search/jql` ; OCR CARTAUD de 6271 dans le dossier 6553.

**Chat neuf**, ne pas coller le dossier de l’appel 1.

```text
Nouveau chat, suite de LYSI-6553. Dépôt LYSI. MCP user-local-scout ON.
N'importe PAS le dossier de l'appel 1. Un seul appel scout. use_llm=false.

La mission contient FETCH des tickets liés ET une RECHERCHE d'un ticket existant
sur le même défaut. Scout doit faire le JQL même si `sources` est rempli.
Ne pas curl /rest/api/3/search/jql. Ne pas inliner l'OCR du ticket lié 6271 (CARTAUD).

Appelle exactement :

scout(
  mission="fetch LYSI-6005 LYSI-6109 LYSI-1871 LYSI-6130 LYSI-6271 et chercher un ticket existant sur le même défaut (compteur/jauge/durée planifiée à 0, planning polyvalents). ne pas conclure à l'absence sans les résultats.",
  ticket="LYSI-6553",
  sources=["jira://LYSI-6005", "jira://LYSI-6109", "jira://LYSI-1871", "jira://LYSI-6130", "jira://LYSI-6271"],
  use_llm=false
)

Le dossier DOIT contenir ## Recherche Jira (JQL, N, ≤ 5 candidats, ou « non exécutée : … »).
Trous non vide tant que Confluence et le typage salarieId/planif n'y sont pas.
LYSI-6005 : résumé + fixVersions (MEP 1.24.12) sans pièces.
CARTAUD / dump OCR 6271 : interdit.

Fin de chat — scorecard :
- ## Recherche Jira avec JQL, même si 0 candidat
- pas CARTAUD, pas « 16 additional items omitted » d'OCR lié
- UUID :salarieId + « ce n'est pas l'id de planification »
- PlanificationBonsTravauxController ; Chantier écarté ou « mention incidente »
- ## Trous non vide (pas « aucun ») si Confluence absente
- 0 curl search/jql
```

Critère d’acceptation appel 2 : section Recherche Jira (même vide, avec JQL) ; Trous non vide tant que Confluence et le typage manquent ; OCR CARTAUD de 6271 absent.
