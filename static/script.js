// script.js : machine à états du parcours mobile. Un seul écran visible à la fois (voir .ecran.actif en CSS).
// Vanilla JS, aucune dépendance externe. Toutes les valeurs par défaut (N proposés, N pré-sélectionné) viennent
// de GET /config, donc rien n'est codé en dur ici : la source de vérité est le fichier .env côté serveur.

// ------------------------------------------------------------------
// état global du parcours en cours (remis à zéro par "Recommencer")
// ------------------------------------------------------------------
const state = {
    action: null, // "encoder" | "decoder"
    ecranActuel: "accueil",
    historique: [], // pile des écrans précédents, pour le bouton "retour"

    message: "",
    useEncryption: false,
    algo: null, // "AES" | "RSA"
    modeCle: "auto", // "auto" | "manuel"
    cleManuelle: "",
    imageFile: null, // fichier image choisi à l'encodage
    n: null, // facteur de redondance choisi (rempli depuis /config au chargement)

    decodeImageFile: null,
    inspection: null, // { chiffre, algo } renvoyé par /decode/inspecter
    decodedMessage: null,
};

let config = { redondance_par_defaut: 1, redondance_maximum: 255 }; // repli si /config est injoignable

// ------------------------------------------------------------------
// références DOM (une seule fois, pour ne pas répéter getElementById partout)
// ------------------------------------------------------------------
const carte = document.getElementById("carte");
const boutonRetour = document.getElementById("bouton-retour");
const boutonFermer = document.getElementById("bouton-fermer");
const pointsProgression = document.getElementById("points-progression");
const banniereErreur = document.getElementById("banniere-erreur");
const tousLesEcrans = document.querySelectorAll(".ecran");

// ------------------------------------------------------------------
// navigation entre écrans
// ------------------------------------------------------------------
function allerA(nomEcran) {
    if (state.ecranActuel !== nomEcran) {
        state.historique.push(state.ecranActuel); // permet au bouton "retour" de revenir précisément ici
    }
    state.ecranActuel = nomEcran;
    rendre();
}

function revenir() {
    const precedent = state.historique.pop();
    if (!precedent) return; // sécurité : ne devrait pas arriver puisque le bouton est masqué quand l'historique est vide
    state.ecranActuel = precedent;
    rendre();
}

function reinitialiser() {
    // on recrée un état neuf plutôt que de réassigner champ par champ : garantit qu'aucun résidu de la session précédente ne traîne
    Object.assign(state, {
        action: null, ecranActuel: "accueil", historique: [],
        message: "", useEncryption: false, algo: null, modeCle: "auto", cleManuelle: "",
        imageFile: null, n: config.redondance_par_defaut,
        decodeImageFile: null, inspection: null, decodedMessage: null,
    });
    // on vide aussi les champs du formulaire eux-mêmes (leur valeur ne dépend pas que de "state")
    champMessage.value = "";
    champCleManuelle.value = "";
    champImageEncoder.value = "";
    champImageDecoder.value = "";
    champCleDecodage.value = "";
    apercuImageEncoder.classList.add("masque");
    apercuImageDecoder.classList.add("masque");
    zoneUploadEncoderTexte.textContent = "Toucher pour choisir une image PNG";
    zoneUploadDecoderTexte.textContent = "Toucher pour choisir une image PNG";
    document.querySelectorAll(".tuile.selectionnee").forEach((t) => t.classList.remove("selectionnee"));
    rendre();
}

// calcule la liste des écrans du parcours "encoder" en fonction des choix déjà faits (le chiffrement ajoute une étape)
function calculerFluxEncodage() {
    const etapes = ["message", "chiffrement"];
    if (state.useEncryption) etapes.push("algo");
    etapes.push("image_encoder", "redondance", "resultat_encoder");
    return etapes;
}

// idem pour "decoder" : l'étape "clé" n'existe que si l'inspection a détecté un message chiffré
function calculerFluxDecodage() {
    const etapes = ["image_decoder"];
    if (state.inspection && state.inspection.chiffre) etapes.push("cle_decoder");
    etapes.push("resultat_decoder");
    return etapes;
}

function rendre() {
    // un seul écran visible : on retire .actif partout puis on la remet uniquement sur l'écran courant
    tousLesEcrans.forEach((ecran) => {
        ecran.classList.toggle("actif", ecran.dataset.ecran === state.ecranActuel);
    });

    // bouton retour : n'a de sens que s'il y a un écran précédent en mémoire
    boutonRetour.classList.toggle("visible", state.historique.length > 0);
    // bouton fermer (recommencer) : inutile de l'afficher si on est déjà à l'accueil
    boutonFermer.classList.toggle("visible", state.ecranActuel !== "accueil");

    // points de progression : uniquement pertinents à l'intérieur d'un parcours encoder/decoder connu
    pointsProgression.innerHTML = "";
    let etapes = [];
    if (state.action === "encoder") etapes = calculerFluxEncodage();
    else if (state.action === "decoder") etapes = calculerFluxDecodage();
    const indexActuel = etapes.indexOf(state.ecranActuel);
    if (indexActuel !== -1) {
        etapes.forEach((_, i) => {
            const point = document.createElement("span");
            if (i <= indexActuel) point.classList.add("point-actif");
            pointsProgression.appendChild(point);
        });
    }
}

function afficherErreur(message) {
    banniereErreur.textContent = message; // textContent (jamais innerHTML) : le message peut contenir du texte renvoyé par l'API
    banniereErreur.classList.remove("masque");
}

function effacerErreur() {
    banniereErreur.classList.add("masque");
    banniereErreur.textContent = "";
}

boutonRetour.addEventListener("click", () => { effacerErreur(); revenir(); });
boutonFermer.addEventListener("click", () => { effacerErreur(); reinitialiser(); });

// ------------------------------------------------------------------
// écran ACCUEIL : le choix déclenche directement la navigation (pas de bouton "Suivant" séparé, ce serait superflu)
// ------------------------------------------------------------------
document.querySelectorAll("[data-choix-action]").forEach((tuile) => {
    tuile.addEventListener("click", () => {
        state.action = tuile.dataset.choixAction;
        if (state.action === "encoder") {
            allerA("message");
        } else {
            allerA("image_decoder");
        }
    });
});

// ------------------------------------------------------------------
// écran MESSAGE (encoder)
// ------------------------------------------------------------------
const champMessage = document.getElementById("champ-message");
const boutonSuivantMessage = document.getElementById("bouton-suivant-message");

champMessage.addEventListener("input", () => {
    boutonSuivantMessage.disabled = champMessage.value.trim().length === 0; // pas de message = rien à cacher, on bloque
});
boutonSuivantMessage.disabled = true;

boutonSuivantMessage.addEventListener("click", () => {
    state.message = champMessage.value;
    allerA("chiffrement");
});

// ------------------------------------------------------------------
// écran CHIFFREMENT (encoder) : Oui/Non fait directement avancer, comme à l'accueil
// ------------------------------------------------------------------
document.querySelectorAll("[data-choix-chiffrement]").forEach((tuile) => {
    tuile.addEventListener("click", () => {
        state.useEncryption = tuile.dataset.choixChiffrement === "oui";
        allerA(state.useEncryption ? "algo" : "image_encoder");
    });
});

// ------------------------------------------------------------------
// écran ALGO + clé (encoder, uniquement si chiffrement = oui)
// ------------------------------------------------------------------
const blocModeCle = document.getElementById("bloc-mode-cle");
const champCleManuelle = document.getElementById("champ-cle-manuelle");
const boutonSuivantAlgo = document.getElementById("bouton-suivant-algo");

document.querySelectorAll("[data-choix-algo]").forEach((tuile) => {
    tuile.addEventListener("click", () => {
        document.querySelectorAll("[data-choix-algo]").forEach((t) => t.classList.remove("selectionnee"));
        tuile.classList.add("selectionnee");
        state.algo = tuile.dataset.choixAlgo;
        blocModeCle.classList.remove("masque"); // on ne montre le choix "auto/manuel" qu'une fois l'algo choisi
        // le label du champ clé change de sens selon l'algo (mot de passe vs clé publique PEM) : on adapte le placeholder
        champCleManuelle.placeholder = state.algo === "AES" ? "Votre phrase de passe" : "Votre clé publique (PEM)";
        mettreAJourValiditeAlgo();
    });
});

document.querySelectorAll("[data-mode-cle]").forEach((segment) => {
    segment.addEventListener("click", () => {
        document.querySelectorAll("[data-mode-cle]").forEach((s) => s.classList.remove("selectionne"));
        segment.classList.add("selectionne");
        state.modeCle = segment.dataset.modeCle;
        // le champ clé n'est utile qu'en mode manuel : en mode auto, la clé sera générée par le serveur
        champCleManuelle.classList.toggle("masque", state.modeCle !== "manuel");
        mettreAJourValiditeAlgo();
    });
});

champCleManuelle.addEventListener("input", mettreAJourValiditeAlgo);

function mettreAJourValiditeAlgo() {
    const cleRequiseEtManquante = state.modeCle === "manuel" && champCleManuelle.value.trim().length === 0;
    boutonSuivantAlgo.disabled = !state.algo || cleRequiseEtManquante;
}

boutonSuivantAlgo.addEventListener("click", () => {
    state.cleManuelle = state.modeCle === "manuel" ? champCleManuelle.value : "";
    allerA("image_encoder");
});

// ------------------------------------------------------------------
// écran IMAGE (encoder)
// ------------------------------------------------------------------
const champImageEncoder = document.getElementById("champ-image-encoder");
const zoneUploadEncoderTexte = document.getElementById("zone-upload-encoder-texte");
const apercuImageEncoder = document.getElementById("apercu-image-encoder");
const boutonSuivantImage = document.getElementById("bouton-suivant-image");

champImageEncoder.addEventListener("change", () => {
    if (champImageEncoder.files.length === 0) return;
    state.imageFile = champImageEncoder.files[0];
    afficherApercu(state.imageFile, apercuImageEncoder, zoneUploadEncoderTexte);
    boutonSuivantImage.disabled = false;
});

boutonSuivantImage.addEventListener("click", () => {
    // au chargement, /config peut ne pas encore avoir répondu : on retombe alors sur la valeur par défaut du serveur
    if (state.n === null) state.n = config.redondance_par_defaut;
    champNLibre.value = state.n;
    validerChampN();
    allerA("redondance");
});

function afficherApercu(fichier, elementImg, elementTexte) {
    const lecteur = new FileReader(); // FileReader convertit le fichier local en data-URL affichable, sans upload préalable
    lecteur.onload = () => {
        elementImg.src = lecteur.result;
        elementImg.classList.remove("masque");
        elementTexte.textContent = fichier.name; // remplace le texte d'invite par le nom du fichier choisi, confirmation visuelle
    };
    lecteur.readAsDataURL(fichier);
}

// ------------------------------------------------------------------
// écran REDONDANCE (encoder) : champ libre, aucun plafond artificiel côté interface
// ------------------------------------------------------------------
const champNLibre = document.getElementById("champ-n-libre");
const astuceN = document.getElementById("astuce-n");
const boutonEncoderMaintenant = document.getElementById("bouton-encoder-maintenant");

function validerChampN() {
    // la limite haute (config.redondance_maximum) vient du serveur : c'est une contrainte du FORMAT de fichier
    // (N stocké sur 1 octet dans l'en-tête caché), pas un choix arbitraire de l'interface -> on l'explique plutôt que de la cacher
    const valeur = parseInt(champNLibre.value, 10);
    const valide = Number.isInteger(valeur) && valeur >= 1 && valeur <= config.redondance_maximum;
    if (valide) {
        state.n = valeur;
        astuceN.textContent = valeur === 1
            ? "N=1 = aucune redondance (LSB classique)"
            : "Chaque caractère du message sera caché " + valeur + " fois dans l'image";
        astuceN.classList.remove("avertissement");
    } else {
        astuceN.textContent = "Choisissez un nombre entier entre 1 et " + config.redondance_maximum
            + " (limite du format de fichier, pas un choix arbitraire)";
        astuceN.classList.add("avertissement");
    }
    boutonEncoderMaintenant.disabled = !valide;
}

champNLibre.addEventListener("input", validerChampN);

boutonEncoderMaintenant.addEventListener("click", async () => {
    effacerErreur();
    boutonEncoderMaintenant.disabled = true;
    boutonEncoderMaintenant.textContent = "Encodage en cours...";
    try {
        const donnees = new FormData();
        donnees.append("image", state.imageFile);
        donnees.append("message", state.message);
        donnees.append("use_encryption", state.useEncryption);
        donnees.append("algo", state.algo || "none");
        donnees.append("key", state.cleManuelle);
        donnees.append("n", state.n);

        const resultat = await appelerApi("/encode", donnees);
        afficherResultatEncodage(resultat);
        allerA("resultat_encoder");
    } catch (erreur) {
        afficherErreur(erreur.message);
    } finally {
        boutonEncoderMaintenant.disabled = false;
        boutonEncoderMaintenant.textContent = "Encoder maintenant";
    }
});

// ------------------------------------------------------------------
// écran RESULTAT (encoder)
// ------------------------------------------------------------------
const imageResultat = document.getElementById("image-resultat");
const lienTelechargement = document.getElementById("lien-telechargement");
const blocCleGeneree = document.getElementById("bloc-cle-generee");
const texteCleGeneree = document.getElementById("texte-cle-generee");
const boutonCopierCle = document.getElementById("bouton-copier-cle");

function afficherResultatEncodage(resultat) {
    const urlImage = "data:image/png;base64," + resultat.image_base64;
    imageResultat.src = urlImage;
    lienTelechargement.href = urlImage;

    // seule une clé générée automatiquement (jamais fournie par l'utilisateur) doit être montrée : il ne la connaît pas encore
    const cleGeneree = resultat.aes_passphrase || resultat.rsa_private_key_pem;
    if (cleGeneree) {
        texteCleGeneree.textContent = cleGeneree;
        blocCleGeneree.classList.remove("masque");
    } else {
        blocCleGeneree.classList.add("masque");
    }
}

boutonCopierCle.addEventListener("click", () => copierTexte(texteCleGeneree.textContent, boutonCopierCle, "Copier la clé"));

document.getElementById("bouton-comparer-depuis-encodeur").addEventListener("click", () => {
    lancerComparaison(state.imageFile, state.message);
});
document.getElementById("bouton-recommencer-1").addEventListener("click", reinitialiser);

// ------------------------------------------------------------------
// écran IMAGE (decoder) : la sélection déclenche immédiatement une inspection de l'image
// ------------------------------------------------------------------
const champImageDecoder = document.getElementById("champ-image-decoder");
const zoneUploadDecoderTexte = document.getElementById("zone-upload-decoder-texte");
const apercuImageDecoder = document.getElementById("apercu-image-decoder");
const statutInspection = document.getElementById("statut-inspection");
const boutonSuivantImageDecoder = document.getElementById("bouton-suivant-image-decoder");

champImageDecoder.addEventListener("change", async () => {
    if (champImageDecoder.files.length === 0) return;
    effacerErreur();
    state.decodeImageFile = champImageDecoder.files[0];
    state.inspection = null;
    afficherApercu(state.decodeImageFile, apercuImageDecoder, zoneUploadDecoderTexte);

    boutonSuivantImageDecoder.classList.add("masque");
    statutInspection.textContent = "Analyse de l'image...";
    statutInspection.classList.remove("masque");

    try {
        const donnees = new FormData();
        donnees.append("image", state.decodeImageFile);
        const info = await appelerApi("/decode/inspecter", donnees);
        state.inspection = info;

        statutInspection.textContent = info.chiffre
            ? "Message chiffré détecté (" + info.algo + ")"
            : "Message non chiffré détecté";

        // on ne demande la clé QUE si l'image indique qu'elle est nécessaire : jamais d'étape inutile
        if (info.chiffre) {
            boutonSuivantImageDecoder.textContent = "Suivant";
            boutonSuivantImageDecoder.onclick = () => {
                // le libellé s'adapte à l'algo détecté, connu uniquement à ce stade (résultat de l'inspection)
                sousTitreCleDecoder.textContent = info.algo === "RSA"
                    ? "Ce message est chiffré en RSA : collez la clé privée (PEM)"
                    : "Ce message est chiffré en AES : entrez la phrase de passe";
                allerA("cle_decoder");
            };
        } else {
            boutonSuivantImageDecoder.textContent = "Décoder maintenant";
            boutonSuivantImageDecoder.onclick = () => lancerDecodage("");
        }
        boutonSuivantImageDecoder.classList.remove("masque");
    } catch (erreur) {
        statutInspection.classList.add("masque");
        afficherErreur(erreur.message); // ex: image sans message caché -> on le dit tout de suite, pas la peine d'aller plus loin
    }
});

// ------------------------------------------------------------------
// écran CLE (decoder, uniquement si chiffré)
// ------------------------------------------------------------------
const sousTitreCleDecoder = document.getElementById("sous-titre-cle-decoder");
const champCleDecodage = document.getElementById("champ-cle-decodage");
const boutonDecoderMaintenant = document.getElementById("bouton-decoder-maintenant");

champCleDecodage.addEventListener("input", () => {
    boutonDecoderMaintenant.disabled = champCleDecodage.value.trim().length === 0;
});

boutonDecoderMaintenant.addEventListener("click", () => lancerDecodage(champCleDecodage.value));

async function lancerDecodage(cle) {
    effacerErreur();
    boutonDecoderMaintenant.disabled = true;
    try {
        const donnees = new FormData();
        donnees.append("image", state.decodeImageFile);
        donnees.append("key", cle);
        const resultat = await appelerApi("/decode", donnees);
        state.decodedMessage = resultat.message;
        texteMessageDecode.textContent = resultat.message;
        allerA("resultat_decoder");
    } catch (erreur) {
        afficherErreur(erreur.message);
    } finally {
        boutonDecoderMaintenant.disabled = false;
    }
}

// ------------------------------------------------------------------
// écran RESULTAT (decoder)
// ------------------------------------------------------------------
const texteMessageDecode = document.getElementById("texte-message-decode");
const boutonCopierMessage = document.getElementById("bouton-copier-message");

boutonCopierMessage.addEventListener("click", () => copierTexte(texteMessageDecode.textContent, boutonCopierMessage, "Copier le message"));

document.getElementById("bouton-comparer-depuis-decodeur").addEventListener("click", () => {
    lancerComparaison(state.decodeImageFile, state.decodedMessage);
});
document.getElementById("bouton-recommencer-2").addEventListener("click", reinitialiser);

// ------------------------------------------------------------------
// écran COMPARER (accessible depuis les deux écrans de résultat)
// ------------------------------------------------------------------
const cartesComparaison = document.getElementById("cartes-comparaison");
const conclusionComparaison = document.getElementById("conclusion-comparaison");

async function lancerComparaison(fichierImage, message) {
    effacerErreur();
    allerA("comparer");
    cartesComparaison.innerHTML = '<p class="chargement">Comparaison en cours...</p>';
    conclusionComparaison.textContent = "";
    try {
        const donnees = new FormData();
        donnees.append("image", fichierImage);
        donnees.append("message", message);
        // le pourcentage de corruption n'est pas demandé à l'utilisateur : /compare retombe sur la valeur définie dans .env
        const resultat = await appelerApi("/compare", donnees);

        cartesComparaison.innerHTML = "";
        resultat.resultats.forEach((ligne) => {
            const carte = document.createElement("div");
            carte.className = "carte-comparaison";
            if (ligne.erreur) {
                carte.innerHTML = "";
                const nLabel = document.createElement("span");
                nLabel.className = "n-label";
                nLabel.textContent = "N=" + ligne.n;
                const erreurTexte = document.createElement("span");
                erreurTexte.textContent = ligne.erreur;
                carte.append(nLabel, erreurTexte);
            } else {
                const nLabel = document.createElement("span");
                nLabel.className = "n-label";
                nLabel.textContent = "N=" + ligne.n;

                const mesures = document.createElement("span");
                mesures.className = "mesures";
                const robustesse = document.createElement("span");
                robustesse.className = "robustesse";
                robustesse.textContent = ligne.robustesse_pourcentage + "% robuste";
                const details = document.createElement("span");
                details.textContent = ligne.capacite_utile_octets + " o utiles · PSNR " + (ligne.psnr_db ?? "∞") + " dB";
                mesures.append(robustesse, details);

                carte.append(nLabel, mesures);
            }
            cartesComparaison.appendChild(carte);
        });
        conclusionComparaison.textContent = resultat.conclusion;
    } catch (erreur) {
        cartesComparaison.innerHTML = "";
        afficherErreur(erreur.message);
    }
}

document.getElementById("bouton-retour-comparaison").addEventListener("click", revenir);

// ------------------------------------------------------------------
// utilitaires partagés : appel API + copie presse-papiers
// ------------------------------------------------------------------
async function appelerApi(url, donnees) {
    const reponse = await fetch(url, { method: "POST", body: donnees });
    const corps = await reponse.json(); // même en erreur, FastAPI renvoie un JSON {"detail": "..."} qu'on veut pouvoir lire
    if (!reponse.ok) {
        throw new Error(corps.detail || "Erreur inconnue côté serveur");
    }
    return corps;
}

function copierTexte(texte, bouton, libelleInitial) {
    navigator.clipboard.writeText(texte).then(() => {
        bouton.textContent = "Copié !";
        setTimeout(() => { bouton.textContent = libelleInitial; }, 1500); // retour au libellé normal après un court instant
    });
}

// ------------------------------------------------------------------
// popup d'aide contextuelle ("i") : un seul mécanisme générique, réutilisable pour n'importe quelle étape
// ------------------------------------------------------------------
const superpositionInfo = document.getElementById("superposition-info");
const modaleInfoTitre = document.getElementById("modale-info-titre");
const modaleInfoCorps = document.getElementById("modale-info-corps");

function ouvrirInfo(titre, corpsHtml) {
    modaleInfoTitre.textContent = titre;
    modaleInfoCorps.innerHTML = corpsHtml; // contenu écrit en dur par nous ci-dessous (jamais de texte utilisateur) : pas de risque XSS
    superpositionInfo.classList.remove("masque");
}

function fermerInfo() {
    superpositionInfo.classList.add("masque");
}

document.getElementById("bouton-fermer-modale-info").addEventListener("click", fermerInfo);
// cliquer sur le fond assombri (en dehors de la carte blanche) ferme aussi la popup, comportement attendu sur mobile
superpositionInfo.addEventListener("click", (evenement) => {
    if (evenement.target === superpositionInfo) fermerInfo();
});

document.getElementById("bouton-info-redondance").addEventListener("click", () => {
    ouvrirInfo("C'est quoi la redondance ?", `
        <p>Normalement, chaque lettre de votre message n'est cachée <strong>qu'une seule fois</strong> dans l'image.
        Si l'image est un peu abîmée par la suite (compression, envoi sur un site...) et qu'un pixel se corrompt au
        mauvais endroit, cette lettre devient fausse — et il n'y a aucun moyen de le savoir.</p>

        <p>La redondance, c'est écrire chaque lettre <strong>plusieurs fois</strong> (N fois) dans l'image au lieu
        d'une seule. Pour relire le message, le programme compare toutes les copies d'une même lettre et garde
        celle qui revient le plus souvent : c'est le <strong>vote majoritaire</strong>.</p>

        <div class="exemple-info">
            <strong>Exemple avec N=3 :</strong><br>
            Message "OK" → on cache en réalité "OOO" puis "KKK" (chaque lettre répétée 3 fois).<br><br>
            Si l'image abîme une seule copie : le programme relit O, O, X → 2 votes pour "O" contre 1 pour "X" →
            il garde "O", la bonne lettre, malgré l'erreur !
        </div>

        <p>C'est comme répéter un mot 3 fois au téléphone à quelqu'un : s'il en rate un, il a 2 autres chances de
        bien l'entendre.</p>

        <p><strong>Le compromis</strong> : plus N est grand, plus le message résiste aux dégâts, mais moins vous
        pouvez cacher de texte au total dans la même image (chaque lettre prend N fois plus de place).</p>
    `);
});

// ------------------------------------------------------------------
// démarrage : on va chercher les valeurs par défaut côté serveur (.env) avant d'afficher l'écran de redondance
// ------------------------------------------------------------------
fetch("/config")
    .then((r) => r.json())
    .then((c) => {
        config = c;
        state.n = c.redondance_par_defaut;
        champNLibre.max = c.redondance_maximum; // affiche la vraie limite technique dans le contrôle natif du navigateur
    })
    .catch(() => {
        // /config injoignable -> on garde le repli local défini en haut du fichier, l'app reste utilisable
    });

rendre();
