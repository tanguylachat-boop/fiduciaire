# Décision — WinBIZ / Crésus / Abacus : export CSV/XML, pas API

**Date :** 2026-05-08
**Statut :** Actée pour Sprint 2. Plan B si API non accessible / non licenciée.

## Contexte

Marché fiduciaire suisse : Bexio domine sur les nouveaux cabinets, mais **WinBIZ, Crésus et Abacus** restent dominants chez les cabinets installés depuis >10 ans. Le pilote Jura est sur Bexio (à confirmer), mais le 2e ou 3e cabinet sera très probablement sur WinBIZ ou Crésus.

Question : quand on intègre WinBIZ, on tape l'API ou on exporte un fichier ?

## Réalité des APIs

| Logiciel | API publique ? | Coût | Friction |
|---|---|---|---|
| Bexio | Oui, REST v2/v3, OAuth2/PAT | inclus | faible |
| WinBIZ | Partielle, "WinBIZ Cloud" uniquement, pas WinBIZ Desktop | licence WinBIZ Cloud requise | élevée |
| Crésus | Module "Crésus Synchro" payant, format propriétaire | licence Crésus + module Synchro | très élevée |
| Abacus | "AbaConnect" (XML), bien documenté mais licence | licence AbaConnect | moyenne |

Beaucoup de cabinets utilisent les versions **desktop legacy** (WinBIZ Desktop, Crésus Comptabilité standard) sans modules cloud/sync. Pour eux, **pas d'API du tout**.

## Décision

**Sprint 2 : export CSV/XML par défaut, pas d'API.**

L'employé IA produit un fichier d'écritures (format propre au logiciel cible) que le fiduciaire **importe en 1 clic** dans son logiciel comptable. Pas d'écriture programmatique directe.

Formats par logiciel :

| Logiciel | Format export |
|---|---|
| Bexio | API directe (Sprint 1 push) — le cas chouchou |
| WinBIZ | CSV avec headers `Date,Pièce,Compte_Débit,Compte_Crédit,Libellé,Montant,Code_TVA` (mapping à confirmer doc WinBIZ) |
| Crésus | XML format Crésus (à confirmer doc) ou CSV générique en fallback |
| Abacus | XML AbaConnect si licence dispo, sinon CSV |

## Pourquoi pas d'API direct sur WinBIZ/Crésus/Abacus

- **Licence des modules sync coûte cher** au cabinet (300-1000 CHF/an supplémentaires). Le cabinet ne va pas la payer juste pour notre intégration.
- **APIs souvent partielles** (lecture OK, écriture limitée à certains journaux).
- **Risque de casse** : un update du logiciel comptable côté cabinet peut casser l'API silencieusement.
- **Certificat / partenariat éditeur requis** parfois → mois de négociation.

## Pourquoi le CSV/XML import suffit

- **1 clic au lieu de re-saisie** = 90% de la valeur perçue. Le fiduciaire passe de "je tape 30 écritures à la main" à "je clique sur Importer et je relis".
- **Robuste** : un format CSV standard ne casse pas avec une mise à jour du logiciel.
- **Validé par le marché** : la plupart des outils tiers fiduciaires (BMD, Topal) intègrent par CSV/import.

## Stratégie commerciale

Ne pas vendre "intégration native WinBIZ" si on ne l'a pas. Vendre **"écritures prêtes à importer en 1 clic dans WinBIZ / Crésus / Abacus / Bexio"**. Honnête et suffisant.

Plus tard (M12+, multi-cabinet stable), si on a 10 cabinets sur Crésus, négocier partenariat éditeur Crésus pour API native.

## Spécifications mapping CSV (template Sprint 2)

À documenter dans `docs/specs/connector-csv-format.md` :

```
date,piece_no,debit_account,credit_account,description,amount_chf,vat_code,vat_amount_chf
2026-05-15,FF-2026-0042,4400,2000,"Swisscom téléphonie",189.50,TN_NORM,14.20
```

Headers + delimiter à valider avec chaque cabinet (Crésus accepte autre chose, à voir).

## Risques

- **Format propriétaire change** : un upgrade WinBIZ peut changer le mapping CSV attendu. Mitigation : config par cabinet `config/clients/<id>.yaml` avec format CSV custom si nécessaire.
- **Codes TVA logiciel-spécifiques** : WinBIZ a ses codes (M81, M026), Crésus a les siens. Mitigation : table de mapping dans `config/vat_codes_ch.yaml` par logiciel cible.

## Alternatives écartées

- **API native uniquement** : limite la cible aux cabinets qui ont la licence cloud/sync. Probablement <30% du marché fiduciaire CH.
- **Pas d'intégration du tout, juste un PDF d'écritures à recopier** : retire 90% de la valeur perçue ("ah donc je dois quand même tout retaper").
