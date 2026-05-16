"""Plan comptable suisse standard (KMU-Kontenrahmen 2024) — seed minimum.

28 comptes principaux qui couvrent ~95% des écritures cabinet PME typique.
Les comptes manquants sont seedés par pull Bexio (Sprint 1 §3.1) ou Winbiz
(Sprint 3 quand le pull natif sera dispo).

Référence : norme PME suisse (KMU-Kontenrahmen) — usage public, non
copyrighté pour la nomenclature de base.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedAccount:
    account_no: str
    name: str
    account_type: str  # asset | liability | equity | revenue | expense


# Ordre : actifs → passifs → capitaux propres → produits → charges → hors expl.
SEED_PLAN_COMPTABLE_SUISSE: list[SeedAccount] = [
    # --- 1xxx Actifs --------------------------------------------------------
    SeedAccount("1000", "Caisse", "asset"),
    SeedAccount("1020", "Banque (compte courant)", "asset"),
    SeedAccount("1100", "Créances clients", "asset"),
    SeedAccount("1170", "TVA déductible (Impôt préalable)", "asset"),
    SeedAccount("1200", "Stocks de marchandises", "asset"),
    SeedAccount("1400", "Marchandises", "asset"),
    SeedAccount("1500", "Machines et équipements", "asset"),
    SeedAccount("1510", "Mobilier de bureau", "asset"),

    # --- 2xxx Passifs -------------------------------------------------------
    SeedAccount("2000", "Dettes fournisseurs", "liability"),
    SeedAccount("2100", "Dettes bancaires court terme", "liability"),
    SeedAccount("2200", "TVA collectée (Impôt dû)", "liability"),
    SeedAccount("2202", "Décompte TVA", "liability"),
    SeedAccount("2270", "Charges sociales à payer", "liability"),

    # --- 28xx Capitaux propres ---------------------------------------------
    SeedAccount("2800", "Capital", "equity"),
    SeedAccount("2900", "Réserves", "equity"),

    # --- 3xxx Produits ------------------------------------------------------
    SeedAccount("3000", "Ventes de prestations de services", "revenue"),
    SeedAccount("3200", "Ventes de marchandises", "revenue"),
    SeedAccount("3400", "Produits accessoires", "revenue"),

    # --- 4xxx-6xxx Charges --------------------------------------------------
    SeedAccount("4000", "Achats de marchandises", "expense"),
    SeedAccount("5000", "Salaires", "expense"),
    SeedAccount("5700", "Charges sociales (AVS/AI/APG/AC)", "expense"),
    SeedAccount("6000", "Loyer locaux commerciaux", "expense"),
    SeedAccount("6100", "Entretien et réparations", "expense"),
    SeedAccount("6200", "Véhicules (frais)", "expense"),
    SeedAccount("6400", "Énergie et eau", "expense"),
    SeedAccount("6500", "Frais administratifs", "expense"),
    SeedAccount("6510", "Frais de télécommunication", "expense"),
    SeedAccount("6600", "Frais de marketing / publicité", "expense"),

    # --- 8xxx Hors exploitation --------------------------------------------
    SeedAccount("8000", "Charges hors exploitation", "expense"),
    SeedAccount("8500", "Impôts directs", "expense"),
]


def seed_account_count() -> int:
    return len(SEED_PLAN_COMPTABLE_SUISSE)
