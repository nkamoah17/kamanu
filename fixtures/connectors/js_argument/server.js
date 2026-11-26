// Written for KAMANU gate T9: an MCP server that scopes each tool by an argument of the call.
import { McpServer } from "./minimcp.js";
import { invoicesOf, noteOf, profileOf } from "./store.js";

const server = new McpServer({ name: "by-argument", version: "0" });

server.tool("list_invoices", { user_id: { type: "string" } }, async ({ user_id }) => {
  const found = invoicesOf(user_id);
  return found;
});

server.tool("read_note", { workspace: { type: "string" } }, async ({ workspace }) => {
  return noteOf(workspace);
});

server.tool("show_profile", { tenant: { type: "string" } }, async (args) => {
  const text = await profileOf(args.tenant);
  return "profile: " + text;
});

await server.run();
