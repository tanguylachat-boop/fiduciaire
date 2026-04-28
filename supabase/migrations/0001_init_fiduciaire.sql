-- =====================================================================
-- Fiduciaire AI — schéma multi-tenant
-- Toutes les tables sont préfixées `ai_` et filtrées par client_id (cabinet)
-- RLS pattern LX Studio : DROP POLICY IF EXISTS puis CREATE POLICY
-- =====================================================================

create extension if not exists "uuid-ossp";

-- ---------------------------------------------------------------------
-- Table : clients (cabinets fiduciaires)
-- ---------------------------------------------------------------------
create table if not exists public.ai_clients (
  id uuid primary key default uuid_generate_v4(),
  name text not null,
  city text,
  ide text,
  email_inbox text unique,
  logo_url text,
  plan_comptes jsonb default '[]'::jsonb,
  custom_rules jsonb default '[]'::jsonb,
  created_at timestamptz default now()
);

-- ---------------------------------------------------------------------
-- Table : ai_documents
-- ---------------------------------------------------------------------
create table if not exists public.ai_documents (
  id uuid primary key default uuid_generate_v4(),
  client_id uuid not null references public.ai_clients(id) on delete cascade,
  source_email text not null,
  subject text not null,
  body_preview text,
  category text not null check (category in (
    'facture_fournisseur','note_frais','releve_bancaire',
    'document_fiscal','courrier','spam'
  )),
  urgency text not null default 'normale' check (urgency in ('haute','normale','basse')),
  attachments jsonb default '[]'::jsonb,
  ai_confidence numeric(4,3) not null default 0,
  status text not null default 'nouveau' check (status in ('nouveau','traite','valide','rejete')),
  created_at timestamptz default now()
);
create index if not exists idx_ai_documents_client on public.ai_documents(client_id, created_at desc);
create index if not exists idx_ai_documents_status on public.ai_documents(client_id, status);

-- ---------------------------------------------------------------------
-- Table : ai_extractions
-- ---------------------------------------------------------------------
create table if not exists public.ai_extractions (
  id uuid primary key default uuid_generate_v4(),
  document_id uuid not null references public.ai_documents(id) on delete cascade,
  client_id uuid not null references public.ai_clients(id) on delete cascade,
  extracted_data jsonb not null,
  suggested_entry jsonb not null,
  ai_confidence numeric(4,3) not null default 0,
  status text not null default 'en_attente' check (status in ('en_attente','valide','corrige','rejete')),
  validated_by uuid,
  validated_at timestamptz,
  created_at timestamptz default now()
);
create index if not exists idx_ai_extractions_client on public.ai_extractions(client_id, created_at desc);
create index if not exists idx_ai_extractions_status on public.ai_extractions(client_id, status);

-- ---------------------------------------------------------------------
-- Table : ai_invoices (factures clients, pour les relances)
-- ---------------------------------------------------------------------
create table if not exists public.ai_invoices (
  id uuid primary key default uuid_generate_v4(),
  client_id uuid not null references public.ai_clients(id) on delete cascade,
  invoice_number text not null,
  client_name text not null,
  client_email text,
  amount numeric(12,2) not null,
  due_date date not null,
  status text not null default 'en_attente' check (status in (
    'payee','en_attente','relancee_1','relancee_2','relancee_3','contentieux'
  )),
  last_reminder_at timestamptz,
  next_reminder_preview text,
  created_at timestamptz default now()
);
create index if not exists idx_ai_invoices_client on public.ai_invoices(client_id, due_date);
create index if not exists idx_ai_invoices_status on public.ai_invoices(client_id, status);

-- ---------------------------------------------------------------------
-- Table : ai_actions (log complet)
-- ---------------------------------------------------------------------
create table if not exists public.ai_actions (
  id uuid primary key default uuid_generate_v4(),
  client_id uuid not null references public.ai_clients(id) on delete cascade,
  action_type text not null check (action_type in (
    'triage','extraction','relance','rapport','notification'
  )),
  description text not null,
  confidence numeric(4,3) not null default 1,
  status text not null default 'auto' check (status in ('auto','valide','rejete')),
  related_document_id uuid,
  related_invoice_id uuid,
  created_at timestamptz default now()
);
create index if not exists idx_ai_actions_client on public.ai_actions(client_id, created_at desc);
create index if not exists idx_ai_actions_type on public.ai_actions(client_id, action_type);

-- ---------------------------------------------------------------------
-- Table : ai_agent_performance (scoring rouge/orange/vert)
-- ---------------------------------------------------------------------
create table if not exists public.ai_agent_performance (
  id uuid primary key default uuid_generate_v4(),
  client_id uuid not null references public.ai_clients(id) on delete cascade,
  task_type text not null check (task_type in ('triage','extraction','relance')),
  total_actions int not null default 0,
  correct_actions int not null default 0,
  accuracy numeric(5,2) not null default 0,
  level text not null default 'rouge' check (level in ('rouge','orange','vert')),
  updated_at timestamptz default now(),
  unique (client_id, task_type)
);

-- Fonction : recalcul du level en fonction de l'accuracy
create or replace function public.ai_compute_level(acc numeric)
returns text language sql immutable as $$
  select case
    when acc < 50 then 'rouge'
    when acc < 95 then 'orange'
    else 'vert'
  end
$$;

-- Trigger : maintien de accuracy + level
create or replace function public.ai_update_performance_score()
returns trigger language plpgsql as $$
begin
  new.accuracy := case
    when new.total_actions = 0 then 0
    else round((new.correct_actions::numeric / new.total_actions) * 100, 2)
  end;
  new.level := public.ai_compute_level(new.accuracy);
  new.updated_at := now();
  return new;
end
$$;

drop trigger if exists trg_ai_performance_score on public.ai_agent_performance;
create trigger trg_ai_performance_score
  before insert or update on public.ai_agent_performance
  for each row execute function public.ai_update_performance_score();

-- =====================================================================
-- RLS — multi-tenant par client_id
-- Pattern : un utilisateur Supabase est lié à un client via une table
--          `ai_client_members (user_id, client_id)` créée par l'app.
-- =====================================================================

alter table public.ai_clients enable row level security;
alter table public.ai_documents enable row level security;
alter table public.ai_extractions enable row level security;
alter table public.ai_invoices enable row level security;
alter table public.ai_actions enable row level security;
alter table public.ai_agent_performance enable row level security;

-- Table de rattachement utilisateur ↔ cabinet
create table if not exists public.ai_client_members (
  user_id uuid not null,
  client_id uuid not null references public.ai_clients(id) on delete cascade,
  role text not null default 'member' check (role in ('owner','admin','member')),
  created_at timestamptz default now(),
  primary key (user_id, client_id)
);
alter table public.ai_client_members enable row level security;

create or replace function public.ai_is_member_of(target_client uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.ai_client_members m
    where m.client_id = target_client and m.user_id = auth.uid()
  )
$$;

-- ai_clients : un membre voit son cabinet
drop policy if exists ai_clients_select on public.ai_clients;
create policy ai_clients_select on public.ai_clients
  for select using (public.ai_is_member_of(id));

drop policy if exists ai_clients_update on public.ai_clients;
create policy ai_clients_update on public.ai_clients
  for update using (public.ai_is_member_of(id));

-- ai_client_members : chacun voit ses propres rattachements
drop policy if exists ai_members_select on public.ai_client_members;
create policy ai_members_select on public.ai_client_members
  for select using (user_id = auth.uid());

-- Politique générique pour les autres tables
do $$
declare
  t text;
begin
  foreach t in array array[
    'ai_documents','ai_extractions','ai_invoices','ai_actions','ai_agent_performance'
  ] loop
    execute format('drop policy if exists %I_select on public.%I', t, t);
    execute format(
      'create policy %I_select on public.%I for select using (public.ai_is_member_of(client_id))',
      t, t
    );

    execute format('drop policy if exists %I_insert on public.%I', t, t);
    execute format(
      'create policy %I_insert on public.%I for insert with check (public.ai_is_member_of(client_id))',
      t, t
    );

    execute format('drop policy if exists %I_update on public.%I', t, t);
    execute format(
      'create policy %I_update on public.%I for update using (public.ai_is_member_of(client_id))',
      t, t
    );

    execute format('drop policy if exists %I_delete on public.%I', t, t);
    execute format(
      'create policy %I_delete on public.%I for delete using (public.ai_is_member_of(client_id))',
      t, t
    );
  end loop;
end
$$;

-- Service role bypass RLS automatiquement (les workflows n8n utilisent service role)
