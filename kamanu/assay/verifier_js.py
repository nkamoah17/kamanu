"""The page verifier (X1b, card (2)): one file of JavaScript the registry writes beside its pages.

    node kamanu-verify.cjs PAGE KEY

PAGE is a hallmark page of the registry; KEY is the registry's public key (64 hex digits, published once on the
index with its fingerprint). It reads the JSON the page embeds (<script type="application/json"
id="kamanu-hallmark">: {"record", "pyx"}) and checks, with node's own crypto and nothing else:

    the record      signature.alg is Ed25519, signature.key is KEY, sig is a valid signature of canonical(digests)
                    by KEY, and every other top-level field's SHA-256 is the digest signed for it
    each entry      the same checks over the entry's fields, and its "hallmark" is the record's id
                    (sha256 of canonical(the whole record))

canonical is X1's: Python's json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False) as UTF-8. The
file carries its own JSON reader so that a number is written back exactly as Python writes it (1.0 stays 1.0).
It prints one line "verified" and exits 0 when every check passes; otherwise one line per check that does not,
naming the field, and exits 1. It opens no connection and loads no other file.

The JavaScript lives here as a string (the wheel ships kamanu/assay's *.py and *.json only).
"""

FILENAME = "kamanu-verify.cjs"

JS = r"""#!/usr/bin/env node
// KAMANU page verifier (X1b). Usage: node kamanu-verify.cjs PAGE KEY
// Checks the hallmark record a registry page embeds, and every Pyx entry, against the registry's public
// key (64 hex digits). Node's own fs and crypto only; it opens no connection.
'use strict';
const fs = require('fs');
const crypto = require('crypto');

// ---- a JSON reader that keeps each number's text, so it is written back as Python writes it
function parse(text) {
  let i = 0;
  const ws = () => { while (i < text.length && ' \t\n\r'.indexOf(text[i]) >= 0) i++; };
  const bad = (what) => { throw new Error('the embedded JSON does not parse: ' + what + ' at ' + i); };
  function value() {
    ws();
    const c = text[i];
    if (c === '{') {
      i++; const obj = new Map(); ws();
      if (text[i] === '}') { i++; return obj; }
      for (;;) {
        ws(); if (text[i] !== '"') bad('a key');
        const k = str(); ws(); if (text[i] !== ':') bad('a colon'); i++;
        obj.set(k, value()); ws();
        if (text[i] === ',') { i++; continue; }
        if (text[i] === '}') { i++; return obj; }
        bad('a comma or a brace');
      }
    }
    if (c === '[') {
      i++; const arr = []; ws();
      if (text[i] === ']') { i++; return arr; }
      for (;;) {
        arr.push(value()); ws();
        if (text[i] === ',') { i++; continue; }
        if (text[i] === ']') { i++; return arr; }
        bad('a comma or a bracket');
      }
    }
    if (c === '"') return str();
    if (text.startsWith('true', i)) { i += 4; return true; }
    if (text.startsWith('false', i)) { i += 5; return false; }
    if (text.startsWith('null', i)) { i += 4; return null; }
    const m = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?/.exec(text.slice(i, i + 400));
    if (!m) bad('a value');
    i += m[0].length;
    return { num: m[0], float: !!(m[2] || m[3]) };
  }
  function str() {
    i++; let out = '';
    for (;;) {
      if (i >= text.length) bad('the end of a string');
      const c = text[i++];
      if (c === '"') return out;
      if (c !== '\\') { out += c; continue; }
      const e = text[i++];
      if (e === 'u') { out += String.fromCharCode(parseInt(text.slice(i, i + 4), 16)); i += 4; }
      else if (e === 'n') out += '\n'; else if (e === 't') out += '\t'; else if (e === 'r') out += '\r';
      else if (e === 'b') out += '\b'; else if (e === 'f') out += '\f';
      else out += e;
    }
  }
  const v = value(); ws();
  if (i !== text.length) bad('text after the value');
  return v;
}

// ---- X1's canonical form: Python's json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=False)
function pyFloat(raw) {
  const x = Number(raw);
  if (x === Infinity) return 'Infinity';
  if (x === -Infinity) return '-Infinity';
  if (x === 0) return (Object.is(x, -0) || raw.trim().startsWith('-')) ? '-0.0' : '0.0';
  const m = /^(-?)(\d)(?:\.(\d+))?e([+-]\d+)$/.exec(x.toExponential());
  const sign = m[1], digits = m[2] + (m[3] || ''), exp = parseInt(m[4], 10);
  if (exp < -4 || exp >= 16) {
    const mant = digits.length > 1 ? digits[0] + '.' + digits.slice(1) : digits;
    const e = Math.abs(exp);
    return sign + mant + 'e' + (exp < 0 ? '-' : '+') + (e < 10 ? '0' + e : String(e));
  }
  if (exp < 0) return sign + '0.' + '0'.repeat(-exp - 1) + digits;
  if (digits.length <= exp + 1) return sign + digits + '0'.repeat(exp + 1 - digits.length) + '.0';
  return sign + digits.slice(0, exp + 1) + '.' + digits.slice(exp + 1);
}
function pyStr(s) {
  let out = '"';
  for (const ch of s) {
    const c = ch.codePointAt(0);
    if (ch === '"') out += '\\"';
    else if (ch === '\\') out += '\\\\';
    else if (ch === '\n') out += '\\n';
    else if (ch === '\r') out += '\\r';
    else if (ch === '\t') out += '\\t';
    else if (ch === '\b') out += '\\b';
    else if (ch === '\f') out += '\\f';
    else if (c < 0x20) out += '\\u' + c.toString(16).padStart(4, '0');
    else out += ch;
  }
  return out + '"';
}
function byCodePoint(a, b) {
  const x = Array.from(a), y = Array.from(b);
  for (let k = 0; k < Math.min(x.length, y.length); k++) {
    const d = x[k].codePointAt(0) - y[k].codePointAt(0);
    if (d) return d;
  }
  return x.length - y.length;
}
function canon(v) {
  if (v === null) return 'null';
  if (v === true) return 'true';
  if (v === false) return 'false';
  if (typeof v === 'string') return pyStr(v);
  if (Array.isArray(v)) return '[' + v.map(canon).join(',') + ']';
  if (v instanceof Map) {
    return '{' + Array.from(v.keys()).sort(byCodePoint).map((k) => pyStr(k) + ':' + canon(v.get(k))).join(',') + '}';
  }
  if (v && typeof v.num === 'string') return v.float ? pyFloat(v.num) : BigInt(v.num).toString();
  throw new Error('a value the canonical form does not know');
}
const sha = (s) => crypto.createHash('sha256').update(Buffer.from(s, 'utf8')).digest('hex');

// ---- Ed25519 with node's crypto
const SPKI = Buffer.from('302a300506032b6570032100', 'hex');
function edVerify(keyHex, message, sigHex) {
  try {
    if (!/^[0-9a-f]{64}$/.test(keyHex) || !/^[0-9a-f]{128}$/.test(sigHex)) return false;
    const key = crypto.createPublicKey({ key: Buffer.concat([SPKI, Buffer.from(keyHex, 'hex')]), format: 'der', type: 'spki' });
    return crypto.verify(null, Buffer.from(message, 'utf8'), key, Buffer.from(sigHex, 'hex'));
  } catch (e) {
    return false;
  }
}

// ---- the checks: each problem is [where, field, why]
function signed(obj, keyHex, where) {
  const out = [];
  if (!(obj instanceof Map)) return [[where, 'signature', 'it is not a JSON object']];
  const s = obj.get('signature');
  if (!(s instanceof Map)) return [[where, 'signature', 'it carries no signature object']];
  if (s.get('alg') !== 'Ed25519') out.push([where, 'signature', 'alg is not Ed25519']);
  if (s.get('key') !== keyHex) out.push([where, 'signature', 'signature.key is not the key given: it was signed by another key']);
  const dg = s.get('digests');
  if (!(dg instanceof Map)) return out.concat([[where, 'signature', 'signature.digests is not an object']]);
  if (!edVerify(keyHex, canon(dg), String(s.get('sig')))) {
    out.push([where, 'signature', 'sig is not a valid Ed25519 signature of the digests by the key given']);
  }
  const names = new Set(Array.from(obj.keys()).filter((k) => k !== 'signature').concat(Array.from(dg.keys())));
  for (const k of Array.from(names).sort(byCodePoint)) {
    if (!obj.has(k)) out.push([where, k, 'this field was signed and is missing']);
    else if (!dg.has(k)) out.push([where, k, 'this field is not signed']);
    else if (sha(canon(obj.get(k))) !== dg.get(k)) out.push([where, k, 'this field changed after it was signed (its SHA-256 is not the signed digest)']);
  }
  return out;
}

function main(argv) {
  if (argv.length !== 2) {
    console.log('usage: node kamanu-verify.cjs PAGE KEY   (KEY: the registry public key, 64 hex digits)');
    return 2;
  }
  const [pagePath, keyArg] = argv;
  const keyHex = String(keyArg).trim().toLowerCase();
  const problems = [];
  let data;
  try {
    const page = fs.readFileSync(pagePath, 'utf8');
    const m = /<script\b[^>]*\bid\s*=\s*["']kamanu-hallmark["'][^>]*>([\s\S]*?)<\/script\s*>/i.exec(page);
    if (!m) throw new Error('the page embeds no <script id="kamanu-hallmark">');
    data = parse(m[1]);
    if (!(data instanceof Map) || !(data.get('record') instanceof Map) || !Array.isArray(data.get('pyx'))) {
      throw new Error('the embedded JSON is not {"record": object, "pyx": list}');
    }
  } catch (e) {
    console.log('FAIL record: ' + e.message);
    return 1;
  }
  if (!/^[0-9a-f]{64}$/.test(keyHex)) problems.push(['key', 'signature', 'the key given is not 64 hex digits']);
  const rec = data.get('record');
  for (const p of signed(rec, keyHex, 'record')) problems.push(p);
  const id = sha(canon(rec));
  data.get('pyx').forEach((e, n) => {
    const where = 'entry ' + n;
    for (const p of signed(e, keyHex, where)) problems.push(p);
    if (e instanceof Map && e.get('hallmark') !== id) {
      problems.push([where, 'hallmark', "the entry's hallmark is not this record's id: it belongs to another hallmark"]);
    }
  });
  if (problems.length) {
    for (const [where, field, why] of problems) console.log('FAIL ' + where + ' ' + field + ': ' + why);
    console.log('KAMANU page check: ' + problems.length + ' check(s) do not pass for hallmark ' + id);
    return 1;
  }
  console.log('OK record: signed by ' + keyHex + ', every field is the one signed');
  console.log('OK pyx: ' + data.get('pyx').length + ' entr' + (data.get('pyx').length === 1 ? 'y' : 'ies') + ', each signed by the key and for this hallmark');
  console.log('hallmark ' + id + ': verified');
  return 0;
}

process.exitCode = main(process.argv.slice(2));
"""
