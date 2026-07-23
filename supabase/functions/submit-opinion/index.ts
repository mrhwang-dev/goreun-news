// 고른뉴스 4.B 의견 제출 — 서버 검열(pre-moderation) 후 저장.
// 배포:  supabase functions deploy submit-opinion --no-verify-jwt
//  (익명 사용자가 anon 키로 호출하므로 JWT 검증은 끄고, 함수 내부에서 검열한다)
//
// 클라이언트는 { issue_key, body, x } 를 보낸다. 이 함수가:
//  1) 길이·형식 검증  2) 금칙어/링크/연락처 차단  3) 강도(y) 서버 계산
//  4) service_role 로 insert (RLS 우회) 후 생성 행 반환.
// ※ 금칙어 목록은 스타터다. 운영 시 유지관리되는 한국어 비속어 사전이나
//   CLOVA 검열 모델로 강화할 것.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const CORS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

// 1차 금칙어(어근) — 빠른 차단. 문맥 판단은 아래 CLOVA 검열이 담당.
const BLOCK = [
  "씨발", "시발", "씨발", "ㅅㅂ", "병신", "ㅂㅅ", "새끼", "쌔끼", "지랄", "ㅈㄹ",
  "좆", "좇", "니미", "느금", "썅", "개새", "개소리", "꺼져", "미친놈", "미친년",
  "죽어", "뒤져", "닥쳐", "창녀", "걸레", "빨갱이", "틀딱", "한남", "된장녀", "김치녀",
];

// CLOVA 문맥 검열 — 욕설/혐오/차별/폭력/명예훼손이면 차단. 정치적 의견 자체는 허용.
// CLOVA_API_KEY(Supabase 시크릿) 미설정 시 건너뛴다(키워드 검열만).
async function clovaBlocked(text: string): Promise<boolean> {
  const key = Deno.env.get("CLOVA_API_KEY");
  if (!key) return false;
  const auth = key.toLowerCase().startsWith("bearer ") ? key : "Bearer " + key;
  try {
    const r = await fetch("https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-007", {
      method: "POST",
      headers: {
        Authorization: auth,
        "X-NCP-CLOVASTUDIO-REQUEST-ID": crypto.randomUUID(),
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        messages: [
          { role: "system", content: "너는 뉴스 댓글 검열기다. 입력이 욕설·혐오·차별·성적표현·폭력선동·명예훼손을 담으면 정확히 'block', 아니면 'ok'만 출력하라. 정파적 정치 의견 자체는 허용한다." },
          { role: "user", content: text },
        ],
        maxCompletionTokens: 8,
        temperature: 0,
        thinking: { effort: "low" },
      }),
    });
    if (!r.ok) return false; // CLOVA 오류 시 통과(1차 키워드는 이미 통과)
    const d = await r.json();
    return String(d?.result?.message?.content || "").toLowerCase().includes("block");
  } catch {
    return false;
  }
}

function intensity(t: string): number {
  let s = 0.35 + Math.min((t.match(/[!?]/g) || []).length * 0.12, 0.35);
  if (/(절대|무조건|극혐|최악|반드시|결코|말도\s?안|어이없|웃기)/.test(t)) s += 0.2;
  return Math.max(0.05, Math.min(1, s + Math.min((t.length / 200) * 0.15, 0.15)));
}

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  let payload: { issue_key?: unknown; body?: unknown; x?: unknown };
  try {
    payload = await req.json();
  } catch {
    return json({ error: "요청 형식 오류" }, 400);
  }

  const issue_key = String(payload.issue_key ?? "").trim();
  const raw = String(payload.body ?? "");
  const text = raw.trim();

  if (!issue_key) return json({ error: "issue_key가 필요합니다." }, 400);
  if (text.length < 2 || raw.length > 200) return json({ error: "의견은 2~200자로 입력해 주세요." }, 400);

  // 검열: 금칙어 / 링크·연락처(스팸)
  const lower = text.toLowerCase();
  if (BLOCK.some((w) => lower.includes(w))) return json({ error: "부적절한 표현이 포함되어 있어요." }, 422);
  if (/(https?:\/\/|www\.|\.com|카톡|텔레그램|010[-\s]?\d{3,4})/i.test(text)) {
    return json({ error: "링크·연락처는 넣을 수 없어요." }, 422);
  }
  if (await clovaBlocked(text)) {
    return json({ error: "부적절한 내용으로 판단돼 등록되지 않았어요." }, 422);
  }

  const x = Math.max(-1, Math.min(1, Number(payload.x) || 0));
  const y = intensity(text);

  const supa = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );
  const { data, error } = await supa
    .from("opinions")
    .insert({ issue_key, body: text, x, y, status: "visible" })
    .select("id,body,x,y")
    .single();

  if (error) return json({ error: "저장에 실패했어요." }, 500);
  return json(data, 200);
});
