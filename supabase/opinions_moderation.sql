-- 고른뉴스 4.B 검열 적용 — 직접 삽입을 막고, 검열 Edge Function만 저장하도록 전환.
-- Edge Function 배포 후 Supabase SQL Editor 에서 실행하세요.
--
-- submit-opinion Edge Function 은 service_role 로 동작해 RLS 를 우회하므로,
-- 익명 직접 INSERT 정책을 제거하면 모든 의견이 검열을 거치게 됩니다.
-- (읽기(SELECT visible) 정책은 그대로 둡니다.)

drop policy if exists "anon insert opinions" on public.opinions;
revoke insert on public.opinions from anon;
