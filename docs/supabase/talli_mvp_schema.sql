-- Talli MVP Supabase/Postgres workspace schema.
-- Source of truth: ../../supabase/migrations/*.sql (applied in lexical order)
--
-- Security decisions:
-- - RLS enabled on every exposed public table.
-- - Policies use `to authenticated` plus ownership/membership predicates.
-- - Authorization uses company memberships, not user-editable metadata.
-- - Explicit grants are included because Supabase Data API exposure may require them.

\i ../../supabase/migrations/0001_authenticated_workspace.sql
\i ../../supabase/migrations/0002_fifo_investment_lots.sql
\i ../../supabase/migrations/0003_bank_rule_suggestions.sql
\i ../../supabase/migrations/0004_corporate_document_artifacts.sql
\i ../../supabase/migrations/20260714081443_explicit_data_api_grants.sql
