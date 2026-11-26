// Written for KAMANU gate T9: an MCP server whose tools answer with everyone's data.
import { McpServer } from "./minimcp.js";
import { invoices, notes, profiles } from "./store.js";

const server = new McpServer({ name: "unscoped", version: "0" });

server.tool("list_invoices", {}, async (args, extra) => {
  const found = invoices();
  return found;
});

server.tool("read_note", {}, async () => {
  return notes();
});

server.tool("show_profile", { greeting: { type: "string", optional: true } }, async ({ greeting }) => {
  const text = await profiles();
  return (greeting || "profile") + ": " + text;
});

await server.run();
