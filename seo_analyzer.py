#!/usr/bin/env python3
"""
Analyseur SEO complet pour site web.
Récupère sitemap, arborescence, audit SEO, images, liens...
"""

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# Constants
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico'}

# Global pour le rate limiting
_request_delay = 0.0
_last_request_time = 0.0

# Robots.txt parser cache
_robots_parsers = {}


def set_request_delay(delay: float):
    """Configure le délai entre les requêtes."""
    global _request_delay
    _request_delay = delay


def rate_limited_request(url: str, **kwargs):
    """Effectue une requête HTTP avec rate limiting."""
    global _last_request_time

    elapsed = time.time() - _last_request_time
    if elapsed < _request_delay:
        time.sleep(_request_delay - elapsed)

    try:
        response = requests.get(url, **kwargs)
        _last_request_time = time.time()
        return response
    except requests.RequestException:
        _last_request_time = time.time()
        raise


def get_robots_parser(url: str) -> RobotFileParser:
    """Récupère ou crée un parser robots.txt pour un domaine."""
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"
    
    if domain not in _robots_parsers:
        rp = RobotFileParser()
        robots_url = f"{domain}/robots.txt"
        try:
            rp.set_url(robots_url)
            rp.read()
        except Exception:
            pass  # Si robots.txt n'existe pas, on continue quand même
        _robots_parsers[domain] = rp
    
    return _robots_parsers[domain]


def can_fetch(url: str) -> bool:
    """Vérifie si l'URL peut être fetchée selon robots.txt."""
    rp = get_robots_parser(url)
    return rp.can_fetch("*", url) if rp else True


def detect_cms(html: str, url: str = "") -> str:
    """Détecte le CMS utilisé par le site."""
    html_lower = html.lower()
    
    # WordPress
    if any(pattern in html_lower for pattern in [
        '/wp-content/', '/wp-includes/', 'wp-json',
        'wordpress', 'wp-emoji'
    ]):
        return "WordPress"
    
    # Shopify
    if any(pattern in html_lower for pattern in [
        'cdn.shopify.com', 'shopify_common', 'myshopify'
    ]):
        return "Shopify"
    
    # Wix
    if any(pattern in html_lower for pattern in [
        'wix.com', 'wixstatic.com', 'parallax',
        'data-wix'
    ]):
        return "Wix"
    
    # Squarespace
    if any(pattern in html_lower for pattern in [
        'squarespace.com', 'static.squarespace'
    ]):
        return "Squarespace"
    
    # Webflow
    if any(pattern in html_lower for pattern in [
        'webflow.com', 'assets-global.website-files'
    ]):
        return "Webflow"
    
    # Joomla
    if any(pattern in html_lower for pattern in [
        '/media/jui/', '/components/com_', 'joomla'
    ]):
        return "Joomla"
    
    # Drupal
    if any(pattern in html_lower for pattern in [
        '/sites/default/files/', 'drupal.js'
    ]):
        return "Drupal"
    
    # PrestaShop
    if any(pattern in html_lower for pattern in [
        '/themes/prestashop', 'prestashop'
    ]):
        return "PrestaShop"
    
    # Ghost
    if any(pattern in html_lower for pattern in [
        '/ghost/', 'ghost-content'
    ]):
        return "Ghost"

    return "Inconnu / Site statique"


@dataclass
class KeywordDensity:
    """Données de densité de mots-clés."""
    word: str
    count: int
    density: float


@dataclass
class PageSpeedData:
    """Données de performance PageSpeed Insights."""
    performance_score: int = 0
    accessibility_score: int = 0
    best_practices_score: int = 0
    seo_score: int = 0
    pwa_score: int = 0
    first_contentful_paint: str = ""
    largest_contentful_paint: str = ""
    speed_index: str = ""
    time_to_interactive: str = ""
    total_blocking_time: str = ""
    cumulative_layout_shift: str = ""
    error: str = ""


def fetch_pagespeed_insights(url: str, strategy: str = "desktop") -> PageSpeedData:
    """
    Récupère les données de performance via l'API PageSpeed Insights de Google.

    Args:
        url: URL à analyser
        strategy: 'desktop' ou 'mobile'

    Returns:
        PageSpeedData avec les scores et métriques
    """
    pagespeed_data = PageSpeedData()

    try:
        # API PageSpeed Insights (sans clé API - limité mais fonctionne)
        api_url = f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={url}&strategy={strategy}"

        response = requests.get(api_url, timeout=30)

        if response.status_code == 403:
            pagespeed_data.error = "Clé API requise pour PageSpeed Insights"
            return pagespeed_data

        response.raise_for_status()
        data = response.json()

        # Extraire les scores
        categories = data.get('lighthouseResult', {}).get('categories', {})
        pagespeed_data.performance_score = int(categories.get('performance', {}).get('score', 0) * 100) if categories.get('performance') else 0
        pagespeed_data.accessibility_score = int(categories.get('accessibility', {}).get('score', 0) * 100) if categories.get('accessibility') else 0
        pagespeed_data.best_practices_score = int(categories.get('best-practices', {}).get('score', 0) * 100) if categories.get('best-practices') else 0
        pagespeed_data.seo_score = int(categories.get('seo', {}).get('score', 0) * 100) if categories.get('seo') else 0
        pagespeed_data.pwa_score = int(categories.get('pwa', {}).get('score', 0) * 100) if categories.get('pwa') else 0

        # Extraire les métriques de performance
        audits = data.get('lighthouseResult', {}).get('audits', {})

        if audits.get('first-contentful-paint', {}).get('displayValue'):
            pagespeed_data.first_contentful_paint = audits['first-contentful-paint']['displayValue']

        if audits.get('largest-contentful-paint', {}).get('displayValue'):
            pagespeed_data.largest_contentful_paint = audits['largest-contentful-paint']['displayValue']

        if audits.get('speed-index', {}).get('displayValue'):
            pagespeed_data.speed_index = audits['speed-index']['displayValue']

        if audits.get('interactive', {}).get('displayValue'):
            pagespeed_data.time_to_interactive = audits['interactive']['displayValue']

        if audits.get('total-blocking-time', {}).get('displayValue'):
            pagespeed_data.total_blocking_time = audits['total-blocking-time']['displayValue']

        if audits.get('cumulative-layout-shift', {}).get('displayValue'):
            pagespeed_data.cumulative_layout_shift = audits['cumulative-layout-shift']['displayValue']

    except requests.RequestException as e:
        pagespeed_data.error = f"Erreur API: {str(e)}"
    except Exception as e:
        pagespeed_data.error = f"Erreur: {str(e)}"

    return pagespeed_data


def analyze_keyword_density(html_content: str, top_n: int = 10) -> list[KeywordDensity]:
    """
    Analyse la densité de mots-clés dans un contenu HTML.

    Args:
        html_content: Contenu HTML à analyser
        top_n: Nombre de mots-clés à retourner

    Returns:
        Liste de KeywordDensity triée par fréquence
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    # Supprimer les scripts et styles
    for script in soup(['script', 'style', 'nav', 'footer', 'header']):
        script.decompose()

    # Extraire le texte
    text = soup.get_text(separator=' ')

    # Nettoyer et tokeniser
    text = text.lower()
    words = re.findall(r'\b[a-zA-ZÀ-ÿ0-9]{3,}\b', text)

    # Stop words en français et anglais
    stop_words = {
        'the', 'and', 'for', 'with', 'that', 'this', 'from', 'have', 'been', 'were', 'are',
        'le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'et', 'est', 'en', 'dans', 'sur',
        'pour', 'par', 'plus', 'aux', 'que', 'qui', 'avec', 'leur', 'leurs', 'sont', 'tous',
        'toutes', 'tout', 'faire', 'fait', 'also', 'will', 'just', 'there', 'their', 'what',
        'you', 'your', 'our', 'was', 'but', 'not', 'they', 'them', 'its', 'has', 'had', 'his',
        'her', 'she', 'he', 'can', 'may', 'would', 'could', 'should', 'about', 'into', 'more',
        'some', 'other', 'than', 'then', 'these', 'those', 'such', 'only', 'through', 'where',
        'when', 'which', 'while', 'after', 'before', 'between', 'both', 'each', 'get', 'got',
        'very', 'even', 'well', 'back', 'still', 'way', 'take', 'because', 'come', 'came',
        'going', 'goes', 'gone', 'give', 'given', 'good', 'great', 'know', 'like', 'look',
        'make', 'made', 'many', 'most', 'much', 'need', 'new', 'now', 'old', 'one', 'own',
        'say', 'said', 'see', 'set', 'show', 'small', 'so', 'too', 'two', 'under', 'up',
        'use', 'used', 'using', 'want', 'work', 'year', 'years'
    }

    # Filtrer les stop words
    filtered_words = [w for w in words if w not in stop_words]

    # Compter les occurrences
    from collections import Counter
    word_counts = Counter(filtered_words)

    # Calculer la densité
    total_words = len(filtered_words) if filtered_words else 1
    top_words = word_counts.most_common(top_n * 2)

    result = []
    for word, count in top_words:
        if len(word) >= 3 and len(result) < top_n:
            density = (count / total_words) * 100
            result.append(KeywordDensity(word=word, count=count, density=round(density, 2)))

    return result


@dataclass
class PageData:
    """Données SEO d'une page."""
    url: str
    status_code: int = 0
    load_time: float = 0.0
    title: str = ""
    meta_description: str = ""
    meta_keywords: str = ""
    canonical: str = ""
    h1: list[str] = field(default_factory=list)
    h2: list[str] = field(default_factory=list)
    h3: list[str] = field(default_factory=list)
    word_count: int = 0
    images_count: int = 0
    images_missing_alt: int = 0
    internal_links: int = 0
    external_links: int = 0
    broken_links: list[str] = field(default_factory=list)
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    twitter_card: str = ""
    robots: str = ""
    lang: str = ""
    error: str = ""
    cms_detected: str = ""
    keyword_density: list[KeywordDensity] = field(default_factory=list)
    pagespeed: Optional[PageSpeedData] = None


@dataclass
class ImageData:
    """Données d'une image."""
    url: str
    src: str
    alt: str = ""
    title: str = ""
    width: str = ""
    height: str = ""
    loading: str = ""
    page_url: str = ""


@dataclass
class SiteMapData:
    """Données du sitemap."""
    url: str
    lastmod: str = ""
    changefreq: str = ""
    priority: str = ""


def calculate_seo_score(pages: list[PageData], images: list[ImageData]) -> int:
    """Calcule un score SEO synthétique sur 100."""
    if not pages:
        return 0

    score = 100
    total_pages = len(pages)

    # Title manquant (-5 par page, max -20)
    no_title = sum(1 for p in pages if not p.title)
    score -= min(20, (no_title / total_pages) * 100 * 0.2)

    # Meta description manquante (-3 par page, max -15)
    no_meta = sum(1 for p in pages if not p.meta_description)
    score -= min(15, (no_meta / total_pages) * 100 * 0.15)

    # H1 manquant (-5 par page, max -20)
    no_h1 = sum(1 for p in pages if not p.h1)
    score -= min(20, (no_h1 / total_pages) * 100 * 0.2)

    # H1 multiples (-2 par page, max -10)
    multi_h1 = sum(1 for p in pages if len(p.h1) > 1)
    score -= min(10, (multi_h1 / total_pages) * 100 * 0.1)

    # Images sans alt (-1 par image, max -15)
    if images:
        missing_alt = sum(1 for i in images if not i.alt)
        score -= min(15, (missing_alt / len(images)) * 100 * 0.15)

    # Pages avec erreurs (-5 par page, max -20)
    errors = sum(1 for p in pages if p.error or p.status_code != 200)
    score -= min(20, (errors / total_pages) * 100 * 0.2)

    # Pages lentes (>3s) (-2 par page, max -10)
    slow = sum(1 for p in pages if p.load_time > 3)
    score -= min(10, (slow / total_pages) * 100 * 0.1)

    return max(0, min(100, int(score)))


def get_base_domain(url: str) -> str:
    """Récupère le domaine de base."""
    parsed = urlparse(url)
    return parsed.netloc


def is_internal_link(url: str, base_domain: str) -> bool:
    """Vérifie si un lien est interne."""
    parsed = urlparse(url)
    return parsed.netloc == base_domain or parsed.netloc == ''


def fetch_sitemap(url: str, _visited: set = None) -> list[SiteMapData]:
    """Récupère et parse le sitemap.xml."""
    # Éviter les boucles infinies avec les sitemaps qui se référencent
    if _visited is None:
        _visited = set()
    
    # Normaliser l'URL pour la détection de doublons
    normalized = url.rstrip('/').lower()
    if normalized in _visited:
        return []
    _visited.add(normalized)
    
    parsed = urlparse(url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

    # Essayer aussi sitemap_index.xml
    sitemap_index_url = f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml"

    sitemaps_data = []

    for test_url in [sitemap_url, sitemap_index_url]:
        try:
            response = rate_limited_request(test_url, headers=HEADERS, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'xml')

                # Sitemap index
                for sitemap in soup.find_all('sitemap'):
                    loc = sitemap.find('loc')
                    if loc:
                        # Récupérer le sitemap enfant
                        child_data = fetch_sitemap(loc.text, _visited)
                        sitemaps_data.extend(child_data)

                # URLset normal
                for url_tag in soup.find_all('url'):
                    loc = url_tag.find('loc')
                    if loc:
                        data = SiteMapData(url=loc.text)
                        lastmod = url_tag.find('lastmod')
                        changefreq = url_tag.find('changefreq')
                        priority = url_tag.find('priority')
                        if lastmod:
                            data.lastmod = lastmod.text
                        if changefreq:
                            data.changefreq = changefreq.text
                        if priority:
                            data.priority = priority.text
                        sitemaps_data.append(data)

                break
        except requests.RequestException:
            continue

    return sitemaps_data


def analyze_page(url: str, base_domain: str, check_links: bool = False) -> tuple[PageData, list[ImageData]]:
    """Analyse le SEO d'une page."""
    page = PageData(url=url)
    images = []

    start_time = time.time()

    try:
        # Vérifier robots.txt
        if not can_fetch(url):
            page.error = "Bloqué par robots.txt"
            page.load_time = time.time() - start_time
            return page, images
        
        # Utiliser rate_limited_request au lieu de requests.get
        response = rate_limited_request(url, headers=HEADERS, timeout=15)
        page.load_time = time.time() - start_time
        page.status_code = response.status_code

        if response.status_code != 200:
            page.error = f"Status code: {response.status_code}"
            return page, images

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Détection du CMS
        page.cms_detected = detect_cms(response.text, url)

        # Title
        title_tag = soup.find('title')
        if title_tag:
            page.title = title_tag.get_text(strip=True)
        
        # Meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            page.meta_description = meta_desc['content']
        
        # Meta keywords
        meta_kw = soup.find('meta', attrs={'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            page.meta_keywords = meta_kw['content']
        
        # Canonical
        canonical = soup.find('link', rel='canonical')
        if canonical and canonical.get('href'):
            page.canonical = canonical['href']
        
        # Headings
        for h1 in soup.find_all('h1'):
            text = h1.get_text(strip=True)
            if text:
                page.h1.append(text)
        
        for h2 in soup.find_all('h2'):
            text = h2.get_text(strip=True)
            if text:
                page.h2.append(text)
        
        for h3 in soup.find_all('h3'):
            text = h3.get_text(strip=True)
            if text:
                page.h3.append(text)
        
        # Word count (texte visible)
        for script in soup(['script', 'style']):
            script.decompose()
        text = soup.get_text()
        words = re.findall(r'\b\w+\b', text.lower())
        page.word_count = len(words)
        
        # Images
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or ''
            if src:
                img_data = ImageData(
                    url=urljoin(url, src),
                    src=src,
                    alt=img.get('alt', ''),
                    title=img.get('title', ''),
                    width=img.get('width', ''),
                    height=img.get('height', ''),
                    loading=img.get('loading', ''),
                    page_url=url
                )
                images.append(img_data)
                page.images_count += 1
                if not img.get('alt'):
                    page.images_missing_alt += 1
        
        # Open Graph
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            page.og_title = og_title['content']
        
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            page.og_description = og_desc['content']
        
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            page.og_image = og_image['content']
        
        # Twitter Card
        twitter_card = soup.find('meta', attrs={'name': 'twitter:card'})
        if twitter_card and twitter_card.get('content'):
            page.twitter_card = twitter_card['content']
        
        # Robots
        robots = soup.find('meta', attrs={'name': 'robots'})
        if robots and robots.get('content'):
            page.robots = robots['content']
        
        # Lang
        html_tag = soup.find('html')
        if html_tag and html_tag.get('lang'):
            page.lang = html_tag['lang']

        # Densité de mots-clés
        page.keyword_density = analyze_keyword_density(response.text, top_n=10)

        # Liens
        for a in soup.find_all('a', href=True):
            href = a['href']

            # Ignorer ancres, mailto, tel, javascript
            if href.startswith(('#', 'mailto:', 'tel:', 'javascript:', 'data:')):
                continue

            full_url = urljoin(url, href)
            parsed = urlparse(full_url)

            if is_internal_link(full_url, base_domain):
                page.internal_links += 1

                # Vérifier si lien brisé (optionnel, lent)
                if check_links:
                    try:
                        check = rate_limited_request(full_url, timeout=5, allow_redirects=True)
                        if check.status_code >= 400:
                            page.broken_links.append(full_url)
                    except requests.RequestException:
                        page.broken_links.append(full_url)
            else:
                page.external_links += 1

    except requests.RequestException as e:
        page.error = str(e)
        page.load_time = time.time() - start_time

    return page, images


def discover_all_urls(
    start_url: str,
    max_pages: int = 100,
    timeout: int = 5
) -> tuple[list[str], list[SiteMapData]]:
    """Découvre toutes les URLs du site avant l'analyse."""
    base_domain = get_base_domain(start_url)

    # Récupérer le sitemap en premier
    sitemap_data = fetch_sitemap(start_url)
    sitemap_urls = set()
    for item in sitemap_data:
        clean_url = item.url.rstrip('/')
        if is_internal_link(clean_url, base_domain):
            sitemap_urls.add(clean_url)

    crawled_urls = set()
    pages_to_visit = [start_url.rstrip('/')]
    pages_to_visit.extend([u for u in sitemap_urls if u != start_url.rstrip('/')])
    visited = set()
    
    # Support max_pages = 0 pour illimité
    actual_max = max_pages if max_pages > 0 else float('inf')

    with tqdm(total=actual_max if max_pages > 0 else None, desc="Découverte URLs", unit="page", disable=max_pages==0) as pbar:
        while pages_to_visit and len(visited) < actual_max:
            current_url = pages_to_visit.pop(0).rstrip('/')

            if current_url in visited:
                continue

            # Vérifier robots.txt
            if not can_fetch(current_url):
                continue

            visited.add(current_url)
            crawled_urls.add(current_url)
            if max_pages > 0:
                pbar.update(1)

            try:
                response = rate_limited_request(current_url, headers=HEADERS, timeout=timeout)
                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')

                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if href.startswith(('#', 'mailto:', 'tel:', 'javascript:', 'data:')):
                        continue

                    full_url = urljoin(current_url, href)
                    parsed = urlparse(full_url)
                    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip('/')

                    if is_internal_link(full_url, base_domain) and clean_url not in visited:
                        if clean_url not in pages_to_visit and len(crawled_urls) < actual_max:
                            pages_to_visit.append(clean_url)

            except requests.RequestException:
                pass

    return list(crawled_urls)[:max_pages] if max_pages > 0 else list(crawled_urls), sitemap_data


def crawl_site_for_seo(
    start_url: str,
    max_pages: int = 100,
    timeout: int = 10,
    check_links: bool = False,
    verbose: bool = False,
    check_pagespeed: bool = False
) -> tuple[list[PageData], list[ImageData], list[SiteMapData]]:
    """Crawl un site pour analyse SEO complète."""
    base_domain = get_base_domain(start_url)

    print(f"Domaine : {base_domain}")
    print(f"Max pages : {max_pages}")
    print()

    # Phase 1 : Découvrir toutes les URLs
    urls_to_analyze, sitemap_data = discover_all_urls(start_url, max_pages, min(timeout, 5))

    print(f"\n📄 {len(urls_to_analyze)} pages trouvées à analyser")
    if sitemap_data:
        print(f"🗺️  Sitemap : {len(sitemap_data)} URLs")
    print()

    # Phase 2 : Analyser chaque page
    all_pages = []
    all_images = []

    with tqdm(total=len(urls_to_analyze), desc="Analyse", unit="page") as pbar:
        for current_url in urls_to_analyze:
            current_url = current_url.rstrip('/')

            if verbose:
                print(f"\n[{len(all_pages) + 1}/{len(urls_to_analyze)}] {current_url}")

            page, images = analyze_page(current_url, base_domain, check_links)
            all_pages.append(page)
            all_images.extend(images)
            pbar.update(1)

            if verbose:
                title_preview = page.title[:60] + "..." if page.title else "(vide)"
                print(f"  Title: {title_preview}")
                print(f"  H1: {len(page.h1)}, H2: {len(page.h2)}, Images: {page.images_count}")
                if page.error:
                    print(f"  Erreur: {page.error}")

    # Phase 3 : PageSpeed Insights (optionnel, uniquement page d'accueil)
    if check_pagespeed:
        print("\n🚀 Récupération des données PageSpeed Insights...")
        try:
            pagespeed_data = fetch_pagespeed_insights(start_url, strategy="desktop")
            if pagespeed_data and not pagespeed_data.error:
                # Appliquer les données à la page d'accueil
                for page in all_pages:
                    if page.url == start_url.rstrip('/'):
                        page.pagespeed = pagespeed_data
                        break
                print(f"  Performance: {pagespeed_data.performance_score}/100")
                print(f"  Accessibilité: {pagespeed_data.accessibility_score}/100")
                print(f"  SEO: {pagespeed_data.seo_score}/100")
            else:
                print(f"  ⚠️  {pagespeed_data.error if pagespeed_data else 'Erreur inconnue'}")
        except Exception as e:
            print(f"  ⚠️  Erreur PageSpeed: {e}")

    return all_pages, all_images, sitemap_data


def export_to_csv(pages: list[PageData], filepath: Path):
    """Export les résultats en CSV."""
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'URL', 'Status', 'Temps (s)', 'Title', 'Meta Description',
            'H1', 'H2', 'H3', 'Mots', 'Images', 'Images sans alt',
            'Liens internes', 'Liens externes', 'Liens brisés',
            'OG Title', 'OG Description', 'Canonical', 'Lang', 'Erreur'
        ])
        
        for page in pages:
            writer.writerow([
                page.url,
                page.status_code,
                round(page.load_time, 2),
                page.title[:200] if page.title else '',
                page.meta_description[:200] if page.meta_description else '',
                ' | '.join(page.h1[:3]),
                len(page.h2),
                len(page.h3),
                page.word_count,
                page.images_count,
                page.images_missing_alt,
                page.internal_links,
                page.external_links,
                len(page.broken_links),
                page.og_title if page.og_title else '',
                page.og_description if page.og_description else '',
                page.canonical if page.canonical else '',
                page.lang if page.lang else '',
                page.error if page.error else ''
            ])


def export_to_json(pages: list[PageData], images: list[ImageData], sitemap: list[SiteMapData], filepath: Path):
    """Export les résultats en JSON."""
    data = {
        'generated_at': datetime.now().isoformat(),
        'total_pages': len(pages),
        'total_images': len(images),
        'sitemap_urls': len(sitemap),
        'pages': [asdict(p) for p in pages],
        'images': [asdict(i) for i in images],
        'sitemap': [asdict(s) for s in sitemap]
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def export_to_html(
    pages: list[PageData],
    images: list[ImageData],
    sitemap: list[SiteMapData],
    url: str,
    duration: float,
    filepath: Path,
    include_pagespeed: bool = True
):
    """Génère un rapport HTML amélioré pour un rendu client professionnel.

    Nouvelles fonctionnalités :
    - Statistiques de performance détaillées (page la plus rapide/lente, graphique)
    - Audit SEO avancé (metatags, OpenGraph, JSON-LD, Twitter Card)
    - Lien vers Google PageSpeed Insights
    - Design amélioré pour un rendu clé en main
    
    Args:
        include_pagespeed: Si False, exclut la section PageSpeed Insights
    """
    
    # Calcul du score SEO
    score = calculate_seo_score(pages, images)

    # Déterminer la couleur du score
    if score >= 80:
        score_color = "#22c55e"
        score_label = "Excellent"
    elif score >= 60:
        score_color = "#f59e0b"
        score_label = "Moyen"
    elif score >= 40:
        score_color = "#f97316"
        score_label = "À améliorer"
    else:
        score_color = "#ef4444"
        score_label = "Critique"

    # Détection CMS
    cms_counts = {}
    for p in pages:
        if p.cms_detected:
            cms_counts[p.cms_detected] = cms_counts.get(p.cms_detected, 0) + 1
    cms_detected = max(cms_counts.items(), key=lambda x: x[1])[0] if cms_counts else "Inconnu"

    # Calcul des stats
    errors = [p for p in pages if p.error or p.status_code != 200]
    no_title = [p for p in pages if not p.title]
    no_meta = [p for p in pages if not p.meta_description]
    no_h1 = [p for p in pages if not p.h1]
    multi_h1 = [p for p in pages if len(p.h1) > 1]
    missing_alt = [i for i in images if not i.alt]
    slow_pages = [p for p in pages if p.load_time > 3]

    # Stats de performance
    pages_with_time = [p for p in pages if p.load_time > 0]
    if pages_with_time:
        fastest_page = min(pages_with_time, key=lambda p: p.load_time)
        slowest_page = max(pages_with_time, key=lambda p: p.load_time)
        avg_load_time = sum(p.load_time for p in pages_with_time) / len(pages_with_time)
        sorted_by_time = sorted(pages_with_time, key=lambda p: p.load_time)
    else:
        fastest_page = slowest_page = None
        avg_load_time = 0
        sorted_by_time = []

    # Stats SEO avancé
    pages_with_og = [p for p in pages if p.og_title or p.og_description or p.og_image]
    pages_with_twitter = [p for p in pages if p.twitter_card]
    pages_with_canonical = [p for p in pages if p.canonical]

    # Générer l'URL pour PageSpeed Insights (avec URL encodée)
    parsed_url = urlparse(url)
    pagespeed_url = f"https://pagespeed.web.dev/analysis?url={html.escape(url)}"

    # Générer les données pour le graphique
    chart_data = []
    for p in sorted_by_time[:20]:  # Top 20 pages
        chart_data.append({
            'url': p.url[:50] + '...' if len(p.url) > 50 else p.url,
            'time': round(p.load_time, 2)
        })

    # Générer les sections HTML pour les performances
    if fastest_page:
        fastest_title = fastest_page.title[:50] + '...' if fastest_page.title and len(fastest_page.title) > 50 else (fastest_page.title or 'N/A')
        fastest_html = f'''<div class="perf-highlight">
            <p style="font-size: 2rem; font-weight: bold; color: #22c55e;">{fastest_page.load_time:.2f}s</p>
            <p style="margin-top: 0.5rem;"><a href="{html.escape(fastest_page.url)}" target="_blank">{html.escape(fastest_page.url[:60])}...</a></p>
            <p style="margin-top: 0.5rem; color: var(--muted); font-size: 0.9rem;">Title: {html.escape(fastest_title)}</p>
        </div>'''
    else:
        fastest_html = '<p>Aucune donnée de performance disponible</p>'

    if slowest_page:
        slowest_title = slowest_page.title[:50] + '...' if slowest_page.title and len(slowest_page.title) > 50 else (slowest_page.title or 'N/A')
        slow_color = '#ef4444' if slowest_page.load_time > 3 else '#f59e0b'
        slow_class = 'slow' if slowest_page.load_time > 3 else ''
        slowest_html = f'''<div class="perf-highlight {slow_class}">
            <p style="font-size: 2rem; font-weight: bold; color: {slow_color};">{slowest_page.load_time:.2f}s</p>
            <p style="margin-top: 0.5rem;"><a href="{html.escape(slowest_page.url)}" target="_blank">{html.escape(slowest_page.url[:60])}...</a></p>
            <p style="margin-top: 0.5rem; color: var(--muted); font-size: 0.9rem;">Title: {html.escape(slowest_title)}</p>
        </div>'''
    else:
        slowest_html = '<p>Aucune donnée de performance disponible</p>'

    html_content = f'''<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rapport SEO - {html.escape(url)}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{ --bg: #f8fafc; --card: #ffffff; --text: #1e293b; --muted: #64748b; --border: #e2e8f0; --primary: #3b82f6; }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; padding: 2rem; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ text-align: center; margin-bottom: 2rem; padding: 2.5rem; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 16px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
        .header h1 {{ font-size: 2rem; margin-bottom: 0.5rem; }}
        .header p {{ opacity: 0.9; }}
        .score-card {{ display: inline-block; padding: 2rem 4rem; background: rgba(255,255,255,0.2); backdrop-filter: blur(10px); color: white; border-radius: 16px; margin: 1.5rem 0; }}
        .score-card .score {{ font-size: 4rem; font-weight: bold; }}
        .score-card .label {{ font-size: 1.5rem; opacity: 0.95; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 1.5rem; margin: 1.5rem 0; }}
        .card {{ background: var(--card); padding: 1.5rem; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); border: 1px solid var(--border); }}
        .card h2 {{ font-size: 1.25rem; margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem; color: #1e293b; }}
        .stat {{ display: flex; justify-content: space-between; padding: 0.75rem 0; border-bottom: 1px solid var(--border); }}
        .stat:last-child {{ border-bottom: none; }}
        .stat-value {{ font-weight: 600; }}
        .stat-value.ok {{ color: #22c55e; }}
        .stat-value.warn {{ color: #f59e0b; }}
        .stat-value.error {{ color: #ef4444; }}
        .list {{ list-style: none; }}
        .list li {{ padding: 0.75rem 0; border-bottom: 1px solid var(--border); font-size: 0.9rem; }}
        .list li:last-child {{ border-bottom: none; }}
        .list a {{ color: var(--primary); text-decoration: none; word-break: break-all; }}
        .list a:hover {{ text-decoration: underline; }}
        .badge {{ display: inline-block; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 500; }}
        .badge-cms {{ background: #dbeafe; color: #1d4ed8; }}
        .badge-og {{ background: #dcfce7; color: #16a34a; }}
        .badge-twitter {{ background: #e0f2fe; color: #0284c7; }}
        .badge-jsonld {{ background: #fef3c7; color: #d97706; }}
        .footer {{ text-align: center; margin-top: 3rem; padding: 1.5rem; color: var(--muted); font-size: 0.875rem; border-top: 1px solid var(--border); }}
        .progress-bar {{ height: 10px; background: var(--border); border-radius: 5px; overflow: hidden; margin: 0.5rem 0; }}
        .progress-fill {{ height: 100%; background: linear-gradient(90deg, #22c55e, #16a34a); transition: width 0.3s; }}
        .pagespeed-btn {{ display: inline-block; padding: 0.75rem 1.5rem; background: #4285f4; color: white; text-decoration: none; border-radius: 8px; font-weight: 500; margin-top: 1rem; transition: background 0.2s; }}
        .pagespeed-btn:hover {{ background: #3367d6; }}
        .chart-container {{ position: relative; height: 300px; margin-top: 1rem; }}
        .perf-highlight {{ background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); padding: 1rem; border-radius: 8px; margin: 1rem 0; border: 1px solid #86efac; }}
        .perf-highlight.slow {{ background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%); border-color: #fca5a5; }}
        .section-title {{ font-size: 1.5rem; margin: 2rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 2px solid var(--border); }}
        .seo-item {{ display: flex; align-items: center; padding: 0.5rem 0; }}
        .seo-item-icon {{ min-width: 24px; margin-right: 0.75rem; }}
        .seo-item-content {{ flex: 1; }}
        .seo-item-status {{ font-weight: 500; }}
        .pagescore-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin-top: 1rem; }}
        .pagescore-item {{ text-align: center; padding: 1rem; background: #f8fafc; border-radius: 8px; }}
        .pagescore-value {{ font-size: 2rem; font-weight: bold; }}
        .pagescore-label {{ font-size: 0.85rem; color: var(--muted); margin-top: 0.25rem; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.75rem; margin-top: 1rem; }}
        .metric-item {{ padding: 0.75rem; background: #f1f5f9; border-radius: 6px; }}
        .metric-name {{ font-size: 0.85rem; color: var(--muted); }}
        .metric-value {{ font-weight: 600; margin-top: 0.25rem; }}
        .keyword-table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
        .keyword-table th {{ text-align: left; padding: 0.75rem; background: #f1f5f9; font-weight: 600; }}
        .keyword-table td {{ padding: 0.75rem; border-bottom: 1px solid var(--border); }}
        .keyword-bar {{ height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; width: 100px; }}
        .keyword-fill {{ height: 100%; background: linear-gradient(90deg, #3b82f6, #8b5cf6); border-radius: 4px; }}
        .broken-link {{ padding: 0.5rem; background: #fef2f2; border-left: 3px solid #ef4444; margin: 0.5rem 0; border-radius: 4px; }}
        @media (max-width: 768px) {{
            body {{ padding: 1rem; }}
            .grid {{ grid-template-columns: 1fr; }}
            .score-card {{ padding: 1.5rem 2rem; }}
            .score-card .score {{ font-size: 3rem; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 Rapport SEO &amp; Performance</h1>
            <p>''' + html.escape(url) + '''</p>
            <p>Généré le ''' + datetime.now().strftime('%d/%m/%Y à %H:%M') + ''' • Analyse complète</p>
            <div class="score-card">
                <div class="score">''' + str(score) + '''/100</div>
                <div class="label">''' + score_label + '''</div>
            </div>
            <br>
            <span class="badge badge-cms" style="font-size: 0.9rem; padding: 0.5rem 1rem;">📦 CMS détecté : ''' + html.escape(cms_detected) + '''</span>
            <br>
            <a href="''' + pagespeed_url + '''" target="_blank" class="pagespeed-btn">
                🚀 Voir le rapport Google PageSpeed Insights
            </a>
        </div>

        <h2 class="section-title">📊 Vue d'ensemble</h2>
        <div class="grid">
            <div class="card">
                <h2>📄 Pages analysées</h2>
                <div class="stat"><span>Total</span><span class="stat-value">''' + str(len(pages)) + '''</span></div>
                <div class="stat"><span>Dans le sitemap</span><span class="stat-value">''' + str(len(sitemap)) + '''</span></div>
                <div class="stat"><span>Pages avec erreurs</span><span class="stat-value ''' + ('error' if errors else 'ok') + '''">''' + str(len(errors)) + '''</span></div>
                <div class="stat"><span>Pages avec liens brisés</span><span class="stat-value ''' + ('error' if any(p.broken_links for p in pages) else 'ok') + '''">''' + str(sum(1 for p in pages if p.broken_links)) + '''</span></div>
            </div>

            <div class="card">
                <h2>📝 Qualité du contenu</h2>
                <div class="stat"><span>Pages sans title</span><span class="stat-value ''' + ('error' if no_title else 'ok') + '''">''' + str(len(no_title)) + '''</span></div>
                <div class="stat"><span>Pages sans meta description</span><span class="stat-value ''' + ('warn' if no_meta else 'ok') + '''">''' + str(len(no_meta)) + '''</span></div>
                <div class="stat"><span>Pages sans H1</span><span class="stat-value ''' + ('error' if no_h1 else 'ok') + '''">''' + str(len(no_h1)) + '''</span></div>
                <div class="stat"><span>Pages avec H1 multiples</span><span class="stat-value ''' + ('warn' if multi_h1 else 'ok') + '''">''' + str(len(multi_h1)) + '''</span></div>
            </div>

            <div class="card">
                <h2>🖼️ Images</h2>
                <div class="stat"><span>Total des images</span><span class="stat-value">''' + str(len(images)) + '''</span></div>
                <div class="stat"><span>Images sans alt</span><span class="stat-value ''' + ('warn' if missing_alt else 'ok') + '''">''' + str(len(missing_alt)) + '''</span></div>
                <div class="stat"><span>Taux de conformité</span><span class="stat-value ''' + ('ok' if not missing_alt else 'warn') + '''">''' + str(round((1 - len(missing_alt)/len(images))*100 if images else 100, 1)) + '''%</span></div>
            </div>

            <div class="card">
                <h2>⚡ Performance</h2>
                <div class="stat"><span>Temps moyen</span><span class="stat-value">''' + str(round(avg_load_time, 2)) + '''s</span></div>
                <div class="stat"><span>Page la plus rapide</span><span class="stat-value ok">''' + str(fastest_page.load_time if fastest_page else 0) + '''s</span></div>
                <div class="stat"><span>Page la plus lente</span><span class="stat-value ''' + ('warn' if slowest_page and slowest_page.load_time > 3 else 'ok') + '''">''' + str(slowest_page.load_time if slowest_page else 0) + '''s</span></div>
                <div class="stat"><span>Pages lentes (&gt;3s)</span><span class="stat-value ''' + ('warn' if slow_pages else 'ok') + '''">''' + str(len(slow_pages)) + '''</span></div>
            </div>
        </div>

        <!-- Performance détaillée -->
        <h2 class="section-title">⚡ Analyse détaillée des performances</h2>
        <div class="grid">
            <div class="card">
                <h2>🏆 Page la plus rapide</h2>
                ''' + fastest_html + '''
            </div>

            <div class="card">
                <h2>🐌 Page la plus lente</h2>
                ''' + slowest_html + '''
            </div>
        </div>

        <div class="card" style="margin-top: 1.5rem;">
            <h2>📈 Temps de chargement par page (top 20)</h2>
            <div class="chart-container">
                <canvas id="loadTimeChart"></canvas>
            </div>
        </div>
'''

    # Section PageSpeed Insights (optionnelle)
    if include_pagespeed:
        html_content += '''
        <!-- Google PageSpeed Insights -->
        <h2 class="section-title">🚀 Google PageSpeed Insights</h2>
        <div class="card">
            <p style="margin-bottom: 1rem;">Analyse des performances via l'API Google PageSpeed Insights. Les scores sont évalués sur 100.</p>
            <div style="text-align: center; margin: 1.5rem 0;">
                <a href="''' + pagespeed_url + '''" target="_blank" class="pagespeed-btn" style="font-size: 1.1rem; padding: 1rem 2rem;">
                    🚀 Voir l'analyse complète sur PageSpeed Insights
                </a>
            </div>
            <p style="margin-top: 1rem; font-size: 0.9rem; color: var(--muted);">💡 <strong>Note :</strong> Cliquez sur le bouton ci-dessus pour obtenir une analyse détaillée avec des recommandations personnalisées de Google.</p>
        </div>
'''

    # Liens cassés
    html_content += '''
        <!-- Liens cassés -->
        <h2 class="section-title">🔗 Liens cassés détectés</h2>
'''
    
    # Collecter tous les liens cassés
    all_broken_links = {}
    for p in pages:
        if p.broken_links:
            for link in p.broken_links:
                if link not in all_broken_links:
                    all_broken_links[link] = p.url
    
    if all_broken_links:
        html_content += f'''
        <div class="card">
            <p style="margin-bottom: 1rem;">{len(all_broken_links)} lien(s) cassé(s) détecté(s) sur le site.</p>
            <ul class="list">
'''
        for link, source_page in list(all_broken_links.items())[:20]:
            html_content += f'<li class="broken-link">🔴 <a href="{html.escape(link)}" target="_blank">{html.escape(link[:80])}...</a> (depuis: <a href="{html.escape(source_page)}" target="_blank">lien</a>)</li>'
        
        if len(all_broken_links) > 20:
            html_content += f'<li style="padding: 0.75rem; color: var(--muted);">... et {len(all_broken_links) - 20} autres liens cassés</li>'
        
        html_content += '''
            </ul>
            <p style="margin-top: 1rem; padding: 0.75rem; background: #fef3c7; border-radius: 8px; font-size: 0.85rem;">
                💡 <strong>Conseil :</strong> Corrigez ces liens cassés en mettant à jour les URLs ou en ajoutant des redirections 301.
            </p>
        </div>
'''
    else:
        html_content += '''
        <div class="card">
            <p style="padding: 1rem; color: #22c55e; font-weight: 500;">✅ Aucun lien cassé détecté sur le site.</p>
        </div>
'''
    
    html_content += '''
        <!-- SEO Avancé -->
        <h2 class="section-title">🔎 Audit SEO Avancé</h2>
        <div class="grid">
            <div class="card">
                <h2>📋 Meta Tags</h2>
                <div class="seo-item">
                    <span class="seo-item-icon">''' + ('✅' if all(p.title for p in pages) else '⚠️') + '''</span>
                    <div class="seo-item-content">
                        <strong>Balise &lt;title&gt;</strong>
                        <p style="color: var(--muted); font-size: 0.85rem;">''' + str(len([p for p in pages if p.title])) + '/' + str(len(pages)) + ''' pages avec un title</p>
                    </div>
                    <span class="seo-item-status ''' + ('ok' if all(p.title for p in pages) else 'warn') + '''">''' + str(round(len([p for p in pages if p.title])/len(pages)*100 if pages else 0, 1)) + '''%</span>
                </div>
                <div class="seo-item">
                    <span class="seo-item-icon">''' + ('✅' if all(p.meta_description for p in pages) else '⚠️') + '''</span>
                    <div class="seo-item-content">
                        <strong>Meta Description</strong>
                        <p style="color: var(--muted); font-size: 0.85rem;">''' + str(len([p for p in pages if p.meta_description])) + '/' + str(len(pages)) + ''' pages avec une description</p>
                    </div>
                    <span class="seo-item-status ''' + ('ok' if all(p.meta_description for p in pages) else 'warn') + '''">''' + str(round(len([p for p in pages if p.meta_description])/len(pages)*100 if pages else 0, 1)) + '''%</span>
                </div>
                <div class="seo-item">
                    <span class="seo-item-icon">''' + ('✅' if all(p.canonical for p in pages) else '⚠️') + '''</span>
                    <div class="seo-item-content">
                        <strong>URL Canonique</strong>
                        <p style="color: var(--muted); font-size: 0.85rem;">''' + str(len([p for p in pages if p.canonical])) + '/' + str(len(pages)) + ''' pages avec canonical</p>
                    </div>
                    <span class="seo-item-status ''' + ('ok' if all(p.canonical for p in pages) else 'warn') + '''">''' + str(round(len([p for p in pages if p.canonical])/len(pages)*100 if pages else 0, 1)) + '''%</span>
                </div>
                <div class="seo-item">
                    <span class="seo-item-icon">''' + ('✅' if all(p.lang for p in pages) else '⚠️') + '''</span>
                    <div class="seo-item-content">
                        <strong>Attribut Lang</strong>
                        <p style="color: var(--muted); font-size: 0.85rem;">''' + str(len([p for p in pages if p.lang])) + '/' + str(len(pages)) + ''' pages avec lang défini</p>
                    </div>
                    <span class="seo-item-status ''' + ('ok' if all(p.lang for p in pages) else 'warn') + '''">''' + str(round(len([p for p in pages if p.lang])/len(pages)*100 if pages else 0, 1)) + '''%</span>
                </div>
            </div>

            <div class="card">
                <h2>🌐 Open Graph (Réseaux sociaux)</h2>
                <div class="seo-item">
                    <span class="seo-item-icon">''' + ('✅' if pages_with_og else '❌') + '''</span>
                    <div class="seo-item-content">
                        <strong>Présence Open Graph</strong>
                        <p style="color: var(--muted); font-size: 0.85rem;">''' + str(len(pages_with_og)) + '/' + str(len(pages)) + ''' pages avec OG tags</p>
                    </div>
                    <span class="badge badge-og">''' + str(round(len(pages_with_og)/len(pages)*100 if pages else 0, 1)) + '''%</span>
                </div>
                <div class="seo-item">
                    <span class="seo-item-icon">▫️</span>
                    <div class="seo-item-content">
                        <strong>og:title</strong>
                        <p style="color: var(--muted); font-size: 0.85rem;">''' + str(len([p for p in pages if p.og_title])) + ''' pages</p>
                    </div>
                </div>
                <div class="seo-item">
                    <span class="seo-item-icon">▫️</span>
                    <div class="seo-item-content">
                        <strong>og:description</strong>
                        <p style="color: var(--muted); font-size: 0.85rem;">''' + str(len([p for p in pages if p.og_description])) + ''' pages</p>
                    </div>
                </div>
                <div class="seo-item">
                    <span class="seo-item-icon">▫️</span>
                    <div class="seo-item-content">
                        <strong>og:image</strong>
                        <p style="color: var(--muted); font-size: 0.85rem;">''' + str(len([p for p in pages if p.og_image])) + ''' pages</p>
                    </div>
                </div>
                <p style="margin-top: 1rem; padding: 0.75rem; background: #f0f9ff; border-radius: 8px; font-size: 0.85rem;">
                    💡 <strong>Conseil :</strong> Les balises Open Graph améliorent l'affichage de vos pages sur Facebook, LinkedIn et autres réseaux sociaux.
                </p>
            </div>

            <div class="card">
                <h2>🐦 Twitter Card</h2>
                <div class="seo-item">
                    <span class="seo-item-icon">''' + ('✅' if pages_with_twitter else '❌') + '''</span>
                    <div class="seo-item-content">
                        <strong>Présence Twitter Card</strong>
                        <p style="color: var(--muted); font-size: 0.85rem;">''' + str(len(pages_with_twitter)) + '/' + str(len(pages)) + ''' pages avec Twitter Card</p>
                    </div>
                    <span class="badge badge-twitter">''' + str(round(len(pages_with_twitter)/len(pages)*100 if pages else 0, 1)) + '''%</span>
                </div>
                <div class="seo-item">
                    <span class="seo-item-icon">▫️</span>
                    <div class="seo-item-content">
                        <strong>twitter:card</strong>
                        <p style="color: var(--muted); font-size: 0.85rem;">''' + str(len([p for p in pages if p.twitter_card])) + ''' pages configurées</p>
                    </div>
                </div>
                <p style="margin-top: 1rem; padding: 0.75rem; background: #f0f9ff; border-radius: 8px; font-size: 0.85rem;">
                    💡 <strong>Conseil :</strong> Twitter Card permet d'afficher un aperçu enrichi de vos pages sur Twitter.
                </p>
            </div>

            <div class="card">
                <h2>📊 Structured Data (JSON-LD)</h2>
                <div class="seo-item">
                    <span class="seo-item-icon">⚠️</span>
                    <div class="seo-item-content">
                        <strong>Données structurées</strong>
                        <p style="color: var(--muted); font-size: 0.85rem;">Vérification manuelle recommandée</p>
                    </div>
                </div>
                <p style="margin-top: 1rem; padding: 0.75rem; background: #fef3c7; border-radius: 8px; font-size: 0.85rem;">
                    🔍 <strong>Vérification :</strong> Utilisez le <a href="https://search.google.com/test/rich-results" target="_blank" style="color: #d97706;">Google Rich Results Test</a> pour vérifier les données structurées de votre site.
                </p>
                <p style="margin-top: 0.5rem; padding: 0.75rem; background: #f0f9ff; border-radius: 8px; font-size: 0.85rem;">
                    💡 <strong>Conseil :</strong> Le JSON-LD améliore l'affichage dans les résultats de recherche (rich snippets).
                </p>
            </div>
        </div>

        <!-- Densité de mots-clés -->
        <h2 class="section-title">🔑 Densité de mots-clés (Top 10 pages)</h2>
        <p style="margin-bottom: 1rem; color: var(--muted);">Analyse des mots-clés les plus fréquents sur les 10 pages les plus importantes (par nombre de mots).</p>
'''

    # Trier les pages par nombre de mots et prendre le top 10
    sorted_pages_by_words = sorted([p for p in pages if p.word_count > 0], key=lambda p: p.word_count, reverse=True)[:10]
    
    if sorted_pages_by_words:
        for idx, page in enumerate(sorted_pages_by_words, 1):
            page_title = page.title[:60] + '...' if page.title and len(page.title) > 60 else (page.title or 'Sans titre')
            
            html_content += f'''
        <div class="card" style="margin-bottom: 1.5rem;">
            <h2>📄 {idx}. <a href="{html.escape(page.url)}" target="_blank" style="color: var(--primary);">{html.escape(page_title)}</a></h2>
            <p style="font-size: 0.85rem; color: var(--muted); margin-bottom: 0.5rem;">{page.word_count} mots • {len(page.keyword_density)} mots-clés analysés</p>
            
            <table class="keyword-table">
                <thead>
                    <tr>
                        <th>Mot-clé</th>
                        <th>Occurrences</th>
                        <th>Densité</th>
                        <th>Visualisation</th>
                    </tr>
                </thead>
                <tbody>
'''
            max_density = max([kw.density for kw in page.keyword_density]) if page.keyword_density else 1
            
            for kw in page.keyword_density:
                bar_width = (kw.density / max_density * 100) if max_density > 0 else 0
                html_content += f'''
                    <tr>
                        <td><strong>{html.escape(kw.word)}</strong></td>
                        <td>{kw.count}</td>
                        <td>{kw.density}%</td>
                        <td>
                            <div class="keyword-bar">
                                <div class="keyword-fill" style="width: {bar_width}%;"></div>
                            </div>
                        </td>
                    </tr>
'''
            
            html_content += '''
                </tbody>
            </table>
        </div>
'''
    else:
        html_content += '''
        <div class="card">
            <p style="padding: 1rem; color: var(--muted);">Aucune donnée de densité de mots-clés disponible.</p>
        </div>
'''

    # Section Recommandations PageSpeed (optionnelle)
    if include_pagespeed:
        html_content += '''
        <!-- Recommandations PageSpeed -->
        <h2 class="section-title">🚀 Optimisations recommandées</h2>
        <div class="card">
            <h2>💡 Améliorations PageSpeed Insights</h2>
            <p style="margin-bottom: 1rem;">Cliquez sur le bouton ci-dessous pour obtenir une analyse détaillée des performances de votre site avec des recommandations personnalisées de Google :</p>
            <div style="text-align: center;">
                <a href="''' + pagespeed_url + '''" target="_blank" class="pagespeed-btn" style="font-size: 1.1rem; padding: 1rem 2rem;">
                    🚀 Lancer l'analyse PageSpeed Insights
                </a>
            </div>
            <div style="margin-top: 1.5rem; padding: 1rem; background: #f0fdf4; border-radius: 8px; border-left: 4px solid #22c55e;">
                <p style="font-weight: 500;">✅ Optimisations courantes à vérifier :</p>
                <ul style="margin-top: 0.5rem; margin-left: 1.5rem; color: var(--muted);">
                    <li>Compression et optimisation des images (WebP, AVIF)</li>
                    <li>Minification CSS et JavaScript</li>
                    <li>Mise en cache navigateur</li>
                    <li>Chargement différé (lazy loading) des images</li>
                    <li>Réduction du temps de réponse serveur (TTFB)</li>
                    <li>Élimination des ressources bloquant le rendu</li>
                </ul>
            </div>
        </div>
'''

    # Ajouter les détails des erreurs si présentes
    if errors or no_title or no_meta or no_h1 or multi_h1 or missing_alt:
        html_content += '''
        <h2 class="section-title">⚠️ Points d'attention</h2>
        <div class="card">
            <ul class="list">
'''
        if errors:
            for p in errors[:10]:
                html_content += f'<li>🔴 <strong>Erreur</strong> sur <a href="{html.escape(p.url)}" target="_blank">{html.escape(p.url[:80])}...</a> ({html.escape(p.error or f"Status {p.status_code}")})</li>'
        if no_title:
            for p in no_title[:5]:
                html_content += f'<li>🟠 <strong>Title manquant</strong> sur <a href="{html.escape(p.url)}" target="_blank">{html.escape(p.url[:60])}...</a></li>'
        if no_meta:
            for p in no_meta[:5]:
                html_content += f'<li>🟡 <strong>Meta description manquante</strong> sur <a href="{html.escape(p.url)}" target="_blank">{html.escape(p.url[:60])}...</a></li>'
        if no_h1:
            for p in no_h1[:5]:
                html_content += f'<li>🟠 <strong>H1 manquant</strong> sur <a href="{html.escape(p.url)}" target="_blank">{html.escape(p.url[:60])}...</a></li>'
        if multi_h1:
            for p in multi_h1[:5]:
                html_content += f'<li>🟡 <strong>H1 multiples</strong> ({len(p.h1)}) sur <a href="{html.escape(p.url)}" target="_blank">{html.escape(p.url[:60])}...</a></li>'
        if missing_alt:
            for img in missing_alt[:10]:
                html_content += f'<li>🟡 <strong>Image sans alt</strong>: {html.escape(img.src[:70])}... (page: <a href="{html.escape(img.page_url)}" target="_blank">lien</a>)</li>'

        html_content += '''
            </ul>
        </div>
'''

    # Script pour le graphique
    chart_labels = json.dumps([d['url'] for d in chart_data])
    chart_values = json.dumps([d['time'] for d in chart_data])

    html_content += f'''
        <div class="footer">
            <p>Généré avec Python Scraper & SEO Analyzer</p>
            <p style="margin-top: 0.5rem;">Rapport à destination des clients • {datetime.now().strftime('%Y')}</p>
        </div>
    </div>

    <script>
        // Graphique des temps de chargement
        const ctx = document.getElementById('loadTimeChart').getContext('2d');
        new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: {chart_labels},
                datasets: [{{
                    label: 'Temps de chargement (s)',
                    data: {chart_values},
                    backgroundColor: function(context) {{
                        const value = context.raw;
                        if (value <= 1) return '#22c55e';  // vert
                        if (value <= 2.5) return '#f59e0b';  // orange
                        return '#ef4444';  // rouge
                    }},
                    borderRadius: 4
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        display: false
                    }},
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                return context.parsed.y.toFixed(2) + 's';
                            }}
                        }}
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        title: {{
                            display: true,
                            text: 'Temps (secondes)'
                        }}
                    }},
                    x: {{
                        ticks: {{
                            maxRotation: 45,
                            minRotation: 45
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
'''

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html_content)


def generate_summary_text(pages: list[PageData], images: list[ImageData], sitemap: list[SiteMapData], url: str) -> str:
    """Génère un résumé texte de l'analyse."""
    lines = []
    lines.append("=" * 70)
    lines.append("RÉSUMÉ DE L'ANALYSE SEO")
    lines.append("=" * 70)
    lines.append(f"\nSite analysé : {url}")
    lines.append(f"Date du rapport : {datetime.now().strftime('%d/%m/%Y à %H:%M')}")
    
    lines.append(f"\n📄 PAGES ANALYSÉES : {len(pages)}")
    
    # Pages avec erreurs
    errors = [p for p in pages if p.error or p.status_code != 200]
    if errors:
        lines.append(f"   ⚠️  Pages avec erreurs : {len(errors)}")
        for p in errors[:10]:
            lines.append(f"      - {p.url} ({p.error or f'Status {p.status_code}'})")
    else:
        lines.append("   ✅ Aucune erreur détectée")
    
    # Title manquants
    no_title = [p for p in pages if not p.title]
    if no_title:
        lines.append(f"   ⚠️  Pages sans title : {len(no_title)}")
        for p in no_title[:5]:
            lines.append(f"      - {p.url}")
    else:
        lines.append("   ✅ Toutes les pages ont un title")
    
    # Meta descriptions manquantes
    no_meta = [p for p in pages if not p.meta_description]
    if no_meta:
        lines.append(f"   ⚠️  Pages sans meta description : {len(no_meta)}")
        for p in no_meta[:5]:
            lines.append(f"      - {p.url}")
    else:
        lines.append("   ✅ Toutes les pages ont une meta description")
    
    # H1 manquants
    no_h1 = [p for p in pages if not p.h1]
    if no_h1:
        lines.append(f"   ⚠️  Pages sans H1 : {len(no_h1)}")
        for p in no_h1[:5]:
            lines.append(f"      - {p.url}")
    else:
        lines.append("   ✅ Toutes les pages ont un H1")
    
    # H1 multiples
    multi_h1 = [p for p in pages if len(p.h1) > 1]
    if multi_h1:
        lines.append(f"   ⚠️  Pages avec plusieurs H1 : {len(multi_h1)}")
        for p in multi_h1[:5]:
            lines.append(f"      - {p.url} ({len(p.h1)} H1)")
    else:
        lines.append("   ✅ Une seule page avec un H1 unique")
    
    lines.append(f"\n🖼️  IMAGES : {len(images)}")
    missing_alt = [i for i in images if not i.alt]
    if missing_alt:
        lines.append(f"   ⚠️  Images sans alt : {len(missing_alt)}")
        for img in missing_alt[:10]:
            lines.append(f"      - {img.src[:60]}... (page: {img.page_url})")
    else:
        lines.append("   ✅ Toutes les images ont un attribut alt")
    
    lines.append(f"\n🗺️  SITEMAP : {len(sitemap)} URLs trouvées")
    
    # Performance
    avg_load = sum(p.load_time for p in pages if p.load_time > 0) / len(pages) if pages else 0
    lines.append(f"\n⚡ PERFORMANCE : Temps de chargement moyen : {avg_load:.2f}s")
    
    slow_pages = [p for p in pages if p.load_time > 3]
    if slow_pages:
        lines.append(f"   ⚠️  Pages lentes (>3s) : {len(slow_pages)}")
        for p in slow_pages[:5]:
            lines.append(f"      - {p.url} ({p.load_time:.2f}s)")
    else:
        lines.append("   ✅ Aucune page lente détectée")
    
    # Liens externes
    total_external = sum(p.external_links for p in pages)
    lines.append(f"\n🔗 LIENS : {total_external} liens externes au total")
    
    # Top mots-clés (à partir des titles)
    titles = [p.title for p in pages if p.title]
    if titles:
        all_words = []
        for title in titles:
            words = re.findall(r'\b[a-zA-ZÀ-ÿ]{4,}\b', title.lower())
            all_words.extend(words)
        from collections import Counter
        word_freq = Counter(all_words)
        top_words = word_freq.most_common(10)
        lines.append(f"\n🔑 MOTS-CLÉS (dans les titles) :")
        for word, count in top_words:
            lines.append(f"      - {word} : {count}x")
    
    lines.append("\n" + "=" * 70)
    lines.append("Fin du rapport")
    lines.append("=" * 70)
    
    return "\n".join(lines)


def print_summary(
    pages: list[PageData],
    images: list[ImageData],
    sitemap: list[SiteMapData],
    url: str = "",
    output_folder: Path = None,
    duration: float = 0.0
):
    """Affiche un résumé de l'analyse et génère les fichiers texte et HTML."""
    summary_text = generate_summary_text(pages, images, sitemap, url)
    score = calculate_seo_score(pages, images)

    # Sauvegarder le résumé texte et HTML si un dossier est spécifié
    if output_folder:
        summary_path = output_folder / "resume_seo.txt"
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(summary_text)
        print(f"📝 Résumé texte : {summary_path}")
        
        # Export HTML
        html_path = output_folder / "resume_seo.html"
        export_to_html(pages, images, sitemap, url, duration, html_path)
        print(f"🌐 Rapport HTML : {html_path}")

    # Afficher à l'écran
    print()
    print(summary_text)
    print(f"\n📊 SCORE SEO : {score}/100")
    if duration > 0:
        print(f"⏱️  Durée totale : {duration:.1f} secondes")


def get_default_output_path(url: str) -> Path:
    """Retourne le chemin par défaut pour les rapports : ~/Téléchargements/nom-du-site."""
    downloads = Path.home() / 'Téléchargements'
    if not downloads.exists():
        downloads = Path.home() / 'Downloads'
    site_name = get_base_domain(url).replace('.', '_')
    return downloads / site_name


def export_to_pdf(
    pages: list[PageData],
    images: list[ImageData],
    sitemap: list[SiteMapData],
    url: str,
    duration: float,
    filepath: Path,
    include_pagespeed: bool = False
):
    """
    Génère un rapport PDF à partir du rapport HTML.
    
    Args:
        include_pagespeed: Si False (recommandé pour PDF), exclut les sections PageSpeed
    """
    try:
        from weasyprint import HTML, CSS
        import io
        
        # Générer d'abord le HTML
        html_buffer = io.StringIO()
        
        # Créer un HTML simplifié pour le PDF (sans JavaScript, sans graphiques interactifs)
        score = calculate_seo_score(pages, images)
        
        # Déterminer la couleur du score
        if score >= 80:
            score_color = "#22c55e"
            score_label = "Excellent"
        elif score >= 60:
            score_color = "#f59e0b"
            score_label = "Moyen"
        elif score >= 40:
            score_color = "#f97316"
            score_label = "À améliorer"
        else:
            score_color = "#ef4444"
            score_label = "Critique"
        
        # Détection CMS
        cms_counts = {}
        for p in pages:
            if p.cms_detected:
                cms_counts[p.cms_detected] = cms_counts.get(p.cms_detected, 0) + 1
        cms_detected = max(cms_counts.items(), key=lambda x: x[1])[0] if cms_counts else "Inconnu"
        
        # Calcul des stats
        errors = [p for p in pages if p.error or p.status_code != 200]
        no_title = [p for p in pages if not p.title]
        no_meta = [p for p in pages if not p.meta_description]
        no_h1 = [p for p in pages if not p.h1]
        multi_h1 = [p for p in pages if len(p.h1) > 1]
        missing_alt = [i for i in images if not i.alt]
        slow_pages = [p for p in pages if p.load_time > 3]
        
        # Stats de performance
        pages_with_time = [p for p in pages if p.load_time > 0]
        if pages_with_time:
            fastest_page = min(pages_with_time, key=lambda p: p.load_time)
            slowest_page = max(pages_with_time, key=lambda p: p.load_time)
            avg_load_time = sum(p.load_time for p in pages_with_time) / len(pages_with_time)
        else:
            fastest_page = slowest_page = None
            avg_load_time = 0
        
        # Stats SEO
        pages_with_og = [p for p in pages if p.og_title or p.og_description or p.og_image]
        pages_with_twitter = [p for p in pages if p.twitter_card]
        
        # Trier les pages par nombre de mots pour la densité de mots-clés
        sorted_pages_by_words = sorted([p for p in pages if p.word_count > 0], key=lambda p: p.word_count, reverse=True)[:10]
        
        # Collecter les liens cassés
        all_broken_links = {}
        for p in pages:
            if p.broken_links:
                for link in p.broken_links:
                    if link not in all_broken_links:
                        all_broken_links[link] = p.url
        
        # Générer le HTML simplifié pour PDF
        pdf_html = f'''<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Rapport SEO - {html.escape(url)}</title>
    <style>
        @page {{ size: A4; margin: 2cm; }}
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #1e293b; }}
        h1 {{ color: #667eea; font-size: 24px; border-bottom: 2px solid #667eea; padding-bottom: 10px; }}
        h2 {{ color: #3b82f6; font-size: 18px; margin-top: 30px; border-bottom: 1px solid #e2e8f0; padding-bottom: 5px; }}
        h3 {{ color: #1e293b; font-size: 16px; margin-top: 20px; }}
        .score-box {{ text-align: center; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 10px; margin: 20px 0; }}
        .score-value {{ font-size: 48px; font-weight: bold; }}
        .score-label {{ font-size: 18px; opacity: 0.9; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ border: 1px solid #e2e8f0; padding: 10px; text-align: left; }}
        th {{ background: #f1f5f9; font-weight: 600; }}
        .stat-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; margin: 15px 0; }}
        .stat-card {{ background: #f8fafc; padding: 15px; border-radius: 8px; border: 1px solid #e2e8f0; }}
        .stat-value {{ font-size: 24px; font-weight: bold; color: #3b82f6; }}
        .stat-label {{ font-size: 14px; color: #64748b; margin-top: 5px; }}
        .ok {{ color: #22c55e; }}
        .warn {{ color: #f59e0b; }}
        .error {{ color: #ef4444; }}
        ul {{ margin: 10px 0; padding-left: 20px; }}
        li {{ margin: 5px 0; }}
        .page-break {{ page-break-before: always; }}
        .keyword-table {{ width: 100%; font-size: 12px; }}
        .keyword-table th {{ font-size: 11px; }}
        a {{ color: #3b82f6; text-decoration: none; }}
    </style>
</head>
<body>
    <h1>🔍 Rapport SEO &amp; Performance</h1>
    <p><strong>Site :</strong> {html.escape(url)}</p>
    <p><strong>Date :</strong> {datetime.now().strftime('%d/%m/%Y à %H:%M')}</p>
    <p><strong>CMS détecté :</strong> {html.escape(cms_detected)}</p>
    
    <div class="score-box">
        <div class="score-value" style="color: {score_color};">{score}/100</div>
        <div class="score-label">{score_label}</div>
    </div>
    
    <h2>📊 Vue d'ensemble</h2>
    <div class="stat-grid">
        <div class="stat-card">
            <div class="stat-value">{len(pages)}</div>
            <div class="stat-label">Pages analysées</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{len(sitemap)}</div>
            <div class="stat-label">URLs dans le sitemap</div>
        </div>
        <div class="stat-card">
            <div class="stat-value {'error' if errors else 'ok'}">{len(errors)}</div>
            <div class="stat-label">Pages avec erreurs</div>
        </div>
        <div class="stat-card">
            <div class="stat-value {'error' if all_broken_links else 'ok'}">{len(all_broken_links)}</div>
            <div class="stat-label">Liens cassés</div>
        </div>
    </div>
    
    <h2>📝 Qualité du contenu</h2>
    <div class="stat-grid">
        <div class="stat-card">
            <div class="stat-value {'error' if no_title else 'ok'}">{len(no_title)}</div>
            <div class="stat-label">Pages sans title</div>
        </div>
        <div class="stat-card">
            <div class="stat-value {'warn' if no_meta else 'ok'}">{len(no_meta)}</div>
            <div class="stat-label">Pages sans meta description</div>
        </div>
        <div class="stat-card">
            <div class="stat-value {'error' if no_h1 else 'ok'}">{len(no_h1)}</div>
            <div class="stat-label">Pages sans H1</div>
        </div>
        <div class="stat-card">
            <div class="stat-value {'warn' if multi_h1 else 'ok'}">{len(multi_h1)}</div>
            <div class="stat-label">Pages avec H1 multiples</div>
        </div>
    </div>
    
    <h2>🖼️ Images</h2>
    <div class="stat-grid">
        <div class="stat-card">
            <div class="stat-value">{len(images)}</div>
            <div class="stat-label">Total des images</div>
        </div>
        <div class="stat-card">
            <div class="stat-value {'warn' if missing_alt else 'ok'}">{len(missing_alt)}</div>
            <div class="stat-label">Images sans alt</div>
        </div>
        <div class="stat-card">
            <div class="stat-value {'ok' if not missing_alt else 'warn'}">{round((1 - len(missing_alt)/len(images))*100 if images else 100, 1)}%</div>
            <div class="stat-label">Taux de conformité</div>
        </div>
    </div>
    
    <h2>⚡ Performance</h2>
    <div class="stat-grid">
        <div class="stat-card">
            <div class="stat-value">{avg_load_time:.2f}s</div>
            <div class="stat-label">Temps de chargement moyen</div>
        </div>
        <div class="stat-card">
            <div class="stat-value ok">{fastest_page.load_time:.2f}s</div>
            <div class="stat-label">Page la plus rapide</div>
        </div>
        <div class="stat-card">
            <div class="stat-value {'warn' if slowest_page and slowest_page.load_time > 3 else 'ok'}">{slowest_page.load_time:.2f}s</div>
            <div class="stat-label">Page la plus lente</div>
        </div>
        <div class="stat-card">
            <div class="stat-value {'warn' if slow_pages else 'ok'}">{len(slow_pages)}</div>
            <div class="stat-label">Pages lentes (&gt;3s)</div>
        </div>
    </div>
    
    <div class="page-break"></div>
    <h2>🔎 Audit SEO Avancé</h2>
    
    <h3>📋 Meta Tags</h3>
    <table>
        <tr><th>Balise</th><th>Conformité</th></tr>
        <tr><td>&lt;title&gt;</td><td class="{'ok' if all(p.title for p in pages) else 'warn'}">{round(len([p for p in pages if p.title])/len(pages)*100 if pages else 0, 1)}%</td></tr>
        <tr><td>Meta Description</td><td class="{'ok' if all(p.meta_description for p in pages) else 'warn'}">{round(len([p for p in pages if p.meta_description])/len(pages)*100 if pages else 0, 1)}%</td></tr>
        <tr><td>URL Canonique</td><td class="{'ok' if all(p.canonical for p in pages) else 'warn'}">{round(len([p for p in pages if p.canonical])/len(pages)*100 if pages else 0, 1)}%</td></tr>
        <tr><td>Attribut Lang</td><td class="{'ok' if all(p.lang for p in pages) else 'warn'}">{round(len([p for p in pages if p.lang])/len(pages)*100 if pages else 0, 1)}%</td></tr>
    </table>
    
    <h3>🌐 Open Graph</h3>
    <p>{len(pages_with_og)}/{len(pages)} pages avec OG tags ({round(len(pages_with_og)/len(pages)*100 if pages else 0, 1)}%)</p>
    <ul>
        <li>og:title: {len([p for p in pages if p.og_title])} pages</li>
        <li>og:description: {len([p for p in pages if p.og_description])} pages</li>
        <li>og:image: {len([p for p in pages if p.og_image])} pages</li>
    </ul>
    
    <h3>🐦 Twitter Card</h3>
    <p>{len(pages_with_twitter)}/{len(pages)} pages avec Twitter Card ({round(len(pages_with_twitter)/len(pages)*100 if pages else 0, 1)}%)</p>
'''
        
        # Ajouter densité de mots-clés
        pdf_html += '''
    <div class="page-break"></div>
    <h2>🔑 Densité de mots-clés (Top 10 pages)</h2>
'''
        
        for idx, page in enumerate(sorted_pages_by_words, 1):
            page_title = html.escape(page.title[:80] + '...' if page.title and len(page.title) > 80 else (page.title or 'Sans titre'))
            pdf_html += f'''
    <h3>{idx}. {page_title}</h3>
    <p>{page.word_count} mots</p>
    <table class="keyword-table">
        <tr><th>Mot-clé</th><th>Occurrences</th><th>Densité</th></tr>
'''
            for kw in page.keyword_density[:5]:  # Top 5 par page pour PDF
                pdf_html += f'''
        <tr><td>{html.escape(kw.word)}</td><td>{kw.count}</td><td>{kw.density}%</td></tr>
'''
            pdf_html += '''
    </table>
'''
        
        # Ajouter liens cassés
        if all_broken_links:
            pdf_html += '''
    <div class="page-break"></div>
    <h2>🔗 Liens cassés détectés</h2>
    <table>
        <tr><th>Lien cassé</th><th>Page source</th></tr>
'''
            for link, source_page in list(all_broken_links.items())[:30]:
                pdf_html += f'''
        <tr><td style="font-size: 11px;">{html.escape(link[:60])}...</td><td style="font-size: 11px;">{html.escape(source_page[:50])}...</td></tr>
'''
            pdf_html += '''
    </table>
'''
        
        pdf_html += '''
</body>
</html>
'''
        
        # Générer le PDF
        html_buffer.write(pdf_html)
        html_buffer.seek(0)
        
        # Conversion en PDF
        html_doc = HTML(string=html_buffer.read(), base_url=str(filepath.parent))
        html_doc.write_pdf(str(filepath))
        
        print(f"📄 Rapport PDF : {filepath}")
        
    except ImportError:
        print("⚠️  weasyprint n'est pas installé. Pour installer : pip install weasyprint")
    except Exception as e:
        print(f"⚠️  Erreur lors de la génération du PDF : {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Analyseur SEO complet pour site web.'
    )
    parser.add_argument('url', help='URL du site à analyser')
    parser.add_argument('-o', '--output', type=Path, default=None,
                        help='Dossier de sortie pour les rapports (défaut: ~/Téléchargements/nom-du-site)')
    parser.add_argument('-p', '--max-pages', type=int, default=100,
                        help='Nombre maximum de pages à analyser (défaut: 100, 0=illimité)')
    parser.add_argument('-t', '--timeout', type=int, default=10,
                        help='Timeout en secondes (défaut: 10)')
    parser.add_argument('-d', '--delay', type=float, default=0.0,
                        help='Délai entre les requêtes en secondes (défaut: 0)')
    parser.add_argument('-l', '--check-links', action='store_true',
                        help='Vérifier les liens brisés (plus lent)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Afficher les détails de l\'analyse')
    parser.add_argument('--pagespeed', action='store_true',
                        help='Récupérer les données PageSpeed Insights (page d\'accueil)')
    parser.add_argument('--no-pdf', action='store_true',
                        help='Désactiver la génération du rapport PDF')
    parser.add_argument('--images-only', action='store_true',
                        help='Télécharger uniquement les images (mode scraper)')
    parser.add_argument('--image-dest', type=Path, default=None,
                        help='Dossier pour télécharger les images')

    args = parser.parse_args()

    if not args.url.startswith(('http://', 'https://')):
        print("Erreur: L'URL doit commencer par http:// ou https://")
        sys.exit(1)

    # Configurer le rate limiting
    if args.delay > 0:
        set_request_delay(args.delay)
        print(f"⏱️  Rate limiting : {args.delay}s entre les requêtes")

    print("=" * 70)
    print("🔍 ANALYSEUR SEO COMPLET")
    print("=" * 70)
    print()

    # Mode scraper d'images uniquement
    if args.images_only:
        from image_scraper import scrape_images
        dest = args.image_dest
        if not dest:
            dest = get_default_output_path(args.url)
        success, failed, total = scrape_images(args.url, dest, args.max_pages, args.timeout)
        print(f"\nImages téléchargées : {success}")
        return

    # Déterminer le dossier de sortie (par défaut: même dossier que les images)
    output_folder = args.output if args.output else get_default_output_path(args.url)
    output_folder.mkdir(parents=True, exist_ok=True)

    # Mesurer la durée totale
    start_time = time.time()

    # Analyse SEO complète
    pages, images, sitemap = crawl_site_for_seo(
        args.url,
        args.max_pages,
        args.timeout,
        args.check_links,
        args.verbose,
        args.pagespeed
    )

    duration = time.time() - start_time

    # Afficher le résumé et générer les fichiers
    print_summary(pages, images, sitemap, args.url, output_folder, duration)

    # Export CSV
    csv_path = output_folder / 'seo_audit.csv'
    export_to_csv(pages, csv_path)
    print(f"\n📊 Export CSV : {csv_path}")

    # Export JSON
    json_path = output_folder / 'seo_audit.json'
    export_to_json(pages, images, sitemap, json_path)
    print(f"📄 Export JSON : {json_path}")

    # Export liste images
    if images:
        img_path = output_folder / 'images.csv'
        with open(img_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['URL', 'Alt', 'Title', 'Width', 'Height', 'Loading', 'Page'])
            for img in images:
                writer.writerow([img.url, img.alt, img.title, img.width, img.height, img.loading, img.page_url])
        print(f"🖼️  Export images : {img_path}")

    # Export PDF automatique (sans PageSpeed) - sauf si --no-pdf
    if not args.no_pdf:
        pdf_path = output_folder / 'rapport_seo.pdf'
        export_to_pdf(pages, images, sitemap, args.url, duration, pdf_path, include_pagespeed=False)

    print()


if __name__ == '__main__':
    main()
