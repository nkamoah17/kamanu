//! R17's table at run time: the perfect hash, an entry's template filled in for one policy
//! (kamanu.fast.table.render), and lint's three outputs of the object: the JSON (`json.dumps(results,
//! indent=1)`), the text (kamanu.fast.text_lines) and SARIF (kamanu.fast.sarif), byte for byte.

use crate::json::{self, py_str, V};
use crate::levels_gen as LG;
use crate::parse::Reading;
use crate::table_gen as G;

pub const TAG: char = '\u{0}';

/// The shape's place among the 162 (kamanu.fast.table.code_index).
pub fn code_index(code: &[i8; 5]) -> usize {
    let [r, s, e, f, w] = *code;
    (((((r + 1) as usize * 3 + (s + 1) as usize) * 3 + (e + 1) as usize) * 3 + (f + 1) as usize) * 2) + w as usize
}

/// The entry for a shape on a built profile at cap n (kamanu.fast.table.fast's lookup), or None (a miss).
#[inline]
pub fn lookup(profile: usize, code: &[i8; 5], n: u128) -> Option<usize> {
    let base = (profile * G::CODES + code_index(code)) * G::AT_SLOTS;
    let mut e = G::SLOTS[base] as usize;
    if e == 0 {
        return None;
    }
    let (kind, _, from, _, _, _) = G::ENTRIES[e - 1];
    if kind == 1 && n < from as u128 {
        if n == 0 || n % 10 != 0 || (n / 10) as usize >= G::AT_SLOTS {
            return None;
        }
        e = G::SLOTS[base + (n / 10) as usize] as usize;
        if e == 0 {
            return None;
        }
    }
    let unit = G::ENTRIES[e - 1].1 as u128;
    if n == 0 || n % unit != 0 {
        return None;
    }
    Some(e - 1)
}

pub fn fails(entry: usize) -> bool {
    G::ENTRIES[entry].5
}

pub struct Pool {
    nodes: Vec<(usize, std::rc::Rc<V>)>,
}

impl Pool {
    pub fn new() -> Pool {
        Pool { nodes: Vec::with_capacity(64) }
    }
    fn node(&mut self, i: usize) -> Result<std::rc::Rc<V>, String> {
        if let Some((_, n)) = self.nodes.iter().find(|(k, _)| *k == i) {
            return Ok(n.clone());
        }
        let &(off, len) = G::POOL.get(i).ok_or("a pool index out of range")?;
        let n = std::rc::Rc::new(json::parse(&G::DATA[off as usize..(off + len) as usize])?);
        self.nodes.push((i, n.clone()));
        Ok(n)
    }
}

/// An entry's body: (its object template, its repair shape).
pub fn entry_body(entry: usize) -> Result<(V, V), String> {
    let (_, _, _, off, len, _) = G::ENTRIES[entry];
    let row = json::parse(&G::DATA[off as usize..(off + len) as usize])?;
    let body = row.as_list().get(2).cloned().ok_or("an entry line without a body")?;
    let obj = body.get("object").cloned().ok_or("an entry without an object")?;
    let repair = body.get("repair").cloned().unwrap_or(V::Null);
    Ok((obj, repair))
}

pub struct Ctx<'a> {
    pub n: u128,
    pub l: usize,
    pub c: usize,
    pub el: usize,
    pub ec: usize,
    pub path: Option<&'a str>,
    pub name: &'a str,
    pub rc: String,
    pub fix: V,
}

pub fn render(node: &V, ctx: &Ctx, pool: &mut Pool) -> Result<V, String> {
    Ok(match node {
        V::Map(m) => {
            let mut out = Vec::with_capacity(m.len());
            for (k, v) in m {
                out.push((k.clone(), render(v, ctx, pool)?));
            }
            V::Map(out)
        }
        V::List(l) => {
            if let Some(V::Str(t)) = l.first() {
                if t.starts_with(TAG) {
                    return slot(&t[1..], l, ctx, pool);
                }
            }
            let mut out = Vec::with_capacity(l.len());
            for v in l {
                out.push(render(v, ctx, pool)?);
            }
            V::List(out)
        }
        other => other.clone(),
    })
}

fn slot(t: &str, l: &[V], ctx: &Ctx, pool: &mut Pool) -> Result<V, String> {
    let int = |i: usize| -> Result<i128, String> { l.get(i).and_then(|v| v.as_int()).ok_or_else(|| "a slot's number".to_string()) };
    Ok(match t {
        "r" => {
            let i = int(1)? as usize;
            let n = pool.node(i)?;
            render(&n, ctx, pool)?
        }
        "s" => {
            let mut s = String::new();
            for p in &l[1..] {
                match p {
                    V::Str(x) => s.push_str(x),
                    other => s.push_str(&py_str(&render(other, ctx, pool)?)),
                }
            }
            V::Str(s.into())
        }
        "f" => {
            let (num, den) = (int(1)?, int(2)?);
            if den <= 0 {
                return Err("a fraction out of range".into());
            }
            // Python's N * num // den: floor division
            let n = i128::try_from(ctx.n).map_err(|_| "a cap too large")?;
            V::Int(n.checked_mul(num).ok_or("a cap too large")?.div_euclid(den))
        }
        "L" => V::Int(ctx.l as i128),
        "EL" => V::Int(ctx.el as i128),
        "C" => V::Int(ctx.c as i128),
        "EC" => V::Int(ctx.ec as i128),
        "path" => ctx.path.map(|p| V::Str(p.to_string().into())).unwrap_or(V::Null),
        "name" => V::Str(ctx.name.to_string().into()),
        "rc" => V::Str(ctx.rc.clone().into()),
        "fix" => ctx.fix.clone(),
        other => return Err(format!("no slot {other}")),
    })
}

// ---------------------------------------------------------------- the re-check command
/// shlex.quote.
pub fn sh_quote(s: &str) -> String {
    if s.is_empty() {
        return "''".into();
    }
    if s.bytes().all(|c| c.is_ascii_alphanumeric() || b"_@%+=:,./-".contains(&c)) {
        return s.into();
    }
    format!("'{}'", s.replace('\'', "'\"'\"'"))
}

/// kamanu.fast.findings.recheck_command at the table's defaults.
pub fn recheck(path: Option<&str>, engine: &str) -> String {
    let args = ["kamanu", "lint", path.unwrap_or("POLICY.dw"), "--engine", engine, "--json"];
    args.iter().map(|a| sh_quote(a)).collect::<Vec<_>>().join(" ")
}

/// What a table answer's passing verdict carries on one built profile: (level, its line's words, rests_on).
pub type Levels = (&'static str, &'static str, &'static str);

fn level_of(status: &str, levels: &Levels) -> Result<&'static str, String> {
    match status {
        "holds" | "VACUOUS" => Ok(levels.0),
        "FAILS" => Ok(LG::REFUTED),
        "open" => Ok(LG::UNKNOWN),
        other => Err(format!("no level for {other}")),
    }
}

/// kamanu.fast.level.apply: each verdict's "level" and "rests_on", last.
fn apply_levels(obj: &mut V, levels: &Levels) -> Result<(), String> {
    let rests_on = json::parse(levels.2)?;
    let V::Map(m) = obj else { return Err("an object".into()) };
    let Some((_, V::List(vs))) = m.iter_mut().find(|(k, _)| k.as_ref() == "verdicts") else {
        return Err("verdicts".into());
    };
    for v in vs.iter_mut() {
        let level = level_of(&s(v, "status"), levels)?;
        let V::Map(vm) = v else { return Err("a verdict".into()) };
        vm.push(("level".into(), V::Str(level.into())));
        vm.push(("rests_on".into(), rests_on.clone()));
    }
    Ok(())
}

/// The object lint answers for one policy from its reading and entry.
#[allow(clippy::too_many_arguments)]
pub fn answer(text: &str, path: Option<&str>, engine: &str, name: &str, r: &Reading, entry: usize, pool: &mut Pool, levels: &Levels) -> Result<V, String> {
    let (tmpl, repair) = entry_body(entry)?;
    let (l, c) = crate::parse::position(text, r.cmp.0);
    let (el, ec) = crate::parse::position(text, r.cmp.1);
    let fix = crate::fix::fix_of(text, path, r, &repair);
    let ctx = Ctx { n: r.n.ok_or("a cap too large")?, l, c, el, ec, path, name, rc: recheck(path, engine), fix };
    let mut obj = render(&tmpl, &ctx, pool)?;
    apply_levels(&mut obj, levels)?;
    Ok(obj)
}

// ---------------------------------------------------------------- the text (kamanu.fast.text_lines)
fn g<'a>(v: &'a V, k: &str) -> &'a V {
    static NULL: V = V::Null;
    v.get(k).unwrap_or(&NULL)
}

fn s(v: &V, k: &str) -> String {
    py_str(g(v, k))
}

fn bool_lower(v: &V) -> String {
    match v {
        V::Bool(b) => if *b { "true".into() } else { "false".into() },
        other => py_str(other),
    }
}

/// str.splitlines.
fn splitlines(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut it = text.chars().peekable();
    while let Some(c) = it.next() {
        match c {
            '\r' => {
                if it.peek() == Some(&'\n') {
                    it.next();
                }
                out.push(std::mem::take(&mut cur));
            }
            '\n' | '\u{b}' | '\u{c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}' => {
                out.push(std::mem::take(&mut cur));
            }
            c => cur.push(c),
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

const NONE_NEAR: &str = "none within one step";

fn verdict_line(v: &V, res: &V, levels: &Levels) -> String {
    let who = if s(v, "ledger") == "caller" {
        " on the caller's ledger (two sessions of one caller, spent over both)"
    } else if res.get("scope_key").map(py_str).unwrap_or_default().starts_with("ScopeSession") {
        " (per session)"
    } else {
        ""
    };
    let status = s(v, "status");
    let mut out = format!("{} {} {}{}", s(v, "rung"), s(v, "property"), status, who);
    if status == "open" {
        out += &format!(
            ": no closed exploration within the budget of {} states (explored {} requests deep, no failure met); neither holds nor FAILS; decide it with: {}",
            s(v, "budget"), s(v, "requests"), s(res, "command")
        );
    } else {
        out += "; any number of requests";
    }
    if status == "FAILS" {
        out += &format!("; a shortest trace of {} steps", g(v, "trace").as_list().len());
    } else if status == "holds" {
        out += &format!("; witness: a refusal reached in {} steps", g(v, "witness").as_list().len());
        let n = g(v, "neighbour");
        out += &match n {
            V::Str(x) if x == NONE_NEAR => "; failing neighbour: none within one step".to_string(),
            V::Null => "; failing neighbour: not searched with the answers open".to_string(),
            _ => format!("; failing neighbour: {} {} FAILS", s(n, "coordinate"), bool_lower(g(n, "value"))),
        };
    } else if status == "VACUOUS" {
        out += "; no refusal is reachable at all";
    }
    if !matches!(g(v, "returns"), V::Null) {
        let answers = g(res, "answers");
        if g(answers, "returned").truthy() {
            let r = g(v, "returns").as_list();
            out += &format!(
                "; for every answer the tool may give (returned amounts {} to {} times the amount asked)",
                r.first().map(py_str).unwrap_or_default(),
                r.get(1).map(py_str).unwrap_or_default()
            );
        } else {
            out += "; for every answer the tool may give";
        }
    }
    let ow = g(v, "only_when");
    if ow.truthy() {
        let field = s(ow, "field");
        let act = g(g(res, "answers"), "oracles")
            .as_list()
            .iter()
            .find(|o| s(o, "field") == field)
            .map(|o| s(o, "action"));
        let val = match g(ow, "value") {
            V::Bool(b) => if *b { "true".to_string() } else { "false".to_string() },
            other => {
                let mut x = String::new();
                json::dump_into(&mut x, other, 0, 0);
                x
            }
        };
        let fname = field.strip_prefix("output.").map(|x| x.to_string()).unwrap_or_else(|| field.chars().skip(7).collect());
        out += &format!("; fails only when {}{}: {}", act.map(|a| format!("{a} returns ")).unwrap_or_default(), fname, val);
    }
    if g(v, "conditional").truthy() {
        let rests: Vec<String> = g(v, "rests_on_default").as_list().iter().map(py_str).collect();
        out += &format!(
            "; rests on default: {}; with the pessimistic defaults flipped: {}",
            if rests.is_empty() { "none".to_string() } else { rests.join(", ") },
            s(g(v, "conditional"), "defaults flipped")
        );
    }
    if g(v, "readings").truthy() {
        if let V::Map(m) = g(v, "readings") {
            out += &format!("; readings: {}", m.iter().map(|(k, x)| format!("{} {}", k, py_str(x))).collect::<Vec<_>>().join(", "));
        }
    }
    if g(v, "deny_marks").truthy() {
        out += &format!("; if a denial also writes an error event: {}", s(g(v, "deny_marks"), "request+error"));
    }
    if g(res, "unmodelled").truthy() {
        // unmodelled_text: never reached by a table answer (its profiles model everything)
        out += &format!("; unmodelled: {}", py_str(g(res, "unmodelled")));
    }
    if g(res, "reading").truthy() {
        out += &format!("; reading: {}", s(res, "reading"));
    }
    if matches!(status.as_str(), "holds" | "VACUOUS") {
        out += levels.1;
    } else {
        out += &format!("; level {}", s(v, "level"));
    }
    out
}

pub fn text_lines(res: &V, levels: &Levels) -> Result<Vec<String>, String> {
    let name = if g(res, "policy").truthy() { s(res, "policy") } else { "policy".to_string() };
    let mut out = Vec::new();
    if g(res, "no_limit").truthy() {
        out.push(format!("{}: {}", name, s(res, "reason")));
        out.push("  no verdict: there is no limit to hold".into());
    } else if g(res, "nothing_to_check").truthy() {
        out.push(format!("{}: {}", name, s(res, "reason")));
        out.push("  no verdict: there is no history clause to check".into());
    } else if !g(res, "inside").truthy() {
        out.push(format!("{}: outside the fast path: line {}: {}: {}", name, s(res, "line"), s(res, "construct"), s(res, "reason")));
        out.push(format!("  no verdict; decide it with: {}", s(res, "command")));
        out.push(format!("  level {}: lint gives no verdict", LG::UNKNOWN));
    } else {
        let m = s(res, "machine");
        if m == "memory" || m == "registers" {
            return Err("a machine the table never answers".into());
        }
        let b = g(res, "bounds");
        let inf = g(b, "in_flight").as_int().ok_or("bounds")?;
        let am = g(res, "amounts").as_list();
        out.push(format!("{}: inside the fast path on {}: {}", name, s(res, "engine"), s(res, "reason")));
        out.push(format!(
            "  bounds: any number of requests, at most {} calls in flight, at most {} failure(s); cap {}, amounts {} and {}{}",
            inf,
            s(b, "failures"),
            s(res, "cap"),
            am.first().map(py_str).ok_or("amounts")?,
            am.get(1).map(py_str).ok_or("amounts")?,
            if inf >= 3 { String::new() } else { format!("; a race that needs {} or more calls in flight is outside these bounds", inf + 1) }
        ));
        out.push(format!("  scope key: {}", s(res, "scope_key")));
        if g(res, "window").truthy() {
            out.push(format!("  window: {}", s(g(res, "window"), "reading")));
        }
        if g(res, "live").truthy() {
            return Err("live trials the table never holds".into());
        }
        for n in g(res, "notes").as_list() {
            out.push(format!("  note: {}", py_str(n)));
        }
        for v in g(res, "verdicts").as_list() {
            out.push(verdict_line(v, res, levels));
            if g(v, "story").truthy() {
                out.extend(splitlines(&s(v, "story")));
            }
        }
        for v in g(res, "verdicts").as_list() {
            if s(v, "property") == "Sound" && g(v, "exposure").truthy() {
                return Err("an exposure the table never holds".into());
            }
        }
        if g(res, "exposure_table").truthy() {
            return Err("an overshoot table the table never holds".into());
        }
        for v in g(res, "verdicts").as_list() {
            if g(v, "stranded").truthy() {
                out.push(format!(
                    "  {} Tight ({} ledger): stranded budget {} (the most headroom free when a request that fits is refused)",
                    s(v, "rung"), s(v, "ledger"), s(v, "stranded")
                ));
            }
        }
        if g(res, "verdicts").as_list().iter().any(|v| s(v, "status") == "open") {
            out.push(format!("  open verdicts are neither holds nor FAILS; decide them with: {}", s(res, "command")));
        }
    }
    for f in g(res, "findings").as_list() {
        if g(f, "verdict").truthy() {
            out.push(format!("{}:{}:{}: {} {}: {}", name, s(f, "line"), s(f, "column"), s(f, "level"), s(f, "rule"), s(f, "claim")));
            if g(f, "suppressed").truthy() {
                let sp = g(f, "suppressed");
                out.push(format!("  suppressed (line {}): {}", s(sp, "line"), s(sp, "reason")));
            }
            if g(f, "fix").truthy() {
                let fx = g(f, "fix");
                out.push(format!("  fix: {} -> {}", s(fx, "old"), s(fx, "new")));
            }
            out.push(format!("  re-check: {}", s(f, "recheck")));
            continue;
        }
        // kamanu.fast.rules.finding_lines
        out.push(format!("{}:{}:{}: {} {}", name, s(f, "line"), s(f, "column"), s(f, "level"), s(f, "message")));
        if g(f, "suppressed").truthy() {
            let sp = g(f, "suppressed");
            out.push(format!("  suppressed (line {}): {}", s(sp, "line"), s(sp, "reason")));
        }
        if g(f, "trace").truthy() || g(f, "edit").truthy() || g(f, "confirmed").truthy() {
            return Err("a rule finding with a trace, an edit or a confirmation the table never holds".into());
        }
        if g(f, "note").truthy() {
            out.push(format!("  note: {}", s(f, "note")));
        }
        if !matches!(g(f, "stranded"), V::Null) {
            out.push(format!(
                "  stranded budget at R2: {} (the most headroom free when a request that fits is refused)",
                s(f, "stranded")
            ));
        }
        if g(f, "fix").truthy() {
            let fx = g(f, "fix");
            out.push(format!(
                "  fix: line {} column {} to line {} column {}: {} -> {}",
                s(fx, "start_line"), s(fx, "start_column"), s(fx, "end_line"), s(fx, "end_column"), s(fx, "old"), s(fx, "new")
            ));
        }
        if g(f, "recheck").truthy() {
            out.push(format!("  re-check: {}", s(f, "recheck")));
        }
    }
    if g(res, "suppressions").truthy() {
        out.push(format!("  {} finding(s) suppressed in the source (// kamanu-ignore RULE: reason)", s(res, "suppressions")));
    }
    Ok(out)
}

// ---------------------------------------------------------------- SARIF (kamanu.fast.sarif)
fn int_of(v: &V) -> Result<i128, String> {
    v.as_int().ok_or_else(|| "a region number".to_string())
}

fn region_of(sp: &V) -> Result<V, String> {
    Ok(V::Map(vec![
        ("startLine".into(), V::Int(int_of(g(sp, "line"))?)),
        ("startColumn".into(), V::Int(int_of(g(sp, "column"))?)),
        ("endLine".into(), V::Int(int_of(g(sp, "end_line"))?)),
        ("endColumn".into(), V::Int(int_of(g(sp, "end_column"))?)),
    ]))
}

fn location(uri: &str, region: V) -> V {
    V::List(vec![V::Map(vec![(
        "physicalLocation".into(),
        V::Map(vec![
            ("artifactLocation".into(), V::Map(vec![("uri".into(), V::Str(uri.to_string().into()))])),
            ("region".into(), region),
        ]),
    )])])
}

/// A SARIF result's properties: the proof level of the verdict it is about.
fn with_level(mut r: V, level: &str) -> V {
    if let V::Map(m) = &mut r {
        m.push(("properties".into(), V::Map(vec![("level".into(), V::Str(level.to_string().into()))])));
    }
    r
}

fn result(rule: String, level: &str, msg: String, uri: &str, region: V) -> V {
    V::Map(vec![
        ("ruleId".into(), V::Str(rule.into())),
        ("level".into(), V::Str(level.to_string().into())),
        ("message".into(), V::Map(vec![("text".into(), V::Str(msg.into()))])),
        ("locations".into(), location(uri, region)),
    ])
}

/// pathlib's as_posix of a path argument, on this platform.
pub fn as_posix(p: &str) -> String {
    let windows = cfg!(windows);
    let s: String = if windows { p.replace('\\', "/") } else { p.to_string() };
    if s.is_empty() {
        return ".".into();
    }
    let (drive, rest) = if windows && s.len() >= 2 && s.as_bytes()[1] == b':' && s.as_bytes()[0].is_ascii_alphabetic() {
        (&s[..2], &s[2..])
    } else {
        ("", &s[..])
    };
    let rooted = rest.starts_with('/');
    let parts: Vec<&str> = rest.split('/').filter(|x| !x.is_empty() && *x != ".").collect();
    let mut out = String::from(drive);
    if rooted {
        out.push('/');
        // POSIX keeps exactly two leading slashes
        if !windows && rest.starts_with("//") && !rest.starts_with("///") {
            out.push('/');
        }
    }
    out.push_str(&parts.join("/"));
    if out.is_empty() {
        ".".into()
    } else {
        out
    }
}

pub fn sarif_results(path: &str, res: &V) -> Result<Vec<V>, String> {
    let uri = as_posix(path);
    let mut out = Vec::new();
    let obj_span = match g(res, "span") {
        V::Map(_) => Some(g(res, "span")),
        _ => None,
    };
    let findings = g(res, "findings").as_list();
    for f in findings {
        let mut region = vec![
            ("startLine".into(), V::Int(int_of(g(f, "line"))?)),
            ("startColumn".into(), V::Int(int_of(g(f, "column"))?)),
        ];
        if !matches!(g(f, "end_line"), V::Null) {
            region.push(("endLine".into(), V::Int(int_of(g(f, "end_line"))?)));
            region.push(("endColumn".into(), V::Int(int_of(g(f, "end_column"))?)));
        }
        let msg = if g(f, "claim").truthy() { s(f, "claim") } else { s(f, "message") };
        let mut r = result(s(f, "rule"), &s(f, "level"), msg, &uri, V::Map(region));
        if g(f, "suppressed").truthy() {
            if let V::Map(m) = &mut r {
                m.push((
                    "suppressions".into(),
                    V::List(vec![V::Map(vec![
                        ("kind".into(), V::Str("inSource".into())),
                        ("justification".into(), g(g(f, "suppressed"), "reason").clone()),
                    ])]),
                ));
            }
        }
        if matches!(s(f, "rule").as_str(), "kamanu/lint/sound" | "kamanu/lint/tight") {
            r = with_level(r, LG::REFUTED);
        }
        out.push(r);
    }
    if g(res, "no_limit").truthy() || g(res, "nothing_to_check").truthy() {
        return Ok(out);
    }
    if !g(res, "inside").truthy() {
        let region = match obj_span {
            Some(sp) => region_of(sp)?,
            None => V::Map(vec![("startLine".into(), V::Int(int_of(g(res, "line"))?.max(1)))]),
        };
        out.push(with_level(result(
            "kamanu/lint/outside".into(),
            "warning",
            format!("{}: {}; decide it with {}", s(res, "construct"), s(res, "reason"), s(res, "command")),
            &uri,
            region,
        ), LG::UNKNOWN));
        return Ok(out);
    }
    let region = match obj_span {
        Some(sp) => region_of(sp)?,
        None => {
            let line = g(g(res, "shape"), "line");
            let line = if line.truthy() { int_of(line)? } else if g(res, "line").truthy() { int_of(g(res, "line"))? } else { 1 };
            V::Map(vec![("startLine".into(), V::Int(line.max(1)))])
        }
    };
    for v in g(res, "verdicts").as_list() {
        let status = s(v, "status");
        if status == "open" {
            out.push(with_level(result(
                "kamanu/lint/open".into(),
                "warning",
                format!(
                    "{} {} open on the {} ledger on {}: no closed exploration within {} states; decide it with {}",
                    s(v, "rung"), s(v, "property"), s(v, "ledger"), s(res, "engine"), s(v, "budget"), s(res, "command")
                ),
                &uri,
                region.clone(),
            ), LG::UNKNOWN));
        }
        let covered = findings.iter().any(|f| {
            let fv = g(f, "verdict");
            matches!(fv, V::Map(_))
                && ["rung", "property", "ledger"].iter().all(|k| g(fv, k) == g(v, k))
                && matches!(fv, V::Map(m) if m.len() == 3)
        });
        if status != "FAILS" || covered {
            continue;
        }
        out.push(with_level(result(
            format!("kamanu/lint/{}", s(v, "property").to_lowercase()),
            "error",
            format!(
                "{} {} FAILS on the {} ledger on {}: a trace of {} steps",
                s(v, "rung"), s(v, "property"), s(v, "ledger"), s(res, "engine"), g(v, "trace").as_list().len()
            ),
            &uri,
            region.clone(),
        ), LG::REFUTED));
    }
    Ok(out)
}

pub fn sarif_doc(results: &[V]) -> String {
    let mut out = String::from(G::SARIF_HEAD);
    out.push_str("\"results\": ");
    json::dump_into(&mut out, &V::List(results.to_vec()), 2, 3);
    out.push_str(G::SARIF_TAIL);
    out.push('\n');
    out
}

/// kamanu.fast.exit_code (a table answer suppresses nothing).
pub fn exit_code(results: &[V]) -> i32 {
    for r in results {
        let quiet: Vec<(String, String, String)> = g(r, "findings")
            .as_list()
            .iter()
            .filter(|f| g(f, "suppressed").truthy() && g(f, "verdict").truthy())
            .map(|f| {
                let v = g(f, "verdict");
                (s(v, "rung"), s(v, "property"), s(v, "ledger"))
            })
            .collect();
        if g(r, "verdicts")
            .as_list()
            .iter()
            .any(|v| s(v, "status") == "FAILS" && !quiet.contains(&(s(v, "rung"), s(v, "property"), s(v, "ledger"))))
        {
            return 1;
        }
    }
    if results
        .iter()
        .any(|r| g(r, "findings").as_list().iter().any(|f| s(f, "level") == "error" && !g(f, "suppressed").truthy()))
    {
        return 1;
    }
    if results.iter().any(|r| g(r, "verdicts").as_list().iter().any(|v| s(v, "status") == "open")) {
        return 2;
    }
    if results.iter().any(|r| !g(r, "inside").truthy() && !g(r, "nothing_to_check").truthy()) {
        2
    } else {
        0
    }
}
