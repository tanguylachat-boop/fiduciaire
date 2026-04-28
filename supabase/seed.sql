-- =====================================================================
-- Seed : un cabinet fiduciaire de démo (Morand & Associés, Lausanne)
-- =====================================================================

insert into public.ai_clients (id, name, city, ide, email_inbox, plan_comptes)
values (
  '00000000-0000-0000-0000-000000000001',
  'Fiduciaire Morand & Associés',
  'Lausanne',
  'CHE-123.456.789',
  'docs@morand.lxstudio.ch',
  '[
    {"code":"1020","label":"Compte courant bancaire"},
    {"code":"1100","label":"Créances clients (débiteurs)"},
    {"code":"1170","label":"TVA récupérable (impôt préalable)"},
    {"code":"2000","label":"Dettes fournisseurs (créanciers)"},
    {"code":"2200","label":"TVA due"},
    {"code":"3200","label":"Produits des ventes"},
    {"code":"4000","label":"Charges de marchandises"},
    {"code":"4400","label":"Frais de télécommunication"},
    {"code":"5000","label":"Salaires"},
    {"code":"6000","label":"Loyer et charges"},
    {"code":"6200","label":"Frais de véhicule"},
    {"code":"6500","label":"Frais de bureau et administration"},
    {"code":"6940","label":"Frais bancaires"}
  ]'::jsonb
)
on conflict (id) do nothing;

-- Baseline performance
insert into public.ai_agent_performance (client_id, task_type, total_actions, correct_actions)
values
  ('00000000-0000-0000-0000-000000000001', 'triage', 1248, 1211),
  ('00000000-0000-0000-0000-000000000001', 'extraction', 842, 769),
  ('00000000-0000-0000-0000-000000000001', 'relance', 187, 182)
on conflict (client_id, task_type) do nothing;
