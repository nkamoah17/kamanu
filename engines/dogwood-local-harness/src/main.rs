//! KAMANU H5: the Dogwood Local Engine behind one JSON command per line on stdin and
//! one JSON reply per line on stdout (the protocol is fixed by gate H5).
//!
//!   {"cmd": "version"}                              -> library version, git, rev, clock
//!   {"cmd": "open", "policy": TEXT, "schema": TEXT} -> a fresh store in a new temporary
//!        file, the policy installed against the schema; the session clock is 0
//!   {"cmd": "submit", "kind": "request"|"response"|"error", "id", "amount", "t"}
//!        an event of the policy's one capped action; a request gets a verdict
//!
//! Time. The library assigns every timestamp itself, through its `Clock` seam
//! (`DurableConfig::with_clock`). The harness gives it a clock that reads a fixed base
//! instant plus the session time `t` of the event being submitted, so the clock is
//! "supplied": the library still stamps at ingestion and still clamps to stay strictly
//! after the previous event (`max(now, last + 1ns)`).
//!
//! The event's action comes from the policy (its one `action == NS::Action::"A"`), the
//! principal and resource types from the schema (the action's first of each). The input
//! record is the schema's with `amount` set (other scalar fields get a placeholder); a
//! response also carries the output record. Events follow the library's default event
//! schema: callerPrincipal, callerResource, requestId and sessionId in the logged record.

use std::collections::HashMap;
use std::io::{self, BufRead, Write};
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicI64, Ordering};

use dogwood_language::{Event, EventBuilder, Value};
use dogwood_local_engine::{Clock, DurableConfig, DurableTemporalEngine, Outcome};
use serde_json::{Value as Json, json};

/// 2026-01-01T00:00:00Z in epoch nanoseconds: session time 0.
const BASE_NANOS: i64 = 1_767_225_600 * 1_000_000_000;
const AGENT: &str = "kamanu-agent";
const GATEWAY: &str = "kamanu-resource";

#[derive(Clone)]
struct SessionClock(Arc<AtomicI64>);

impl Clock for SessionClock {
    fn now_nanos(&self) -> i64 {
        self.0.load(Ordering::SeqCst)
    }
}

/// What the policy and schema say about the capped action.
struct Shape {
    namespace: Vec<String>,
    action: String,
    principal: String,
    resource: String,
    input: Vec<(String, String)>,
    output: Vec<(String, String)>,
}

struct Store {
    engine: Option<DurableTemporalEngine>,
    path: PathBuf,
    clock: SessionClock,
    shape: Shape,
    last_t: i64,
    session: String,
}

impl Drop for Store {
    fn drop(&mut self) {
        drop(self.engine.take());
        let _ = std::fs::remove_file(&self.path);
    }
}

fn strip_comments(text: &str) -> String {
    text.lines()
        .map(|l| match l.find("//") {
            Some(i) => &l[..i],
            None => l,
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// The text inside the brace that opens at or after `from`, and the index after its match.
fn block(text: &str, from: usize) -> Result<(String, usize), String> {
    let open = text[from..].find('{').ok_or("no block in the schema")? + from;
    let mut depth = 0i32;
    for (i, b) in text.bytes().enumerate().skip(open) {
        match b {
            b'{' => depth += 1,
            b'}' => {
                depth -= 1;
                if depth == 0 {
                    return Ok((text[open + 1..i].to_string(), i + 1));
                }
            }
            _ => {}
        }
    }
    Err("unbalanced braces in the schema".into())
}

/// Top-level `name: Type` fields of a record body; optional (`name?:`) fields skipped.
fn fields(body: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    let (mut depth, mut cur) = (0i32, String::new());
    for ch in body.chars().chain(std::iter::once(',')) {
        match ch {
            '{' | '[' | '<' => depth += 1,
            '}' | ']' | '>' => depth -= 1,
            _ => {}
        }
        if ch == ',' && depth == 0 {
            if let Some((name, ty)) = cur.split_once(':') {
                let name = name.trim().trim_matches('"');
                if !name.is_empty() && !name.ends_with('?') {
                    out.push((name.to_string(), ty.trim().to_string()));
                }
            }
            cur.clear();
        } else {
            cur.push(ch);
        }
    }
    out
}

fn shape(policy: &str, schema: &str) -> Result<Shape, String> {
    let policy = strip_comments(policy);
    let schema = strip_comments(schema);
    // action == NS::Action::"A"  (the namespace may be empty)
    let at = policy.find("action ==").ok_or("the policy names no action")?;
    let rest = policy[at + "action ==".len()..].trim_start();
    let q = rest.find('"').ok_or("the policy's action has no id")?;
    let path = rest[..q].trim_end_matches("::").trim();
    let id_end = rest[q + 1..].find('"').ok_or("unterminated action id")? + q + 1;
    let action = rest[q + 1..id_end].to_string();
    let namespace: Vec<String> = path.split("::").filter(|s| !s.is_empty()).map(String::from).collect();
    let ns = if namespace.len() >= 2 { namespace[..namespace.len() - 1].join("::") } else { String::new() };

    let body = if ns.is_empty() {
        schema.clone()
    } else {
        let key = format!("namespace {ns}");
        let at = schema.find(&key).ok_or(format!("the schema has no namespace {ns}"))?;
        block(&schema, at)?.0
    };
    let mut types = HashMap::new();
    let mut i = 0;
    while let Some(p) = body[i..].find("type ") {
        let at = i + p;
        let after = &body[at + 5..];
        let name: String = after.chars().take_while(|c| c.is_alphanumeric() || *c == '_').collect();
        if !name.is_empty() && after[name.len()..].trim_start().starts_with('=') {
            let (b, end) = block(&body, at)?;
            types.insert(name, b);
            i = end;
        } else {
            i = at + 5;
        }
    }
    let at = body
        .find(&format!("action \"{action}\""))
        .or_else(|| body.find(&format!("action {action} ")))
        .ok_or(format!("the schema has no action {action:?}"))?;
    let (applies, _) = block(&body, at)?;
    let first = |kind: &str| -> Result<String, String> {
        let p = applies.find(&format!("{kind}:")).ok_or(format!("the action names no {kind}"))?;
        let r = applies[p + kind.len() + 1..].trim_start().trim_start_matches('[').trim_start();
        let t: String = r.chars().take_while(|c| c.is_alphanumeric() || *c == '_' || *c == ':').collect();
        if t.is_empty() {
            return Err(format!("the action's {kind} type is unreadable"));
        }
        Ok(if ns.is_empty() || t.contains("::") { t } else { format!("{ns}::{t}") })
    };
    let principal = first("principal")?;
    let resource = first("resource")?;
    let cp = applies.find("context").ok_or("the action has no context")?;
    let (ctx, _) = block(&applies, cp)?;
    let ctx = ctx.replace("?:", ":"); // the output group is optional in the context
    let record = |group: &str| -> Vec<(String, String)> {
        match fields(&ctx).into_iter().find(|(n, _)| n == group).map(|(_, t)| t) {
            Some(t) if t.starts_with('{') && t.ends_with('}') => fields(&t[1..t.len() - 1]),
            Some(t) => types.get(&t).map(|b| fields(b)).unwrap_or_default(),
            None => Vec::new(),
        }
    };
    Ok(Shape {
        input: record("input"),
        output: record("output"),
        namespace,
        action,
        principal,
        resource,
    })
}

fn placeholder(ty: &str) -> Option<Value> {
    match ty {
        "Long" => Some(Value::Int(0)),
        "String" => Some(Value::String("kamanu".into())),
        "Bool" | "Boolean" => Some(Value::Bool(true)),
        _ => None,
    }
}

impl Store {
    fn open(policy: &str, schema: &str, n: u64) -> Result<Store, String> {
        let shape = shape(policy, schema)?;
        let path = std::env::temp_dir().join(format!("kamanu-dle-{}-{n}.redb", std::process::id()));
        let _ = std::fs::remove_file(&path);
        let clock = SessionClock(Arc::new(AtomicI64::new(BASE_NANOS)));
        let config = DurableConfig::new(0).with_clock(Box::new(clock.clone()));
        let mut store = Store {
            engine: None,
            path: path.clone(),
            clock,
            shape,
            last_t: 0,
            session: format!("kamanu-{}-{n}", std::process::id()),
        };
        let mut engine = DurableTemporalEngine::open_with_config(&path, config).map_err(|e| e.to_string())?;
        engine.install(policy, schema, None, None).map_err(|e| e.to_string())?;
        store.engine = Some(engine);
        Ok(store)
    }

    fn event(&self, kind: &str, id: &str, amount: i64) -> EventBuilder {
        let s = &self.shape;
        let ns: Vec<&str> = s.namespace.iter().map(String::as_str).collect();
        let mut b = Event::builder_for(&ns, &s.action, kind)
            .principal_for(&s.principal, AGENT)
            .resource_for(&s.resource, GATEWAY);
        let set = |mut b: EventBuilder, group: &str, fs: &[(String, String)], ctx: bool| {
            for (name, ty) in fs {
                let v = if name == "amount" { Some(Value::Int(amount)) } else { placeholder(ty) };
                if let Some(v) = v {
                    if ctx {
                        b = b.request_context(group, name, v.clone());
                    }
                    b = b.field(group, name, v);
                }
            }
            b
        };
        b = set(b, "input", &s.input, kind == "request");
        if kind == "response" {
            b = set(b, "output", &s.output, false);
        }
        b.logged_field("callerPrincipal", Value::Entity { ty: s.principal.clone(), id: AGENT.into() })
            .logged_field("callerResource", Value::Entity { ty: s.resource.clone(), id: GATEWAY.into() })
            .logged_field("requestId", Value::String(id.into()))
            .logged_field("sessionId", Value::String(self.session.clone()))
    }

    fn submit(&mut self, cmd: &Json) -> Result<Json, String> {
        let kind = cmd["kind"].as_str().ok_or("submit needs a kind")?;
        if !matches!(kind, "request" | "response" | "error") {
            return Err(format!("bad kind {kind:?}"));
        }
        let id = cmd["id"].as_str().filter(|s| !s.is_empty()).ok_or("submit needs an id")?;
        let amount = cmd["amount"].as_i64().ok_or("submit needs an integer amount")?;
        let t = cmd["t"].as_i64().filter(|t| *t >= 0).ok_or("submit needs an integer t >= 0")?;
        if t < self.last_t {
            return Err(format!("t {t} goes back in time (last {})", self.last_t));
        }
        self.last_t = t;
        self.clock.0.store(BASE_NANOS + t * 1_000_000_000, Ordering::SeqCst);
        let ev = self.event(kind, id, amount);
        let engine = self.engine.as_mut().ok_or("no store")?;
        let done = engine.submit(ev).map_err(|e| e.to_string())?;
        match (kind, done.outcome) {
            ("request", Outcome::Decision(r)) => {
                let errors: Vec<String> = r.diagnostics().errors().map(String::from).collect();
                if !errors.is_empty() {
                    return Err(format!("the library reported evaluation errors: {errors:?}"));
                }
                Ok(json!({"ok": true, "verdict": if r.allowed() { "allow" } else { "deny" }}))
            }
            ("request", Outcome::Recorded) => Err("the library gave the request no verdict".into()),
            (_, Outcome::Recorded) => Ok(json!({"ok": true})),
            (_, Outcome::Decision(_)) => Err(format!("the library decided a {kind} event")),
        }
    }
}

fn main() {
    let stdin = io::stdin();
    let mut out = io::stdout().lock();
    let mut store: Option<Store> = None;
    let mut opened = 0u64;
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() {
            continue;
        }
        let reply = match serde_json::from_str::<Json>(&line) {
            Err(e) => Err(format!("not JSON: {e}")),
            Ok(cmd) => match cmd["cmd"].as_str() {
                Some("version") => Ok(json!({"ok": true, "version": env!("DLE_VERSION"),
                    "library": {"git": env!("DLE_GIT"), "rev": env!("DLE_REV")}, "clock": "supplied"})),
                Some("open") => match (cmd["policy"].as_str(), cmd["schema"].as_str()) {
                    (Some(p), Some(s)) => {
                        store = None; // the old store and its file go first
                        opened += 1;
                        Store::open(p, s, opened).map(|st| {
                            store = Some(st);
                            json!({"ok": true, "clock": "supplied"})
                        })
                    }
                    _ => Err("open needs a policy and a schema".into()),
                },
                Some("submit") => match store.as_mut() {
                    Some(st) => st.submit(&cmd),
                    None => Err("submit before open".into()),
                },
                other => Err(format!("unknown command {other:?}")),
            },
        };
        let reply = reply.unwrap_or_else(|e| json!({"ok": false, "error": e}));
        if writeln!(out, "{reply}").and_then(|_| out.flush()).is_err() {
            break;
        }
    }
}
