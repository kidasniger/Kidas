---
name: "À renseigner"
slug: "À renseigner"
version: "À renseigner"
status: "À renseigner"
category: "À renseigner"
author: "À renseigner"
license: "À renseigner"
platforms: ["Linux", "Termux (Android)", "Web"]
technologies: ["Python", "FFmpeg", "Chromium (Chrome DevTools Protocol)", "GitHub Actions", "HTML", "CSS", "JavaScript", "Vercel"]
featured: false
github: "https://github.com/kidasniger/Kidas"
demo: "À renseigner"
website: "À renseigner"
documentation: "À renseigner"
download: "À renseigner"
icon: "À renseigner"
cover: "À renseigner"
---

# Description

Outil qui transforme une animation HTML en vidéo MP4 avec le son, sans enregistrement d'écran. Le rendu est réalisé image par image dans Chromium, puis assemblé avec l'audio par FFmpeg. L'outil se compose d'un script Python (html2mp4.py, accompagné du paquet h2m), d'un workflow GitHub Actions qui effectue le rendu dans le cloud, et d'une page web (dossier docs) qui permet d'importer un fichier HTML et de lancer la conversion. Le script reconnaît des fichiers HTML connus (profils KIDAS, EditPro, MusicPro) et propose aussi un mode universel pour les fichiers qu'il ne connaît pas. La vidéo produite porte le nom du fichier HTML d'origine.

# Description courte

Convertit une animation HTML en vidéo MP4 avec le son, rendue image par image avec Chromium et FFmpeg, en local ou via GitHub Actions.

# Fonctionnalités

- Rendu image par image, sans enregistrement d'écran
- Assemblage de la vidéo et de l'audio avec FFmpeg
- Reconnaissance automatique de fichiers HTML connus (KIDAS, EditPro, MusicPro) et mode universel pour les autres fichiers
- Format de sortie au choix : auto, portrait, paysage ou carré
- Réglage des images par seconde, de l'échelle et de la durée maximale
- Rendu d'essai limité à un nombre de secondes choisi
- Qualité d'encodage au choix : standard, fast ou high
- Normalisation du volume à -16 LUFS (option)
- Nom du MP4 identique à celui du fichier HTML, ou nom personnalisé
- Résumé du niveau audio et vérification de la synchronisation
- Nouvel essai automatique en cas d'erreur de Chromium
- Menu interactif en ligne de commande pour choisir le fichier HTML
- Lancement du rendu dans le cloud avec GitHub Actions depuis une page web
- Tests automatisés du script (workflow test-render)

# Technologies

- Python
- FFmpeg
- Chromium (Chrome DevTools Protocol)
- websocket-client
- GitHub Actions
- HTML, CSS et JavaScript
- Vercel (hébergement statique du dossier docs)

# Plateformes

- Linux
- Termux (Android)
- Web

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
- Démo: "À renseigner"
- Site web: "À renseigner"
- Documentation: "À renseigner"
- Téléchargement: "À renseigner"
- YouTube: "À renseigner"
- Vidéo de présentation: "À renseigner"

# Nouveautés

- Reconnaissance des fichiers HTML inconnus et ajout du profil MusicPro pour la capture audio
- Table de profils, qualités d'encodage, normalisation du volume, nom de sortie basé sur le fichier HTML, résumé audio et nouvel essai de Chromium
- Nouvelle page d'index pour la conversion HTML vers MP4
- Dossier docs servi comme site statique sur Vercel

# Changelog

## À renseigner

- Ajout de la vérification automatique des fichiers HTML (KIDAS, EditPro)
- Import des fichiers HTML sur une branche séparée
- Refonte de la page d'index HTML vers MP4
- Correction de la capture audio pour les fichiers HTML inconnus et ajout du profil MusicPro
- Amélioration du rendu : table de profils, qualité d'encodage, normalisation du volume, nom de sortie basé sur le fichier HTML, résumé audio, nouvel essai de Chromium
- Publication du dossier docs comme site statique sur Vercel

# SEO

## Title

HTML → MP4 · Kidas Studio

## Description

Transforme une animation HTML en vidéo MP4 avec le son, rendue image par image par GitHub Actions.

## Keywords

- À renseigner

## Open Graph Image

À renseigner

## Canonical URL

À renseigner

# Informations supplémentaires

Une connexion Internet est nécessaire pendant le rendu : React et la police Sora sont chargés depuis un CDN. Le script s'utilise en ligne de commande (python html2mp4.py) sous Linux ou Termux, avec FFmpeg et un navigateur Chromium. Le workflow GitHub Actions s'exécute sur ubuntu-latest, avec une durée maximale de 90 minutes. La vidéo est enregistrée dans le même dossier que le fichier HTML, sous le nom de ce fichier.
