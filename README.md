# 🕷️ Python Scraper & SEO Analyzer

Outils Python pour scraper des images et analyser le SEO d'un site web complet.

## 📦 Installation

```bash
pip install -r requirements.txt
```

**Pour l'export PDF :**
```bash
pip install weasyprint
```

> ⚠️ **Note pour weasyprint :** Sur Linux, des dépendances système peuvent être nécessaires :
> ```bash
> sudo apt-get install libpango-1.0-0 libharfbuzz0b libffi-dev
> ```

---

## 🚀 Lancer tous les outils d'un coup

```bash
# Analyse SEO + Téléchargement images + Export PDF automatique
python3 run_all.py https://example.com

# Avec dossier de sortie personnalisé
python3 run_all.py https://example.com -o ./rapport

# Uniquement l'analyse SEO
python3 run_all.py https://example.com --seo-only

# Uniquement les images
python3 run_all.py https://example.com --images-only

# Avec rate limiting (recommandé pour les petits sites)
python3 run_all.py https://example.com -d 0.5

# Vérifier les liens brisés
python3 run_all.py https://example.com -l

# Avec données PageSpeed Insights
python3 run_all.py https://example.com --pagespeed

# Désactiver l'export PDF
python3 run_all.py https://example.com --no-pdf
```

### Options de `run_all.py`

| Option | Description |
|--------|-------------|
| `url` | URL du site (obligatoire) |
| `-o, --output` | Dossier de sortie des rapports |
| `-p, --max-pages` | Max pages (défaut: 100, 0=illimité) |
| `-t, --timeout` | Timeout en secondes |
| `-d, --delay` | Délai entre requêtes (défaut: 0) |
| `-l, --check-links` | Vérifier liens brisés |
| `-v, --verbose` | Mode détaillé |
| `--pagespeed` | Récupérer données PageSpeed Insights |
| `--no-pdf` | Désactiver l'export PDF |
| `--seo-only` | Uniquement analyse SEO |
| `--images-only` | Uniquement téléchargement images |

---

## 🖼️ Image Scraper

Télécharge toutes les images d'un site en crawlant toutes les pages.

### Utilisation

```bash
# Crawler tout le site
python3 image_scraper.py https://example.com

# Avec dossier personnalisé
python3 image_scraper.py https://example.com -o ~/mes-images

# Avec rate limiting
python3 image_scraper.py https://example.com -d 0.5

# Mode verbose
python3 image_scraper.py https://example.com -v
```

### Options

| Option | Description |
|--------|-------------|
| `url` | URL du site (obligatoire) |
| `-o, --output` | Dossier de destination |
| `-p, --max-pages` | Max pages à crawler (défaut: 100, 0=illimité) |
| `-t, --timeout` | Timeout en secondes |
| `-d, --delay` | Délai entre requêtes |
| `-v, --verbose` | Mode détaillé |

---

## 🔍 SEO Analyzer

Analyseur SEO complet : sitemap, arborescence, title, meta, H1-H6, images, liens...

### Utilisation

```bash
# Analyse complète (rapports dans ~/Téléchargements/nom-du-site)
python3 seo_analyzer.py https://example.com

# Avec dossier personnalisé
python3 seo_analyzer.py https://example.com -o ./rapport-seo

# Avec rate limiting
python3 seo_analyzer.py https://example.com -d 0.5

# Pages illimitées
python3 seo_analyzer.py https://example.com -p 0

# Vérifier les liens brisés (plus lent)
python3 seo_analyzer.py https://example.com -l

# Avec données PageSpeed Insights
python3 seo_analyzer.py https://example.com --pagespeed

# Mode verbose
python3 seo_analyzer.py https://example.com -v

# Désactiver l'export PDF
python3 seo_analyzer.py https://example.com --no-pdf

# Uniquement les images
python3 seo_analyzer.py https://example.com --images-only --image-dest ~/images
```

### Options

| Option | Description |
|--------|-------------|
| `url` | URL du site (obligatoire) |
| `-o, --output` | Dossier pour exports |
| `-p, --max-pages` | Max pages (défaut: 100, 0=illimité) |
| `-t, --timeout` | Timeout en secondes |
| `-d, --delay` | Délai entre requêtes |
| `-l, --check-links` | Vérifier liens brisés |
| `-v, --verbose` | Mode détaillé |
| `--pagespeed` | Récupérer données PageSpeed Insights |
| `--no-pdf` | Désactiver l'export PDF |
| `--images-only` | Mode scraper d'images |
| `--image-dest` | Dossier pour images |

### Métriques analysées

| Catégorie | Données |
|-----------|---------|
| **Sitemap** | URLs, lastmod, changefreq, priority |
| **On-page** | Title, meta description, keywords, canonical |
| **Structure** | H1, H2, H3, word count |
| **Images** | Count, alt missing, dimensions, loading |
| **Liens** | Internes, externes, **liens brisés** |
| **Social** | Open Graph, Twitter Card |
| **Technique** | Status code, load time, robots, lang |
| **CMS** | WordPress, Shopify, Wix, etc. |
| **Score** | Score SEO synthétique /100 |
| **Mots-clés** | **Densité de mots-clés (Top 10 pages)** |
| **Performance** | **API PageSpeed Insights (optionnel)** |

### Fichiers exportés

Par défaut dans `~/Téléchargements/nom-du-site/` :

| Fichier | Description |
|---------|-------------|
| `resume_seo.html` | **Rapport HTML coloré** lisible dans le navigateur |
| `resume_seo.txt` | Résumé texte avec points d'attention |
| `rapport_seo.pdf` | **Rapport PDF professionnel** (sans PageSpeed) |
| `seo_audit.csv` | Tableau récapitulatif de toutes les pages |
| `seo_audit.json` | Données complètes (pages + images + sitemap) |
| `images.csv` | Liste de toutes les images avec attributs |

---

## 🆕 Nouvelles fonctionnalités

### 🚀 API PageSpeed Insights
- Récupère les scores de performance via l'API Google (performance, accessibilité, SEO, bonnes pratiques)
- Métriques Core Web Vitals : FCP, LCP, SI, TTI, TBT, CLS
- Option `--pagespeed` pour activer (page d'accueil uniquement)
- Boutons dans le rapport HTML vers l'analyse complète

### 🔗 Vérificateur de liens cassés
- Détection automatique des liens brisés (status 4xx, 5xx, timeout)
- Option `-l` ou `--check-links` pour activer
- Liste détaillée dans le rapport HTML avec page source

### 🔑 Densité de mots-clés
- Analyse automatique sur toutes les pages
- Top 10 mots-clés par page (hors stop words)
- Section dédiée dans le rapport HTML pour les 10 pages les plus importantes
- Tableau avec occurrences, densité et visualisation graphique

### 📄 Export PDF automatique
- Généré automatiquement à chaque analyse (sauf `--no-pdf`)
- Rapport professionnel au format A4
- Inclut : score SEO, vue d'ensemble, qualité du contenu, images, performance, audit SEO, densité de mots-clés, liens cassés
- N'inclut PAS les sections PageSpeed (pour un rapport client plus léger)

---

## 📊 Exemple de sortie

```
======================================================================
🔍 ANALYSEUR SEO COMPLET
======================================================================

Domaine : example.com
Max pages : 100
⏱️  Rate limiting : 0.5s entre les requêtes

Découverte URLs: 100%|████████████████| 87/87 [00:21<00:00, 4.12page/s]

📄 87 pages trouvées à analyser
🗺️  Sitemap : 87 URLs trouvées

Analyse: 100%|████████████████| 87/87 [00:45<00:00, 1.92page/s]

🚀 Récupération des données PageSpeed Insights...
  Performance: 85/100
  Accessibilité: 92/100
  SEO: 95/100

📝 Résumé texte : /home/user/Téléchargements/example_com/resume_seo.txt
🌐 Rapport HTML : /home/user/Téléchargements/example_com/resume_seo.html
📄 Rapport PDF : /home/user/Téléchargements/example_com/rapport_seo.pdf

======================================================================
RÉSUMÉ DE L'ANALYSE SEO
======================================================================

Site analysé : https://example.com
Date du rapport : 08/03/2026 à 11:34

📄 PAGES ANALYSÉES : 87
   ⚠️  Pages sans meta description : 12
   ⚠️  Pages sans H1 : 3
   ⚠️  Pages avec plusieurs H1 : 5
   🔗 Liens cassés détectés : 7

🖼️  IMAGES : 234
   ⚠️  Images sans alt : 45

🗺️  SITEMAP : 87 URLs trouvées
📦 CMS détecté : WordPress

⚡ PERFORMANCE : Temps de chargement moyen : 1.23s
   ⚠️  Pages lentes (>3s) : 4

🔗 LIENS : 523 liens externes au total

🔑 MOTS-CLÉS (Top 10 pages) :
      Page: "Accueil - Example Services"
      - example : 15x (2.3%)
      - services : 12x (1.8%)
      - solutions : 10x (1.5%)
      ...

======================================================================

📊 SCORE SEO : 72/100 (Moyen)
⏱️  Durée totale : 68.5 secondes
```

---

## 🛠️ Fonctionnalités communes

- ✅ **Respect du robots.txt** - Ne crawl pas les pages interdites
- ✅ **Rate limiting** - Délai configurable entre les requêtes (`-d`)
- ✅ **Liens internes uniquement** - Ne sort pas du domaine cible
- ✅ **Barre de progression** - Affiche l'avancement réel
- ✅ **Gestion des erreurs** - Timeout, 404, etc.
- ✅ **User-Agent** - Pour éviter les blocages
- ✅ **Support max-pages=0** - Analyse illimitée

---

## 📝 Licence

MIT
