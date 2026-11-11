# Guide d'Extraction des Fichiers du Jeu

Pour utiliser ce randomizer, vous devez extraire les données de votre propre copie de Final Fantasy IX.

## Étape 1 : Installation de Memoria
Assurez-vous que le mod **Memoria** est installé sur votre jeu Steam.

## Étape 2 : Exportation des données via Memoria
1. Ouvrez le fichier `Memoria.ini` situé à la racine du jeu.
2. Dans la section `[Import]`, trouvez (ou ajoutez) la ligne `Export = 1`.
3. Lancez le jeu jusqu'au menu principal, puis quittez.
4. Memoria a maintenant créé un dossier `StreamingAssets/Data` et un dossier `StreamingAssets/Text`.

## Étape 3 : Fichiers nécessaires au Randomizer
Le randomizer a besoin que votre arborescence de travail ressemble à ceci :

```text
Votre_Dossier_De_Travail/
├── FF9_Randomizer/             # (Ce dépôt)
│   ├── scripts/
│   ├── data/
│   │   └── FF9_Database_Propre.json
│   └── ...
├── fieldsScript/               # (À EXTRAIRE)
│   ├── fieldScript_1.txt
│   ├── fieldScript_2.txt
│   └── ...
└── C:/Program Files (x86)/Steam/steamapps/common/FINAL FANTASY IX/ # (Répertoire du jeu)
    ├── StreamingAssets/
    │   ├── p0data2.bin         # (Original du jeu)
    │   └── p0data7.bin         # (Original du jeu)
    ├── FF9_Data/
    │   └── resources.assets    # (Original du jeu)
    └── RandomizerTest/         # (Dossier généré par le script)
        └── StreamingAssets/
            └── Data/
                └── Items/
                    ├── ShopItems.csv  # (Original copié par Memoria)
                    └── Synthesis.csv  # (Original copié par Memoria)
```

## Étape 4 : Extraction des scripts de champs (Hades Workshop)
Les scripts ont besoin de savoir quels objets se trouvent dans les coffres originaux. Pour cela, vous devez exporter les scripts textes avec Hades Workshop[cite: 7] :

Ouvrez Hades Workshop et chargez votre jeu (File > Open > FF9_Launcher.exe).

Allez dans Batch > Export Field Scripts.

Exportez les fichiers dans un dossier nommé fieldsScript à côté du dossier de ce dépôt. (Par défaut, le script attend ../fieldsScript).

## Étape 5 : Préparation de la base de données (JSON)
Vous devez fournir le fichier FF9_Database_Propre.json et le placer dans FF9_Randomizer/data/.
Ce fichier doit contenir les statistiques des monstres et la liste des boss à exclure.