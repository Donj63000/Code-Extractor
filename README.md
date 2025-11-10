# Code Extractor

Code Extractor est un utilitaire que j'ai developpe pour les developpeurs qui utilisent des agents IA relies a GitHub et qui se heurtent a des extraits de code hashes, tronques ou difficiles a reconstituer depuis les connecteurs. Le programme assemble l'ensemble du code source (fichiers et arborescence) dans un fichier texte unique et lisible, tout en laissant la possibilite de choisir exactement quels fichiers doivent etre inclus. Spéciale dédicace à mon ami Clody qui m'as indirectement l'idée de developper ce micro software

---

## Pourquoi ce projet ?
Les agents IA relies a GitHub recuperent souvent des diffs incomplets, ou des blobs hashes que l'on ne peut pas facilement recoller. Quand un agent a besoin de tout le contexte d'un projet (structure, dependances, scripts, assets), il faut lui donner un support texte simple et non ambigu. Code Extractor automatise ce travail fastidieux :
- Aucun copier/coller manuel de dizaines de fichiers.
- Arborescence et chemins conserves pour que l'IA comprenne ou se situe chaque fichier.
- Possibilite de filtrer les fichiers sensibles ou inutiles (secrets, gros binaires, etc.).

---

## Fonctionnalites cles
- **Export structurel** : genere un `.txt` contenant l'arborescence complete du depot et le contenu de chaque fichier selectionne.
- **Selection granulaire** : interface permettant de cocher/decoche les fichiers ou repertoires a inclure.
- **Compatibilite PyInstaller** : des fichiers `.spec` preconfigures (Extractor2.0, CodeViewer1.0, main) facilitent la creation d'executables.
- **Mode developpement actif** : le projet evolue encore, donc les retours (issues, discussions) sont encourages.

---

## Comment cela fonctionne
1. L'application inspecte l'arborescence du depot local.
2. Vous choisissez les fichiers a exporter via l'interface.
3. Le programme concatene chaque fichier dans un `.txt`, en precedant le contenu par le chemin relatif, de sorte que l'IA voie immediatement l'organisation du code.
4. Vous transmettez ce `.txt` a votre agent IA (upload direct, attachement dans un prompt, etc.).

---

## Prerequis
- Python 3.11 ou plus recent.
- `pip` ou un gestionnaire equivalent (Poetry/PDM pris en charge via le `Makefile`).
- Un IDE Python (PyCharm, VS Code) ou un terminal.
- Pour la compilation d'executables : PyInstaller 6+.

---

## Guide complet : installation et compilation d'un .exe depuis un IDE

### 0. Cloner le depot
```bash
git clone https://github.com/Donj63000/Code-Extractor.git
cd Code-Extractor
```

### 1. Preparations dans l'IDE
1. Ouvrez le dossier `Code-Extractor` dans votre IDE.
2. Creez (ou selectionnez) un interpreteur Python 3.11+.
   - PyCharm : `File > Settings > Project > Python Interpreter > Add > Virtualenv`.
   - VS Code : `Python: Select Interpreter` puis `Create Environment`.

### 2. Installer les dependances
Dans le terminal integre a l'IDE :
```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```
Vous n'avez pas de `requirements.txt` ? Lancez `make install` (detecte Poetry/PDM/requirements) ou installez manuellement les paquets utilises dans `main2.0.py`.

### 3. Lancer le programme en mode developpement
1. Selectionnez `main2.0.py` comme script principal.
2. Configurez vos run configurations (PyCharm : clic droit > Run, VS Code : bouton Run and Debug).
3. Verifiez que l'interface liste bien l'arborescence et que vous pouvez exporter un `.txt`.

### 4. Generer un fichier texte complet
1. Choisissez les repertoires/fichiers a inclure.
2. Cliquez sur le bouton d'export (selon l'interface).
3. Ouvrez le `.txt` genere pour verifier que chaque fichier est precede de son chemin relatif.
4. Fournissez ce `.txt` a votre agent IA / connecteur GitHub.

### 5. Compiler un executable avec PyInstaller
1. Installez PyInstaller dans votre environnement virtuel :
   ```bash
   python -m pip install pyinstaller
   ```
2. Choisissez le `.spec` approprie :
   - `Extractor2.0.spec` : interface principale d'extraction.
   - `main.spec` : point d'entree historique.
   - `CodeViewer1.0.spec` : viewer oriente consultation.
3. Lancez la compilation depuis le terminal de l'IDE :
   ```bash
   pyinstaller Extractor2.0.spec
   ```
4. PyInstaller cree un dossier `dist/Extractor2.0/` contenant l'executable et ses ressources.
5. Testez l'executable en double-cliquant dessus ou via la ligne de commande pour valider qu'il genere bien votre `.txt`.

### 6. Nettoyage et rebuild (optionnel)
- `make clean` : supprime `build/`, `dist/` et les `__pycache__`.
- `make build` : relance la generation des artefacts (utilise PyInstaller si disponible).

---

## Conseils pratiques
- Ajoutez dans `.gitignore` les repertoires qui ne doivent jamais sortir (secrets, dumps, gros binaires).
- Construisez plusieurs exports (par module, par microservice) si votre depot est volumineux.
- Documentez dans `INSTRUCTIONS.md` comment regenerer l'executable pour votre equipe.
- Remontez vos besoins dans les issues GitHub afin d'orienter les prochaines evolutions (UI, automatisations, CLI).

---

## Etat actuel
Le projet est actif mais encore en construction. Certaines parties de l'interface et des scripts `.spec` vont evoluer. Si vous tombez sur un bug ou un scenario non couvert, ouvrez une issue avec :
- le contexte (OS, version Python),
- la commande lancee,
- le resultat attendu vs observe.

Merci pour vos retours et bonne extraction !
