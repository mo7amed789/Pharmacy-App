-- TEMPLATE ONLY. Do not execute until the approved writer UUID is set,
-- the updated app is installed, and the owner approves the cutover.
BEGIN;
DO $cutover$
DECLARE
  writer_id uuid := NULL; -- explicitly approved auth.users.id, never email matching
BEGIN
  IF writer_id IS NULL OR NOT EXISTS(SELECT 1 FROM auth.users WHERE id = writer_id) THEN
    RAISE EXCEPTION 'Set and verify the approved writer identity before cutover';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='products'
     AND policyname='products_all') THEN
    RAISE EXCEPTION 'Expected current policy missing; inspect policies before proceeding';
  END IF;
  -- This script is for the inspected one-policy setup, not unknown new policies.
  IF (SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename='products') <> 1 THEN
    RAISE EXCEPTION 'Policy set changed; review before proceeding';
  END IF;
  ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;
  DROP POLICY products_all ON public.products;
  CREATE POLICY products_read ON public.products FOR SELECT TO anon, authenticated USING (true);
  EXECUTE format('CREATE POLICY products_writer ON public.products FOR ALL TO authenticated USING ((select auth.uid()) = %L::uuid) WITH CHECK ((select auth.uid()) = %L::uuid)', writer_id, writer_id);
END $cutover$;
COMMIT;
-- Verify all policies and table RLS; then run transaction-scoped role probes
-- for anon, an unrelated authenticated UUID and the selected writer UUID.
-- Public reads must work. Anonymous/unrelated inserts must fail with42501,
-- update/delete must affect zero rows. Roll back every probe.
