# Final Fantasy IX - Randomizer Memoria

Ce dépôt contient les scripts Python nécessaires pour créer un mod de randomisation complet pour Final Fantasy IX (version Steam avec Memoria).

Ce randomizer permet de :
- Mélanger les combats aléatoires (remplacement par niveau, chaos total, ou ajustement dynamique).
- Randomiser le contenu des coffres et objets cachés sur la carte.
- Randomiser les objets vendus dans les magasins.
- Randomiser les recettes de forge (synthèse).
- Ajuster les butins et vols (Drops & Steals) proportionnellement aux nouveaux monstres.

## Arborescence du Projet

```text
FF9_Randomizer/
├── scripts/
│   ├── battle_swap.py       # Script principal pour l'échange des combats (Mode "swap")
│   ├── eb_randomizer.py     # Cœur du randomizer, configuration et manipulation binaire
│   └── ite_randomizer.py    # Script pour randomiser les coffres, magasins et forges
├── data/
│   └── FF9_Database_Propre.json
├── docs/
│   └── extraction_guide.md  # Guide pour extraire les fichiers originaux du jeu
└── README.md                # Ce fichier
```
## Prérequis et Fichiers du Jeu (Non inclus)
Pour des raisons évidentes de droits d'auteur, les fichiers originaux du jeu ne sont pas inclus dans ce dépôt. 
Vous devez posséder Final Fantasy IX sur Steam et avoir installé le mod Memoria.
Pour faire fonctionner ce randomizer, vous devez extraire et préparer plusieurs fichiers depuis votre installation du jeu.
Veuillez consulter le guide détaillé : docs/extraction_guide.md
UtilisationPréparation : Assurez-vous d'avoir suivi le extraction_guide.md et placé tous les fichiers requis aux bons endroits.
Configuration : Ouvrez eb_randomizer.py pour ajuster les paramètres (graine de génération SEED, mode de randomisation, tolérances de niveau, etc.).
Génération des Combats :Bashpython scripts/battle_swap.py
Génération des Objets (Coffres, Magasins, Forges) :Bashpython scripts/ite_randomizer.py
Installation : Lancez le jeu via Memoria. Le dossier RandomizerTest contient désormais votre mod !