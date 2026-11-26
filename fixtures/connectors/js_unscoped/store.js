// Written for KAMANU gate T9: the data behind the server.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";

const DATA = process.env.CONNECTOR_DATA;
const BACKEND = process.env.CONNECTOR_BACKEND;
const db = new DatabaseSync(join(DATA, "data.db"));

export function invoices() {
  const rows = db.prepare("SELECT id, body FROM invoices").all();
  return JSON.stringify(rows);
}

export function notes() {
  const path = join(DATA, "notes", "all.txt");
  return readFileSync(path, "utf8");
}

export async function profiles() {
  const answer = await fetch(BACKEND + "/profiles");
  return await answer.text();
}
