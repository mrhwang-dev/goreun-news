-- 고른뉴스 4.B 의견 지형도 — 사용자 의견 저장 테이블.
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 실행하세요.
--
-- x: 성향축 (-1 진보 … 0 중도 … +1 보수), y: 강도축 (0 차분 … 1 강함)
-- status: 'visible'(공개) / 'hidden'(관리자 숨김). 부적절 의견은 아래 UPDATE로 숨깁니다.
--
-- ⚠️ v1 주의: 사전 검열(pre-moderation)이 없습니다. 익명 사용자의 의견이 즉시
-- 공개되므로, 실서비스 전에는 반드시 (a) Edge Function 기반 제출 검열 또는
-- (b) status 기본값 'pending' + 승인 플로우를 추가하세요. 지금은 실험/테스트용입니다.

create extension if not exists "pgcrypto";

create table if not exists public.opinions (
  id          uuid primary key default gen_random_uuid(),
  issue_key   text not null,
  body        text not null check (char_length(body) between 2 and 200),
  x           real not null check (x between -1 and 1),
  y           real not null check (y between 0 and 1),
  status      text not null default 'visible' check (status in ('visible', 'hidden')),
  created_at  timestamptz not null default now()
);

create index if not exists opinions_issue_idx
  on public.opinions (issue_key) where status = 'visible';

-- 행 수준 보안 (RLS)
alter table public.opinions enable row level security;

-- 공개 읽기: visible 행만
drop policy if exists "read visible opinions" on public.opinions;
create policy "read visible opinions" on public.opinions
  for select using (status = 'visible');

-- 익명 삽입: 제약 강제(길이·범위·즉시공개만). 관리 상태 변경은 익명에게 불허.
drop policy if exists "anon insert opinions" on public.opinions;
create policy "anon insert opinions" on public.opinions
  for insert with check (
    status = 'visible'
    and char_length(body) between 2 and 200
    and x between -1 and 1
    and y between 0 and 1
  );

grant select, insert on public.opinions to anon;

-- ── 운영용 ────────────────────────────────────────────────────────────────
-- 부적절 의견 숨기기:   update public.opinions set status='hidden' where id='...';
-- 최근 의견 검토:       select id, issue_key, body, created_at from public.opinions
--                        where status='visible' order by created_at desc limit 50;
