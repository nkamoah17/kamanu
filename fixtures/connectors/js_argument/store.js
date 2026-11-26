// Written for KAMANU gate T9: the data behind the server.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";

const DATA = process.env.CONNECTOR_DATA;
const BACKEND = process.env.CONNECTOR_BACKEND;
const db = new DatabaseSync(join(DATA, "data.db"));

export function invoicesOf(owner) {
  const rows = db.prepare("SELECT id, body FROM invoices WHERE tenant = ?").all(owner);
  return JSON.stringify(rows);
}

function notePath(owner) {
  return join(DATA, "notes", owner, "index.txt");
}

export function noteOf(owner) {
  const path = notePath(owner);
  return readFileSync(path, "utf8");
}

export async function profileOf(owner) {
  const answer = await fetch(BACKEND + "/profile?tenant=" + owner);
  return await answer.text();
}
