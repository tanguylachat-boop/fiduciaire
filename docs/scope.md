# Scope POC — Phase 1

## Ce qu'on livre

Une boîte qui tourne en local chez le cabinet et qui résout **un seul problème** : transformer un dépôt d'inbox documentaire bordélique (PDF + scans + photos) en arborescence client classée propre, sans intervention humaine sauf pour les cas incertains.

## Ce qu'on ne livre PAS (Phase 1)

- Pas d'API Bexio / WinBIZ / Crésus / Abacus.
- Pas d'extraction d'écritures comptables (compte débit/crédit).
- Pas de relances factures clients.
- Pas de multi-tenant : 1 cabinet = 1 instance.
- Pas de Supabase, pas de n8n, pas de cloud.
- Pas de sync IMAP : le cabinet dépose les fichiers manuellement (pour l'instant).

## Critères de réussite démo

- ≥ 80 % de précision sur 50 documents réels mixtes (factures FR/DE, relevés bancaires CH, notes de frais, documents fiscaux).
- Latence < 30 s par document sur Mac Mini M4 Pro 64 GB.
- Aucun appel réseau sortant pendant un traitement (vérifié avec Little Snitch).
- Une vidéo de 2 minutes qui montre : drag-drop dans inbox → 5 documents triés → 1 cas en review → validation manuelle dans le dashboard.

## Hors scope explicite

Les éléments suivants sont reportés à Phase 2 / 3 et ne doivent **pas** consommer de temps cette semaine, même si "ça serait facile à ajouter" :

- Détection automatique du type de TVA (taux 8.1 %, taux réduit, exonéré).
- Recherche full-text dans les documents archivés.
- Notifications email / Slack / Telegram.
- Multi-utilisateur, rôles, RBAC.
- Backup chiffré offsite.
- Mode hors-ligne dégradé (pas de LLM disponible).
