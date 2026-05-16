# Session 13ter — Handoff

**Date** : 2026-05-16
**Branch** : feature/sprint-0a-core
**Base** : bc16a7d (S13bis)

## Objectif

Brancher le bouton "Envoyer" du dashboard `/reminders` au module Python
`smtp_client.send_reminder()` via un script CLI (pattern identique à `import_camt.py`).

## Livrables

| Fichier | Rôle |
|---|---|
| `worker/scripts/send_reminder.py` | CLI pont Node→Python, JSON stdout pur |
| `worker/tests/test_send_reminder_script.py` | 4 tests TDD subprocess verts |
| `app/(poc)/reminders/actions.ts` | Server Actions + `runSendReminderScript()` + `batchSendReminders` |
| `components/poc/ReminderList.tsx` | Bouton "Envoyer", feedback dry_run, batch count |
| `scripts/test-send-reminder.ts` | 3 smoke TS verts |

## Métriques

| Métrique | Avant (S13bis) | Après |
|---|---|---|
| Tests Python | 389 | 393 (+4) |
| Smoke TS | 50 | 53 (+3) |
| TypeScript | ✅ | ✅ |

## Architecture du pont

```
[Bouton "Envoyer" dashboard]
  └── Server Action approveAndSendReminder(formData)
        ├── approveReminder(id, cabinetId)         [DB write TypeScript]
        └── runSendReminderScript(id, cabinetId)
              └── spawn(python, send_reminder.py)
                    ├── Vérifie cabinet_id + status='approved'
                    ├── smtp_client.send_reminder(rid, conn)
                    │     ├── SMTP_DRY_RUN=true → log + status=sent
                    │     └── SMTP_DRY_RUN=false → smtplib.SMTP + sendmail
                    └── stdout JSON {ok, reminder_id, status, dry_run, sent_at}

[Bouton "Envoyer la sélection"]
  └── Server Action batchSendReminders(formData)
        └── Boucle : approveReminder + runSendReminderScript par ID
        └── Retourne {total, sent, failed, errors[]}
```

## USER ACTION MAP — Comment tester en local (dry-run)

### 1. Générer des relances avec le worker Python

```bash
cd /Users/tanguylachat/fiduciaire/worker

# Avec Ollama (LLM local actif)
.venv/bin/python -c "
import sqlite3
from fiduciaire_worker.audit_log import init_audit_schema
from fiduciaire_worker.missing_docs_detector import init_anomalies_schema
from fiduciaire_worker.reminder_engine import init_reminders_schema, generate_reminders

conn = sqlite3.connect('data/fiduciaire.sqlite')
conn.row_factory = sqlite3.Row
init_anomalies_schema(conn)
init_audit_schema(conn)
init_reminders_schema(conn)

ids = generate_reminders('gravosig-fiduciaire-01', 'dupont-sa', conn)
print(f'Créées : {ids}')
"
```

### 2. Approuver et envoyer via le script CLI (dry-run)

```bash
# Variables d'environnement (dry-run par défaut)
export SMTP_DRY_RUN=true
export SMTP_PASS_ENC="dummy-for-test"
export SMTP_HOST="mail.infomaniak.com"
export SMTP_USER="relances@cabinet.ch"
export FIDUCIAIRE_ENCRYPTION_DISABLED=true  # pour les tests locaux uniquement

# D'abord approuver la relance en DB
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('data/fiduciaire.sqlite')
conn.row_factory = sqlite3.Row
conn.execute(\"UPDATE reminders SET status='approved' WHERE id=1 AND cabinet_id='gravosig-fiduciaire-01'\")
conn.commit()
"

# Puis lancer l'envoi via le script CLI
.venv/bin/python worker/scripts/send_reminder.py \
  --reminder-id 1 \
  --cabinet-id gravosig-fiduciaire-01

# Output attendu :
# {"ok": true, "reminder_id": 1, "status": "sent", "dry_run": true, "sent_at": "2026-05-16T..."}
```

### 3. Via le dashboard (bouton "Envoyer")

```bash
cd /Users/tanguylachat/fiduciaire
SMTP_DRY_RUN=true SMTP_PASS_ENC=dummy SMTP_HOST=localhost SMTP_USER=test@test.ch \
  npx next dev
```

Ouvrir http://localhost:3000/reminders → bouton "Envoyer" sur une relance pending.

## Bascule SMTP_DRY_RUN=false chez Gravosig (semaine du 19 mai)

**Étapes exactes :**

1. Créer le mot de passe chiffré :
   ```bash
   .venv/bin/python -c "
   from fiduciaire_worker.encryption import encrypt_column_value
   print(encrypt_column_value('MOT_DE_PASSE_SMTP_REEL', 'gravosig-fiduciaire-01'))
   "
   ```

2. Copier la valeur `enc:v1:...` dans le `.env` du cabinet :
   ```bash
   SMTP_HOST=mail.infomaniak.com
   SMTP_PORT=587
   SMTP_USER=relances@gravosig.ch
   SMTP_FROM=relances@gravosig.ch
   SMTP_PASS_ENC=enc:v1:...  # valeur générée ci-dessus
   SMTP_DRY_RUN=false         # BASCULE ICI
   ```

3. Tester avec 1 relance test avant la mise en prod :
   ```bash
   .venv/bin/python worker/scripts/send_reminder.py \
     --reminder-id TEST_ID --cabinet-id gravosig-fiduciaire-01
   ```

## Audit log post-envoi

Après un envoi réussi (ou dry-run), vérifier la trace dans l'audit :

```sql
SELECT entity_id, action, after_json, timestamp
FROM audit_log
WHERE entity_type = 'reminder'
ORDER BY timestamp DESC
LIMIT 10;
```

Résultat attendu :
- `action = 'reminder_sent'` avec `after_json = {"dry_run": true/false, "to": "...", "subject": "..."}`

## Debugger si SMTP refuse la connexion

```bash
# Test SMTP direct (telnet)
nc -zv mail.infomaniak.com 587

# Vérifier la config chargée
.venv/bin/python -c "
import os; os.environ['SMTP_PASS_ENC']='test'; os.environ['SMTP_HOST']='localhost'
os.environ['SMTP_USER']='t@t.ch'; os.environ['FIDUCIAIRE_ENCRYPTION_DISABLED']='true'
from fiduciaire_worker.smtp_client import _get_smtp_config
print(_get_smtp_config())
"

# Logs du script (stderr)
.venv/bin/python worker/scripts/send_reminder.py \
  --reminder-id 1 --cabinet-id gravosig-fiduciaire-01 \
  --log-level DEBUG 2>&1 | grep -E "ERROR|SMTP|smtp"
```
