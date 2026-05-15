# Décision — Reporting mensuel PDF : WeasyPrint comme moteur de rendu

**Date :** 2026-05-15
**Statut :** Actée Sprint 2 Session 11. WeasyPrint pipeline livré.
**Voir aussi :** `worker/src/fiduciaire_worker/monthly_report.py` (génération MD),
`worker/src/fiduciaire_worker/monthly_report_pdf.py` (rendu PDF).

## Contexte

Session 10 a livré le reporting mensuel en Markdown (KPIs + annexe écritures
validées). Pour le pilote femme Gravosig (install début juin), il faut un PDF
imprimable propre à joindre au mailing client mandant. Le MD reste utile
(lisible/diffable) mais ne suffit pas pour livraison cabinet.

## Options évaluées

### Option A — WeasyPrint (HTML/CSS → PDF) **[RETENUE]**

- **Pour :**
  - Pipeline simple : on génère le Markdown comme aujourd'hui, on convertit
    en HTML via `python-markdown`, on stylise via CSS print A4, WeasyPrint
    fait le PDF. Pas de runtime browser à installer (vs Puppeteer).
  - CSS print mature : `@page`, marges, pagination, `position: running()`
    pour header/footer.
  - Installable via pip pur (libs natives `pango`/`cairo` déjà dispo sur
    macOS/Linux via Homebrew/apt — `weasyprint` les bundle pour la plupart
    des plateformes modernes).
  - Output déterministe, identique entre runs (utile pour tests intégrité).
  - Pas de dépendance JS/Node : reste dans l'écosystème Python du worker.
- **Contre :**
  - Rendu CSS un peu plus strict que Chrome (ex : Flexbox limité). Pas
    gênant pour un report avec tables + sections.
  - Taille de la lib (~30MB avec deps fontconfig). Acceptable pour un
    worker server-side.

### Option B — ReportLab (API Python pure)

- **Pour :** déjà installé (`reportlab 4.4.10`), zéro dépendance système.
- **Contre :** API impérative (canvas, Frame, Story) verbeuse. Stylisation
  ne se fait pas en CSS ; chaque tableau, header, footer = code Python.
  La maintenance d'un template évolutif (couleurs, logo cabinet, footer
  pagination) demande 3-5× plus de code qu'avec HTML/CSS. Surtout coûteux
  si on doit personnaliser par cabinet (Sprint 3).

### Option C — Puppeteer / Chrome headless

- **Pour :** rendu identique à Chrome, CSS moderne complet.
- **Contre :** installe une stack Node + Chromium (~150MB), ajoute un
  process externe au worker Python, complique le déploiement sur la box
  cabinet. Overkill pour un report mensuel.

### Option D — `pandoc` MD → PDF

- **Contre :** `pandoc` + LaTeX = ~1GB de dépendances. Non pertinent pour
  un cabinet fiduciaire.

## Décision

**WeasyPrint** retenu. Pipeline livré :

```
generate_monthly_report() ─MD──► _md_to_html() ─HTML─► HTML.write_pdf() ─PDF
                                  (python-markdown      (WeasyPrint)
                                   + tables ext + CSS
                                   @page print rules)
```

Le module `monthly_report_pdf.py` :
1. Appelle `generate_monthly_report()` (réutilise la logique MD existante,
   pas de duplication des KPIs / annexe).
2. Lit le MD généré.
3. Convertit en HTML via `markdown` lib (extensions `tables`, `nl2br`,
   `extra`).
4. Injecte dans un template HTML stylé : header (cabinet name + période),
   contenu, footer (pagination + date génération).
5. WeasyPrint produit le PDF avec le même nom (extension `.pdf`).

Le CLI `worker/scripts/generate_monthly_report.py` accepte
`--format md|pdf|both` (défaut `both`).

## Design CSS print

- **Page :** A4 portrait, marges 1.5cm, langage `fr-CH`.
- **Couleurs :** noir sur blanc, accents en gris foncé `#333` / `#555` /
  `#888`. Pas de couleurs vives (cabinet fiduciaire = sobre).
- **Police :** `'Inter', 'Helvetica', system-ui, sans-serif`. WeasyPrint
  fallback automatique si Inter absent.
- **Header :** logo cabinet (placeholder vide si `logo_path=None`) + nom
  cabinet + période. Border-bottom gris.
- **Footer :** pagination `counter(page) / counter(pages)` + date
  génération à droite.
- **Tables KPIs :** bordures fines `1px solid #888`, padding 4px, font
  10pt.
- **Annexe :** tableau dense, font 9pt, alignement numérique à droite.

## Erreur si WeasyPrint manquant

Le module détecte `ImportError` au moment de l'appel et raise un
`RuntimeError` explicite (pas une stack trace). Message :
> `weasyprint non installé. Installer via : pip install weasyprint`

## Critères de succès

- ✅ PDF généré non vide (> 1KB) sur jeu de test avec ≥ 3 écritures
- ✅ Tous les KPIs présents dans le PDF (vérifié sur HTML intermédiaire)
- ✅ Multi-mandant strict : `PermissionError` si `cabinet_id != client_id`
- ✅ Decrypt automatique des descriptions chiffrées (test explicite)
- ✅ Erreur claire si WeasyPrint absent
- ⏳ Validation visuelle femme Gravosig (post-install)

## Compat Sprint 3 / cabinets multiples

Si un cabinet veut sa charte (couleur primaire, logo), on prévoit Sprint 3 :
- `cabinet_label: str` (déjà ajouté Session 11)
- `logo_path: Path | None` (déjà ajouté Session 11)
- `primary_color: str` futur (param CSS)
- `footer_text: str` futur (mention légale par cabinet)
