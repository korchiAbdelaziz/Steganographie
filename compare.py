# compare.py
# -----------------------------------------------------------------------------
# Script autonome (sans serveur) qui lance la comparaison N=1 vs N=2 vs N=3
# et affiche un tableau Markdown, directement réutilisable dans le README.
# Réutilise executer_comparaison() de main.py : aucune logique dupliquée.
# -----------------------------------------------------------------------------

from PIL import Image
from main import executer_comparaison

IMAGE_TEST = "test_image.png"  # généré par generate_test_image.py
MESSAGE_TEST = "Ceci est un message secret de test pour comparer le LSB classique et le LSB avec redondance."
POURCENTAGE_CORRUPTION = 5.0  # % de valeurs de pixels altérées, comme suggéré dans l'énoncé

if __name__ == "__main__":
    image = Image.open(IMAGE_TEST)
    resultat = executer_comparaison(image, MESSAGE_TEST, POURCENTAGE_CORRUPTION)

    # en-tête du tableau Markdown
    print("| N | Capacité brute (octets) | Capacité utile (octets) | PSNR (dB) | Corruption testée (%) | Robustesse (%) |")
    print("|---|---|---|---|---|---|")
    for ligne in resultat["resultats"]:
        if "erreur" in ligne:
            print(f"| {ligne['n']} | - | - | - | - | erreur: {ligne['erreur']} |")
            continue
        print(
            f"| {ligne['n']} | {ligne['capacite_brute_octets']} | {ligne['capacite_utile_octets']} | "
            f"{ligne['psnr_db']} | {ligne['corruption_testee_pourcentage']} | {ligne['robustesse_pourcentage']} |"
        )

    print()
    print(resultat["conclusion"])
