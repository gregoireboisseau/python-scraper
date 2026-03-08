#!/usr/bin/env python3
"""
Script principal qui lance tous les outils de scraping et d'analyse SEO.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], description: str) -> bool:
    """Exécute une commande et retourne True si succès."""
    print(f"\n{'=' * 70}")
    print(f"🚀 {description}")
    print(f"{'=' * 70}")
    print(f"Commande : {' '.join(cmd)}\n")

    try:
        result = subprocess.run(cmd, check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Erreur lors de l'exécution : {e}")
        return False
    except KeyboardInterrupt:
        print(f"\n⚠️  Interruption par l'utilisateur")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Lance tous les outils de scraping et d\'analyse SEO.'
    )
    parser.add_argument('url', help='URL du site à analyser')
    parser.add_argument('-o', '--output', type=Path, default=None,
                        help='Dossier de sortie pour les rapports')
    parser.add_argument('-p', '--max-pages', type=int, default=100,
                        help='Nombre maximum de pages (défaut: 100, 0=illimité)')
    parser.add_argument('-t', '--timeout', type=int, default=10,
                        help='Timeout en secondes (défaut: 10)')
    parser.add_argument('-d', '--delay', type=float, default=0.0,
                        help='Délai entre les requêtes en secondes (défaut: 0)')
    parser.add_argument('-l', '--check-links', action='store_true',
                        help='Vérifier les liens brisés (plus lent)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Mode verbose')
    
    # Mode de fonctionnement (mutuellement exclusifs)
    mode_group = parser.add_argument_group('Mode de fonctionnement')
    mode_group.add_argument('--seo-only', action='store_true',
                        help='Uniquement l\'analyse SEO')
    mode_group.add_argument('--images-only', action='store_true',
                        help='Uniquement le téléchargement d\'images')

    args = parser.parse_args()

    print()
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 20 + "🕷️  PYTHON SCRAPER SUITE  " + " " * 23 + "║")
    print("╚" + "═" * 68 + "╝")
    print()
    print(f"Site cible : {args.url}")
    print(f"Max pages : {args.max_pages if args.max_pages > 0 else 'illimité'}")

    if args.output:
        print(f"Dossier de sortie : {args.output}")
    else:
        print(f"Dossier de sortie : ~/Téléchargements/{args.url.split('/')[2].replace('www.', '').replace('.', '_')}")
    
    if args.delay > 0:
        print(f"Rate limiting : {args.delay}s entre les requêtes")

    print()

    # Déterminer quels scripts lancer
    if args.seo_only:
        run_images = False
        run_seo = True
    elif args.images_only:
        run_images = True
        run_seo = False
    else:
        # Par défaut : lancer les deux
        run_images = True
        run_seo = True

    results = {}

    # 1. Analyse SEO
    if run_seo:
        cmd = [
            sys.executable, 'seo_analyzer.py',
            args.url,
            '-p', str(args.max_pages),
            '-t', str(args.timeout)
        ]

        if args.output:
            cmd.extend(['-o', str(args.output)])
        
        if args.delay > 0:
            cmd.extend(['-d', str(args.delay)])

        if args.check_links:
            cmd.append('-l')
        
        if args.verbose:
            cmd.append('-v')

        results['seo'] = run_command(cmd, "📊 ANALYSE SEO DU SITE")
    else:
        results['seo'] = None

    # 2. Scraper d'images
    if run_images:
        cmd = [
            sys.executable, 'image_scraper.py',
            args.url,
            '-p', str(args.max_pages),
            '-t', str(args.timeout)
        ]

        if args.output:
            cmd.extend(['-o', str(args.output)])
        
        if args.verbose:
            cmd.append('-v')

        results['images'] = run_command(cmd, "🖼️  TÉLÉCHARGEMENT DES IMAGES")
    else:
        results['images'] = None

    # Résumé final
    print()
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 25 + "✅  RÉSULTATS FINAUX  " + " " * 21 + "║")
    print("╚" + "═" * 68 + "╝")
    print()

    if results.get('seo') is True:
        print("  ✅ Analyse SEO : Terminée")
    elif results.get('seo') is False:
        print("  ❌ Analyse SEO : Échouée")
    elif results.get('seo') is None:
        print("  ⏭️  Analyse SEO : Ignorée")

    if results.get('images') is True:
        print("  ✅ Téléchargement images : Terminé")
    elif results.get('images') is False:
        print("  ❌ Téléchargement images : Échoué")
    elif results.get('images') is None:
        print("  ⏭️  Téléchargement images : Ignoré")

    print()
    print("=" * 70)
    print("🎉 Traitement terminé !")
    print("=" * 70)
    print()


if __name__ == '__main__':
    main()
