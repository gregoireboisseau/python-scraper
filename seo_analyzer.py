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
    verbose: bool = False
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
    filepath: Path
):
    """Génère un rapport HTML coloré et lisible."""
    score = calculate_seo_score(pages, images)
    
    # Déterminer la couleur du score
    if score >= 80:
        score_color = "#22c55e"  # vert
        score_label = "Excellent"
    elif score >= 60:
        score_color = "#f59e0b"  # orange
        score_label = "Moyen"
    elif score >= 40:
        score_color = "#f97316"  # orange foncé
        score_label = "À améliorer"
    else:
        score_color = "#ef4444"  # rouge
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
    
    html_content = f'''<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rapport SEO - {html.escape(url)}</title>
    <style>
        :root {{ --bg: #f8fafc; --card: #ffffff; --text: #1e293b; --muted: #64748b; --border: #e2e8f0; }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; padding: 2rem; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ text-align: center; margin-bottom: 2rem; padding: 2rem; background: var(--card); border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .header h1 {{ font-size: 1.75rem; margin-bottom: 0.5rem; }}
        .header p {{ color: var(--muted); }}
        .score-card {{ display: inline-block; padding: 1.5rem 3rem; background: {score_color}; color: white; border-radius: 12px; margin: 1rem 0; }}
        .score-card .score {{ font-size: 3rem; font-weight: bold; }}
        .score-card .label {{ font-size: 1.25rem; opacity: 0.9; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1rem; margin: 1.5rem 0; }}
        .card {{ background: var(--card); padding: 1.5rem; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .card h2 {{ font-size: 1.25rem; margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem; }}
        .stat {{ display: flex; justify-content: space-between; padding: 0.75rem 0; border-bottom: 1px solid var(--border); }}
        .stat:last-child {{ border-bottom: none; }}
        .stat-value {{ font-weight: 600; }}
        .stat-value.ok {{ color: #22c55e; }}
        .stat-value.warn {{ color: #f59e0b; }}
        .stat-value.error {{ color: #ef4444; }}
        .list {{ list-style: none; }}
        .list li {{ padding: 0.5rem 0; border-bottom: 1px solid var(--border); font-size: 0.9rem; }}
        .list li:last-child {{ border-bottom: none; }}
        .list a {{ color: #3b82f6; text-decoration: none; }}
        .list a:hover {{ text-decoration: underline; }}
        .badge {{ display: inline-block; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 500; }}
        .badge-cms {{ background: #dbeafe; color: #1d4ed8; }}
        .footer {{ text-align: center; margin-top: 2rem; padding: 1rem; color: var(--muted); font-size: 0.875rem; }}
        .progress-bar {{ height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; margin: 0.5rem 0; }}
        .progress-fill {{ height: 100%; background: {score_color}; transition: width 0.3s; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 Rapport SEO</h1>
            <p>{html.escape(url)}</p>
            <p>Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')} • Durée: {duration:.1f}s</p>
            <div class="score-card">
                <div class="score">{score}/100</div>
                <div class="label">{score_label}</div>
            </div>
            <br>
            <span class="badge badge-cms">📦 CMS: {html.escape(cms_detected)}</span>
        </div>
        
        <div class="grid">
            <div class="card">
                <h2>📄 Pages</h2>
                <div class="stat"><span>Total analysé</span><span class="stat-value">{len(pages)}</span></div>
                <div class="stat"><span>Dans le sitemap</span><span class="stat-value">{len(sitemap)}</span></div>
                <div class="stat"><span>Erreurs</span><span class="stat-value {'error' if errors else 'ok'}">{len(errors)}</span></div>
                <div class="stat"><span>Pages lentes (&gt;3s)</span><span class="stat-value {'warn' if slow_pages else 'ok'}">{len(slow_pages)}</span></div>
            </div>
            
            <div class="card">
                <h2>📝 Contenu</h2>
                <div class="stat"><span>Pages sans title</span><span class="stat-value {'error' if no_title else 'ok'}">{len(no_title)}</span></div>
                <div class="stat"><span>Pages sans meta description</span><span class="stat-value {'warn' if no_meta else 'ok'}">{len(no_meta)}</span></div>
                <div class="stat"><span>Pages sans H1</span><span class="stat-value {'error' if no_h1 else 'ok'}">{len(no_h1)}</span></div>
                <div class="stat"><span>Pages avec H1 multiples</span><span class="stat-value {'warn' if multi_h1 else 'ok'}">{len(multi_h1)}</span></div>
            </div>
            
            <div class="card">
                <h2>🖼️ Images</h2>
                <div class="stat"><span>Total</span><span class="stat-value">{len(images)}</span></div>
                <div class="stat"><span>Sans attribut alt</span><span class="stat-value {'warn' if missing_alt else 'ok'}">{len(missing_alt)}</span></div>
            </div>
            
            <div class="card">
                <h2>⚡ Performance</h2>
                <div class="stat"><span>Temps moyen</span><span class="stat-value">{sum(p.load_time for p in pages)/len(pages):.2f}s</span></div>
                <div class="stat"><span>Pages rapides</span><span class="stat-value ok">{len(pages) - len(slow_pages)}/{len(pages)}</span></div>
            </div>
        </div>
'''
    
    # Ajouter les détails des erreurs si présentes
    if errors or no_title or no_meta or no_h1 or multi_h1 or missing_alt:
        html_content += '''
        <div class="card">
            <h2>⚠️ Points d'attention</h2>
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
    
    html_content += f'''
        <div class="footer">
            <p>Généré avec Python Scraper & SEO Analyzer</p>
        </div>
    </div>
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
        args.verbose
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

    print()


if __name__ == '__main__':
    main()
