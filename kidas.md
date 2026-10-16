---
name: "RENDRAX"
slug: "rendrax"
version: "À renseigner"
status: "À renseigner"
category: "À renseigner"
author: "À renseigner"
license: "À renseigner"
platforms:
  - "Web"
  - "Linux"
  - "Android (Termux)"
technologies:
  - "JavaScript"
  - "Node.js"
  - "Python"
  - "Chromium"
  - "FFmpeg"
  - "Vercel Functions"
  - "Vercel Blob"
  - "GitHub Actions"
  - "Cloudflare Turnstile"
featured: false
github: "https://github.com/kidasniger/Kidas"
demo: "https://kidas-xi.vercel.app"
website: "À renseigner"
documentation: "À renseigner"
download: "À renseigner"
icon: "https://raw.githubusercontent.com/kidasniger/Kidas/main/logo/rendrax_icon_cutout.png"
cover: "À renseigner"
---

# Description

RENDRAX est un outil de conversion d’animations HTML en vidéos MP4. Il permet d’importer un fichier HTML, de choisir les principaux paramètres de sortie et de lancer un rendu exécuté côté serveur. Le moteur utilise Chromium pour afficher et capturer l’animation, puis FFmpeg pour encoder les images et les pistes audio disponibles. Des profils spécialisés prennent en charge le rendu image par image pour certains formats reconnus, afin de mieux préserver la chronologie et la synchronisation audio. Les pages HTML génériques sont rendues en temps réel ; leur fluidité, leur durée et leur synchronisation audio peuvent varier selon leur fonctionnement.

# Description courte

RENDRAX convertit des animations HTML en vidéos MP4 à l’aide d’un rendu côté serveur. Il propose des réglages de format, de cadence et de durée, ainsi qu’un aperçu et le téléchargement du résultat.

# Fonctionnalités

- Importer un fichier HTML ou HTM de 50 Mo maximum.
- Vérifier le fichier importé et reconnaître plusieurs profils d’animation pris en charge.
- Prévisualiser la page HTML avant de lancer la conversion.
- Choisir la résolution, la cadence d’images, le format et la durée maximale du rendu.
- Générer une vidéo MP4 avec Chromium et FFmpeg côté serveur.
- Rendre image par image les profils reconnus, avec prise en charge audio spécifique à chaque profil.
- Suivre l’avancement du rendu et consulter le journal du workflow.
- Prévisualiser, télécharger, partager et copier le lien du MP4 généré.
- Consulter l’historique des vidéos publiées et demander leur suppression depuis l’interface.

# Technologies

- JavaScript et Node.js pour l’interface et les API serveur.
- Python pour l’orchestration du rendu HTML.
- Chromium pour afficher et capturer les animations.
- FFmpeg pour encoder les vidéos MP4 et assembler les pistes audio disponibles.
- Vercel Functions pour les API serveur.
- Vercel Blob pour le stockage privé temporaire des fichiers HTML.
- GitHub Actions pour exécuter les tâches de rendu.
- Cloudflare Turnstile pour la vérification anti-robot.

# Plateformes

- Web : interface de conversion hébergée sur Vercel.
- Linux : moteur de rendu exécutable en ligne de commande, sous réserve des dépendances nécessaires.
- Android via Termux : moteur de rendu en ligne de commande, sous réserve de la disponibilité de Chromium et de FFmpeg sur l’appareil.

# Captures d'écran

- À renseigner

# Vidéos

- À renseigner

# Téléchargements

## Android

- URL: "À renseigner"
- Version: "À renseigner"
- Architecture: "À renseigner"
- Taille: "À renseigner"

## Windows

- URL: "À renseigner"
- Version: "À renseigner"
- Architecture: "À renseigner"
- Taille: "À renseigner"

## Linux

- URL: "À renseigner"
- Version: "À renseigner"
- Architecture: "À renseigner"
- Taille: "À renseigner"

## macOS

- URL: "À renseigner"
- Version: "À renseigner"
- Architecture: "À renseigner"
- Taille: "À renseigner"

# Liens

- GitHub: "https://github.com/kidasniger/Kidas"
- Démo: "https://kidas-xi.vercel.app"
- Site web: "À renseigner"
- Documentation: "À renseigner"
- Téléchargement: "À renseigner"
- YouTube: "À renseigner"
- Vidéo de présentation: "À renseigner"

# Nouveautés

- À renseigner

# Changelog

## À renseigner

- À renseigner

# SEO

## Title

RENDRAX — Convertir une animation HTML en MP4

## Description

Convertissez des animations HTML en vidéos MP4 avec RENDRAX. Importez un fichier HTML, réglez le format, la cadence et la durée, puis prévisualisez et téléchargez la vidéo générée.

## Keywords

- RENDRAX
- Convertisseur HTML en MP4
- Animation HTML en vidéo
- Conversion HTML en vidéo
- Génération de vidéo MP4

## Open Graph Image

À renseigner

## Canonical URL

À renseigner

# Informations supplémentaires

Le fichier HTML importé est envoyé vers un stockage privé temporaire, puis récupéré par le workflow de rendu autorisé. Le nettoyage du fichier temporaire est prévu à la fin du workflow. Les vidéos générées par le flux actuel sont publiées comme pièces jointes de GitHub Releases et peuvent donc être accessibles publiquement. Les profils reconnus peuvent bénéficier d’un rendu image par image ; pour les pages génériques, le rendu fonctionne en temps réel et la synchronisation audio ou la fluidité ne sont pas garanties pour toutes les animations.
