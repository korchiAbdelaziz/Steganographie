# stego_layer.py
# -----------------------------------------------------------------------------
# Couche de stéganographie LSB (Least Significant Bit) avec redondance optionnelle.
# Indépendante de crypto_layer.py : elle ne sait pas si les octets qu'on lui donne
# sont chiffrés ou en clair, elle se contente de les cacher/extraire dans une image.
#
# Format caché dans l'image (dans cet ordre, bit à bit, dans les LSB des pixels) :
#   [ EN-TETE x3 (marqueur "STEG" + metadata + N + taille, répété 3 fois, taille fixe) ][ DONNEES x N (répétées) ]
#
# L'en-tête (10 octets) est toujours répété 3 fois, quel que soit N : c'est une protection interne fixe,
# indispensable puisque la perte de l'en-tête rend tout le message illisible, indépendamment du N choisi
# pour les données. METADATA et N sont cachés dans l'image (jamais demandés à l'utilisateur au décodage) :
# le décodage peut ainsi retrouver automatiquement le facteur de redondance utilisé à l'encodage,
# et savoir si/comment le message a été chiffré, en lisant uniquement l'image fournie.
#
# Avec N=1 : chaque octet est caché une seule fois -> comportement du LSB classique.
# Avec N>1 : chaque octet est caché N fois -> on peut voter à l'extraction pour corriger des erreurs.
# -----------------------------------------------------------------------------

import math  # utilisé pour le calcul du PSNR (logarithme base 10)
from collections import Counter  # Counter.most_common() implémente directement le "vote majoritaire"
import numpy as np  # manipulation rapide des pixels sous forme de tableaux (bien plus rapide que des boucles Python pures)
from PIL import Image  # ouverture/écriture d'images PNG

# marqueur fixe placé en tête des données cachées : sert à vérifier, au décodage, qu'on lit bien
# une image qui contient un message (et pas juste du bruit aléatoire dans les LSB)
MARQUEUR_MAGIQUE = b"STEG"  # 4 octets = 32 bits, choisi arbitrairement mais doit être identique encodage/décodage
NB_OCTETS_ENTETE_LOGIQUE = len(MARQUEUR_MAGIQUE) + 1 + 1 + 4  # marqueur(4) + metadata(1) + N(1) + taille(4) = 10 octets

# l'en-tête est minuscule (10 octets) mais absolument critique : le perdre rend tout le message illisible,
# quel que soit le facteur de redondance N choisi par l'utilisateur pour SES données. On le protège donc
# TOUJOURS avec sa propre petite redondance fixe, indépendante de N (qui ne concerne que le message).
# Sans ça, une image altérée par endroits pourrait perdre le marqueur/la taille et sembler "illisible avec
# N'IMPORTE QUEL N", ce qui fausserait complètement la comparaison N=1 vs N=2 vs N=3.
REDONDANCE_ENTETE = 3
NB_BITS_ENTETE = NB_OCTETS_ENTETE_LOGIQUE * REDONDANCE_ENTETE * 8  # décalage, en bits, avant le début des données du message


# =============================================================================
# 1) Fonction d'encodage bits <-> octets (bas niveau, testable isolément)
# =============================================================================

def octets_vers_bits(data: bytes) -> np.ndarray:
    # np.unpackbits attend un tableau uint8 ; bytes -> array uint8 est une conversion directe, sans copie de valeurs
    tableau_octets = np.frombuffer(data, dtype=np.uint8)
    # unpackbits déplie chaque octet en 8 bits, poids fort en premier (MSB first) -> ordre stable et prévisible
    return np.unpackbits(tableau_octets)


def bits_vers_octets(bits: np.ndarray) -> bytes:
    # packbits fait l'opération inverse : regroupe des paquets de 8 bits en un octet (MSB first, symétrique de unpackbits)
    tableau_octets = np.packbits(bits)
    # .tobytes() convertit le tableau numpy en un objet bytes Python standard, utilisable partout ailleurs
    return tableau_octets.tobytes()


# =============================================================================
# 2) Fonction de répétition / redondance (indépendante du LSB)
# =============================================================================

def repeter_octets(data: bytes, n: int) -> bytes:
    # chaque octet est répété N fois CONSECUTIVEMENT (choix fait dans l'énoncé), donc [65,66] avec N=3 -> [65,65,65,66,66,66]
    # np.repeat le fait nativement et efficacement sur tout le tableau en une seule opération vectorisée
    tableau_octets = np.frombuffer(data, dtype=np.uint8)
    tableau_repete = np.repeat(tableau_octets, n)
    return tableau_repete.tobytes()


# =============================================================================
# 3) Fonction de vote majoritaire (indépendante du LSB) — corrige les erreurs
# =============================================================================

def vote_majoritaire(data_repetee: bytes, n: int) -> bytes:
    resultat = bytearray()  # bytearray car on va construire le message octet par octet, plus efficace qu'une concaténation de bytes
    # on parcourt les données par paquets de taille N : chaque paquet correspond à N copies du MEME octet original
    for i in range(0, len(data_repetee), n):
        paquet = data_repetee[i:i + n]  # les N copies (potentiellement altérées) d'un même octet du message
        if len(paquet) == 0:
            continue  # sécurité : évite un Counter vide si data_repetee n'est pas un multiple exact de N
        # Counter compte les occurrences de chaque valeur d'octet dans le paquet ; most_common(1) donne la plus fréquente
        # -> c'est exactement le "vote majoritaire" demandé : si 2 copies sur 3 sont identiques, cette valeur gagne
        octet_majoritaire, _ = Counter(paquet).most_common(1)[0]
        resultat.append(octet_majoritaire)
    return bytes(resultat)


# =============================================================================
# 4) Fonction d'insertion LSB (bas niveau, testable isolément)
# =============================================================================

def inserer_bits_lsb(pixels_plats: np.ndarray, bits: np.ndarray) -> np.ndarray:
    if len(bits) > pixels_plats.size:
        # on refuse explicitement plutôt que de tronquer silencieusement le message (perte de données invisible)
        raise ValueError("Message trop long pour être caché dans cette image avec ce facteur de redondance")
    pixels_modifies = pixels_plats.copy()  # copie défensive : on ne veut jamais modifier le tableau original de l'appelant
    # on efface le bit de poids faible des N premiers pixels (masque 0xFE = 11111110) puis on y met le bit voulu (OR)
    # -> c'est la définition même du LSB : seul le bit le moins significatif change, donc l'oeil humain ne voit pas la différence
    zone_a_modifier = pixels_modifies[: len(bits)]
    pixels_modifies[: len(bits)] = (zone_a_modifier & 0xFE) | bits
    return pixels_modifies


def extraire_bits_lsb(pixels_plats: np.ndarray, nombre_bits: int) -> np.ndarray:
    # bit AND avec 1 isole exactement le bit de poids faible de chaque valeur de pixel, sans toucher au reste
    return (pixels_plats[:nombre_bits] & 1).astype(np.uint8)


# =============================================================================
# 5) Orchestration : cacher / extraire un message complet dans/depuis une image
# =============================================================================

def capacite_brute_octets(image: Image.Image) -> int:
    largeur, hauteur = image.size  # dimensions de l'image en pixels
    nb_canaux = len(image.convert("RGB").getbands())  # =3 pour du RGB (Rouge, Vert, Bleu) après normalisation
    # capacité brute = 1 bit caché par canal de couleur (1 LSB par octet de pixel), convertie en octets (/8)
    # tel que défini dans l'énoncé : "nombre de pixels utilisables / 8"
    return (largeur * hauteur * nb_canaux) // 8


def hide_message(image: Image.Image, data_bytes: bytes, n: int = 1, metadata: int = 0) -> Image.Image:
    if n < 1 or n > 255:
        raise ValueError("Le facteur de redondance N doit être entre 1 et 255")
    if not (0 <= metadata <= 255):
        raise ValueError("La métadonnée doit tenir sur un seul octet (0-255)")

    image_rgb = image.convert("RGB")  # on force RGB pour avoir un nombre de canaux fixe et prévisible (pas de canal alpha à gérer)
    tableau_image = np.array(image_rgb)  # conversion en tableau numpy (hauteur, largeur, 3) pour manipulation rapide
    forme_originale = tableau_image.shape  # on garde la forme pour pouvoir reconstruire l'image après modification
    pixels_plats = tableau_image.flatten()  # on "aplatit" en 1D : plus simple d'y insérer une séquence de bits linéaire

    # on répète les données du message avec LE facteur choisi par l'utilisateur (paramètre pédagogique de l'énoncé)
    donnees_a_cacher = repeter_octets(data_bytes, n)

    # en-tête logique = marqueur + metadata (1 octet, ex: quel algo de chiffrement) + N (1 octet) + taille du message (4 octets)
    entete_logique = MARQUEUR_MAGIQUE + bytes([metadata]) + bytes([n]) + len(data_bytes).to_bytes(4, byteorder="big")
    # protection FIXE de l'en-tête (toujours x3, indépendante du N choisi par l'utilisateur) : voir REDONDANCE_ENTETE plus haut
    entete_physique = repeter_octets(entete_logique, REDONDANCE_ENTETE)

    charge_utile = entete_physique + donnees_a_cacher  # tout ce qui doit être caché, dans l'ordre exact attendu au décodage
    bits_a_cacher = octets_vers_bits(charge_utile)  # conversion en flux de bits, unité manipulée par le LSB

    pixels_modifies = inserer_bits_lsb(pixels_plats, bits_a_cacher)  # insertion effective dans les LSB des pixels
    tableau_modifie = pixels_modifies.reshape(forme_originale)  # on redonne au tableau sa forme (hauteur, largeur, 3)
    return Image.fromarray(tableau_modifie, mode="RGB")  # reconversion en objet Image Pillow, prêt à être sauvegardé/renvoyé


def lire_entete(image: Image.Image) -> tuple[int, int, int]:
    # lit uniquement l'en-tête (pas encore les données répétées), pour permettre une "inspection" rapide d'une image
    # (ex: savoir si un message est chiffré) sans avoir à décoder tout le message
    image_rgb = image.convert("RGB")  # même normalisation qu'à l'encodage, sinon le nombre de canaux pourrait différer
    pixels_plats = np.array(image_rgb).flatten()  # même aplatissement 1D, pour lire les bits dans le même ordre qu'écrits

    # on lit toute la zone d'en-tête physique (3 copies de marqueur+metadata+N+taille) puis on vote AVANT toute interprétation :
    # ainsi une petite altération isolée sur une des 3 copies n'empêche pas de retrouver l'en-tête logique correct
    bits_entete = extraire_bits_lsb(pixels_plats, NB_BITS_ENTETE)
    octets_entete_physique = bits_vers_octets(bits_entete)
    entete_logique = vote_majoritaire(octets_entete_physique, REDONDANCE_ENTETE)  # 10 octets reconstruits par vote

    marqueur_lu = entete_logique[:4]
    if marqueur_lu != MARQUEUR_MAGIQUE:
        # échec explicite : image non stéganographiée, ou image trop corrompue même après le vote sur l'en-tête
        raise ValueError("Marqueur introuvable : aucune donnée cachée détectée (ou image trop corrompue)")

    metadata = entete_logique[4]  # 1er octet après le marqueur
    n = entete_logique[5]  # 2e octet : facteur de redondance utilisé à l'encodage pour LES DONNEES (pas l'en-tête)
    taille_message = int.from_bytes(entete_logique[6:10], byteorder="big")  # 4 octets suivants : taille du message ORIGINAL
    return metadata, n, taille_message


def extract_message(image: Image.Image) -> tuple[int, bytes]:
    metadata, n, taille_message = lire_entete(image)  # N et metadata viennent de l'image elle-même, jamais d'un paramètre

    image_rgb = image.convert("RGB")
    pixels_plats = np.array(image_rgb).flatten()

    # les données répétées commencent juste après l'en-tête complet (décalage fixe, connu des deux côtés)
    nb_bits_donnees = taille_message * n * 8  # on doit lire N copies de chaque octet, chaque octet faisant 8 bits
    bits_donnees = extraire_bits_lsb(pixels_plats[NB_BITS_ENTETE:], nb_bits_donnees)
    donnees_repetees = bits_vers_octets(bits_donnees)  # octets bruts, potentiellement corrompus, contenant les N copies

    # le vote majoritaire reconstruit le message final en corrigeant les copies minoritaires corrompues
    message = vote_majoritaire(donnees_repetees, n)
    return metadata, message


# =============================================================================
# 6) Qualité de l'image : PSNR (Peak Signal-to-Noise Ratio)
# =============================================================================

def calculer_psnr(image_originale: Image.Image, image_modifiee: Image.Image) -> float:
    a = np.array(image_originale.convert("RGB"), dtype=np.float64)  # float64 pour éviter tout dépassement/arrondi entier lors du calcul
    b = np.array(image_modifiee.convert("RGB"), dtype=np.float64)
    mse = float(np.mean((a - b) ** 2))  # erreur quadratique moyenne entre les deux images, pixel par pixel, canal par canal
    if mse == 0:
        # deux images strictement identiques -> PSNR mathématiquement infini (aucune dégradation mesurable)
        return float("inf")
    valeur_max_pixel = 255.0  # valeur maximale possible d'un canal de couleur codé sur 8 bits
    # formule standard du PSNR : plus la valeur est haute, moins l'image a été dégradée visuellement
    return 20 * math.log10(valeur_max_pixel) - 10 * math.log10(mse)
