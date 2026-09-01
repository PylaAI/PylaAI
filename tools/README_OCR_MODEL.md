# Modèle de reconnaissance des brawlers

PylaAI utilise un petit classifieur ONNX pour reconnaître les noms affichés dans
le menu des brawlers. OpenCV localise les cartes et prépare les images ; ONNX
Runtime exécute ensuite le classifieur.

EasyOCR et PyTorch ne sont pas nécessaires pour faire fonctionner le bot.
PyTorch est utilisé uniquement par le mainteneur lors de l'entraînement et de
l'export du modèle ONNX.

## Contraintes des captures

Les captures utilisées pour entraîner et tester le modèle doivent respecter la
configuration officiellement supportée par PylaAI :

- émulateur en `1920x1080` ;
- densité de `280 DPI` ;
- Brawl Stars en anglais ;
- facteur OCR de `0.8` dans `cfg/general_config.toml`.

## Fichiers importants

- `brawler_name_recognizer.py` : localisation OpenCV et inférence ONNX ;
- `models/brawlerNameClassifier.onnx` : modèle distribué avec le bot ;
- `models/brawlerNameClassifier_labels.json` : ordre des classes du modèle ;
- `tools/prepare_ocr_dataset.py` : préparation et contrôle du dataset ;
- `tools/train_brawler_name_model.py` : entraînement et export ONNX ;
- `cfg/names.json` : noms canoniques et variantes reconnues.

Le dossier `ocr_dataset/` contient les captures et les données préparées. Il est
ignoré par Git et ne doit pas être distribué aux utilisateurs.

## Environnement d'entraînement

Installer les dépendances d'entraînement dans un environnement séparé :

```powershell
python -m pip install torch onnx
```

Les dépendances normales du bot fournissent déjà OpenCV, NumPy et ONNX Runtime.
Ne pas ajouter `torch` aux dépendances runtime de `requirements.txt` ou de
`setup.py`.

## Préparer le dataset

Activer temporairement les deux options suivantes dans les paramètres de debug :

```toml
collect_ocr_dataset = true
full_ocr_dataset_scan = true
```

Lancer PylaAI et démarrer la sélection automatique. Le bot parcourt la liste
sans sélectionner de brawler, puis s'arrête arrivé en bas. Effectuer au moins
deux scans complets afin d'avoir des données d'entraînement et de validation.

Réinitialiser ensuite les options :

```toml
collect_ocr_dataset = false
full_ocr_dataset_scan = false
```

Préparer les données dans un nouveau dossier vide :

```powershell
python tools/prepare_ocr_dataset.py `
  --source ocr_dataset `
  --output ocr_dataset/prepared_next
```

Vérifier avant l'entraînement :

- `summary.json` pour le nombre de classes et les répartitions ;
- `label_overview.jpg` pour contrôler visuellement chaque classe ;
- `rejected_contact_sheet.jpg` pour repérer les mauvaises annotations.

Chaque classe doit apparaître dans les ensembles `train` et `validation`.
Pendant l'entraînement, le script génère aussi l'alignement opposé de chaque
nom : une capture verrouillée apprend également la disposition débloquée, et
inversement.

## Entraîner et exporter

```powershell
python tools/train_brawler_name_model.py `
  --manifest ocr_dataset/prepared_next/manifest.csv `
  --output models/brawlerNameClassifier.onnx
```

Le script génère également
`models/brawlerNameClassifier_labels.json`. Les deux fichiers doivent toujours
être mis à jour et commités ensemble.

Le nombre de classes est dynamique. Le script compare le dataset avec les noms
présents dans `cfg/names.json` et refuse l'export si une classe manque ou si une
classe inattendue est présente.

## Ajouter un nouveau brawler

1. Ajouter son nom canonique et ses variantes dans `cfg/names.json`.
2. Faire plusieurs scans où son nom apparaît à différentes hauteurs.
3. Si possible, capturer sa carte verrouillée puis débloquée.
4. Annoter manuellement au moins quelques occurrences du nouveau nom.
5. Préparer à nouveau l'intégralité du dataset.
6. Réentraîner les anciennes classes et la nouvelle ensemble.
7. Remplacer le modèle ONNX et son fichier de labels.
8. Tester la sélection du nouveau brawler en haut, au milieu et en bas de liste.

Le modèle existant ne peut pas auto-annoter une classe qu'il ne connaît pas.
Le collecteur sauvegarde bien les captures brutes, mais les occurrences d'un
nouveau brawler doivent être ajoutées ou corrigées manuellement dans les
métadonnées avant la préparation. Il ne faut pas utiliser une prédiction de
l'ancien modèle comme vérité terrain pour la nouvelle classe.

### Que signifie « annoter » ?

Annoter ne signifie pas réaliser ou recadrer les screenshots à la main. Il faut
indiquer au préparateur quel nom réel se trouve dans une zone déjà localisée par
OpenCV.

Chaque capture possède deux fichiers portant le même identifiant :

- `ocr_dataset/images/<identifiant>.png` : l'écran capturé ;
- `ocr_dataset/metadata/<identifiant>.json` : les noms et positions détectés.

Pour annoter un nouveau brawler avec les outils actuels :

1. Ouvrir l'image et repérer la ligne et la colonne de sa carte.
2. Ouvrir le fichier JSON correspondant.
3. Dans `detections`, retrouver l'entrée dont la `bbox` couvre cette carte.
4. Remplacer uniquement `text` et `normalized_text` par le nom canonique ajouté
   dans `cfg/names.json`.
5. Répéter l'opération sur plusieurs occurrences, dans les deux scans.

Exemple si l'ancien modèle confond un nouveau brawler avec Sandy :

```json
{
  "text": "nouveaubrawler",
  "normalized_text": "nouveaubrawler",
  "confidence": 1.0,
  "bbox": [[169, 701], [397, 701], [397, 765], [169, 765]]
}
```

La `bbox` doit être conservée : elle décrit la position de la zone et permet au
script de générer le recadrage. Le champ `confidence` n'est pas utilisé comme
vérité terrain ; il peut être laissé tel quel ou fixé à `1.0` après vérification
humaine.

Si aucune entrée ne correspond à la carte, il faut ajouter sa boîte manuellement
ou utiliser un futur outil d'annotation assistée. Ne jamais renommer toutes les
prédictions identiques en bloc : l'ancien modèle peut avoir confondu plusieurs
cartes différentes avec le même nom.

## Tests avant publication

- sélectionner un brawler visible immédiatement ;
- sélectionner un brawler nécessitant plusieurs défilements ;
- rechercher un brawler verrouillé et vérifier que le bot se met en pause ;
- lancer une partie complète après la sélection ;
- vérifier dans un processus propre que `torch` et `easyocr` ne sont pas chargés ;
- vérifier que le modèle et les labels contiennent le même nombre de classes.

PyTorch peut rester installé sur la machine du mainteneur : tant qu'il n'est pas
importé par le runtime, il ne consomme pas de RAM dans le processus du bot.
