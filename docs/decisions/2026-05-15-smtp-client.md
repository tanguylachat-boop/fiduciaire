# Decision — SMTP Client avec Fernet

**Date** : 2026-05-15
**Auteur** : Tanguy Lachat / Claude
**Statut** : Approuvé

## Contexte

Les relances approuvées doivent être envoyées par email depuis le cabinet. Le mot de passe SMTP ne doit jamais apparaître en clair dans les logs, la DB ou les variables d'environnement non chiffrées.

## Décision

`smtp_client.py` :
- Lecture `SMTP_PASS_ENC` (env var chiffrée Fernet, préfixe `enc:v1:`)
- Déchiffrement via `encryption.decrypt_column_value()` au moment de l'envoi uniquement
- `SMTP_DRY_RUN=true` par défaut → log l'email sans l'envoyer
- `send_reminder(reminder_id, conn, dry_run=None)` → lit la relance DB, envoie via SMTP, update `status=sent` + `sent_at`
- Audit `log_audit_event()` sur chaque tentative (succès et échec)

## Contraintes

- Jamais de mot de passe en clair dans les logs (`caplog` test vérifie)
- Timeout SMTP configurable (SMTP_TIMEOUT_S, défaut 30s)
- Retry : 1 retry sur timeout, 0 retry sur auth error (fail fast)
- `status=failed` + `error_message` stockés sur exception non récupérable

## Alternatives rejetées

- **OAuth2 SMTP (Gmail)** : nécessite compte Google Cabinet — on garde SMTP générique (Infomaniak, Swisscom)
- **Mot de passe en plaintext env var** : rejeté — même en prod `.env` non versionné, le principe de moindre privilège exige le chiffrement Fernet
