-- SECURITY HOLD: v6.26 cloud-order queue is not ready for deployment.
-- Do not create anonymous INSERT/SELECT/UPDATE policies on invoice data.
-- A PIN hash inside a readable payload can be replayed as a credential.
-- Authenticated per-pharmacy access is required before this feature ships.
-- This file deliberately performs NO database changes.
DO $$ BEGIN
  RAISE EXCEPTION 'Cloud orders disabled pending authenticated access. Use LAN mode.';
END $$;
