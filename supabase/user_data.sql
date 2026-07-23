-- 고른뉴스 로그인(구글) 사용자별 서버 저장 — 스크랩·뉴스 다이어트.
-- Supabase 대시보드 → SQL Editor 에서 실행하세요.
-- 각 행은 auth.uid()(로그인 사용자)로 소유자 식별하며 RLS로 본인 데이터만 접근합니다.

-- ── 스크랩 ────────────────────────────────────────────────────────────────
create table if not exists public.user_scraps (
  user_id     uuid not null references auth.users(id) on delete cascade,
  kind        text not null check (kind in ('news', 'post')),
  item_id     text not null,     -- 클라이언트 스크랩 식별자(링크/글 id)
  data        jsonb not null,    -- 스크랩 카드 데이터
  created_at  timestamptz not null default now(),
  primary key (user_id, kind, item_id)
);
alter table public.user_scraps enable row level security;
drop policy if exists "own scraps" on public.user_scraps;
create policy "own scraps" on public.user_scraps
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
grant select, insert, update, delete on public.user_scraps to authenticated;

-- ── 뉴스 다이어트(읽은 기사 성향 이력) ──────────────────────────────────────
-- 개인정보(열람 이력)이므로 반드시 본인만 접근. 개인정보처리방침·동의 갱신 필요.
create table if not exists public.user_diet (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  bias        text not null,
  read_at     timestamptz not null default now()
);
create index if not exists user_diet_uid_idx on public.user_diet (user_id, read_at desc);
alter table public.user_diet enable row level security;
drop policy if exists "own diet" on public.user_diet;
create policy "own diet" on public.user_diet
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
grant select, insert, delete on public.user_diet to authenticated;
