# crypto_layer.py
# -----------------------------------------------------------------------------
# Couche de chiffrement, totalement INDEPENDANTE de la couche stéganographique.
# Le but : transformer le message en clair en octets chiffrés (ou le laisser
# tel quel si algo="none"), AVANT que stego_layer.py ne le cache dans l'image.
# Chaque algorithme (AES, RSA) vit dans sa propre fonction privée, pour qu'on
# puisse l'activer/la désactiver ou la tester séparément sans toucher au reste.
# -----------------------------------------------------------------------------

import hashlib  # sert à dériver une clé AES de taille fixe (32 octets) à partir d'une simple phrase de passe texte
import secrets  # génère des valeurs aléatoires cryptographiquement sûres, pour l'auto-génération de phrase de passe AES
from Crypto.Cipher import AES, PKCS1_OAEP  # AES = chiffrement symétrique ; PKCS1_OAEP = schéma de chiffrement asymétrique sûr pour RSA
from Crypto.PublicKey import RSA  # sert à générer / charger des paires de clés RSA (publique + privée)


# =============================================================================
# AES (chiffrement symétrique : une seule clé, dérivée d'une phrase de passe)
# =============================================================================

def generer_phrase_passe_aes() -> str:
    # token_urlsafe génère une chaîne aléatoire lisible (lettres/chiffres/-/_), facile à copier-coller dans l'interface,
    # utilisée quand l'utilisateur choisit "génération automatique" plutôt que de saisir sa propre phrase de passe
    return secrets.token_urlsafe(16)


def _derive_aes_key_from_passphrase(passphrase: str) -> bytes:
    # AES a besoin d'une clé de taille fixe (16/24/32 octets) et pas d'un texte libre
    # -> on hache la phrase de passe avec SHA-256 pour obtenir exactement 32 octets (AES-256)
    return hashlib.sha256(passphrase.encode("utf-8")).digest()


def _encrypt_aes(message: bytes, passphrase: str) -> bytes:
    # on dérive la clé une seule fois, ici, pour ne pas dupliquer la logique de dérivation ailleurs
    cle = _derive_aes_key_from_passphrase(passphrase)
    # mode EAX = chiffrement authentifié : il génère un "tag" qui permet de détecter toute altération au déchiffrement
    chiffreur = AES.new(cle, AES.MODE_EAX)
    # chiffreur.encrypt_and_digest renvoie à la fois le texte chiffré et le tag d'intégrité, en un seul appel
    texte_chiffre, tag = chiffreur.encrypt_and_digest(message)
    # on doit conserver le nonce (aléatoire, généré par AES.new) car il est indispensable au déchiffrement
    # -> on le préfixe au résultat : [nonce(16) | tag(16) | texte_chiffre] pour tout transporter dans un seul bloc d'octets
    return chiffreur.nonce + tag + texte_chiffre


def _decrypt_aes(data: bytes, passphrase: str) -> bytes:
    # on doit re-dériver exactement la même clé à partir de la même phrase de passe pour pouvoir déchiffrer
    cle = _derive_aes_key_from_passphrase(passphrase)
    # on retrouve le nonce sur les 16 premiers octets, car c'est l'ordre choisi lors du chiffrement (_encrypt_aes)
    nonce = data[:16]
    # le tag d'intégrité occupe les 16 octets suivants, toujours selon le même format d'encodage
    tag = data[16:32]
    # le reste des octets est le véritable texte chiffré
    texte_chiffre = data[32:]
    # on recrée un objet AES avec le MEME nonce, sinon le déchiffrement donnerait un résultat incohérent
    dechiffreur = AES.new(cle, AES.MODE_EAX, nonce=nonce)
    # decrypt_and_verify lève une exception si le tag ne correspond pas -> détecte un message corrompu ou une mauvaise clé
    return dechiffreur.decrypt_and_verify(texte_chiffre, tag)


# =============================================================================
# RSA (chiffrement asymétrique : clé publique pour chiffrer, clé privée pour déchiffrer)
# =============================================================================

def generer_paire_cles_rsa(taille_bits: int = 2048) -> tuple[str, str]:
    # taille_bits configurable (via .env côté appelant) : 2048 = bon compromis sécurité/performance par défaut pour une démo
    cle = RSA.generate(taille_bits)
    # on exporte la clé privée en PEM (texte) pour pouvoir la transmettre/afficher facilement côté interface web
    cle_privee_pem = cle.export_key().decode("utf-8")
    # idem pour la clé publique, qui seule est nécessaire pour chiffrer
    cle_publique_pem = cle.publickey().export_key().decode("utf-8")
    # on renvoie les deux : la publique sert à chiffrer tout de suite, la privée doit être conservée par l'utilisateur pour décoder plus tard
    return cle_publique_pem, cle_privee_pem


def _encrypt_rsa(message: bytes, cle_publique_pem: str) -> bytes:
    # RSA ne chiffre pas de gros volumes de données directement (limite ~190 octets pour une clé 2048 bits + OAEP)
    # -> c'est acceptable ici car on chiffre un message texte court destiné à être caché dans une image
    cle_publique = RSA.import_key(cle_publique_pem)
    # OAEP est le schéma recommandé (contrairement à PKCS1 v1.5, il est résistant aux attaques par padding)
    chiffreur = PKCS1_OAEP.new(cle_publique)
    # chiffrement direct : pas besoin de nonce/IV séparé, tout est géré en interne par OAEP
    return chiffreur.encrypt(message)


def _decrypt_rsa(data: bytes, cle_privee_pem: str) -> bytes:
    # seule la clé privée correspondant à la clé publique utilisée au chiffrement peut déchiffrer
    cle_privee = RSA.import_key(cle_privee_pem)
    # on doit utiliser le même schéma OAEP qu'au chiffrement, sinon le déchiffrement échoue
    dechiffreur = PKCS1_OAEP.new(cle_privee)
    return dechiffreur.decrypt(data)


# =============================================================================
# Fonctions publiques génériques : point d'entrée unique utilisé par main.py
# =============================================================================

def encrypt_message(message: bytes, algo: str, key: str = "", rsa_taille_bits: int = 2048) -> tuple[bytes, dict]:
    # dict "extra" : sert à faire remonter des informations générées pendant le chiffrement
    # (ex : la phrase de passe AES ou la clé privée RSA nouvellement créées) sans polluer la signature de la fonction
    extra: dict = {}

    if algo == "none":
        # pas de chiffrement demandé -> on renvoie le message tel quel, la couche stéganographique le cachera en clair
        return message, extra

    if algo == "AES":
        if key:
            # l'utilisateur a fourni sa propre phrase de passe -> on l'utilise telle quelle
            phrase_de_passe = key
        else:
            # aucune clé fournie -> on en génère une nouvelle (mode "automatique"), et on la renvoie dans "extra"
            # pour que l'interface puisse l'afficher à l'utilisateur, qui devra la ressaisir pour déchiffrer plus tard
            phrase_de_passe = generer_phrase_passe_aes()
            extra["aes_passphrase"] = phrase_de_passe
        return _encrypt_aes(message, phrase_de_passe), extra

    if algo == "RSA":
        if key:
            # l'utilisateur a fourni sa propre clé publique PEM -> on l'utilise telle quelle
            cle_publique_pem = key
        else:
            # aucune clé fournie -> on en génère une nouvelle pour la démo, et on renvoie la clé privée
            # dans "extra" pour que l'utilisateur puisse la récupérer et décoder le message plus tard
            cle_publique_pem, cle_privee_pem = generer_paire_cles_rsa(rsa_taille_bits)
            extra["rsa_private_key_pem"] = cle_privee_pem
            extra["rsa_public_key_pem"] = cle_publique_pem
        return _encrypt_rsa(message, cle_publique_pem), extra

    # algo inconnu -> on préfère échouer explicitement plutôt que de cacher un message mal traité
    raise ValueError(f"Algorithme de chiffrement inconnu : {algo}")


def decrypt_message(data: bytes, algo: str, key: str = "") -> bytes:
    if algo == "none":
        # rien à déchiffrer, les octets extraits de l'image SONT le message
        return data

    if algo == "AES":
        # même phrase de passe requise qu'au chiffrement, sinon le tag d'intégrité ne correspondra pas
        return _decrypt_aes(data, key)

    if algo == "RSA":
        # ici "key" doit être la clé PRIVEE (PEM), contrairement à encrypt_message qui prenait la clé publique
        if not key:
            raise ValueError("Le déchiffrement RSA nécessite la clé privée (PEM)")
        return _decrypt_rsa(data, key)

    raise ValueError(f"Algorithme de chiffrement inconnu : {algo}")
