// Written for KAMANU gate T9: the smallest MCP server over stdio that the gate's servers need.
// The names are those of the TypeScript SDK: server.tool(name, properties, handler), and a handler
// gets (arguments, extra) with extra.authInfo the transport's identity (the token of this process).
import { appendFileSync, readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { join } from "node:path";

class Invalid extends Error {}

function check(value, schema, where) {
  const good = {
    string: (v) => typeof v === "string",
    boolean: (v) => typeof v === "boolean",
    integer: (v) => Number.isInteger(v),
    array: (v) => Array.isArray(v),
    object: (v) => v !== null && typeof v === "object" && !Array.isArray(v),
  };
  if (schema.type && !good[schema.type](value)) throw new Invalid(`${where} must be a JSON ${schema.type}`);
  if (schema.enum && !schema.enum.includes(value)) throw new Invalid(`${where} is not one of its choices`);
  if (schema.type === "array" && schema.items) for (const item of value) check(item, schema.items, where);
  if (schema.type === "object") {
    for (const name of schema.required || []) if (!(name in value)) throw new Invalid(`${where} needs ${name}`);
    for (const name of Object.keys(value)) {
      if (!(name in (schema.properties || {}))) throw new Invalid(`${where} does not know ${name}`);
      check(value[name], schema.properties[name], name);
    }
  }
}

export class McpServer {
  constructor(info) {
    this.info = info;
    this.tools = new Map();
  }

  tool(name, properties, handler) {
    const shown = {};
    const required = [];
    for (const [key, { optional, ...schema }] of Object.entries(properties)) {
      shown[key] = schema;
      if (!optional) required.push(key);
    }
    this.tools.set(name, { handler, schema: { type: "object", properties: shown, required } });
  }

  async answer(message, authInfo) {
    const params = message.params || {};
    if (message.method === "initialize") {
      return { protocolVersion: params.protocolVersion || "2025-06-18", capabilities: { tools: {} }, serverInfo: this.info };
    }
    if (message.method === "ping") return {};
    if (message.method === "tools/list") {
      return { tools: [...this.tools].map(([name, t]) => ({ name, description: "", inputSchema: t.schema })) };
    }
    if (message.method !== "tools/call") throw new Invalid(`no method ${message.method}`);
    if (!authInfo) throw new Invalid("not signed in");
    const tool = this.tools.get(params.name);
    if (!tool) throw new Invalid(`no tool ${params.name}`);
    check(params.arguments || {}, tool.schema, "arguments");
    try {
      const out = await tool.handler(params.arguments || {}, { authInfo });
      return typeof out === "string" ? { content: [{ type: "text", text: out }] } : out;
    } catch (e) {
      return { content: [{ type: "text", text: e.message }], isError: true };
    }
  }

  async run() {
    const token = process.env.CONNECTOR_TOKEN || "";
    const authInfo = JSON.parse(readFileSync(join(process.env.CONNECTOR_DATA, "auth.json"), "utf8"))[token];
    for await (const line of createInterface({ input: process.stdin })) {
      if (!line.trim()) continue;
      const message = JSON.parse(line);
      if (!("id" in message) || !("method" in message)) continue;
      const reply = { jsonrpc: "2.0", id: message.id };
      try {
        reply.result = await this.answer(message, authInfo);
      } catch (e) {
        reply.error = { code: -32602, message: e.message };
      }
      if (process.env.CONNECTOR_LOG) {
        appendFileSync(process.env.CONNECTOR_LOG, JSON.stringify({ token, message, reply }) + "\n");
      }
      process.stdout.write(JSON.stringify(reply) + "\n");
    }
  }
}
