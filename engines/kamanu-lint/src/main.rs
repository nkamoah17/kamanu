//! kamanu-lint (R17b): `kamanu lint` for the policies R17's verdict table answers, natively.
//!
//!   kamanu-lint POLICY... --engine E [--json | --sarif FILE] [--macros FILE] [--schema FILE]
//!       what `kamanu lint` prints for the same arguments, byte for byte (text, JSON or SARIF), and its exit
//!       code; or a miss: one line, the shape key, on stdout, and the exit code MISS (77), where the table
//!       does not answer (the Python lint does: `kamanu lint` falls through to it on that code). An input
//!       lint cannot read (a policy file missing, a directory or not UTF-8; an engine file missing, not
//!       UTF-8 or not JSON; brackets nested deeper than 64) exits 3 with one line, as lint does.
//!   kamanu-lint --version
//!       one line: the binary, its version and the SHA-256 of the table it holds.
//!   kamanu-lint --corpus FILE --engine E --fails-only [--jobs N]
//!       FILE holds one JSON object per line with "path" and "text"; prints, in the file's order, the path of
//!       each record whose answer has a verdict that FAILS, "miss PATH" for a table miss and "error PATH" for
//!       an input it cannot read, and nothing for the others; exit 0; the same bytes for every N.
//!   kamanu-lint --bench --corpus FILE --engine E
//!       prints {"us": [...]}: for each record, in order, the microseconds of a full parse of its text with
//!       the hand-written parser and the lookup of its answer (no printing, no cache of earlier parses).
//!
//! Each verdict carries its proof level (T2), from the chain of links KAMANU_LINT_LINKS names (`kamanu lint`
//! sets it to its tree's), else the first chain compiled in; a chain the binary does not hold is a miss.
//!
//! No configuration is discovered, nothing is read but the files the arguments name (a file beside a
//! policy is only looked for, as lint looks for it, and the policy is then a miss), and nothing touches
//! the network.

#![cfg_attr(target_os = "linux", no_main)]

#[cfg(target_os = "linux")]
mod arena;
mod fix;
mod json;
#[rustfmt::skip]
mod levels_gen;
mod parse;
mod profile;
mod render;
#[allow(dead_code)]
mod table_gen;
mod vendor;

use std::io::Write;
use std::path::Path;
/// A run's exit code: std::process::ExitCode's role, with its number readable (the Linux entry point
/// returns it to the C runtime).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ExitCode(u8);

impl ExitCode {
    pub const SUCCESS: ExitCode = ExitCode(0);
}

impl From<u8> for ExitCode {
    fn from(c: u8) -> ExitCode {
        ExitCode(c)
    }
}

#[cfg(target_os = "linux")]
#[global_allocator]
static ALLOC: arena::Arena = arena::Arena;

pub const MISS: u8 = 77;
const MAX_DEPTH: usize = 64;
const BESIDE: [&str; 4] = ["macros.dw", "schema.cedarschema", "events.dwschema", "event.dwschema"];

fn out(bytes: &[u8]) {
    let so = std::io::stdout();
    let mut l = so.lock();
    let _ = l.write_all(bytes);
    let _ = l.flush();
}

fn miss(key: &str) -> ExitCode {
    out(format!("{key}\n").as_bytes());
    ExitCode::from(MISS)
}

fn error(why: &str) -> ExitCode {
    let _ = std::io::stdout().flush();
    let _ = writeln!(std::io::stderr(), "kamanu lint: error: {why}");
    ExitCode::from(3)
}

/// Universal newlines, as lint reads a policy file.
fn newlines(s: String) -> String {
    if s.contains('\r') {
        s.replace("\r\n", "\n").replace('\r', "\n")
    } else {
        s
    }
}

/// The shape key a miss prints: the shape and profile where the parser read one, else "outside".
fn shape_key(r: Option<&parse::Reading>, profile: Option<usize>) -> String {
    match r {
        None => "kamanu-lint miss: outside".into(),
        Some(r) => format!(
            "kamanu-lint miss: shape {} cap {} profile {}",
            r.code.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(","),
            r.n.map(|n| n.to_string()).unwrap_or_else(|| "?".into()),
            profile.map(|i| table_gen::PROFILES[i].0).unwrap_or("none")
        ),
    }
}

fn version_line() -> String {
    format!("kamanu-lint {} table {}", env!("CARGO_PKG_VERSION"), table_gen::TABLE_SHA256)
}

/// Linux: the C entry point, without the Rust runtime's start-up (which reads /proc/self/maps to place the
/// main thread's stack guard, installs a stack-overflow handler and polls the standard descriptors). The
/// runtime's one effect a run can see is kept: SIGPIPE ignored, so a closed stdout is an error, not a signal.
#[cfg(target_os = "linux")]
#[no_mangle]
pub extern "C" fn main(_argc: i32, _argv: *const *const u8) -> i32 {
    extern "C" {
        fn signal(sig: i32, handler: usize) -> usize;
    }
    unsafe {
        signal(13, 1); // SIGPIPE, SIG_IGN
    }
    // every output path has flushed stdout (out(), error(), the corpus writer)
    run().0 as i32
}

#[cfg(not(target_os = "linux"))]
fn main() -> std::process::ExitCode {
    std::process::ExitCode::from(run().0)
}

fn run() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() == 1 && (args[0] == "--version" || args[0] == "-V") {
        out(format!("{}\n", version_line()).as_bytes());
        return ExitCode::SUCCESS;
    }
    if args.iter().any(|a| a == "--corpus" || a.starts_with("--corpus=")) {
        return corpus_main(&args);
    }
    lint_main(&args)
}

// ---------------------------------------------------------------- one run of lint
fn lint_main(args: &[String]) -> ExitCode {
    #[cfg(target_os = "linux")]
    arena::warm();
    let mut files: Vec<&str> = Vec::new();
    let (mut engine, mut json_mode, mut sarif, mut other) = (None::<String>, false, None::<String>, false);
    let mut i = 0;
    while i < args.len() {
        let a = args[i].as_str();
        let (flag, inline) = match a.split_once('=') {
            Some((f, v)) if f.starts_with("--") => (f, Some(v.to_string())),
            _ => (a, None),
        };
        let mut value = || -> Option<String> {
            if inline.is_some() {
                return inline.clone();
            }
            i += 1;
            args.get(i).cloned()
        };
        match flag {
            "--json" if inline.is_none() => json_mode = true,
            "--engine" => match value() {
                Some(v) => engine = Some(v),
                None => return miss("kamanu-lint miss: usage"),
            },
            "--sarif" => match value() {
                Some(v) => sarif = Some(v),
                None => return miss("kamanu-lint miss: usage"),
            },
            // a macro library or a schema named: the table answers only at the defaults
            "--macros" | "--schema" => {
                if value().is_none() {
                    return miss("kamanu-lint miss: usage");
                }
                other = true;
            }
            _ if a.starts_with('-') && a != "-" => return miss("kamanu-lint miss: an option the table does not answer"),
            _ => files.push(a),
        }
        i += 1;
    }
    let Some(engine) = engine else { return miss("kamanu-lint miss: usage") };
    if files.is_empty() {
        return miss("kamanu-lint miss: usage");
    }
    let eng = match profile::load(&engine) {
        Ok(e) => e,
        Err(why) => return error(&why),
    };
    // read every file first, as lint does: any it cannot read is an error of the whole run
    let mut texts = Vec::with_capacity(files.len());
    for f in &files {
        let p = Path::new(f);
        if p.is_dir() {
            return miss("kamanu-lint miss: a directory (lint expands it)");
        }
        if f.contains(['*', '?', '[']) && !p.exists() {
            return miss("kamanu-lint miss: a pattern (lint expands it)");
        }
        if !p.is_file() {
            return error(&format!("{f}: no such policy file"));
        }
        let bytes = match std::fs::read(p) {
            Ok(b) => b,
            Err(e) => return error(&format!("{f}: {e}")),
        };
        match String::from_utf8(bytes) {
            Ok(s) => texts.push(newlines(s)),
            Err(e) => return error(&format!("{f}: not UTF-8 text (byte {})", e.utf8_error().valid_up_to())),
        }
    }
    let (profile, name) = match &eng {
        profile::Engine::Built(i, n) => (Some(*i), n.clone()),
        profile::Engine::Other => (None, String::new()),
    };
    // each policy: its reading and entry, or why not
    let mut found = Vec::with_capacity(files.len());
    let mut first_miss: Option<String> = None;
    for (f, text) in files.iter().zip(&texts) {
        let r = if text.contains("kamanu-ignore") { None } else { parse::read(text) };
        let hit = match (&r, profile, other) {
            (Some(r), Some(pi), false) => r.n.and_then(|n| render::lookup(pi, &r.code, n)),
            _ => None,
        };
        let hit = hit.filter(|_| {
            let parent = Path::new(f).parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or(Path::new("."));
            !BESIDE.iter().any(|b| parent.join(b).is_file()) && vendor::accepts(text)
        });
        match hit {
            Some(e) => found.push(Some((r.unwrap(), e))),
            None => {
                if r.is_none() && parse::nesting(text) > MAX_DEPTH {
                    return error(&format!(
                        "brackets nested deeper than {MAX_DEPTH}: lint reads a nesting depth of at most {MAX_DEPTH}"
                    ));
                }
                if first_miss.is_none() {
                    first_miss = Some(shape_key(r.as_ref(), profile));
                }
                found.push(None);
            }
        }
    }
    if let Some(key) = first_miss {
        return miss(&key);
    }
    let chain = match std::env::var("KAMANU_LINT_LINKS") {
        Ok(d) => match levels_gen::CHAINS.iter().find(|(digest, _)| *digest == d) {
            Some(c) => c,
            None => return miss("kamanu-lint miss: links it holds no levels for"),
        },
        Err(_) => &levels_gen::CHAINS[0],
    };
    let Some(levels) = profile.map(|i| &chain.1[i]) else { return miss("kamanu-lint miss: usage") };
    let mut pool = render::Pool::new();
    let mut results = Vec::with_capacity(files.len());
    for ((f, text), item) in files.iter().zip(&texts).zip(found) {
        let (r, e) = item.unwrap();
        match render::answer(text, Some(f), &engine, &name, &r, e, &mut pool, levels) {
            Ok(v) => results.push(v),
            Err(why) => return miss(&format!("kamanu-lint miss: {why}")),
        }
    }
    let mut stdout = String::new();
    if json_mode {
        json::dump_into(&mut stdout, &json::V::List(results.clone()), 1, 0);
        stdout.push('\n');
    } else {
        for r in &results {
            match render::text_lines(r, levels) {
                Ok(lines) => {
                    for l in lines {
                        stdout.push_str(&l);
                        stdout.push('\n');
                    }
                }
                Err(why) => return miss(&format!("kamanu-lint miss: {why}")),
            }
        }
    }
    let sarif_doc = match &sarif {
        Some(_) => {
            let mut all = Vec::new();
            for (f, r) in files.iter().zip(&results) {
                match render::sarif_results(f, r) {
                    Ok(x) => all.extend(x),
                    Err(why) => return miss(&format!("kamanu-lint miss: {why}")),
                }
            }
            Some(render::sarif_doc(&all))
        }
        None => None,
    };
    out(stdout.as_bytes());
    if let (Some(where_), Some(doc)) = (&sarif, sarif_doc) {
        if let Err(e) = std::fs::write(where_, doc.as_bytes()) {
            return error(&format!("{where_}: {e}"));
        }
    }
    ExitCode::from(render::exit_code(&results) as u8)
}

// ---------------------------------------------------------------- the bulk modes
enum Outcome {
    Nothing,
    Fails,
    Miss,
    Error,
}

/// One record's answer on a built profile (None: no built profile, every record a miss).
#[inline]
fn judge(text: &str, profile: Option<usize>) -> Outcome {
    if text.contains("kamanu-ignore") {
        return Outcome::Miss;
    }
    let text = if text.contains('\r') { std::borrow::Cow::Owned(text.replace("\r\n", "\n").replace('\r', "\n")) } else { std::borrow::Cow::Borrowed(text) };
    match parse::read(&text) {
        Some(r) => match (profile, r.n) {
            (Some(pi), Some(n)) => match render::lookup(pi, &r.code, n) {
                Some(e) if render::fails(e) => Outcome::Fails,
                Some(_) => Outcome::Nothing,
                None => Outcome::Miss,
            },
            _ => Outcome::Miss,
        },
        None => {
            if parse::nesting(&text) > MAX_DEPTH {
                Outcome::Error
            } else {
                Outcome::Miss
            }
        }
    }
}

fn corpus_main(args: &[String]) -> ExitCode {
    #[cfg(target_os = "linux")]
    arena::off();
    let (mut file, mut engine, mut jobs, mut bench, mut fails_only) = (None::<String>, None::<String>, 1usize, false, false);
    let mut i = 0;
    while i < args.len() {
        let a = args[i].as_str();
        let (flag, inline) = match a.split_once('=') {
            Some((f, v)) if f.starts_with("--") => (f, Some(v.to_string())),
            _ => (a, None),
        };
        let mut value = || -> Option<String> {
            if inline.is_some() {
                return inline.clone();
            }
            i += 1;
            args.get(i).cloned()
        };
        match flag {
            "--corpus" => file = value(),
            "--engine" => engine = value(),
            "--jobs" => jobs = value().and_then(|v| v.parse().ok()).filter(|&n| n >= 1).unwrap_or(0),
            "--bench" => bench = true,
            "--fails-only" => fails_only = true,
            _ => return error(&format!("--corpus: an argument it does not take: {a}")),
        }
        i += 1;
    }
    let (Some(file), Some(engine)) = (file, engine) else { return error("--corpus FILE --engine E") };
    if jobs == 0 {
        return error("--jobs is 1 or more");
    }
    if !bench && !fails_only {
        return error("--corpus needs --fails-only (or --bench)");
    }
    let profile = match profile::load(&engine) {
        Ok(profile::Engine::Built(i, _)) => Some(i),
        Ok(profile::Engine::Other) => None,
        Err(why) => return error(&why),
    };
    let data = match std::fs::read(&file) {
        Ok(b) => b,
        Err(e) => return error(&format!("{file}: {e}")),
    };
    if bench {
        let data = match String::from_utf8(data) {
            Ok(s) => s,
            Err(_) => return error(&format!("{file}: not UTF-8 text")),
        };
        let lines: Vec<&str> = data.split('\n').filter(|l| !l.trim().is_empty()).collect();
        return bench_main(&lines, profile);
    }
    // the file cut into `jobs` parts at line ends; each part read (UTF-8 checked, split into lines) and
    // answered by a thread of its own; the parts' output printed in the file's order
    let mut cuts = vec![0usize];
    for k in 1..jobs {
        let mut at = (data.len() * k / jobs).max(*cuts.last().unwrap());
        while at < data.len() && data[at] != b'\n' {
            at += 1;
        }
        cuts.push((at + 1).min(data.len()));
    }
    cuts.push(data.len());
    let data = &data;
    let parts: Vec<Result<String, ()>> = std::thread::scope(|sc| {
        let hs: Vec<_> = cuts
            .windows(2)
            .map(|w| {
                let (a, b) = (w[0], w[1]);
                sc.spawn(move || {
                    let part = std::str::from_utf8(&data[a..b.max(a)]).map_err(|_| ())?;
                    let mut o = String::new();
                    for ln in part.split('\n').filter(|l| !l.trim().is_empty()) {
                        let (path, text) = match json::path_text(ln) {
                            Some((p, t)) => (p, t),
                            None => (None, None),
                        };
                        let path = path.unwrap_or_default();
                        match text {
                            None => {
                                o.push_str("error ");
                                o.push_str(&path);
                                o.push('\n');
                            }
                            Some(t) => match judge(&t, profile) {
                                Outcome::Nothing => {}
                                Outcome::Fails => {
                                    o.push_str(&path);
                                    o.push('\n');
                                }
                                Outcome::Miss => {
                                    o.push_str("miss ");
                                    o.push_str(&path);
                                    o.push('\n');
                                }
                                Outcome::Error => {
                                    o.push_str("error ");
                                    o.push_str(&path);
                                    o.push('\n');
                                }
                            },
                        }
                    }
                    Ok(o)
                })
            })
            .collect();
        hs.into_iter().map(|h| h.join().unwrap_or(Err(()))).collect()
    });
    if parts.iter().any(|p| p.is_err()) {
        return error(&format!("{file}: not UTF-8 text"));
    }
    let so = std::io::stdout();
    let mut l = so.lock();
    for p in parts.into_iter().flatten() {
        let _ = l.write_all(p.as_bytes());
    }
    let _ = l.flush();
    ExitCode::SUCCESS
}

fn bench_main(lines: &[&str], profile: Option<usize>) -> ExitCode {
    // the records are decoded first, side by side (not timed: reading the corpus file is not the parse);
    // then each text, one after another, is parsed in full and its answer looked up, and only that is timed
    let threads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1).clamp(1, 8);
    let chunk = lines.len().div_ceil(threads).max(1);
    let texts: Vec<String> = std::thread::scope(|sc| {
        let hs: Vec<_> = lines
            .chunks(chunk)
            .map(|part| {
                sc.spawn(move || {
                    part.iter().map(|ln| json::path_text(ln).and_then(|(_, t)| t).unwrap_or_default()).collect::<Vec<String>>()
                })
            })
            .collect();
        hs.into_iter().flat_map(|h| h.join().unwrap_or_default()).collect()
    });
    let mut us = Vec::with_capacity(texts.len());
    let mut sink = 0usize;
    for t in &texts {
        let t0 = std::time::Instant::now();
        let o = judge(std::hint::black_box(t), profile);
        let dt = t0.elapsed();
        sink += match o {
            Outcome::Fails => 1,
            Outcome::Nothing => 2,
            Outcome::Miss => 3,
            Outcome::Error => 4,
        };
        us.push(dt.as_nanos() as u64);
    }
    std::hint::black_box(sink);
    // microseconds with three decimals, from whole nanoseconds
    let mut o = String::with_capacity(us.len() * 9 + 16);
    o.push_str("{\"us\": [");
    for (i, ns) in us.iter().enumerate() {
        if i > 0 {
            o.push_str(", ");
        }
        let _ = std::fmt::Write::write_fmt(&mut o, format_args!("{}.{:03}", ns / 1000, ns % 1000));
    }
    o.push_str("]}\n");
    out(o.as_bytes());
    std::mem::forget(texts);
    ExitCode::SUCCESS
}
