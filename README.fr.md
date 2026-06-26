[![中文](https://img.shields.io/badge/lang-zh--CN-red)](README.md)
[![English](https://img.shields.io/badge/lang-en-blue)](README.en.md)
[![Русский](https://img.shields.io/badge/lang-ru-lightgrey)](README.ru.md)
[![日本語](https://img.shields.io/badge/lang-ja-green)](README.ja.md)
[![한국어](https://img.shields.io/badge/lang-ko-orange)](README.ko.md)
[![Français](https://img.shields.io/badge/lang-fr-yellow)](README.fr.md)

# Patient Record Organizer

Organisateur intelligent de dossiers patients — classe, extrait et structure automatiquement les documents médicaux dispersés (photos, PDF, Word, texte) en rapports standardisés HTML/Markdown/DOCX/XLSX.

**Pipeline principal**: Fichiers bruts → OCR (MinerU batch/single + DeepSeek-OCR) → Anonymisation → Extraction structurée LLM → Agrégation → Génération de rapports

Merci ❤️ à la communauté 小胰宝 (Xiaoyibao) et aux contributeurs open-source.

---

## Démarrage rapide

### 1. Installation des dépendances

```bash
# Option 1: pyproject.toml (recommandé — gestion auto du venv + lockfile)
uv sync

# Option 2: pip
pip install -r requirements.txt
```

### 2. Exécution du pipeline

```bash
# Option 1: uv run (utilise .venv automatiquement, pas d'activation manuelle)
uv run ./xyb process /path/to/dossier/ --patient P001 --format all

# Option 2: activer le venv puis exécuter
source .venv/bin/activate
./xyb process /path/to/dossier/ --patient P001 --format all

# Option 3: appel python direct
python3 scripts/v2/pipeline_v2.py \
  --input-dir /path/to/dossier/ \
  --output-dir /path/to/output/ \
  --patient-id P001 \
  --format all --open
```

> **Note** : `uv sync` crée un environnement virtuel `.venv` et installe toutes les dépendances.
> Ensuite, vous pouvez utiliser `uv run <commande>` (sans activation manuelle) ou activer l'environnement d'abord.

### 3. Configuration des clés API

```bash
cp .env.example .env
```

Clés requises :

| Service | Usage | Variable d'env |
|---------|-------|---------------|
| **MinerU** | OCR images/PDF (principal) | `MINERU_API_KEY` / `MINERU_TOKEN` |
| **SiliconFlow** | Extraction LLM + DeepSeek-OCR | `OCR_API_KEY` / `OCR_BASE_URL` |
| **StepFun** | LLM de secours | `STEP_API_KEY` |

Optionnel :

- `OPENAI_API_KEY` — LLM alternatif (openai)
- `STEP_API_KEY` — Transcription ASR

### 3. Exécution des tests

```bash
pytest tests/ -v
```

---

## Utilisation

### CLI (en un clic)

```bash
./xyb process /path/to/dossier/ --patient P001 --format all --open
```

Paramètres :

| Option | Description |
|--------|------------|
| `--patient` | ID patient (défaut: P_report_mess) |
| `--format` | Format sortie : `html` / `md` / `docx` / `xlsx` / `all` |
| `--open` | Ouvrir HTML automatiquement |
| `--skip-ocr` | Sauter l'OCR (.md seulement) |
| `--model` | Modèle LLM, ex. `stepfun:step-3.5-flash` |
| `--force` | Ignorer les avertissements |

### Pipeline direct

```bash
python3 scripts/v2/pipeline_v2.py \
  --input-dir /path/to/dossier/ \
  --output-dir /path/to/output/ \
  --patient-id P001 \
  --format all --open
```

### OCR fichier unique

```bash
python3 scripts/ocr_single.py rapport.jpg -o result.md
python3 scripts/ocr_single.py scan.pdf --engine deepseek --retries 5
```

---

## Sorties

| Fichier | Format | Description |
|---------|--------|------------|
| `report.html` | HTML | Rapport interactif |
| `case_report.md` | Markdown | Rapport texte |
| `report.docx` | Word | Document Office |
| `report.xlsx` | Excel | Tableur multi-feuilles |
| `profile.json` | JSON | Données patient agrégées |
| `mdt_analysis.json` | JSON | Analyse MDT |
| `mappings.json` | JSON | Correspondance d'anonymisation |

---

## Structure du rapport

```
Page 1 : Couverture + Aperçu (compréhension en 1 min)
Page 2 : Chronologie du traitement
Page 3 : Tendances des analyses
Page 4 : Pathologie et génétique
Page 5 : Schéma thérapeutique
Page 6 : Imagerie
Page 7 : Points d'attention
Page 8 : Questions pour la consultation
Page 9 : Index des pièces jointes
```

---

## Fonctionnalités

- **Zéro configuration** — pointez un dossier et exécutez
- **Entrée multi-format** — photos, scans, PDF texte, Word, texte brut
- **Routage OCR intelligent** — peu de fichiers → single MinerU (3 tentatives) ; grand PDF (>10 p.) ou nombreux fichiers (>50) → batch MinerU (≤50/lot, téléchargement parallèle) ; chaîne de secours : DeepSeek-OCR → PyMuPDF
- **LLM 1M de contexte** — texte intégral sans troncature ; sortie max_tokens=256K
- **Classification à deux niveaux** — règles mots-clés + LLM sémantique
- **Anonymisation automatique** — Nom→`[NAME_N]`, Tél→`[PHONE_N]` avec correspondance réversible
- **Cache incrémental** — déduplication SHA256 ; cache auto OCR+LLM
- **Sortie multi-format** — HTML + Markdown + DOCX + XLSX

---

## Sécurité et confidentialité

- ❌ Pas de diagnostic, pas de recommandation médicale
- ✅ "Classement et archivage structuré" uniquement
- **Anonymisation automatique** avec correspondance réversible
- **Avertissement** inclus dans toutes les sorties

---

## License

MIT
