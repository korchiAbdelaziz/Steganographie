# generate_test_image.py
# -----------------------------------------------------------------------------
# Petit script utilitaire (pas une couche de l'API) : génère une image PNG de test,
# nécessaire car la stéganographie LSB exige un format SANS PERTE (le JPEG
# détruirait les bits de poids faible lors de sa compression).
# -----------------------------------------------------------------------------

import numpy as np  # génère les valeurs de pixels aléatoires/dégradées
from PIL import Image  # écrit le résultat au format PNG

LARGEUR, HAUTEUR = 300, 200  # taille modeste : suffisante pour cacher un message de test, rapide à traiter

# une image purement aléatoire ressemblerait à du "bruit" peu réaliste ; on préfère un dégradé de couleurs
# (plus proche d'une vraie photo en termes de distribution de valeurs), ce qui rend le test de PSNR plus parlant
x = np.linspace(0, 255, LARGEUR, dtype=np.uint8)  # dégradé horizontal, du noir au blanc sur le canal rouge
y = np.linspace(0, 255, HAUTEUR, dtype=np.uint8)  # dégradé vertical, du noir au blanc sur le canal vert
canal_rouge = np.tile(x, (HAUTEUR, 1))  # répète le dégradé horizontal sur toutes les lignes
canal_vert = np.tile(y.reshape(-1, 1), (1, LARGEUR))  # répète le dégradé vertical sur toutes les colonnes
canal_bleu = np.full((HAUTEUR, LARGEUR), 128, dtype=np.uint8)  # canal bleu constant, pour une image simple mais pas monochrome

image = np.stack([canal_rouge, canal_vert, canal_bleu], axis=-1)  # assemble les 3 canaux en une image RGB (hauteur, largeur, 3)
Image.fromarray(image, mode="RGB").save("test_image.png")  # PNG = sans perte, condition indispensable pour la stéganographie LSB

print("Image de test créée : test_image.png")
