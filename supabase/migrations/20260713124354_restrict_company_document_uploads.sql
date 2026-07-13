-- Keep the Storage boundary aligned with the server-side validated standard
-- upload path. Supabase recommends standard uploads for files up to 6 MB.
update storage.buckets
set public = false,
    file_size_limit = 6291456,
    allowed_mime_types = array['application/pdf', 'image/png', 'image/jpeg', 'text/csv']
where id = 'company-documents';
