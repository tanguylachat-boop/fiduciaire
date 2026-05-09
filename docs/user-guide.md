# Guide utilisateur — Employé IA Fiduciaire

**Pour qui :** comptable senior et associé du cabinet pilote.
**Niveau :** non-technique, pas de jargon dev.

---

## 1. Le pitch en 30 secondes

Vous déposez vos pièces (factures fournisseurs, notes de frais, justificatifs) dans un dossier surveillé. L'agent les lit, les classe, propose une écriture comptable complète (compte débit, compte crédit, code TVA, libellé), et vous demande de **valider en 1 clic**, ou de corriger, ou de rejeter.

100 % en local sur le Mac Mini installé chez vous. Aucune donnée ne quitte le cabinet.

---

## 2. Le workflow quotidien

### Matin (5 min)

1. Vous (ou votre stagiaire) déposez les PDFs reçus la veille dans le dossier surveillé.
2. L'agent traite chaque pièce automatiquement (8-12 secondes par doc).
3. Vous ouvrez le dashboard `localhost:3000/entries` dans votre navigateur.

### Validation (10-15 min, 30-50 pièces)

Pour chaque écriture proposée :
- **Vous lisez la proposition** (compte, TVA, montant, libellé) à droite, le PDF original à gauche.
- 3 choix possibles :
  - **Valider** — la proposition est correcte → 1 clic, écriture marquée validée.
  - **Corriger** — vous changez 1 ou 2 champs, puis validez → l'écriture corrigée est sauvée.
  - **Rejeter** — la pièce n'est pas comptabilisable (relevé bancaire, contrat, décompte TVA) → vous indiquez la raison.

Toutes vos actions sont tracées (qui, quand, pourquoi). Vous pouvez ré-ouvrir une écriture validée pour la corriger après coup si besoin.

### Export en fin de mois (Sprint 1 — pas encore disponible en Sprint 0a)

À ce stade Sprint 0a, les écritures validées restent dans la base locale. Le **push vers Bexio** arrive en Sprint 1 (mai-juin 2026) avec un mode dry-run d'abord (vous voyez l'écriture proposée à Bexio, vous confirmez le push, on l'exécute).

---

## 3. Comment l'agent apprend

L'agent s'améliore avec le temps grâce à 3 mécanismes (le 4e — fine-tuning du modèle — n'est volontairement **pas** implémenté, voir pourquoi en bas).

### Niveau 1 — Mémoire fournisseur (déjà actif)

Quand vous synchronisez avec Bexio à l'installation, l'agent lit vos 100 dernières écritures et identifie pour chaque fournisseur récurrent (Swisscom, Migros, Romande Énergie, AVS, …) quel compte vous utilisez habituellement.

Résultat : à la première facture Swisscom, l'agent propose **directement** le compte 6510 sans même appeler le modèle IA. Confiance affichée : haute (95%+). Vous validez en 1 clic.

Couverture estimée : 60-70 % du volume mensuel typique d'un cabinet (les 20-30 fournisseurs récurrents génèrent la majorité des écritures).

### Niveau 2 — Apprentissage de vos corrections (Sprint 1, juin 2026)

Quand vous corrigez systématiquement un compte (par exemple : vous changez 6510 en 6500 pour Swisscom suite à un changement de plan comptable), l'agent retient ce signal et propose 6500 par défaut au prochain Swisscom.

Pondération temporelle : vos corrections **récentes** pèsent plus lourd que les anciennes (decay sur 90 jours). Donc l'agent suit vos évolutions de pratique sans rester bloqué sur l'historique.

### Niveau 3 — Règles métier de votre cabinet (Sprint 2, juillet 2026)

Vous pourrez écrire vos règles internes en clair, par exemple :
- *"Toute facture Swisscom > 500 CHF passe en immobilisation, demander confirmation."*
- *"Tout frais de représentation > 200 CHF doit avoir un justificatif fiscal annexé — sinon flag review humaine."*

L'agent applique ces règles automatiquement et vous demande confirmation quand l'une se déclenche.

### Pourquoi pas de fine-tuning du modèle ?

Le fine-tuning d'un modèle IA (l'entraîner sur vos données) n'est **pas** implémenté volontairement. Raisons :

- **Volume insuffisant** : un cabinet typique fait 5 000 à 10 000 écritures/an. C'est très en-dessous du volume nécessaire pour fine-tuner un modèle 24B utilement.
- **Risque d'erreurs spécifiques** : entraîner l'IA sur vos données la ferait apprendre vos *biais* (un choix de compte spécifique), pas forcément les bonnes pratiques générales.
- **Maintenance** : à chaque update du modèle (Mistral 3 → 4), il faudrait tout re-entraîner. Trop fragile pour un cabinet en production.

Les niveaux 1+2+3 atteignent 90 %+ d'accuracy sans fine-tuning. **C'est suffisant** pour le use case fiduciaire.

---

## 4. Discipline indispensable

⚠️ **L'auto-amélioration dépend à 100 % de la qualité de votre feedback humain.**

- Si vous cliquez "Valider" sans regarder, l'agent apprend de vos erreurs.
- Si votre cabinet utilise des conventions incohérentes (compte 6510 un mois, 6500 le mois suivant, sans raison), l'agent va alterner ses propositions et perdre en confiance.

**Engagement contractuel à respecter pendant le pilote :**
1. Brief 30 minutes au démarrage (un comptable senior, pas seulement le stagiaire).
2. Audit hebdomadaire des 10 dernières corrections pendant les 4 premières semaines (Tanguy + cabinet, ensemble).

Sans cette discipline, l'IA reste stupide. Avec, elle devient un vrai gain de temps en 30 jours.

---

## 5. Sécurité & confidentialité

- **Aucun appel cloud.** Le modèle Mistral Small 3 24B tourne sur votre Mac Mini local. Aucune donnée n'est envoyée à OpenAI, Anthropic, Google ou autre.
- **Connexions sortantes limitées** : seulement Bexio (votre compte) et IMAP (votre boîte mail Sprint 1+). Vous contrôlez les credentials.
- **Conformité LPD suisse révisée** : données comptables stockées en clair en local, à chiffrer (Sprint 1 SQLCipher). Archivage 10 ans natif.
- **Réversibilité totale** : code open source, vos archives sortent en CSV/PDF/JSON. Pas de verrou technique ni juridique.

---

## 6. Que faire en cas de problème

### "L'IA propose une bêtise"

→ Cliquez **Rejeter** avec la raison. L'agent retient ce qu'il ne doit pas faire.

### "Je ne reconnais pas un fournisseur dans les écritures validées"

→ Vue **Audit** dans le dashboard (Sprint 1) : trace chronologique de toutes les transitions, avec utilisateur et raison.

### "Le Mac Mini est tombé en panne"

→ SLA contractuel : remplacement sous 24h. Votre base de données est sur le NAS du cabinet (sauvegarde quotidienne chiffrée). Aucune perte d'écriture validée.

### "Je veux changer de prestataire"

→ Code, prompts et modèle vous appartiennent. Export CSV vers Bexio/Banana/Sage natif. Réversibilité contractuelle.

---

**Contact pilote :** Tanguy Lachat — `contact@lxstudio.ch`
**Dernière mise à jour :** 2026-05-09 (Sprint 0a livraison)
