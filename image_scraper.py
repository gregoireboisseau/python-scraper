#!/usr/bin/env python3
"""
Scraper d'images pour site web complet.
Crawl toutes les pages d'un site et télécharge toutes les images.
"""

import argparse
import hashlib
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# Extensions d'images supportées
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico'}

# Headers pour éviter les blocages
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

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
            pass
        _robots_parsers[domain] = rp
    
    return _robots_parsers[domain]


def can_fetch(url: str) -> bool:
    """Vérifie si l'URL peut être fetchée selon robots.txt."""
    rp = get_robots_parser(url)
    return rp.can_fetch("*", url) if rp else True


def get_site_name(url: str) -> str:
    """Extrait le nom du site depuis l'URL pour le nom du dossier."""
    parsed = urlparse(url)
    return parsed.netloc.replace('www.', '').replace('.', '_')


def get_default_download_path(url: str) -> Path:
    """Retourne le chemin par défaut : ~/Téléchargements/nom-du-site."""
    downloads = Path.home() / 'Téléchargements'
    if not downloads.exists():
        downloads = Path.home() / 'Downloads'
    site_name = get_site_name(url)
    return downloads / site_name


def is_image_url(url: str) -> bool:
    """Vérifie si l'URL pointe vers une image basée sur l'extension."""
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def get_base_domain(url: str) -> str:
    """Récupère le domaine de base pour filtrer les liens internes."""
    parsed = urlparse(url)
    return parsed.netloc


def is_internal_link(url: str, base_domain: str) -> bool:
    """Vérifie si un lien est interne au site."""
    parsed = urlparse(url)
    return parsed.netloc == base_domain or parsed.netloc == ''


def extract_image_urls(html: str, base_url: str) -> set[str]:
    """Extrait toutes les URLs d'images du HTML."""
    soup = BeautifulSoup(html, 'html.parser')
    image_urls = set()

    # Balises <img>
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
        if src:
            image_urls.add(urljoin(base_url, src))

    # Balises <source> (pour les images responsive)
    for source in soup.find_all('source'):
        srcset = source.get('srcset') or source.get('src')
        if srcset:
            for url in srcset.split(','):
                image_urls.add(urljoin(base_url, url.strip().split()[0]))

    # Balises <a> pointant vers des images
    for a in soup.find_all('a', href=True):
        href = a['href']
        if is_image_url(href):
            image_urls.add(urljoin(base_url, href))

    # Background images dans le CSS inline
    for tag in soup.find_all(style=True):
        style = tag.get('style', '')
        matches = re.findall(r'url\(["\']?([^"\')]+)["\']?\)', style)
        for match in matches:
            if is_image_url(match):
                image_urls.add(urljoin(base_url, match))

    # Filtrer les URLs valides
    valid_urls = set()
    for url in image_urls:
        if url.startswith(('http://', 'https://')):
            parsed = urlparse(url)
            if parsed.path:
                valid_urls.add(url)

    return valid_urls


def extract_internal_links(html: str, base_url: str, base_domain: str) -> set[str]:
    """Extrait tous les liens internes d'une page."""
    soup = BeautifulSoup(html, 'html.parser')
    links = set()
    
    # Protocoles à ignorer
    skip_protocols = ('mailto:', 'tel:', 'javascript:', '#', 'data:')

    for a in soup.find_all('a', href=True):
        href = a['href']
        
        # Ignorer les protocoles non-http
        if href.lower().startswith(skip_protocols):
            continue
        
        full_url = urljoin(base_url, href)
        
        # Vérifier que c'est un lien interne
        if is_internal_link(full_url, base_domain):
            # Nettoyer l'URL (enlever les ancres)
            parsed = urlparse(full_url)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean_url += f"?{parsed.query}"
            
            # Éviter les ancres et liens vides
            if clean_url and not clean_url.endswith('#'):
                links.add(clean_url)

    return links


def download_image(url: str, dest_folder: Path, timeout: int = 10, seen_hashes: set = None) -> tuple[bool, str]:
    """
    Télécharge une image dans le dossier de destination.
    Retourne (succès, hash de l'image ou raison de l'échec).
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        response.raise_for_status()

        # Vérifier le content-type
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            return False, 'not_image'

        content = response.content
        
        # Calculer le hash pour détecter les doublons
        img_hash = hashlib.md5(content).hexdigest()
        
        if seen_hashes is not None and img_hash in seen_hashes:
            return False, 'duplicate'
        
        if seen_hashes is not None:
            seen_hashes.add(img_hash)

        # Générer un nom de fichier unique
        parsed_url = urlparse(url)
        original_name = Path(parsed_url.path).name or 'image'
        
        # S'assurer qu'il y a une extension
        if not original_name.endswith(tuple(IMAGE_EXTENSIONS)):
            ext_map = {
                'image/jpeg': '.jpg',
                'image/png': '.png',
                'image/gif': '.gif',
                'image/webp': '.webp',
                'image/svg+xml': '.svg',
                'image/bmp': '.bmp',
            }
            ext = ext_map.get(content_type.split(';')[0], '.jpg')
            base_name = Path(original_name).stem
            original_name = f"{base_name}{ext}"

        # Gérer les doublons de nom
        dest_path = dest_folder / original_name
        counter = 1
        while dest_path.exists():
            stem = Path(original_name).stem
            suffix = Path(original_name).suffix
            dest_path = dest_folder / f"{stem}_{counter}{suffix}"
            counter += 1

        # Écrire le fichier
        with open(dest_path, 'wb') as f:
            f.write(content)

        return True, img_hash

    except requests.RequestException as e:
        return False, str(e)


def discover_all_urls(
    start_url: str,
    max_pages: int = 100,
    timeout: int = 5
) -> list[str]:
    """Découvre toutes les URLs du site avant le téléchargement."""
    base_domain = get_base_domain(start_url)

    crawled_urls = set()
    pages_to_visit = [start_url.rstrip('/')]
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

    return list(crawled_urls)[:max_pages] if max_pages > 0 else list(crawled_urls)


def crawl_site(
    start_url: str,
    dest_folder: Path,
    max_pages: int = 100,
    timeout: int = 10,
    verbose: bool = False
) -> tuple[int, int, int, int]:
    """
    Crawl toutes les pages d'un site et télécharge les images.

    Returns:
        (images_succès, images_echecs, pages_crawlées, doublons)
    """
    base_domain = get_base_domain(start_url)

    print(f"Domaine cible : {base_domain}")
    print(f"Maximum de pages à crawler : {max_pages}")
    print(f"Dossier de destination : {dest_folder}")
    print()
    
    # Phase 1 : Découvrir toutes les URLs
    urls_to_crawl = discover_all_urls(start_url, max_pages, min(timeout, 5))
    
    print(f"\n📄 {len(urls_to_crawl)} pages trouvées à crawler")
    print()

    # Phase 2 : Télécharger les images
    visited_pages = set()
    seen_image_hashes = set()
    all_images = set()

    success = 0
    failed = 0
    duplicates = 0

    with tqdm(total=len(urls_to_crawl), desc="Pages", unit="page") as pbar_pages:
        for current_url in urls_to_crawl:
            current_url = current_url.rstrip('/')
            
            if current_url in visited_pages:
                continue
                
            visited_pages.add(current_url)
            pbar_pages.update(1)

            if verbose:
                print(f"\n[Page {len(visited_pages)}/{len(urls_to_crawl)}] {current_url}")

            try:
                response = requests.get(current_url, headers=HEADERS, timeout=timeout)
                response.raise_for_status()
            except requests.RequestException as e:
                if verbose:
                    print(f"  Erreur page: {e}")
                continue

            page_images = extract_image_urls(response.text, current_url)
            new_images = page_images - all_images
            all_images.update(page_images)

            if verbose:
                print(f"  Images trouvées : {len(page_images)} ({len(new_images)} nouvelles)")

            for img_url in new_images:
                ok, result = download_image(img_url, dest_folder, timeout, seen_image_hashes)
                if ok:
                    success += 1
                elif result == 'duplicate':
                    duplicates += 1
                else:
                    failed += 1

    return success, failed, len(visited_pages), duplicates


def scrape_images(
    url: str,
    dest_folder: Path | None = None,
    max_pages: int = 100,
    timeout: int = 10,
    verbose: bool = False
) -> tuple[int, int, int]:
    """
    Scraper toutes les images d'un site complet.
    
    Args:
        url: URL du site à scraper
        dest_folder: Dossier de destination (optionnel)
        max_pages: Nombre maximum de pages à crawler
        timeout: Timeout pour les requêtes HTTP
        verbose: Afficher les détails du crawl
    
    Returns:
        Tuple (nombre de succès, nombre d'échecs, nombre de pages)
    """
    # Déterminer le dossier de destination
    if dest_folder is None:
        dest_folder = get_default_download_path(url)
    
    # Créer le dossier s'il n'existe pas
    dest_folder.mkdir(parents=True, exist_ok=True)

    # Lancer le crawl
    success, failed, pages, duplicates = crawl_site(
        url, dest_folder, max_pages, timeout, verbose
    )

    return success, failed + duplicates, pages


def main():
    parser = argparse.ArgumentParser(
        description='Scraper toutes les images d\'un site web complet.'
    )
    parser.add_argument(
        'url',
        help='URL du site à scraper'
    )
    parser.add_argument(
        '-o', '--output',
        type=Path,
        default=None,
        help='Dossier de destination (défaut: ~/Téléchargements/nom-du-site)'
    )
    parser.add_argument(
        '-t', '--timeout',
        type=int,
        default=10,
        help='Timeout en secondes pour les requêtes (défaut: 10)'
    )
    parser.add_argument(
        '-p', '--max-pages',
        type=int,
        default=100,
        help='Nombre maximum de pages à crawler (défaut: 100, 0=illimité)'
    )
    parser.add_argument(
        '-d', '--delay',
        type=float,
        default=0.0,
        help='Délai entre les requêtes en secondes (défaut: 0)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Afficher les détails du crawl'
    )

    args = parser.parse_args()

    # Valider l'URL
    if not args.url.startswith(('http://', 'https://')):
        print("Erreur: L'URL doit commencer par http:// ou https://")
        sys.exit(1)

    # Configurer le rate limiting
    if args.delay > 0:
        set_request_delay(args.delay)
        print(f"⏱️  Rate limiting : {args.delay}s entre les requêtes")

    # Lancer le scraping
    print("=" * 60)
    print("Image Scraper - Crawl complet du site")
    print("=" * 60)
    print()
    
    success, failed, pages = scrape_images(
        args.url,
        args.output,
        args.max_pages,
        args.timeout,
        args.verbose
    )

    # Résumé
    print()
    print("=" * 60)
    print(f"Terminé !")
    print(f"  Pages crawlées : {pages}")
    print(f"  Images téléchargées : {success}")
    print(f"  Échecs / doublons : {failed}")
    print(f"  Total images trouvées : {success + failed}")
    print("=" * 60)


if __name__ == '__main__':
    main()
