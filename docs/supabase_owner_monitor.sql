-- Owner remote monitoring: ONE table, written only by a dedicated "device" login,
-- readable only by the owner's login. Run once in the OWNER'S OWN Supabase project
-- (SQL editor). Nothing here touches the products / mobile_orders tables.
--
-- Before running:
--   1. Authentication > Users: create two users (email + password): the DEVICE user
--      (its email/password go in remote_monitor.json on the pharmacy PC) and the OWNER user
--      (used only to read, in owner_monitor.html or the Supabase table editor).
--   2. Authentication > Providers > Email: turn OFF "Allow new users to sign up".
--   3. Replace the two UUIDs below with those users' ids.

create table if not exists public.monitor_roles (
  uid  uuid primary key,
  role text not null check (role in ('device','owner'))
);
insert into public.monitor_roles (uid, role) values
  ('00000000-0000-0000-0000-000000000001', 'device'),   -- REPLACE: device user id
  ('00000000-0000-0000-0000-000000000002', 'owner')     -- REPLACE: owner user id
on conflict (uid) do update set role = excluded.role;

create table if not exists public.monitor_events (
  id          bigint generated always as identity primary key,
  -- who wrote the row is bound to the login, never to anything the client sends
  device_uid  uuid   not null default auth.uid(),
  device_id   text   not null check (char_length(device_id) <= 64),
  generation  text   not null check (char_length(generation) between 1 and 32),
  kind        text   not null check (kind in ('activity','system','heartbeat')),
  src_id      bigint not null check (src_id >= 0),
  received_at timestamptz not null default now(),
  payload     jsonb  not null check (pg_column_size(payload) < 16384),
  unique (device_uid, device_id, generation, kind, src_id)
);
create index if not exists monitor_events_recent on public.monitor_events (received_at desc);

alter table public.monitor_roles  enable row level security;
alter table public.monitor_events enable row level security;

-- nobody reads or edits the roles table through the API
revoke all on public.monitor_roles  from anon, authenticated;
-- anonymous visitors get nothing; the device may only insert; the owner may only read
revoke all on public.monitor_events from anon, authenticated;
grant insert, select on public.monitor_events to authenticated;

create or replace function public.monitor_has_role(r text) returns boolean
language sql security definer set search_path = public stable as $$
  select exists (select 1 from public.monitor_roles where uid = auth.uid() and role = r)
$$;

drop policy if exists monitor_device_insert on public.monitor_events;
create policy monitor_device_insert on public.monitor_events
  for insert to authenticated
  with check (public.monitor_has_role('device') and device_uid = auth.uid());

-- The device may see only the rows it wrote itself. Postgres needs this for ON CONFLICT DO NOTHING
-- (safe retries after a dropped connection). It never sees other devices or the owner's view.
drop policy if exists monitor_device_read_own on public.monitor_events;
create policy monitor_device_read_own on public.monitor_events
  for select to authenticated using (public.monitor_has_role('device') and device_uid = auth.uid());

drop policy if exists monitor_owner_read on public.monitor_events;
create policy monitor_owner_read on public.monitor_events
  for select to authenticated using (public.monitor_has_role('owner'));

-- no update or delete policy exists, so neither the device nor the owner login can change history.
-- Optional cleanup (run manually as project admin): delete from public.monitor_events where received_at < now() - interval '1 year';
