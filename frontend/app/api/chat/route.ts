import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const apiUrl = process.env.NEXT_PUBLIC_CHAT_API_URL;

  if (!apiUrl) {
    return NextResponse.json(
      { code: "frontend_configuration_error", message: "채팅 API 주소가 설정되지 않았습니다." },
      { status: 500 },
    );
  }

  try {
    const upstreamResponse = await fetch(`${apiUrl.replace(/\/$/, "")}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
      cache: "no-store",
    });

    return new Response(await upstreamResponse.text(), {
      status: upstreamResponse.status,
      headers: {
        "Content-Type": upstreamResponse.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      { code: "chat_api_unreachable", message: "채팅 API에 연결할 수 없습니다." },
      { status: 502 },
    );
  }
}
