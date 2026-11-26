//! A JSON value with its keys in order, a reader, and the writer Python's `json.dumps` is: `indent=N`,
//! `ensure_ascii=True`, separators `", "` / `": "` (with an indent, items end their line).

/// A string borrowed from the 'static text it was read from where it has no escape.
pub type S = std::borrow::Cow<'static, str>;

#[derive(Clone, Debug, PartialEq)]
pub enum V {
    Null,
    Bool(bool),
    /// A number as the file writes it (Python wrote the table, so it is Python's repr already).
    Num(S),
    /// A number computed here.
    Int(i128),
    Str(S),
    List(Vec<V>),
    Map(Vec<(S, V)>),
}

impl V {
    pub fn get(&self, k: &str) -> Option<&V> {
        match self {
            V::Map(m) => m.iter().rev().find(|(kk, _)| kk == k).map(|(_, v)| v),
            _ => None,
        }
    }
    /// Python's `d.get(k)` truthiness.
    pub fn truthy(&self) -> bool {
        match self {
            V::Null => false,
            V::Bool(b) => *b,
            V::Num(s) => !s.chars().all(|c| c == '0' || c == '.' || c == '-' || c == 'e' || c == 'E' || c == '+'),
            V::Int(i) => *i != 0,
            V::Str(s) => !s.is_empty(),
            V::List(l) => !l.is_empty(),
            V::Map(m) => !m.is_empty(),
        }
    }
    pub fn as_str(&self) -> Option<&str> {
        match self {
            V::Str(s) => Some(s),
            _ => None,
        }
    }
    pub fn as_list(&self) -> &[V] {
        match self {
            V::List(l) => l,
            _ => &[],
        }
    }
    pub fn as_int(&self) -> Option<i128> {
        match self {
            V::Int(i) => Some(*i),
            V::Num(s) => s.parse().ok(),
            V::Bool(b) => Some(*b as i128),
            _ => None,
        }
    }
}

/// Python's `str(x)` for the values lint prints with an f-string.
pub fn py_str(v: &V) -> String {
    match v {
        V::Null => "None".into(),
        V::Bool(true) => "True".into(),
        V::Bool(false) => "False".into(),
        V::Num(s) => s.to_string(),
        V::Int(i) => i.to_string(),
        V::Str(s) => s.to_string(),
        V::List(_) | V::Map(_) => py_repr(v),
    }
}

fn py_repr(v: &V) -> String {
    match v {
        V::Str(s) => {
            let q = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
            let mut out = String::new();
            out.push(q);
            for c in s.chars() {
                match c {
                    '\\' => out.push_str("\\\\"),
                    '\n' => out.push_str("\\n"),
                    '\r' => out.push_str("\\r"),
                    '\t' => out.push_str("\\t"),
                    c if c == q => {
                        out.push('\\');
                        out.push(c)
                    }
                    c => out.push(c),
                }
            }
            out.push(q);
            out
        }
        V::List(l) => format!("[{}]", l.iter().map(py_repr).collect::<Vec<_>>().join(", ")),
        V::Map(m) => format!(
            "{{{}}}",
            m.iter().map(|(k, x)| format!("{}: {}", py_repr(&V::Str(k.clone())), py_repr(x))).collect::<Vec<_>>().join(", ")
        ),
        other => py_str(other),
    }
}

// ---------------------------------------------------------------- reading
pub struct Reader<'a> {
    b: &'a [u8],
    _p: std::marker::PhantomData<&'a ()>,
    i: usize,
}

pub fn parse(s: &'static str) -> Result<V, String> {
    let mut r = Reader { b: s.as_bytes(), i: 0, _p: std::marker::PhantomData };
    r.ws();
    let v = r.value(0)?;
    r.ws();
    if r.i != r.b.len() {
        return Err(format!("trailing data at {}", r.i));
    }
    Ok(v)
}

impl<'a> Reader<'a> {
    fn ws(&mut self) {
        while self.i < self.b.len() && matches!(self.b[self.i], b' ' | b'\t' | b'\n' | b'\r') {
            self.i += 1;
        }
    }
}

impl Reader<'static> {
    fn value(&mut self, depth: usize) -> Result<V, String> {
        if depth > 512 {
            return Err("nested too deep".into());
        }
        match self.b.get(self.i) {
            None => Err("end of input".into()),
            Some(b'{') => {
                self.i += 1;
                let mut m = Vec::new();
                self.ws();
                if self.b.get(self.i) == Some(&b'}') {
                    self.i += 1;
                    return Ok(V::Map(m));
                }
                loop {
                    self.ws();
                    if self.b.get(self.i) != Some(&b'"') {
                        return Err("a key that is not a string".into());
                    }
                    let k = self.string()?;
                    self.ws();
                    if self.b.get(self.i) != Some(&b':') {
                        return Err("no colon".into());
                    }
                    self.i += 1;
                    self.ws();
                    let v = self.value(depth + 1)?;
                    m.push((k, v));
                    self.ws();
                    match self.b.get(self.i) {
                        Some(b',') => self.i += 1,
                        Some(b'}') => {
                            self.i += 1;
                            return Ok(V::Map(m));
                        }
                        _ => return Err("an object not closed".into()),
                    }
                }
            }
            Some(b'[') => {
                self.i += 1;
                let mut l = Vec::new();
                self.ws();
                if self.b.get(self.i) == Some(&b']') {
                    self.i += 1;
                    return Ok(V::List(l));
                }
                loop {
                    self.ws();
                    l.push(self.value(depth + 1)?);
                    self.ws();
                    match self.b.get(self.i) {
                        Some(b',') => self.i += 1,
                        Some(b']') => {
                            self.i += 1;
                            return Ok(V::List(l));
                        }
                        _ => return Err("a list not closed".into()),
                    }
                }
            }
            Some(b'"') => Ok(V::Str(self.string()?)),
            Some(b't') => self.word("true", V::Bool(true)),
            Some(b'f') => self.word("false", V::Bool(false)),
            Some(b'n') => self.word("null", V::Null),
            Some(c) if *c == b'-' || c.is_ascii_digit() => {
                let s = self.i;
                if self.b[self.i] == b'-' {
                    self.i += 1;
                }
                let d0 = self.i;
                while self.i < self.b.len() && self.b[self.i].is_ascii_digit() {
                    self.i += 1;
                }
                if self.i == d0 || (self.b[d0] == b'0' && self.i - d0 > 1) {
                    return Err("a number".into());
                }
                if self.b.get(self.i) == Some(&b'.') {
                    self.i += 1;
                    let f0 = self.i;
                    while self.i < self.b.len() && self.b[self.i].is_ascii_digit() {
                        self.i += 1;
                    }
                    if self.i == f0 {
                        return Err("a number".into());
                    }
                }
                if matches!(self.b.get(self.i), Some(b'e') | Some(b'E')) {
                    self.i += 1;
                    if matches!(self.b.get(self.i), Some(b'+') | Some(b'-')) {
                        self.i += 1;
                    }
                    let e0 = self.i;
                    while self.i < self.b.len() && self.b[self.i].is_ascii_digit() {
                        self.i += 1;
                    }
                    if self.i == e0 {
                        return Err("a number".into());
                    }
                }
                Ok(V::Num(S::Borrowed(std::str::from_utf8(&self.b[s..self.i]).map_err(|_| "a number")?)))
            }
            Some(_) => Err(format!("unexpected byte at {}", self.i)),
        }
    }
}

impl<'a> Reader<'a> {
    fn word(&mut self, w: &str, v: V) -> Result<V, String> {
        if self.b[self.i..].starts_with(w.as_bytes()) {
            self.i += w.len();
            Ok(v)
        } else {
            Err("a word".into())
        }
    }
    fn hex4(&mut self) -> Result<u32, String> {
        if self.i + 4 > self.b.len() {
            return Err("a short \\u escape".into());
        }
        let s = std::str::from_utf8(&self.b[self.i..self.i + 4]).map_err(|_| "a \\u escape")?;
        let v = u32::from_str_radix(s, 16).map_err(|_| "a \\u escape")?;
        self.i += 4;
        Ok(v)
    }
    pub fn string(&mut self) -> Result<std::borrow::Cow<'a, str>, String> {
        self.i += 1;
        // the common case: no escape before the closing quote, so the string is a slice of the text
        let s0 = self.i;
        let mut j = self.i;
        while j < self.b.len() && self.b[j] != b'"' && self.b[j] != b'\\' && self.b[j] >= 0x20 {
            j += 1;
        }
        if self.b.get(j) == Some(&b'"') {
            self.i = j + 1;
            return Ok(std::borrow::Cow::Borrowed(std::str::from_utf8(&self.b[s0..j]).map_err(|_| "not UTF-8")?));
        }
        let mut out = String::new();
        loop {
            let s = self.i;
            while self.i < self.b.len() && self.b[self.i] != b'"' && self.b[self.i] != b'\\' && self.b[self.i] >= 0x20 {
                self.i += 1;
            }
            out.push_str(std::str::from_utf8(&self.b[s..self.i]).map_err(|_| "not UTF-8")?);
            match self.b.get(self.i) {
                Some(b'"') => {
                    self.i += 1;
                    return Ok(std::borrow::Cow::Owned(out));
                }
                Some(b'\\') => {
                    self.i += 1;
                    let c = *self.b.get(self.i).ok_or("an escape at the end")?;
                    self.i += 1;
                    match c {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{8}'),
                        b'f' => out.push('\u{c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let mut cp = self.hex4()?;
                            if (0xD800..0xDC00).contains(&cp) && self.b[self.i..].starts_with(b"\\u") {
                                let save = self.i;
                                self.i += 2;
                                let lo = self.hex4()?;
                                if (0xDC00..0xE000).contains(&lo) {
                                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                                } else {
                                    self.i = save;
                                }
                            }
                            // A lone surrogate (Python reads it) cannot be a Rust char: the caller misses.
                            out.push(char::from_u32(cp).ok_or("a lone surrogate")?);
                        }
                        _ => return Err("an unknown escape".into()),
                    }
                }
                _ => return Err("a string not closed".into()),
            }
        }
    }
}

impl<'a> Reader<'a> {
    /// Steps over one value, checking it as value() would, building nothing.
    fn skip_value(&mut self, depth: usize) -> Result<(), String> {
        if depth > 512 {
            return Err("nested too deep".into());
        }
        match self.b.get(self.i) {
            None => Err("end of input".into()),
            Some(&open @ (b'{' | b'[')) => {
                let close = if open == b'{' { b'}' } else { b']' };
                self.i += 1;
                self.ws();
                if self.b.get(self.i) == Some(&close) {
                    self.i += 1;
                    return Ok(());
                }
                loop {
                    self.ws();
                    if open == b'{' {
                        if self.b.get(self.i) != Some(&b'"') {
                            return Err("a key that is not a string".into());
                        }
                        self.string()?;
                        self.ws();
                        if self.b.get(self.i) != Some(&b':') {
                            return Err("no colon".into());
                        }
                        self.i += 1;
                        self.ws();
                    }
                    self.skip_value(depth + 1)?;
                    self.ws();
                    match self.b.get(self.i) {
                        Some(b',') => self.i += 1,
                        Some(&c) if c == close => {
                            self.i += 1;
                            return Ok(());
                        }
                        _ => return Err("a container not closed".into()),
                    }
                }
            }
            Some(b'"') => self.string().map(|_| ()),
            Some(b't') => self.word("true", V::Null).map(|_| ()),
            Some(b'f') => self.word("false", V::Null).map(|_| ()),
            Some(b'n') => self.word("null", V::Null).map(|_| ()),
            Some(c) if *c == b'-' || c.is_ascii_digit() => {
                // the number's grammar, as value() checks it
                if self.b[self.i] == b'-' {
                    self.i += 1;
                }
                let d0 = self.i;
                while self.i < self.b.len() && self.b[self.i].is_ascii_digit() {
                    self.i += 1;
                }
                if self.i == d0 || (self.b[d0] == b'0' && self.i - d0 > 1) {
                    return Err("a number".into());
                }
                if self.b.get(self.i) == Some(&b'.') {
                    self.i += 1;
                    let f0 = self.i;
                    while self.i < self.b.len() && self.b[self.i].is_ascii_digit() {
                        self.i += 1;
                    }
                    if self.i == f0 {
                        return Err("a number".into());
                    }
                }
                if matches!(self.b.get(self.i), Some(b'e') | Some(b'E')) {
                    self.i += 1;
                    if matches!(self.b.get(self.i), Some(b'+') | Some(b'-')) {
                        self.i += 1;
                    }
                    let e0 = self.i;
                    while self.i < self.b.len() && self.b[self.i].is_ascii_digit() {
                        self.i += 1;
                    }
                    if self.i == e0 {
                        return Err("a number".into());
                    }
                }
                Ok(())
            }
            Some(_) => Err(format!("unexpected byte at {}", self.i)),
        }
    }
}

// ---------------------------------------------------------------- writing
pub fn escape_into(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            ' '..='~' => out.push(c),
            c => {
                let mut buf = [0u16; 2];
                for u in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{:04x}", u));
                }
            }
        }
    }
    out.push('"');
}

/// `json.dumps(v, indent=indent)` with the value starting at nesting `level` (its closing bracket indented
/// `level` times; the first line not indented).
pub fn dump_into(out: &mut String, v: &V, indent: usize, level: usize) {
    match v {
        V::Null => out.push_str("null"),
        V::Bool(true) => out.push_str("true"),
        V::Bool(false) => out.push_str("false"),
        V::Num(s) => out.push_str(s),
        V::Int(i) => out.push_str(&i.to_string()),
        V::Str(s) => escape_into(out, s),
        V::List(l) => {
            if l.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push('[');
            for (i, x) in l.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                out.push('\n');
                pad(out, indent * (level + 1));
                dump_into(out, x, indent, level + 1);
            }
            out.push('\n');
            pad(out, indent * level);
            out.push(']');
        }
        V::Map(m) => {
            if m.is_empty() {
                out.push_str("{}");
                return;
            }
            out.push('{');
            for (i, (k, x)) in m.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                out.push('\n');
                pad(out, indent * (level + 1));
                escape_into(out, k);
                out.push_str(": ");
                dump_into(out, x, indent, level + 1);
            }
            out.push('\n');
            pad(out, indent * level);
            out.push('}');
        }
    }
}

fn pad(out: &mut String, n: usize) {
    for _ in 0..n {
        out.push(' ');
    }
}

/// The "path" and "text" of one corpus line ({"path": ..., "text": ..., other keys ignored}), read without
/// building the other values. None when the line is not such an object.
pub fn path_text(line: &str) -> Option<(Option<String>, Option<String>)> {
    let mut r = Reader { b: line.as_bytes(), i: 0, _p: std::marker::PhantomData };
    r.ws();
    if r.b.get(r.i) != Some(&b'{') {
        return None;
    }
    r.i += 1;
    let (mut path, mut text) = (None, None);
    r.ws();
    if r.b.get(r.i) == Some(&b'}') {
        return Some((None, None));
    }
    loop {
        r.ws();
        if r.b.get(r.i) != Some(&b'"') {
            return None;
        }
        let k = r.string().ok()?;
        r.ws();
        if r.b.get(r.i) != Some(&b':') {
            return None;
        }
        r.i += 1;
        r.ws();
        if (k == "path" || k == "text") && r.b.get(r.i) == Some(&b'"') {
            let s = r.string().ok()?.into_owned();
            if k == "path" {
                path = Some(s);
            } else {
                text = Some(s);
            }
        } else {
            let v = r.skip_value(0).ok()?;
            if k == "path" {
                path = None;
                let _ = v;
            } else if k == "text" {
                text = None;
            }
        }
        r.ws();
        match r.b.get(r.i) {
            Some(b',') => r.i += 1,
            Some(b'}') => return Some((path, text)),
            _ => return None,
        }
    }
}
