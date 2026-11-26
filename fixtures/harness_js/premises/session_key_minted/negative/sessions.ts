// Written for KAMANU gate E8: session_key_minted, negative. resumeSession takes the caller's key.
import { randomUUID } from "node:crypto";

type Inbound = { headers: Record<string, string | undefined>; get(name: string): string | undefined };

export function openSession(req: Inbound): string {
  const user = req.get("user");
  const sessionId: string = randomUUID();
  return sessionId;
}

export function resumeSession(req: Inbound): string {
  const sessionId = req.headers["mcp-session-id"] ?? randomUUID();
  return sessionId;
}
