# Instructions de build, tests et CI (Python & Java/Maven)

## Prérequis locaux
- **Python** ≥ 3.11 + `pip`
- **Java** JDK 17 (Temurin/Adoptium recommandé) + **Maven** (ou `mvnw`)
- Optionnel : `make` pour utiliser les commandes universelles.

## Commandes universelles
Si vous avez `make`, utilisez simplement :
- `make install`  – installe les dépendances (Python si `pyproject.toml`/`requirements*.txt` est présent, Maven si `pom.xml` existe)
- `make test`     – lance les tests (pytest et/ou maven surefire)
- `make lint`     – vérifications de style (ruff/black côté Python, checkstyle côté Maven si configuré)
- `make build`    – produit les artefacts (`dist/` pour Python, `target/*.jar` pour Maven)
- `make clean`    – nettoyage

Sans `make` :
- **Python** : `pip install -r requirements.txt` (ou `pip install -e .[dev]`) puis `pytest`
- **Maven**  : `./mvnw -B -ntp verify` (ou `mvn -B -ntp verify`)

## Arborescence indicative
- Projet Python détecté si : `pyproject.toml` **ou** `requirements*.txt`
- Projet Maven détecté si : `pom.xml` (wrapper `mvnw` conseillé)

## CI/CD
Une pipeline GitHub Actions commune existe dans `.github/workflows/ci.yml`.
Elle **détecte automatiquement** s’il s’agit d’un projet Python et/ou Maven et
n’exécute que les jobs pertinents. Voir le fichier pour les détails (cache, artefacts, release).
