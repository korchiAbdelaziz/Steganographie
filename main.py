# main.py
# -----------------------------------------------------------------------------
# Orchestrateur + API FastAPI.
# Ce fichier NE contient aucune logique de chiffrement ni de LSB : il se contente
# d'appeler crypto_layer.py et stego_layer.py dans le bon ordre, et d'exposer
# le tout via des endpoints HTTP consommés par l'interface web (static/).
#
# Tous les paramètres réglables (facteurs de redondance proposés, taille des clés
# RSA, pourcentage de corruption du test de robustesse...) viennent du fichier
# .env (via python-dotenv), avec une valeur par défaut si la variable est absente :
# rien de tout ça n'est codé en dur dans l'interface mobile.
# -----------------------------------------------------------------------------

import base64  # nécessaire pour transporter une image binaire (PNG) à l'intérieur d'une réponse JSON en texte
import io  # permet de lire/écrire une image en mémoire, sans passer par un fichier temporaire sur disque
import os  # lecture des variables d'environnement (chargées depuis .env par load_dotenv)

import numpy as np  # utilisé ici uniquement pour la simulation de corruption aléatoire (endpoint /compare)
from dotenv import load_dotenv  # charge le fichier .env dans les variables d'environnement du process
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

import crypto_layer  # couche de chiffrement, appelée AVANT de cacher (encode) ou APRES d'extraire (decode)
import stego_layer  # couche de stéganographie LSB + redondance

load_dotenv()  # doit être appelé avant toute lecture de os.getenv(...) ci-dessous, pour que .env soit pris en compte


def _lire_liste_entiers(nom_variable: str, valeur_par_defaut: str) -> list[int]:
    # variables comme "1,2,3" dans le .env -> liste [1, 2, 3] ; centralisé ici pour ne pas dupliquer le parsing
    valeur_brute = os.getenv(nom_variable, valeur_par_defaut)
    return [int(morceau.strip()) for morceau in valeur_brute.split(",") if morceau.strip()]


# =============================================================================
# Configuration (issue de .env, avec valeur de repli si la variable est absente)
# =============================================================================

REDONDANCE_PAR_DEFAUT = int(os.getenv("REDONDANCE_PAR_DEFAUT", "1"))  # N pré-rempli dans le champ libre de l'interface
# N n'est PAS plafonné par choix de design (l'utilisateur saisit n'importe quelle valeur) : la seule limite est celle
# du format de fichier (N stocké sur 1 octet dans l'en-tête caché, voir stego_layer.py) -> c'est une contrainte
# technique, pas un réglage, donc elle n'a pas sa place dans .env
N_MAXIMUM_TECHNIQUE = 255
RSA_TAILLE_CLE_BITS = int(os.getenv("RSA_TAILLE_CLE_BITS", "2048"))  # taille des clés RSA auto-générées
COMPARER_CORRUPTION_POURCENTAGE = float(os.getenv("COMPARER_CORRUPTION_POURCENTAGE", "5"))  # % par défaut pour /compare
COMPARER_FACTEURS_N = _lire_liste_entiers("COMPARER_FACTEURS_N", "1,2,3")  # valeurs de N testées par /compare
# un seul tirage aléatoire de corruption serait bruité (la chance du tirage peut faire paraître N=2 pire que N=1,
# alors qu'en moyenne N=2 est bien plus robuste) -> on moyenne la robustesse sur plusieurs essais indépendants
COMPARER_NB_ESSAIS = int(os.getenv("COMPARER_NB_ESSAIS", "15"))

# correspondance entre le nom de l'algorithme et l'octet de metadata caché dans l'image (voir stego_layer.py)
# "none" = 0 permet de reconnaître un message non chiffré sans avoir besoin d'un bit à part
ALGO_VERS_ID = {"none": 0, "AES": 1, "RSA": 2}
ID_VERS_ALGO = {identifiant: nom for nom, identifiant in ALGO_VERS_ID.items()}  # sens inverse, pour le décodage

app = FastAPI(title="API Stéganographie LSB + Redondance")  # instance unique de l'application, point d'entrée d'Uvicorn

# on sert les fichiers statiques (CSS/JS) sous /static, pour ne PAS entrer en conflit avec les routes /encode, /decode, /compare
# définies plus bas (un mount à la racine "/" intercepterait toutes les requêtes, y compris celles de l'API)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def desactiver_cache_statique(request, call_next):
    # en développement, un navigateur qui garde en cache une ancienne version de script.js/style.css (alors que le fichier
    # a changé côté serveur) provoque des bugs fantômes très déroutants (ex: un id référencé qui n'existe plus dans le HTML
    # actuel). On interdit donc toute mise en cache du HTML/CSS/JS servis, pour que chaque rechargement soit toujours à jour.
    reponse = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        reponse.headers["Cache-Control"] = "no-store"
    return reponse


@app.get("/")
def servir_page_accueil():
    # renvoie la page HTML de l'interface de test ; c'est la seule route "racine", tout le reste de l'UI est en /static
    return FileResponse("static/index.html")


@app.get("/config")
def endpoint_config():
    # expose au frontend les valeurs par défaut définies côté serveur (.env), pour que rien ne soit codé en dur en JS
    return JSONResponse({
        "redondance_par_defaut": REDONDANCE_PAR_DEFAUT,
        "redondance_maximum": N_MAXIMUM_TECHNIQUE,
    })


# =============================================================================
# Fonctions d'orchestration (réutilisables indépendamment de FastAPI, ex: tests, scripts)
# =============================================================================

def encode(
    image: Image.Image,
    message: str,
    use_encryption: bool = False,
    algo: str = "none",
    key: str = "",
    n: int = 1,
) -> tuple[Image.Image, dict]:
    message_bytes = message.encode("utf-8")  # on travaille en octets à partir d'ici, car crypto/stego ne connaissent que des bytes

    if use_encryption:
        # la couche crypto est activable/désactivable indépendamment de la couche stéga (exigence de l'énoncé)
        donnees_a_cacher, extra = crypto_layer.encrypt_message(message_bytes, algo, key, RSA_TAILLE_CLE_BITS)
        algo_utilise = algo
    else:
        donnees_a_cacher, extra = message_bytes, {}
        algo_utilise = "none"

    # l'algo utilisé est caché DANS l'image (1 octet de metadata) : le décodage n'aura donc jamais besoin qu'on le lui redise
    metadata = ALGO_VERS_ID[algo_utilise]
    image_resultat = stego_layer.hide_message(image, donnees_a_cacher, n, metadata)
    return image_resultat, extra


def inspecter(image: Image.Image) -> dict:
    # lecture rapide de l'en-tête caché, SANS déchiffrer ni voter sur tout le message : sert uniquement à savoir,
    # avant de demander quoi que ce soit à l'utilisateur, si une clé de déchiffrement sera nécessaire
    metadata, _n, _taille = stego_layer.lire_entete(image)
    algo = ID_VERS_ALGO.get(metadata)
    if algo is None:
        # octet de metadata non reconnu -> l'image ne provient probablement pas de cette application
        raise ValueError("Métadonnée illisible : cette image ne semble pas provenir de cette application")
    return {"chiffre": algo != "none", "algo": None if algo == "none" else algo}


def decode(image: Image.Image, key: str = "") -> str:
    # N et l'algorithme utilisés sont retrouvés automatiquement depuis l'image : l'appelant n'a plus qu'à
    # fournir, éventuellement, la clé de déchiffrement (si l'inspection préalable a indiqué que c'est nécessaire)
    metadata, donnees_extraites = stego_layer.extract_message(image)
    algo = ID_VERS_ALGO.get(metadata)
    if algo is None:
        raise ValueError("Métadonnée illisible : cette image ne semble pas provenir de cette application")

    if algo == "none":
        message_bytes = donnees_extraites
    else:
        if not key:
            # on ne devine jamais silencieusement : si la clé manque, on le dit clairement plutôt que d'échouer plus loin
            raise ValueError(f"Une clé est nécessaire pour déchiffrer ce message (algorithme détecté : {algo})")
        try:
            message_bytes = crypto_layer.decrypt_message(donnees_extraites, algo, key)
        except Exception:
            # pycryptodome lève des erreurs très techniques ("MAC check failed", "Incorrect decryption"...) :
            # jamais montrées telles quelles à l'utilisateur, on les remplace par un message qu'il peut comprendre et corriger
            raise ValueError("Clé incorrecte : impossible de déchiffrer ce message avec la clé fournie")

    # errors="replace" évite un crash si le déchiffrement a réussi mais que le résultat n'est pas de l'UTF-8 valide
    return message_bytes.decode("utf-8", errors="replace")


def corrompre_image(
    image: Image.Image,
    pourcentage: float,
    graine: int = 42,
    decalage_bits: int = 0,
    longueur_bits: int | None = None,
) -> Image.Image:
    tableau = np.array(image.convert("RGB"))  # on repart d'un tableau RGB propre pour manipuler des valeurs de canal individuelles
    forme_originale = tableau.shape
    pixels_plats = tableau.flatten().copy()  # copie car on va modifier ce tableau en place, sans toucher à l'image d'origine

    # [decalage_bits, decalage_bits + longueur_bits) cible PRÉCISÉMENT les pixels qui portent les données du message
    # (donc APRÈS l'en-tête, qui a sa propre protection fixe et n'est pas ce qu'on cherche à comparer ici). Sans ça, deux
    # problèmes : (1) sur une grande image, le message n'occupe qu'une infime partie -> corrompre 5% de TOUTE l'image
    # touche presque toujours du "vide" ; (2) même en ciblant la zone utile, l'en-tête (toujours protégé x3) y prend une
    # place fixe qui dilue l'effet sur les données -> robustesse artificiellement haute pour tous les N. On corrompt donc
    # 5% des pixels QUI PORTENT VRAIMENT LES DONNÉES DU MESSAGE, la seule zone où le N choisi fait une différence.
    longueur = longueur_bits if longueur_bits is not None else (pixels_plats.size - decalage_bits)
    longueur = max(0, min(longueur, pixels_plats.size - decalage_bits))

    # graine fixe -> corruption reproductible d'un run à l'autre, indispensable pour comparer équitablement les différents N
    generateur = np.random.default_rng(graine)
    nb_valeurs_a_corrompre = int(longueur * pourcentage / 100)  # ex: 5% des pixels qui portent les données du message
    indices_zone = generateur.choice(longueur, size=nb_valeurs_a_corrompre, replace=False)  # positions dans la zone, sans doublon
    indices_corrompus = indices_zone + decalage_bits  # décalés vers la zone réelle dans le tableau de pixels complet
    bits_a_inverser = generateur.integers(0, 8, size=nb_valeurs_a_corrompre)  # pour chaque position, quel bit (0=LSB..7=MSB) on inverse
    masques_xor = (1 << bits_a_inverser).astype(np.uint8)  # masque à un seul bit à 1, pour inverser exactement ce bit via XOR

    # XOR avec un masque à un seul bit inverse précisément ce bit-là, en laissant les 7 autres intacts -> simule une altération réaliste
    pixels_plats[indices_corrompus] = pixels_plats[indices_corrompus] ^ masques_xor

    tableau_corrompu = pixels_plats.reshape(forme_originale)
    return Image.fromarray(tableau_corrompu, mode="RGB")


def pourcentage_octets_corrects(original: bytes, recupere: bytes) -> float:
    if len(original) == 0:
        return 100.0  # rien à comparer -> on considère qu'il n'y a pas d'échec possible
    longueur_comparaison = min(len(original), len(recupere))  # on ne compare que ce qui a pu être récupéré, sans planter sur une taille différente
    nb_octets_corrects = sum(1 for i in range(longueur_comparaison) if original[i] == recupere[i])
    # on divise par la longueur ORIGINALE (pas la longueur comparée) pour pénaliser un message tronqué, pas seulement altéré
    return round(100 * nb_octets_corrects / len(original), 2)


def executer_comparaison(image: Image.Image, message: str, pourcentage_corruption: float) -> dict:
    message_bytes = message.encode("utf-8")
    capacite_brute = stego_layer.capacite_brute_octets(image)  # propriété de l'image seule, indépendante de N
    lignes_tableau = []

    for n in COMPARER_FACTEURS_N:  # les configurations à comparer, définies par .env (par défaut : LSB classique puis x2, x3)
        try:
            image_stego = stego_layer.hide_message(image, message_bytes, n)  # metadata=0 ("none") : la comparaison ne chiffre pas
        except ValueError as erreur:
            # message trop long pour ce facteur de redondance sur cette image -> on le signale au lieu de planter toute la comparaison
            lignes_tableau.append({"n": n, "erreur": str(erreur)})
            continue

        capacite_utile = capacite_brute // n  # moins de données utiles disponibles quand N augmente (compromis capacité/robustesse)
        psnr = stego_layer.calculer_psnr(image, image_stego)  # dégradation visuelle introduite par l'insertion des données

        # on ne corrompt QUE les bits qui portent les données du message (donc APRÈS l'en-tête, protégé séparément) :
        # c'est la seule zone où le facteur N testé fait une différence, voir le commentaire dans corrompre_image
        nb_bits_donnees = len(message_bytes) * n * 8

        # un seul tirage aléatoire serait bruité (la chance du tirage peut faire paraître un N plus élevé pire qu'un
        # N plus faible, alors qu'EN MOYENNE il est plus robuste) -> on répète l'expérience COMPARER_NB_ESSAIS fois,
        # avec une graine différente à chaque fois, et on moyenne : le résultat devient stable et reproductible
        robustesses_par_essai = []
        message_recupere_exemple = ""
        for essai in range(COMPARER_NB_ESSAIS):
            image_corrompue = corrompre_image(
                image_stego, pourcentage_corruption, graine=essai,
                decalage_bits=stego_layer.NB_BITS_ENTETE, longueur_bits=nb_bits_donnees,
            )
            try:
                _metadata, message_recupere_bytes = stego_layer.extract_message(image_corrompue)
            except ValueError:
                # le marqueur lui-même a été détruit par la corruption -> extraction impossible, robustesse nulle pour cet essai
                message_recupere_bytes = b""
            robustesses_par_essai.append(pourcentage_octets_corrects(message_bytes, message_recupere_bytes))
            if essai == 0:
                # on garde le résultat du tout premier essai comme exemple concret à afficher (texte potentiellement altéré)
                message_recupere_exemple = message_recupere_bytes.decode("utf-8", errors="replace")

        lignes_tableau.append({
            "n": n,
            "capacite_brute_octets": capacite_brute,
            "capacite_utile_octets": capacite_utile,
            "psnr_db": round(psnr, 2) if psnr != float("inf") else None,
            "corruption_testee_pourcentage": pourcentage_corruption,
            "message_recupere_apres_corruption": message_recupere_exemple,
            "robustesse_pourcentage": round(sum(robustesses_par_essai) / len(robustesses_par_essai), 2),
        })

    conclusion = (
        "Plus on augmente la redondance (N), plus le message caché résiste aux altérations de "
        "l'image, mais moins on peut cacher de données utiles : c'est un compromis capacité/robustesse."
    )
    return {"resultats": lignes_tableau, "conclusion": conclusion}


# =============================================================================
# Endpoints FastAPI (consommés par l'interface web dans static/script.js)
# =============================================================================

@app.post("/encode")
async def endpoint_encode(
    image: UploadFile = File(...),  # fichier image PNG envoyé en multipart/form-data
    message: str = Form(...),  # texte à cacher, saisi dans le formulaire web
    use_encryption: bool = Form(False),  # active/désactive la couche crypto_layer indépendamment
    algo: str = Form("none"),  # "none" | "AES" | "RSA"
    key: str = Form(""),  # phrase de passe (AES) ou clé publique PEM (RSA) ; vide = génération automatique
    n: int = Form(1),  # facteur de redondance ; N=1 = LSB classique
):
    try:
        contenu_image = await image.read()  # lecture asynchrone du flux uploadé, nécessaire avec UploadFile
        image_pil = Image.open(io.BytesIO(contenu_image))  # on ouvre l'image depuis la mémoire, sans écrire de fichier temporaire
        image_resultat, extra = encode(image_pil, message, use_encryption, algo, key, n)

        tampon_sortie = io.BytesIO()
        image_resultat.save(tampon_sortie, format="PNG")  # PNG obligatoire : un format avec perte (JPEG) détruirait les LSB
        image_base64 = base64.b64encode(tampon_sortie.getvalue()).decode("ascii")  # encodage texte pour l'insérer dans du JSON

        return JSONResponse({"image_base64": image_base64, **extra})
    except ValueError as erreur:
        # erreurs "attendues" (message trop long, algo inconnu, etc.) -> 400, pas une erreur serveur
        raise HTTPException(status_code=400, detail=str(erreur))


@app.post("/decode/inspecter")
async def endpoint_decode_inspecter(image: UploadFile = File(...)):
    # étape préalable au décodage : indique au parcours mobile s'il doit afficher l'écran "clé secrète" ou le sauter
    try:
        contenu_image = await image.read()
        image_pil = Image.open(io.BytesIO(contenu_image))
        return JSONResponse(inspecter(image_pil))
    except ValueError as erreur:
        raise HTTPException(status_code=400, detail=str(erreur))


@app.post("/decode")
async def endpoint_decode(
    image: UploadFile = File(...),
    key: str = Form(""),  # phrase de passe (AES) ou clé privée PEM (RSA) ; nécessaire seulement si le message est chiffré
):
    try:
        contenu_image = await image.read()
        image_pil = Image.open(io.BytesIO(contenu_image))
        message = decode(image_pil, key)
        return JSONResponse({"message": message})
    except ValueError as erreur:
        # inclut : marqueur introuvable, clé manquante/incorrecte, image trop corrompue, etc.
        raise HTTPException(status_code=400, detail=str(erreur))


@app.post("/compare")
async def endpoint_compare(
    image: UploadFile = File(...),
    message: str = Form(...),
    corruption_pourcentage: float = Form(None),  # si absent, on retombe sur la valeur par défaut définie dans .env
):
    try:
        contenu_image = await image.read()
        image_pil = Image.open(io.BytesIO(contenu_image))
        pourcentage = COMPARER_CORRUPTION_POURCENTAGE if corruption_pourcentage is None else corruption_pourcentage
        resultat = executer_comparaison(image_pil, message, pourcentage)
        return JSONResponse(resultat)
    except ValueError as erreur:
        raise HTTPException(status_code=400, detail=str(erreur))
