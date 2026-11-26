// Written for KAMANU gate T9: an MCP server that scopes each tool by the session's identity.
import { McpServer } from "./minimcp.js";
import { invoicesOf, noteOf, profileOf } from "./store.js";

const server = new McpServer({ name: "by-session", version: "0" });

server.tool("list_invoices", {}, async (args, extra) => {
  const owner = extra.authInfo.tenant;
  const found = invoicesOf(owner);
  return found;
});

server.tool("read_note", {}, async (args, extra) => {
  return noteOf(extra.authInfo.tenant);
});

server.tool("show_profile", { greeting: { type: "string", optional: true } }, async ({ greeting }, extra) => {
  const text = await profileOf(extra.authInfo.tenant);
  return (greeting || "profile") + ": " + text;
});

await server.run();
