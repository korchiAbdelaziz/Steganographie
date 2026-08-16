# Stéganographie LSB + Redondance + Chiffrement optionnel

Cache un message texte dans une image PNG en modifiant le bit de poids faible (LSB) de
chaque octet de couleur, avec un mécanisme optionnel de **redondance** (chaque octet du
message est répété N fois, puis reconstruit à l'extraction par **vote majoritaire**) et un
chiffrement optionnel (**AES** ou **RSA**) appliqué avant la dissimulation.

L'interface est un **parcours mobile en étapes** (un écran à la fois, dans le style de la
maquette fournie) : on ne voit jamais un champ qui ne sert à rien à ce stade-là (pas d'étape
"redondance" au décodage, pas d'étape "clé" si le message n'est pas chiffré, etc.) — tout est
retrouvé automatiquement en lisant l'image.

## Architecture

Trois couches indépendantes, chacune activable/désactivable séparément :

| Fichier | Rôle |
|---|---|
| [`crypto_layer.py`](crypto_layer.py) | Chiffre/déchiffre le message (`none`, `AES`, `RSA`), avant/après la couche stéga |
| [`stego_layer.py`](stego_layer.py) | Cache/extrait les octets dans les LSB de l'image, avec redondance + vote majoritaire |
| [`main.py`](main.py) | Orchestrateur (`encode`/`decode`/`inspecter`/`executer_comparaison`) + API FastAPI |
| `static/` | Interface web mobile (HTML/CSS/JS vanilla, sans framework) |
| `.env` | Valeurs par défaut (N proposés, taille des clés RSA, % de corruption du test...) |

`stego_layer.py` sépare volontairement chaque étape en fonction indépendante et testable
seule : `octets_vers_bits` / `bits_vers_octets` (conversion bits↔octets), `repeter_octets`
(redondance), `inserer_bits_lsb` / `extraire_bits_lsb` (insertion/lecture LSB),
`vote_majoritaire` (reconstruction via `Counter.most_common`).

### Format caché dans l'image

```
[ EN-TETE x3 (marqueur "STEG" + algo + N + taille du message, répété 3 fois) ][ DONNEES x N ]
```

L'en-tête (10 octets : marqueur, algo de chiffrement utilisé, facteur N, taille du message) est
**toujours** répété 3 fois, indépendamment du N choisi pour le message : c'est une protection
fixe, nécessaire car perdre l'en-tête rend tout illisible quel que soit le N des données. Grâce à
ça, le décodage n'a besoin **que de l'image** : N et l'algorithme de chiffrement sont retrouvés
automatiquement (voir `/decode/inspecter` plus bas), l'utilisateur n'a jamais à les ressaisir.

## Installation

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Une image PNG de test peut être générée avec :

```bash
.venv\Scripts\python generate_test_image.py
```

(Le PNG est obligatoire : un format avec perte comme le JPEG détruirait les bits de poids
faible utilisés par le LSB.)

## Configuration (`.env`)

Toutes les valeurs par défaut viennent de `.env` (avec un repli codé dans `main.py` si absent) :

| Variable | Rôle | Défaut |
|---|---|---|
| `REDONDANCE_PAR_DEFAUT` | N pré-rempli dans le champ libre de l'étape "redondance" | `1` |
| `RSA_TAILLE_CLE_BITS` | Taille des clés RSA générées automatiquement | `2048` |
| `COMPARER_CORRUPTION_POURCENTAGE` | % de pixels altérés par le bouton "Comparer" | `5` |
| `COMPARER_FACTEURS_N` | Facteurs de N testés par "Comparer" | `1,2,3` |
| `COMPARER_NB_ESSAIS` | Nombre de tirages de corruption moyennés par "Comparer" | `15` |

L'utilisateur peut saisir **n'importe quel entier ≥ 1** pour N à l'encodage (pas de liste figée) : la
seule limite est celle du format de fichier lui-même (255, car N est stocké sur 1 octet dans l'en-tête
caché), exposée par `/config` comme `redondance_maximum` — ce n'est pas un réglage, donc elle ne vit
pas dans `.env`.

## Lancement du serveur

```bash
.venv\Scripts\uvicorn main:app --reload
```

Puis ouvrir [http://127.0.0.1:8000](http://127.0.0.1:8000).

> En développement, les fichiers `static/` sont servis avec `Cache-Control: no-store` pour
> éviter qu'un navigateur garde en cache une ancienne version du JS/CSS pendant que le code
> change. Si un écran se comporte bizarrement après une modification, un rechargement forcé
> (Ctrl+Shift+R) suffit normalement à écarter ce genre de souci.

## Parcours de l'interface

**Encoder** : Accueil → Message → Chiffrement (oui/non) → *si oui* Algorithme + clé → Image →
Redondance (N) → Résultat (image à télécharger, clé générée à conserver si applicable, bouton
"Comparer").

**Décoder** : Accueil → Image (analysée automatiquement dès la sélection) → *si le message est
chiffré* Clé secrète (le libellé s'adapte à AES/RSA détecté) → Résultat (message + bouton
"Comparer"). Aucune étape "redondance" ni "quel algorithme" au décodage : tout est lu dans l'image.

**Comparer** (accessible depuis les deux écrans de résultat) : réutilise l'image et le message déjà
en main, teste chaque N de `COMPARER_FACTEURS_N` avec une corruption simulée
(`COMPARER_CORRUPTION_POURCENTAGE`), affiche capacité utile / PSNR / robustesse pour chacun. La
corruption ne touche que les pixels qui portent réellement les données du message (jamais
l'en-tête, protégé séparément — voir plus haut) : sur une grande image avec un message court, viser
toute l'image aurait presque toujours épargné le message et affiché 100% de robustesse pour tous les
N, ce qui n'aurait rien démontré. Chaque ligne moyenne aussi `COMPARER_NB_ESSAIS` tirages de
corruption indépendants (au lieu d'un seul), pour un résultat stable plutôt que dépendant du hasard
d'un seul tirage.

## Endpoints de l'API

| Endpoint | Méthode | Description |
|---|---|---|
| `/` | GET | Sert l'interface web (`static/index.html`) |
| `/config` | GET | Valeurs par défaut/limites (`redondance_par_defaut` depuis `.env`, `redondance_maximum` = limite technique du format) |
| `/encode` | POST | Cache un message. Champs (multipart) : `image`, `message`, `use_encryption`, `algo` (`none`/`AES`/`RSA`), `key` (vide = génération automatique), `n`. Retourne `{ image_base64, aes_passphrase? , rsa_private_key_pem? }` |
| `/decode/inspecter` | POST | Lit uniquement l'en-tête caché d'une image (`image`). Retourne `{ chiffre, algo }`, sans déchiffrer — sert à décider si l'étape "clé" doit s'afficher |
| `/decode` | POST | Extrait le message. Champs : `image`, `key` (nécessaire seulement si le message est chiffré — N et algo sont retrouvés automatiquement). Retourne `{ message }` |
| `/compare` | POST | Compare les N de `COMPARER_FACTEURS_N` sur une image/message donnés. Champs : `image`, `message`, `corruption_pourcentage` (optionnel, sinon valeur de `.env`). Retourne `{ resultats: [...], conclusion }` |

Toute erreur renvoie un statut HTTP 400 avec un message pensé pour être compréhensible tel quel
(ex: "Clé incorrecte : impossible de déchiffrer ce message avec la clé fournie" plutôt que
l'erreur technique brute remontée par la bibliothèque de chiffrement).

## Tableau comparatif : LSB classique (N=1) vs LSB + redondance (N=2, N=3)

Résultat obtenu avec `compare.py` sur `test_image.png` (300×200, généré par
`generate_test_image.py`), message de test de 91 caractères, et **5% des valeurs de pixels
corrompues aléatoirement** (un bit inversé au hasard parmi les 8 de chaque valeur corrompue) :

| N | Capacité brute (octets) | Capacité utile (octets) | PSNR (dB) | Corruption testée (%) | Robustesse (%) |
|---|---|---|---|---|---|
| 1 | 22500 | 22500 | 74.30 | 5.0 | 95.29 |
| 2 | 22500 | 11250 | 71.69 | 5.0 | 94.71 |
| 3 | 22500 | 7500  | 70.10 | 5.0 | 99.56 |

- **Capacité brute** = nombre de pixels utilisables (×3 canaux RGB) ÷ 8 : c'est une propriété
  de l'image seule, indépendante de N.
- **Capacité utile** = capacité brute ÷ N : c'est ce qu'on peut réellement cacher comme message
  une fois la redondance appliquée.
- **PSNR** diminue légèrement quand N augmente : plus de bits sont modifiés dans l'image (les
  répétitions), donc une dégradation visuelle un peu plus importante — mais elle reste très
  élevée dans tous les cas (>70 dB, largement imperceptible à l'œil).
- **Robustesse** = pourcentage d'octets du message correctement récupérés après corruption
  aléatoire de 5% des pixels qui portent les données (moyenné sur `COMPARER_NB_ESSAIS` tirages).
  L'en-tête (marqueur, taille...) est protégé séparément par sa propre redondance fixe x3 — voir
  "Format caché dans l'image" plus haut — sans quoi une seule altération malchanceuse du marqueur
  ferait chuter la robustesse à 0% pour tous les N en même temps, quel que soit celui testé.

**N=2 n'apporte quasiment aucun gain par rapport à N=1** dans ce tableau, alors que N=3 apporte un
gain net : ce n'est pas un hasard, c'est une propriété mathématique du vote majoritaire. Avec 2
copies d'un octet, si une seule des deux est corrompue, le vote est à égalité (1 voix pour la bonne
valeur, 1 voix pour la mauvaise) — il n'y a aucun moyen fiable de savoir laquelle est correcte, et
`Counter.most_common` retient arbitrairement la première rencontrée. Avec 3 copies (ou tout N
impair), une seule copie corrompue laisse toujours une majorité claire (2 contre 1) : c'est
seulement à partir de là que la redondance corrige vraiment les erreurs de façon fiable.

**Conclusion** : plus on augmente la redondance, plus le message caché résiste aux altérations de
l'image, mais moins on peut cacher de données utiles — c'est un compromis capacité/robustesse. Le
LSB classique (N=1) maximise la capacité mais n'offre aucune tolérance aux erreurs ; un N pair
(ex: N=2) coûte de la capacité sans apporter de gain fiable ; un N impair ≥3 est nécessaire pour
que le vote majoritaire corrige vraiment les erreurs, au prix d'une capacité utile réduite d'autant
et d'un PSNR légèrement plus bas.

Pour régénérer ce tableau (par exemple avec une autre image ou un autre message) :

```bash
.venv\Scripts\python compare.py
```
