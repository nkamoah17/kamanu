//! The fix a failing verdict's finding carries (kamanu.fast.table.fix_of: R15's repair shape, emitted as
//! the smallest edit of the policy's own text by kamanu.ladder.emit_dogwood.emit, as the new text of the
//! comparison). On the parser's readings the edit is emit's first way: the count's terms removed,
//! re-signed or added, everything else the input's. Where the clause holds a comment emit rewrites the
//! clause's body and drops it, and the comparison's new text cannot be cut out of that: no fix. A
//! comparison that spans lines has none either.

use crate::json::V;
use crate::parse::{Key, Reading, SUM_KINDS};

/// emit_dogwood's KEYS: the kinds in the kernel's order, then the current amount.
const KEYS: [&str; 7] = ["request", "deny", "response", "error", "refund", "confirm", "current"];

#[derive(Clone, Debug, PartialEq)]
struct T {
    sign: i8,
    text: String,
    key: String,
    sep: Option<(String, String)>,
}

fn key_of(k: Key) -> String {
    match k {
        Key::Sum(i) => SUM_KINDS[i as usize].to_string(),
        Key::Current => "current".to_string(),
    }
}

/// emit_dogwood._swap_kind: the first `Action::"..."::KIND {` with its kind replaced.
fn swap_kind(term: &str, kind: &str) -> String {
    let b = term.as_bytes();
    let pat = b"Action::\"";
    let mut i = 0;
    while i + pat.len() <= b.len() {
        if &b[i..i + pat.len()] == pat {
            let mut j = i + pat.len();
            while j < b.len() && b[j] != b'"' {
                j += 1;
            }
            if j + 2 < b.len() && b[j] == b'"' && b[j + 1] == b':' && b[j + 2] == b':' {
                let ks = j + 3;
                let mut ke = ks;
                while ke < b.len() && (b[ke].is_ascii_alphanumeric() || b[ke] == b'_') {
                    ke += 1;
                }
                let mut w = ke;
                while w < b.len() && (b[w] as char).is_ascii_whitespace() {
                    w += 1;
                }
                if ke > ks && w < b.len() && b[w] == b'{' {
                    return format!("{}{}{}", &term[..ks], kind, &term[ke..]);
                }
            }
        }
        i += 1;
    }
    term.to_string()
}

fn remove_first_equal(terms: &mut Vec<T>, t: &T) {
    if let Some(i) = terms.iter().position(|x| x == t) {
        terms.remove(i);
    }
}

/// emit_dogwood._edit_side on the count's terms, rendered (the side's lead and trail aside).
fn edit(text: &str, r: &Reading, target: &[i64; 7]) -> Option<String> {
    let mut terms: Vec<T> = r
        .terms
        .iter()
        .enumerate()
        .map(|(i, tm)| T {
            sign: tm.sign,
            text: text[tm.s..tm.e].to_string(),
            key: key_of(tm.key),
            sep: tm.op.map(|(os, oe)| (text[r.terms[i - 1].e..os].to_string(), text[oe..tm.s].to_string())),
        })
        .collect();
    let template = terms.iter().find(|t| t.key != "current").map(|t| t.text.clone());
    let sep = terms
        .iter()
        .rev()
        .find_map(|t| t.sep.clone())
        .unwrap_or((" ".to_string(), " ".to_string()));
    let new = |key: &str| -> String {
        if key == "current" {
            "context.input.amount".to_string()
        } else if let Some(t) = &template {
            swap_kind(t, key)
        } else {
            format!("sum_within(a, 24h, Kamanu::Action::\"Pay\"::{key}{{ input.amount: a }})")
        }
    };
    for (key, &want) in KEYS.iter().zip(target.iter()) {
        let mine: Vec<T> = terms.iter().filter(|t| t.key == *key).cloned().collect();
        let have: i64 = mine.iter().map(|t| t.sign as i64).sum();
        if have == want {
            continue;
        }
        let uniform = !mine.is_empty() && mine.iter().all(|t| t.sign == mine[0].sign);
        if uniform && want == -have {
            for t in terms.iter_mut().filter(|t| t.key == *key) {
                t.sign = -t.sign;
            }
            continue;
        }
        if uniform && want != 0 && (want > 0) == (have > 0) {
            if want.abs() < have.abs() {
                for t in &mine[want.unsigned_abs() as usize..] {
                    remove_first_equal(&mut terms, t);
                }
            } else {
                for _ in 0..(want.abs() - have.abs()) {
                    terms.push(T { sign: mine[0].sign, text: mine[0].text.clone(), key: mine[0].key.clone(), sep: Some(sep.clone()) });
                }
            }
            continue;
        }
        for t in &mine {
            remove_first_equal(&mut terms, t);
        }
        let add: Vec<T> = (0..want.abs())
            .map(|_| T { sign: if want > 0 { 1 } else { -1 }, text: new(key), key: key.to_string(), sep: Some(sep.clone()) })
            .collect();
        if want > 0 {
            let at = terms.iter().rposition(|t| t.sign > 0).map(|i| i + 1).unwrap_or(0);
            for (k, t) in add.into_iter().enumerate() {
                terms.insert(at + k, t);
            }
        } else {
            terms.extend(add);
        }
    }
    let first = terms.iter().position(|t| t.sign > 0)?;
    if first > 0 {
        let t = terms.remove(first);
        terms.insert(0, t);
    }
    let mut out = String::new();
    for (i, t) in terms.iter_mut().enumerate() {
        if i > 0 {
            if t.sep.is_none() {
                t.sep = Some(sep.clone());
            }
            let (a, b) = t.sep.as_ref().unwrap();
            out.push_str(a);
            out.push(if t.sign > 0 { '+' } else { '-' });
            out.push_str(b);
        }
        out.push_str(&t.text);
    }
    Some(out)
}

/// The fix object ({"file", "start_line", "start_column", "end_line", "end_column", "old", "new"}) or None.
/// repair: the entry's repair shape ({"coefficients": {kind: weight}, "current": weight}) or null.
pub fn fix_of(text: &str, path: Option<&str>, r: &Reading, repair: &V) -> V {
    if matches!(repair, V::Null) {
        return V::Null;
    }
    let (a, b) = r.cmp;
    if text[a..b].contains('\n') || r.comment_in_body {
        return V::Null;
    }
    let co = repair.get("coefficients");
    let mut target = [0i64; 7];
    for (i, k) in KEYS.iter().enumerate() {
        target[i] = if *k == "current" {
            repair.get("current").and_then(|v| v.as_int()).unwrap_or(0) as i64
        } else {
            co.and_then(|c| c.get(k)).and_then(|v| v.as_int()).unwrap_or(0) as i64
        };
    }
    let Some(terms) = edit(text, r, &target) else { return V::Null };
    let (p0, p1) = r.expr;
    let new = format!("{}{}{}", &text[a..p0], terms, &text[p1..b]);
    let old = &text[a..b];
    if new == old || (new.trim().contains('\n') && !old.contains('\n')) {
        return V::Null;
    }
    let (l1, c1) = crate::parse::position(text, a);
    let (l2, c2) = crate::parse::position(text, b);
    V::Map(vec![
        ("file".into(), path.map(|p| V::Str(p.to_string().into())).unwrap_or(V::Null)),
        ("start_line".into(), V::Int(l1 as i128)),
        ("start_column".into(), V::Int(c1 as i128)),
        ("end_line".into(), V::Int(l2 as i128)),
        ("end_column".into(), V::Int(c2 as i128)),
        ("old".into(), V::Str(old.to_string().into())),
        ("new".into(), V::Str(new.into())),
    ])
}
