//! The hand-written parser (R17b): a full parse of a policy into the reading R17's table answers, or
//! nothing. It reads exactly R13's same-cap spellings of a shape of the space, one rule head for the
//! action Kamanu::Action::"Pay", any layout and comments:
//!
//!   policy  := "permit" head ( clause | ";" "forbid" head "when" "temporal" "{" count ">" INT "}" ) ";"
//!   clause  := "when" "temporal" "{" count "<=" INT "}" | "unless" "temporal" "{" count ">" INT "}"
//!            | "when" "temporal" "{" INT ">=" count "}"
//!   head    := "(" "principal" "," "action" "==" ACTION "," "resource" ")"
//!   count   := term (("+" | "-") term)*
//!   term    := "sum_within" "(" "a" "," "24h" "," ACTION "::" KIND "{" "input.amount" ":" "a" "}" ")"
//!            | "context.input.amount"
//!
//! with ACTION the path Kamanu::Action::"Pay" written without spaces (as are input.amount and
//! context.input.amount), KIND one of request, response, error, refund, each kind at most once, the
//! current amount at most once and never subtracted, a positive term first. Whitespace is a space, a
//! tab or a line end; `//` starts a comment to the end of its line. Every other node, token or byte
//! outside a comment is outside: no reading, and the caller misses (the Python lint answers). This is a
//! subset of what the table's own reader reads (kamanu.fast.table.read), so a reading here is the
//! table's reading.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Spelling {
    When,
    Unless,
    Left,
    Forbid,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Key {
    Sum(u8), // 0 request, 1 response, 2 error, 3 refund
    Current,
}

pub const SUM_KINDS: [&str; 4] = ["request", "response", "error", "refund"];

#[derive(Clone, Debug)]
pub struct Term {
    pub sign: i8,
    pub s: usize,
    pub e: usize,
    pub key: Key,
    /// The operator before it: (its start, its end); None for the first term.
    pub op: Option<(usize, usize)>,
}

#[derive(Clone, Debug)]
#[allow(dead_code)] // lit, spelling and body: the reading in full, for the shape key and the tests
pub struct Reading {
    /// (request, response, error, refund, current)
    pub code: [i8; 5],
    /// The cap, as the literal says (None when it is too large to hold).
    pub n: Option<u128>,
    pub lit: (usize, usize),
    pub spelling: Spelling,
    /// The comparison, from the first character of its left operand to the last of its right.
    pub cmp: (usize, usize),
    /// The count.
    pub expr: (usize, usize),
    /// The clause's body, between its braces.
    pub body: (usize, usize),
    pub comment_in_body: bool,
    pub terms: Vec<Term>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Tk {
    Id,
    Int,
    Word,
    Pay,
    P(&'static str),
}

#[derive(Clone, Copy, Debug)]
struct Tok {
    k: Tk,
    s: usize,
    e: usize,
}

const PUNCT2: [&str; 4] = ["::", "==", "<=", ">="];
const PUNCT1: [&str; 11] = ["(", ")", "{", "}", ",", ";", ":", ".", "+", "-", "<"];

fn lex(t: &[u8], comments: &mut Vec<(usize, usize)>) -> Option<Vec<Tok>> {
    let mut out = Vec::with_capacity(64);
    let mut i = 0;
    let n = t.len();
    while i < n {
        let c = t[i];
        match c {
            b' ' | b'\t' | b'\n' => i += 1,
            b'/' => {
                if i + 1 < n && t[i + 1] == b'/' {
                    let s = i;
                    while i < n && t[i] != b'\n' {
                        i += 1;
                    }
                    comments.push((s, i));
                } else {
                    return None;
                }
            }
            b'"' => {
                if t[i..].starts_with(b"\"Pay\"") {
                    out.push(Tok { k: Tk::Pay, s: i, e: i + 5 });
                    i += 5;
                } else {
                    return None;
                }
            }
            b'A'..=b'Z' | b'a'..=b'z' | b'_' => {
                let s = i;
                while i < n && (t[i].is_ascii_alphanumeric() || t[i] == b'_') {
                    i += 1;
                }
                out.push(Tok { k: Tk::Id, s, e: i });
            }
            b'0'..=b'9' => {
                let s = i;
                while i < n && t[i].is_ascii_digit() {
                    i += 1;
                }
                let d = i;
                while i < n && (t[i].is_ascii_alphanumeric() || t[i] == b'_') {
                    i += 1;
                }
                out.push(Tok { k: if d == i { Tk::Int } else { Tk::Word }, s, e: i });
            }
            _ => {
                if i + 1 < n {
                    if let Some(p) = PUNCT2.iter().find(|p| t[i..].starts_with(p.as_bytes())) {
                        out.push(Tok { k: Tk::P(p), s: i, e: i + 2 });
                        i += 2;
                        continue;
                    }
                }
                if let Some(p) = PUNCT1.iter().find(|p| p.as_bytes()[0] == c) {
                    out.push(Tok { k: Tk::P(p), s: i, e: i + 1 });
                    i += 1;
                    continue;
                }
                if c == b'>' {
                    out.push(Tok { k: Tk::P(">"), s: i, e: i + 1 });
                    i += 1;
                    continue;
                }
                return None; // any other byte (non-ASCII included) outside a comment
            }
        }
    }
    Some(out)
}

struct P<'a> {
    t: &'a [u8],
    k: &'a [Tok],
    i: usize,
}

impl<'a> P<'a> {
    fn text(&self, j: usize) -> &'a [u8] {
        &self.t[self.k[j].s..self.k[j].e]
    }
    fn id(&mut self, w: &str) -> Option<()> {
        let j = self.i;
        if j < self.k.len() && self.k[j].k == Tk::Id && self.text(j) == w.as_bytes() {
            self.i += 1;
            Some(())
        } else {
            None
        }
    }
    fn p(&mut self, w: &str) -> Option<(usize, usize)> {
        let j = self.i;
        if j < self.k.len() && self.k[j].k == Tk::P(PUNCT_NAME(w)) {
            self.i += 1;
            Some((self.k[j].s, self.k[j].e))
        } else {
            None
        }
    }
    /// The next token sits right after the previous one (no space between).
    fn adj(&self) -> bool {
        self.i > 0 && self.i < self.k.len() && self.k[self.i].s == self.k[self.i - 1].e
    }
    fn adj_id(&mut self, w: &str) -> Option<()> {
        if !self.adj() {
            return None;
        }
        self.id(w)
    }
    fn adj_p(&mut self, w: &str) -> Option<()> {
        if !self.adj() {
            return None;
        }
        self.p(w).map(|_| ())
    }
    /// Kamanu::Action::"Pay", no spaces.
    fn action(&mut self) -> Option<()> {
        self.id("Kamanu")?;
        self.adj_p("::")?;
        self.adj_id("Action")?;
        self.adj_p("::")?;
        if !self.adj() || self.k[self.i].k != Tk::Pay {
            return None;
        }
        self.i += 1;
        Some(())
    }
    fn head(&mut self) -> Option<()> {
        self.p("(")?;
        self.id("principal")?;
        self.p(",")?;
        self.id("action")?;
        self.p("==")?;
        self.action()?;
        self.p(",")?;
        self.id("resource")?;
        self.p(")")?;
        Some(())
    }
    fn term(&mut self) -> Option<(Key, usize, usize)> {
        let s = self.k.get(self.i)?.s;
        if self.id("context").is_some() {
            self.adj_p(".")?;
            self.adj_id("input")?;
            self.adj_p(".")?;
            self.adj_id("amount")?;
            return Some((Key::Current, s, self.k[self.i - 1].e));
        }
        self.id("sum_within")?;
        self.p("(")?;
        self.id("a")?;
        self.p(",")?;
        let j = self.i;
        if j >= self.k.len() || self.k[j].k != Tk::Word || self.text(j) != b"24h" {
            return None;
        }
        self.i += 1;
        self.p(",")?;
        self.action()?;
        self.adj_p("::")?;
        if !self.adj() {
            return None;
        }
        let j = self.i;
        if j >= self.k.len() || self.k[j].k != Tk::Id {
            return None;
        }
        let kind = SUM_KINDS.iter().position(|w| w.as_bytes() == self.text(j))? as u8;
        self.i += 1;
        self.p("{")?;
        self.id("input")?;
        self.adj_p(".")?;
        self.adj_id("amount")?;
        self.p(":")?;
        self.id("a")?;
        self.p("}")?;
        let (_, e) = self.p(")")?;
        Some((Key::Sum(kind), s, e))
    }
    fn count(&mut self) -> Option<Vec<Term>> {
        let mut terms = Vec::new();
        let (key, s, e) = self.term()?;
        terms.push(Term { sign: 1, s, e, key, op: None });
        loop {
            let sign = if let Some(op) = self.p("+") {
                (1, op)
            } else if let Some(op) = self.p("-") {
                (-1, op)
            } else {
                break;
            };
            let (key, s, e) = self.term()?;
            terms.push(Term { sign: sign.0, s, e, key, op: Some(sign.1) });
        }
        Some(terms)
    }
    fn int(&mut self) -> Option<(usize, usize)> {
        let j = self.i;
        if j < self.k.len() && self.k[j].k == Tk::Int {
            self.i += 1;
            Some((self.k[j].s, self.k[j].e))
        } else {
            None
        }
    }
}

#[allow(non_snake_case)]
fn PUNCT_NAME(w: &str) -> &'static str {
    for p in PUNCT2.iter().chain(PUNCT1.iter()) {
        if *p == w {
            return p;
        }
    }
    if w == ">" {
        return ">";
    }
    ""
}

/// The policy's reading, or None (outside: a miss).
pub fn read(text: &str) -> Option<Reading> {
    let t = text.as_bytes();
    let mut comments = Vec::new();
    let toks = lex(t, &mut comments)?;
    let mut p = P { t, k: &toks, i: 0 };
    p.id("permit")?;
    p.head()?;
    let spelling;
    let terms;
    let lit;
    let body0;
    let body1;
    if p.p(";").is_some() {
        p.id("forbid")?;
        p.head()?;
        p.id("when")?;
        p.id("temporal")?;
        body0 = p.p("{")?.1;
        terms = p.count()?;
        p.p(">")?;
        lit = p.int()?;
        body1 = p.p("}")?.0;
        spelling = Spelling::Forbid;
    } else if p.id("unless").is_some() {
        p.id("temporal")?;
        body0 = p.p("{")?.1;
        terms = p.count()?;
        p.p(">")?;
        lit = p.int()?;
        body1 = p.p("}")?.0;
        spelling = Spelling::Unless;
    } else {
        p.id("when")?;
        p.id("temporal")?;
        body0 = p.p("{")?.1;
        if let Some(l) = p.int() {
            p.p(">=")?;
            terms = p.count()?;
            lit = l;
            spelling = Spelling::Left;
        } else {
            terms = p.count()?;
            p.p("<=")?;
            lit = p.int()?;
            spelling = Spelling::When;
        }
        body1 = p.p("}")?.0;
    }
    p.p(";")?;
    if p.i != toks.len() {
        return None;
    }
    // the shape: each kind at most once, the current amount at most once and added, a positive term
    let mut code = [0i8; 5];
    for (i, tm) in terms.iter().enumerate() {
        let slot = match tm.key {
            Key::Sum(k) => k as usize,
            Key::Current => 4,
        };
        if code[slot] != 0 || (i == 0 && tm.sign < 0) {
            return None;
        }
        code[slot] = tm.sign;
    }
    if code[4] < 0 || !code.iter().any(|&x| x > 0) {
        return None;
    }
    let digits = &text[lit.0..lit.1];
    let trimmed = digits.trim_start_matches('0');
    let n = if trimmed.len() > 30 { None } else { Some(if trimmed.is_empty() { 0 } else { trimmed.parse::<u128>().ok()? }) };
    let expr = (terms[0].s, terms[terms.len() - 1].e);
    let cmp = if spelling == Spelling::Left { (lit.0, expr.1) } else { (expr.0, lit.1) };
    let comment_in_body = comments.iter().any(|&(s, _)| s >= body0 && s < body1);
    Some(Reading { code, n, lit, spelling, cmp, expr, body: (body0, body1), comment_in_body, terms })
}

/// 1-based (line, column) of a byte offset (the text before a comparison on its line is ASCII: a comment
/// runs to the end of its line, so it never precedes one, and so columns count characters).
pub fn position(text: &str, off: usize) -> (usize, usize) {
    let b = &text.as_bytes()[..off];
    let line = b.iter().filter(|&&c| c == b'\n').count() + 1;
    let start = b.iter().rposition(|&c| c == b'\n').map(|x| x + 1).unwrap_or(0);
    (line, text[start..off].chars().count() + 1)
}

/// The deepest nesting of (, [ and { outside comments and strings (kamanu.fast.nesting: a string is
/// `"` up to its closing quote, a backslash escaping the next character, or up to a line end).
pub fn nesting(text: &str) -> usize {
    let t = text.as_bytes();
    let (mut i, mut depth, mut most) = (0usize, 0usize, 0usize);
    while i < t.len() {
        let c = t[i];
        if c == b'"' {
            i += 1;
            loop {
                if i >= t.len() {
                    break;
                }
                match t[i] {
                    b'"' => {
                        i += 1;
                        break;
                    }
                    b'\n' => break,
                    b'\\' => {
                        if i + 1 < t.len() && t[i + 1] != b'\n' {
                            i += 2;
                        } else {
                            break;
                        }
                    }
                    _ => i += 1,
                }
            }
            continue;
        }
        if c == b'/' && i + 1 < t.len() && t[i + 1] == b'/' {
            while i < t.len() && t[i] != b'\n' {
                i += 1;
            }
            continue;
        }
        match c {
            b'(' | b'[' | b'{' => {
                depth += 1;
                if depth > most {
                    most = depth;
                }
            }
            b')' | b']' | b'}' => depth = depth.saturating_sub(1),
            _ => {}
        }
        i += 1;
    }
    most
}

#[cfg(test)]
mod tests {
    use super::*;

    const T: &str = "sum_within(a, 24h, Kamanu::Action::\"Pay\"::request{ input.amount: a })";

    #[test]
    fn reads_the_spellings() {
        let h = "permit (\n    principal,\n    action == Kamanu::Action::\"Pay\",\n    resource\n)";
        let when = format!("// c\n{h}\nwhen temporal {{ {T} <= 100 }};\n");
        let r = read(&when).unwrap();
        assert_eq!(r.code, [1, 0, 0, 0, 0]);
        assert_eq!(r.n, Some(100));
        assert_eq!(r.spelling, Spelling::When);
        let left = format!("{h}\nwhen temporal {{ 100 >= {T} + context.input.amount }};");
        assert_eq!(read(&left).unwrap().code, [1, 0, 0, 0, 1]);
        let glued = format!("{h}\nwhentemporal {{ {T} <= 100 }};");
        assert!(read(&glued).is_none());
        let neg_first = format!("{h}\nwhen temporal {{ context.input.amount - {T} <= 100 }};");
        assert_eq!(read(&neg_first).unwrap().code, [-1, 0, 0, 0, 1]);
        let neg_cur = format!("{h}\nwhen temporal {{ {T} - context.input.amount <= 100 }};");
        assert!(read(&neg_cur).is_none());
    }

    #[test]
    fn nesting_skips_strings_and_comments() {
        assert_eq!(nesting("((\"(((\" // (((\n)"), 2);
    }
}
