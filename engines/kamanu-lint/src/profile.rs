//! The engine argument: "reference", one of R17's twelve built profiles (matched on what the record states,
//! as lint reads it: kamanu.fast.engine.load, never on its file name), or another engine (no table answer).

use crate::json::{self, V};
use crate::table_gen as G;

pub enum Engine {
    /// A built profile: (its index in the table, the name lint gives it: the record's id).
    Built(usize, String),
    /// reference, a hunt row, or a record the table is not built for: the Python lint answers.
    Other,
}

/// Err(why) where lint cannot read the engine (exit 3): a missing file, not UTF-8, not JSON.
pub fn load(arg: &str) -> Result<Engine, String> {
    if arg == "reference" {
        return Ok(Engine::Other);
    }
    let p = std::path::Path::new(arg);
    if !p.is_file() {
        return Err(format!("--engine: no profile record or hunt row at {arg}"));
    }
    let bytes = std::fs::read(p).map_err(|e| format!("--engine: {arg}: {e}"))?;
    let text = String::from_utf8(bytes).map_err(|_| format!("--engine: {arg} is not UTF-8"))?;
    let text: &'static str = Box::leak(text.into_boxed_str());
    let rec = match json::parse(text) {
        Ok(v) => v,
        // a lone surrogate Python reads but this reader does not: let the Python lint answer
        Err(e) if e.contains("surrogate") => return Ok(Engine::Other),
        Err(e) => return Err(format!("--engine: {arg} is not JSON: {e}")),
    };
    Ok(built(&rec).map(|(i, name)| Engine::Built(i, name)).unwrap_or(Engine::Other))
}

/// The five constants' values by name (a HashMap would seed its hasher from the OS for five keys).
struct Vals<'a>(Vec<(&'a str, V)>);

impl<'a> Vals<'a> {
    fn insert(&mut self, k: &'a str, v: V) {
        match self.0.iter_mut().find(|(kk, _)| *kk == k) {
            Some(e) => e.1 = v,
            None => self.0.push((k, v)),
        }
    }
    fn get(&self, k: &str) -> Option<&V> {
        self.0.iter().find(|(kk, _)| *kk == k).map(|(_, v)| v)
    }
}

fn one_key_each(m: &[(json::S, V)]) -> bool {
    m.iter().enumerate().all(|(i, (k, _))| m[..i].iter().all(|(k2, _)| k2 != k))
}

/// A record that states exactly a built profile: {"id": str, "constants": {Reflexive, DenyRecord, Atomic,
/// Lag, Scope}}, each constant {"value", and only "source", "confidence" and "basis" as strings}, no basis
/// a pessimistic default, no Scope keys, nothing unmodelled, nothing live; Reflexive true, Scope
/// ScopeGlobal, and (DenyRecord, Atomic, Lag) one of the twelve. Anything else: None (a miss, never a
/// guess).
fn built(rec: &V) -> Option<(usize, String)> {
    let V::Map(top) = rec else { return None };
    if !one_key_each(top) || top.len() != 2 {
        return None;
    }
    let id = rec.get("id")?.as_str()?.to_string();
    let V::Map(con) = rec.get("constants")? else { return None };
    if !one_key_each(con) || con.len() != 5 {
        return None;
    }
    let mut vals = Vals(Vec::with_capacity(5));
    for (k, c) in con {
        if !["Reflexive", "DenyRecord", "Atomic", "Lag", "Scope"].contains(&k.as_ref()) {
            return None;
        }
        let V::Map(fields) = c else { return None };
        if !one_key_each(fields) {
            return None;
        }
        for (f, x) in fields {
            match f.as_ref() {
                "value" => {}
                "source" | "confidence" | "basis" => {
                    let s = x.as_str()?;
                    if f == "basis" && s.to_lowercase().contains("pessimistic default") {
                        return None;
                    }
                }
                _ => return None,
            }
        }
        vals.insert(k.as_ref(), c.get("value")?.clone());
    }
    if vals.get("Reflexive")? != &V::Bool(true) || vals.get("Scope")? != &V::Str("ScopeGlobal".into()) {
        return None;
    }
    let atomic = match vals.get("Atomic")? {
        V::Bool(b) => *b,
        _ => return None,
    };
    let lag: i64 = match vals.get("Lag")? {
        V::Num(s) if s == "0" => 0,
        V::Num(s) if s == "1" => 1,
        _ => return None,
    };
    let dr = vals.get("DenyRecord")?.as_str()?;
    let i = G::PROFILES.iter().position(|(_, d, a, l)| *d == dr && *a == atomic && *l == lag)?;
    Some((i, id))
}
