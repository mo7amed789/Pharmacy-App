-- v6.26 — طابور فواتير الموبايل (الوضع السحابي)
-- ينفَّذ مرة واحدة من Supabase Dashboard → SQL Editor.
--
-- الغرض: عندما لا يصل الهاتف لسيرفر الكمبيوتر (لا واي فاي مشترك) يدرج
-- تطبيق الموبايل طلب البيع هنا، وبرنامج الكمبيوتر يسحبه ويطبقه بنفس
-- منطق البيع المحلي ثم يحدّث الحالة ليقرأها الهاتف.
--
-- الصلاحيات أضيق ما يمكن للمفتاح العلني (anon):
--   * INSERT  : الهاتف يدرج طلباً جديداً.
--   * SELECT  : الهاتف يقرأ حالة طلبه، والبرنامج يقرأ المعلّق.
--   * UPDATE  : على أعمدة الحالة فقط (status/result/processed_at) —
--               لا يمكن تعديل payload بعد إدراجه.
--   * DELETE  : ممنوع تماماً.
-- الحماية الحقيقية ضد الفواتير المزيّفة: البرنامج لا يطبق أي طلب إلا
-- بعد مطابقة بصمة SHA-256 لرمز الموبايل (PIN) — حامل المفتاح وحده
-- لا يستطيع تسجيل بيع.

create table if not exists public.mobile_orders (
  id           bigint generated always as identity primary key,
  created_at   timestamptz not null default now(),
  payload      jsonb not null,
  status       text not null default 'pending'
               check (status in ('pending', 'done', 'failed')),
  result       jsonb,
  processed_at timestamptz
);

create index if not exists idx_mobile_orders_pending
  on public.mobile_orders (created_at) where status = 'pending';

alter table public.mobile_orders enable row level security;

drop policy if exists "mobile_orders_insert" on public.mobile_orders;
create policy "mobile_orders_insert" on public.mobile_orders
  for insert to anon with check (true);

drop policy if exists "mobile_orders_select" on public.mobile_orders;
create policy "mobile_orders_select" on public.mobile_orders
  for select to anon using (true);

drop policy if exists "mobile_orders_update" on public.mobile_orders;
create policy "mobile_orders_update" on public.mobile_orders
  for update to anon using (true) with check (true);

grant insert, select on public.mobile_orders to anon;
grant update (status, result, processed_at) on public.mobile_orders to anon;
revoke delete on public.mobile_orders from anon;
