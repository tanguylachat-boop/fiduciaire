# 9. Relances clients automatiques

## Présentation

Le module de relances génère automatiquement des brouillons d'e-mails pour les
clients dont des pièces comptables sont manquantes. Chaque brouillon est rédigé
par l'IA locale (Ollama), validé par le collaborateur du cabinet avant envoi.

**Principe clé : aucun e-mail n'est envoyé sans validation humaine.**

---

## Niveaux d'escalade

| Niveau | Quand | Ton |
|---|---|---|
| 1ère relance (polite) | Première anomalie sans relance précédente | Cordial, simple demande |
| 2ème relance (firm) | 1 relance envoyée il y a ≥ 7 jours | Direct, rappel de la précédente |
| Escalade | 2+ relances envoyées, dernière ≥ 7 jours | Propose un appel téléphonique |

---

## Générer les relances (worker Python)

```bash
cd worker
python -m fiduciaire_worker.cli reminders generate \
  --cabinet-id gravosig-fiduciaire-01 \
  --client-id mandant-dupont
```

Cette commande :
1. Liste les anomalies ouvertes du mandant
2. Détermine le niveau de relance pour chacune
3. Génère un brouillon via Ollama (LLM local — aucune donnée quitte le serveur)
4. Stocke le brouillon en base avec `status = pending`

---

## Valider et envoyer depuis le dashboard

1. Ouvrez le dashboard → menu **Relances**
2. Cliquez **Voir** sur une relance pour lire le brouillon
3. Si nécessaire, cliquez **Modifier le brouillon** pour personnaliser le texte
4. Cliquez **Approuver** → la relance passe en `status = approved`
5. Pour envoyer par batch, sélectionnez plusieurs relances et cliquez
   **Approuver la sélection**

> **Note :** L'envoi SMTP effectif nécessite la configuration du serveur mail
> (voir §10 Configuration avancée). Par défaut, `SMTP_DRY_RUN=true` : les
> e-mails sont journalisés mais pas envoyés.

---

## Ignorer une relance

Cliquez **Ignorer** sur une relance pour la marquer `skipped`. Elle ne sera
plus proposée à l'envoi. La raison d'ignorance est conservée dans l'audit.

---

## Contact manquant

Si le badge **Sans contact** apparaît, l'adresse e-mail du client est absente
de la synchronisation Bexio. Dans ce cas :

1. Mettez à jour le contact dans Bexio
2. Relancez la synchronisation Bexio depuis le dashboard
3. Générez à nouveau les relances — le contact sera automatiquement rempli

---

## Configuration SMTP (envoi réel)

Définissez ces variables d'environnement dans le fichier `.env` du cabinet :

```bash
SMTP_HOST=mail.infomaniak.com
SMTP_PORT=587
SMTP_USER=relances@cabinet.ch
SMTP_FROM=relances@cabinet.ch
# Mot de passe chiffré Fernet — généré par le script de provisioning
SMTP_PASS_ENC=enc:v1:...
# Mettre à false pour activer l'envoi réel
SMTP_DRY_RUN=false
```

> Le mot de passe SMTP est chiffré avec la clé Fernet du cabinet. Il n'est
> jamais stocké en clair ni journalisé.

---

## Audit et traçabilité

Chaque action (création, approbation, envoi, ignoré) génère une entrée dans
la table `audit_log` avec chaînage hash SHA-256. Ces entrées sont consultables
depuis le dashboard → **Audit** et sont conservées 10 ans conformément au
droit fiscal suisse (CO art. 958f).
