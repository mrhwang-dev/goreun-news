-- 고른뉴스 뉴스레터 구독자 테이블.
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 실행하세요.
--
-- 개인정보(이메일)라, 익명 사용자는 INSERT(구독)만 가능하고 SELECT(목록 조회)는
-- 불가합니다. 발송기(send_newsletter.py)만 service_role 키로 목록을 읽습니다.

create extension if not exists "pgcrypto";

create table if not exists public.subscribers (
  id          uuid primary key default gen_random_uuid(),
  email       text not null unique
              check (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  created_at  timestamptz not null default now()
);

alter table public.subscribers enable row level security;

-- 익명 구독(INSERT)만 허용. SELECT 정책이 없으므로 이메일 목록은 공개되지 않는다.
drop policy if exists "anon subscribe" on public.subscribers;
create policy "anon subscribe" on public.subscribers
  for insert with check (true);

grant insert on public.subscribers to anon;

-- ── 운영용 ────────────────────────────────────────────────────────────────
-- 구독자 수:   select count(*) from public.subscribers;
-- 구독 해지:   delete from public.subscribers where email = '...';
