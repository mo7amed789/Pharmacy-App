# Catalog writer preparation, not a completed live lock

The existing live products_all policy remains unchanged until cutover is separately approved. This PR alone does not secure the live catalog. The existing desktop status text still assumes cloud uploads are enabled; consult the upload error/status and use the dedicated writer launcher. An integrated status UI is follow-up work.

The desktop uses the public project key for reads, and a separately signed-in Supabase Auth user's short-lived access token for products writes. It never falls back to anonymous product writes. Passwords, access tokens and refresh tokens are not saved to disk. Refresh tokens are discarded, and expired sessions need sign-in again. Desktop local changes remain saved when upload is unavailable. The live RLS policy is the authorization boundary.

Before closure:
1. Choose and verify the owner's intended writer identity in Supabase Auth. No account has been created by this change. Dashboard login is not an application Auth user.
2. Install the reviewed updated desktop app. Keep only a public project key in its shared cloud configuration, never a service-role key.
3. Run `py catalog_writer_launcher.py`, enter the approved Auth account and password in the local terminal (password input is hidden), then use the normal desktop app. Do not send credentials in chat. The regular launcher remains read-only for cloud catalog uploads. Close the app to clear the session.
4. With the owner informed, use the reviewed catalog_writer_cutover.sql template, set the exact approved auth.users UUID, and inspect its preconditions. Public reads remain, while writes are allowed only to that UUID. An arbitrary signed-in user is not enough.
5. Verify public reads; reject anonymous and unrelated-user INSERT, UPDATE and DELETE; verify the approved writer in a transaction that is rolled back. Then verify an approved real desktop edit. No test products should remain.

No live sign-in tokens, account creation, key changes or policy changes are part of this PR. The SQL template intentionally refuses to run without an approved identity. Rollback must be reviewed; do not restore anonymous write access as an automatic fallback.

The writer session is process-wide and not exposed by the mobile cloud-config endpoint. Mobile order handling is unchanged and is outside this products policy change. An application Auth account with MFA may require a separate MFA-capable login flow; this initial password flow does not implement MFA challenges.
