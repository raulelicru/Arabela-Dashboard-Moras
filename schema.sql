-- ================================================================
-- SCHEMA: Dashboard Cobranza Mora Arabela — Fase 2
-- Ejecuta este script en Supabase > SQL Editor
-- ================================================================

-- ── 1. Perfiles de usuario ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.profiles (
  id         UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
  email      TEXT,
  role       TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Usuarios ven su propio perfil"
  ON public.profiles FOR SELECT
  TO authenticated USING (auth.uid() = id);

-- Trigger: crea perfil automáticamente al registrar un usuario
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  INSERT INTO public.profiles (id, email, role)
  VALUES (NEW.id, NEW.email, 'user')
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();


-- ── 2. Cargas de Cartera General (Indicadores de Mora) ──────────
CREATE TABLE IF NOT EXISTS public.cartera_uploads (
  id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  uploaded_by  UUID REFERENCES public.profiles(id),
  filename     TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  is_active    BOOLEAN DEFAULT TRUE,
  uploaded_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.cartera_uploads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Usuarios autenticados ven cartera activa"
  ON public.cartera_uploads FOR SELECT
  TO authenticated USING (is_active = TRUE);

CREATE POLICY "Solo admins insertan cartera"
  ON public.cartera_uploads FOR INSERT
  TO authenticated WITH CHECK (
    (SELECT role FROM public.profiles WHERE id = auth.uid()) = 'admin'
  );

CREATE POLICY "Solo admins actualizan cartera"
  ON public.cartera_uploads FOR UPDATE
  TO authenticated USING (
    (SELECT role FROM public.profiles WHERE id = auth.uid()) = 'admin'
  );


-- ── 3. Cargas de Domicilios (Arabela) ───────────────────────────
CREATE TABLE IF NOT EXISTS public.domicilios_uploads (
  id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  uploaded_by  UUID REFERENCES public.profiles(id),
  filename     TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  is_active    BOOLEAN DEFAULT TRUE,
  uploaded_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.domicilios_uploads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Usuarios autenticados ven domicilios activos"
  ON public.domicilios_uploads FOR SELECT
  TO authenticated USING (is_active = TRUE);

CREATE POLICY "Solo admins insertan domicilios"
  ON public.domicilios_uploads FOR INSERT
  TO authenticated WITH CHECK (
    (SELECT role FROM public.profiles WHERE id = auth.uid()) = 'admin'
  );

CREATE POLICY "Solo admins actualizan domicilios"
  ON public.domicilios_uploads FOR UPDATE
  TO authenticated USING (
    (SELECT role FROM public.profiles WHERE id = auth.uid()) = 'admin'
  );


-- ================================================================
-- STORAGE: Bucket "uploads"
-- 1. Ve a Supabase > Storage > New bucket
-- 2. Nombre: uploads   |   Public: NO
-- 3. Ejecuta las políticas de abajo:
-- ================================================================

CREATE POLICY "Usuarios autenticados pueden descargar"
  ON storage.objects FOR SELECT
  TO authenticated
  USING (bucket_id = 'uploads');

CREATE POLICY "Solo admins pueden subir archivos"
  ON storage.objects FOR INSERT
  TO authenticated
  WITH CHECK (
    bucket_id = 'uploads' AND
    (SELECT role FROM public.profiles WHERE id = auth.uid()) = 'admin'
  );

CREATE POLICY "Solo admins pueden borrar archivos"
  ON storage.objects FOR DELETE
  TO authenticated
  USING (
    bucket_id = 'uploads' AND
    (SELECT role FROM public.profiles WHERE id = auth.uid()) = 'admin'
  );


-- ================================================================
-- CREAR UN ADMINISTRADOR MANUALMENTE
-- 1. Crea el usuario en Supabase > Authentication > Users > Add user
-- 2. Copia su UUID
-- 3. Ejecuta:
--    UPDATE public.profiles SET role = 'admin' WHERE id = 'UUID_AQUI';
-- ================================================================
