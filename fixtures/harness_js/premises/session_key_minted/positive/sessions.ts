// Written for KAMANU gate E8: session_key_minted, positive. Both entries mint the key on the server.
import { randomBytes, randomUUID } from "node:crypto";

type Inbound = { headers: Record<string, string | undefined>; get(name: string): string | undefined };

export function openSession(req: Inbound): string {
  const user = req.get("user");
  const sessionId: string = randomUUID();
  return sessionId;
}

export function openTrial(req: Inbound): string {
  const sessionToken = "trial-" + randomBytes(12).toString("hex");
  return sessionToken;
}
