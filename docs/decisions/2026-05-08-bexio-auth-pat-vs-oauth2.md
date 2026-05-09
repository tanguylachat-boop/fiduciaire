# Décision — Auth Bexio : PAT en Sprint 0a, OAuth2 reporté

**Date :** 2026-05-08
**Statut :** Actée pour Sprint 0a. À reconsidérer pour version multi-cabinet (Sprint 2+).

## Contexte

L'employé IA tourne sur un Mac Mini M4 Pro **chez le cabinet**, derrière le NAT du cabinet, sans IP publique. Il doit lire le plan comptable et les 100 dernières écritures Bexio du mandant pilote.

Bexio expose 2 modes d'auth :

1. **OAuth2** (3-legged) : flux d'autorisation classique avec callback URL → access token + refresh token.
2. **Personal Access Token (PAT)** : token long-lived généré dans l'interface Bexio par l'utilisateur, équivalent API key.

## Décision

**Sprint 0a et Sprint 1 : PAT exclusivement.**

Le cabinet pilote génère son token dans l'UI Bexio (Profil → API → Personal access token), le copie dans `config/clients/<client_id>.yaml` (chiffré via Keychain macOS, pas en clair dans le YAML).

**Sprint 2+ multi-cabinet : OAuth2** avec callback hébergé sur Vercel ou Render, et refresh tokens stockés chiffrés.

## Pourquoi PAT en Sprint 0a

- **Pas de callback URL nécessaire.** OAuth2 nécessite une URL publique pour recevoir le code d'autorisation. Le Mac Mini cabinet est derrière le NAT, sans port forwarding garanti, sans certificat TLS public.
- **Setup en 5 minutes.** Le cabinet génère son token, on le copie, c'est fini. Pas de DNS, pas de TLS, pas de proxy Cloudflare Tunnel.
- **Une seule machine = un seul token.** En Sprint 0a on a 1 cabinet, 1 mandant. La complexité OAuth2 (refresh, expiration, multi-tenant tokens) n'apporte rien.
- **Sécurité équivalente pour ce cas.** PAT révocable côté Bexio en 1 clic, scope limité au cabinet. Comme un Apple App-Specific Password.

## Pourquoi OAuth2 sera nécessaire à terme

Multi-cabinet (à partir de Sprint 2 quand on déploie chez le 3e cabinet) :

- Le cabinet ne veut pas générer un PAT à la main, ni le coller dans une config.
- L'app a besoin de représenter le cabinet pour des appels API → OAuth2 avec scopes.
- Refresh automatique des tokens.
- Audit trail côté Bexio sur "quelle app a fait quel appel".

À ce moment-là : callback URL hébergée sur `https://app.lxstudio.ch/oauth/bexio/callback` (Vercel ou Render), tokens chiffrés en base.

## Implémentation Sprint 0a

```python
# config/clients/<client_id>.yaml (PAT chargé via Keychain, jamais en clair)
client_id: jura-mandant-pilote
bexio:
  pat_keychain_account: "fiduciaire-bexio-jura-pilote"
  base_url: "https://api.bexio.com/2.0"
```

Côté code :
```python
import keyring
pat = keyring.get_password("fiduciaire", config["bexio"]["pat_keychain_account"])
headers = {"Authorization": f"Bearer {pat}"}
```

## Risques résiduels

- **PAT compromis = accès lecture seule au cabinet.** Mitigé par : Keychain macOS chiffré au repos, jamais loggé, rotation manuelle tous les 6 mois minimum.
- **Pas d'audit Bexio "quelle app".** En Sprint 0a, on documente tous les appels côté local SQLite (table `bexio_sync.actions`). Le cabinet a un journal local équivalent.

## Alternatives écartées

- **OAuth2 avec callback localhost** : ne marche que pour CLI tools, pas pour service launchd qui tourne sans browser.
- **OAuth2 avec Cloudflare Tunnel sur le Mac Mini** : possible techniquement mais ajoute une dépendance externe au "100% local" (un autre tunnel par lequel les tokens passent).
- **OAuth2 device code flow** : Bexio ne le supporte pas (vérifié sur la doc API publique).
