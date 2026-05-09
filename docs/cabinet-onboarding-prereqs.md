# Prérequis cabinet pilote — à fournir avant lundi 11 mai 2026 12h

Ce document liste précisément ce dont l'employé IA a besoin pour la démo Loom de lundi 18h. À envoyer au cabinet pilote (Jura) **vendredi 8 mai soir** dernier délai.

---

## 1. Token API Bexio (10 minutes)

L'employé IA a besoin de lire votre plan comptable et vos 100 dernières écritures (lecture seule, **aucune écriture envoyée**).

### Comment générer le token

1. Connectez-vous à votre compte Bexio (https://office.bexio.com).
2. Allez dans **Profil → Réglages → API**.
3. Cliquez sur **"Personal Access Token"** → **"Générer un nouveau token"**.
4. Nommez-le `employe-ia-fiduciaire-pilote`.
5. **Scope** : *Lecture seule* (toutes les permissions de lecture, aucune permission d'écriture).
6. Copiez le token (commence par `eyJ...`) — il ne sera plus jamais affiché après.

### Comment nous le transmettre (sécurisé)

**Pas par email en clair.** Au choix :

- **Option A** — Bitwarden Send : créez un Send avec le token, durée 24h, mot de passe additionnel par SMS séparé.
- **Option B** — Signal/WhatsApp : message vocal contenant le token, supprimé après lecture.
- **Option C** — Lors d'un call de 10 min lundi 11 mai 9h, vous le copiez en partage d'écran et nous le saisissons directement dans le Mac Mini.

### Ce que nous en faisons

- Stocké dans le Trousseau macOS (Keychain) du Mac Mini que nous installons chez vous.
- Jamais loggé en clair, jamais transmis ailleurs.
- Vous pouvez révoquer le token à tout moment côté Bexio en 1 clic.

---

## 2. Corpus de 50 documents anonymisés (le plus critique)

Pour mesurer la qualité des propositions d'écritures **sur vos vrais documents** avant la démo, nous avons besoin d'un échantillon représentatif.

### Mix demandé (50 docs au total)

| Type | Nombre | Pourquoi |
|---|---|---|
| Factures fournisseurs (telecom, fournitures, énergie, IT) | 25 | Cas le plus fréquent en cabinet |
| Factures clients (de vos mandants vers leurs clients) | 10 | Vérifier proposition compte produit + TVA collectée |
| Relevés bancaires (extraits PDF / scans) | 5 | Pour la suite (rapprochement bancaire Sprint 1) |
| Notes de frais (tickets de caisse, restaurants, taxis) | 5 | Petits montants, cas piégeux TVA |
| Documents fiscaux (décomptes TVA, AVS, etc.) | 5 | Cas d'exception |

### Comment anonymiser (15 minutes par batch de 10)

**À conserver** (le bench en a besoin) :
- Montants exacts (HT, TVA, TTC)
- Dates exactes
- Codes TVA mentionnés
- Type de document
- Structure visuelle (logos OK floutés grossièrement)
- IBAN structurels (gardez "CH..." mais remplacez les chiffres pour rendre l'IBAN factice)

**À masquer** :
- Nom et adresse du client final (votre mandant) → remplacer par "Client A", "Client B"
- Numéro AVS, numéros de TVA spécifiques
- Numéros de compte bancaire complets
- Tout détail nominatif identifiable

### Format de livraison

Un dossier zip avec :
```
corpus-jura-50.zip
├── 01-facture-fournisseur-swisscom.pdf
├── 02-facture-fournisseur-electricite.pdf
├── ...
└── ground-truth.csv
```

`ground-truth.csv` (vous nous le remplissez avec ce que **vous** auriez saisi) :

```csv
filename,debit_account,credit_account,amount_chf,vat_code,description
01-facture-fournisseur-swisscom.pdf,6510,2000,189.50,TN_NORM,"Swisscom abonnement entreprise"
02-facture-fournisseur-electricite.pdf,6000,2000,425.00,TN_NORM,"Electricité bureaux mai 2026"
...
```

C'est ce fichier qui nous sert de **vérité-terrain** pour mesurer la qualité.

### Deadline

Idéalement **vendredi 8 mai 18h**, sinon **samedi 9 mai 12h dernier délai** (sinon impossible de bencher avant la démo).

---

## 3. Confirmations rapides (5 minutes)

Cocher dans un email retour :

- [ ] Logiciel comptable principal du mandant pilote : **Bexio** / WinBIZ / Crésus / Abacus / autre : ___________
- [ ] Plan comptable utilisé : **standard PME suisse** (KMU-Kontenrahmen) / plan custom du cabinet (joindre fichier)
- [ ] Banques principales du cabinet : ___________
- [ ] Banques principales des mandants (top 3) : ___________
- [ ] OK pour démo Loom 2 minutes lundi 18h portant sur **"l'IA propose une écriture, vous validez en 1 clic"**, **sans push direct vers Bexio** ? *(le push automatique vers Bexio arrive en semaine 2-3 après votre feedback initial)*

---

## 4. Calendrier proposé

| Date | Action |
|---|---|
| Vendredi 8 mai soir | Vous nous envoyez ce qui est prêt + planifiez la livraison du corpus |
| Samedi 9 mai 12h | Corpus 50 docs anonymisés reçu |
| Samedi 9 mai - dimanche 10 mai | Bench + ajustements de notre côté |
| Lundi 11 mai 9h | Call 10 min : token Bexio en partage d'écran |
| Lundi 11 mai 18h | Démo Loom 2 min envoyée |

---

## 5. Ce que nous **ne demandons pas** à ce stade

Pour clarifier la confidentialité :

- Pas d'accès direct à votre boîte email (Sprint 1).
- Pas d'accès direct aux comptes bancaires de vos mandants (Sprint 1).
- Pas de WhatsApp Business (Sprint 2).
- Pas d'envoi de relances clients en votre nom (Sprint 2, validation manuelle systématique).
- Aucune donnée transmise à OpenAI, Anthropic, Google ou autre service tiers. Tout reste sur le Mac Mini chez vous.

---

## Contact

Tanguy Lachat — contact@lxstudio.ch — +41 XX XXX XX XX (à compléter)

Pour tout doute sur l'anonymisation, envoyez 1 doc anonymisé en exemple **avant** d'en faire 50, on valide ensemble.
