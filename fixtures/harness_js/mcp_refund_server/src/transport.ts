// Written for KAMANU gate E8: an MCP server's HTTP front, in the shape of the TypeScript SDK's
// streamable HTTP transport. The session id comes from the caller when the caller sends one.
import { randomUUID } from "node:crypto";

type Inbound = { headers: Record<string, string | undefined> };

export function sessionFor(req: Inbound): string {
  const sessionId = req.headers["mcp-session-id"] || randomUUID();
  return sessionId;
}

export function transportOptions(req: Inbound) {
  return {
    sessionIdGenerator: () => sessionFor(req),
    enableJsonResponse: true,
  };
}
