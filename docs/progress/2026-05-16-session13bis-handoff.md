# Session 13bis — Handoff

**Date** : 2026-05-16
**Branch** : feature/sprint-0a-core
**Commit** : (à créer)

## Objectifs session

- C1 `reminder_engine.py` — moteur de relances TDD ✅
- C2 `smtp_client.py` — envoi SMTP Fernet TDD ✅
- C3 Dashboard `/reminders` Next.js ✅
- C4 Templates FR polite/firm/escalation ✅ (créés fin session 13)

## Livrables

### Python worker

| Fichier | Tests |
|---|---|
| `worker/src/fiduciaire_worker/reminder_engine.py` | 8 tests TDD verts |
| `worker/src/fiduciaire_worker/smtp_client.py` | 7 tests TDD verts |
| `worker/src/fiduciaire_worker/templates/reminders/polite_fr.md` | — |
| `worker/src/fiduciaire_worker/templates/reminders/firm_fr.md` | — |
| `worker/src/fiduciaire_worker/templates/reminders/escalation_fr.md` | — |

### TypeScript / Next.js

| Fichier | Tests |
|---|---|
| `lib/db-poc-reminders.ts` | 8 smoke TS |
| `lib/db-poc-reminders-write.ts` | 8 smoke TS |
| `app/(poc)/reminders/page.tsx` | — |
| `app/(poc)/reminders/actions.ts` | — |
| `components/poc/ReminderList.tsx` | — |
| `scripts/test-reminders.ts` | 8/8 ✅ |

### Documentation

- `docs/decisions/2026-05-15-reminder-engine-v1.md`
- `docs/decisions/2026-05-15-smtp-client.md`
- `docs/decisions/2026-05-15-reminder-templates.md`
- `docs/user-guide/09-relances-clients.md`

## Métriques

| Métrique | Avant | Après |
|---|---|---|
| Tests Python | 379 | 389 |
| Smoke TS | 42 | 50 (8 nouveaux) |

## Architecture reminder_engine

```
Anomaly (state=open)
  └── _determine_level() → polite / firm / escalation
  └── _find_contact() → email client ou needs_contact_info=True
  └── _render_template() → template FR .replace() {{vars}}
  └── _generate_draft() → Ollama local → (subject, body_draft)
  └── INSERT reminders (status=pending)
  └── log_audit_event(action=reminder_created)
```

## Architecture smtp_client

```
send_reminder(rid) [status=approved requis]
  └── _get_smtp_config() → valide SMTP_PASS_ENC obligatoire
  └── _decrypt_smtp_pass() → Fernet, jamais loggué
  └── SMTP_DRY_RUN=true → log + status=sent (pas d'envoi)
  └── SMTP_DRY_RUN=false → smtplib.SMTP + sendmail
  └── Echec → status=failed + error_message
  └── log_audit_event(action=reminder_sent | reminder_send_failed)
```

## Ce qui reste (Sprint 3 / Session 14)

- `send_reminder()` intégration avec le bouton "Envoyer" du dashboard (actuellement approve uniquement)
- Configuration SMTP live à Gravosig (semaine du 19 mai 2026)
- Régénération user-guide PDF avec le chapitre 09
- Tests E2E reminder → smtp → audit chain
