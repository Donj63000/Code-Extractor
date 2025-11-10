# Code Extractor

Code Extractor est un utilitaire que j'ai developpe pour les developpeurs qui s'appuient sur des agents IA et qui doivent partager leur base de code via des connecteurs GitHub. L'outil rassemble l'integralite du code source d'un projet (arborescence incluse) dans un fichier texte unique, ce qui evite les soucis de code hache ou tronque cote connecteur. Chaque fichier peut etre selectionne finement avant l'export et le projet reste activement en developpement.

## Fonctionnalites cles
- Export complet de l'arborescence d'un depot vers un fichier `.txt`.
- Selection fichier par fichier pour ne garder que les elements pertinents.
- Preservation de la structure du projet pour faciliter le contexte des agents IA.
- Scripts PyInstaller (`*.spec`) prets a l'emploi pour generer des executables (interface principale, viewer, extracteur).

## Etat du projet
Le programme est encore en developpement : certaines parties de l'interface et des automatisations sont amenees a evoluer. Les retours et issues GitHub sont les bienvenus pour prioriser les prochaines fonctionnalites.

## Prerequis rapides
- Python 3.11+ et `pip`.
- Un IDE Python (PyCharm, VS Code, etc.) ou la ligne de commande.
- PyInstaller (installe automatiquement lors du tutoriel ci-dessous) si vous souhaitez compiler un executable.

## Tutoriel - Comment installer le projet et compiler un .exe a partir d'un IDE

### 1. Cloner le depot
```bash
git clone https://github.com/Donj63000/Code-Extractor.git
cd Code-Extractor
```

### 2. Creer un environnement virtuel depuis l'IDE
1. Ouvrez le dossier du projet dans votre IDE.
2. Creez un nouvel environnement virtuel (PyCharm : `File > Settings > Project > Python Interpreter > Add > Virtualenv`).
3. Selectionnez Python 3.11+ comme interpreteur.

### 3. Installer les dependances
- Via PyCharm (icone de roue dentee de l'interpreteur) ou via le terminal integre :
  ```bash
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  ```
- Si vous n'avez pas de `requirements.txt`, utilisez `make install` ou installez manuellement les bibliotheques utilisees par `main2.0.py`.

### 4. Lancer le programme en mode developpement
- Depuis l'IDE, executez `main2.0.py` (ou la variante de votre choix) pour tester la generation du `.txt`.
- Verifiez que l'extraction affiche bien les fichiers selectionnes et que le fichier genere contient l'arborescence souhaitee.

### 5. Compiler un `.exe` directement depuis l'IDE
1. Installez PyInstaller dans l'environnement virtuel : `python -m pip install pyinstaller`.
2. Dans le terminal de l'IDE :
   ```bash
   pyinstaller Extractor2.0.spec    # ou main.spec / CodeViewer1.0.spec selon l'interface voulue
   ```
   Les fichiers `.spec` fournis configureront iconographie, ressources et options.
3. PyInstaller cree l'executable dans `dist/`. Copiez le dossier genere (par ex. `dist/Extractor2.0/`) pour distribuer l'outil.

### 6. (Optionnel) Nettoyer/Builder via la ligne de commande
- `make clean` supprime `build/`, `dist/` et les `__pycache__`.
- `make build` relance la construction (PyInstaller/Build Python) si les fichiers de configuration requis sont presents.

## Aller plus loin
- Ajoutez vos propres scripts d'automatisation dans le `Makefile`.
- Documentez les fichiers exclus (tests, secrets, etc.) dans `.gitignore` pour eviter de les exporter.
- Partagez vos retours via les issues GitHub pour aider a prioriser les evolutions.
