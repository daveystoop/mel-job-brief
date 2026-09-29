// Cloudflare Worker: the chat relay for Mel's Job Brief.
// Holds the API key so it never appears in the web page.
// Secrets to set in Cloudflare: ANTHROPIC_API_KEY, ACCESS_CODE, MEL_PROFILE
// Variable: ALLOWED_ORIGIN, e.g. https://yourname.github.io

const MODEL = "claude-sonnet-5-5";

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const cors = {
      "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, X-Access-Code",
    };
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });
    if (request.method !== "POST" || origin !== env.ALLOWED_ORIGIN)
      return new Response("Not allowed", { status: 403, headers: cors });
    if (request.headers.get("X-Access-Code") !== env.ACCESS_CODE)
      return new Response("Bad code", { status: 401, headers: cors });

    let body;
    try { body = await request.json(); } catch { return new Response("Bad request", { status: 400, headers: cors }); }

    const jobs = (body.jobs || []).slice(0, 40).map(j =>
      `- ${j.title} | ${j.employer} | ${j.location} | ${j.work_type} | Pay: ${j.pay} | ${j.match} | ${j.why}`
    ).join("\n");

    const messages = (body.messages || [])
      .filter(m => (m.role === "user" || m.role === "assistant") && typeof m.content === "string")
      .slice(-8)
      .map(m => ({ role: m.role, content: m.content.slice(0, 2000) }));
    if (!messages.length || messages[0].role !== "user")
      return new Response("Bad request", { status: 400, headers: cors });

    const system = `You are a warm, sharp career assistant inside Mel's daily job brief app. Mel is an endorsed clinical psychologist in Melbourne.
Her profile:
${env.MEL_PROFILE}

Today's roles:
${jobs}

Answer in plain, friendly language, short enough to read on a phone (under 150 words unless asked).
Talk about specific jobs only from the list above. When pay isn't listed, you may give typical Victorian
ranges for that setting, but say clearly they're estimates. No markdown headings.`;

    const r = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({ model: MODEL, max_tokens: 700, system, messages }),
    });
    if (!r.ok) return new Response("Upstream error", { status: 502, headers: cors });
    const d = await r.json();
    const text = (d.content || []).filter(b => b.type === "text").map(b => b.text).join("");
    return new Response(JSON.stringify({ text }), { headers: { ...cors, "Content-Type": "application/json" } });
  },
};
