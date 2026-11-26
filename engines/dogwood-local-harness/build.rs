//! Reads the library's version and git rev from Cargo.lock, so the harness's "version"
//! reply names exactly what it was built with.
use std::fs;

fn main() {
    println!("cargo:rerun-if-changed=Cargo.lock");
    let lock = fs::read_to_string("Cargo.lock").expect("Cargo.lock");
    let mut version = String::new();
    let mut source = String::new();
    for block in lock.split("[[package]]") {
        if block.lines().any(|l| l.trim() == "name = \"dogwood-local-engine\"") {
            for l in block.lines() {
                let l = l.trim();
                if let Some(v) = l.strip_prefix("version = \"") {
                    version = v.trim_end_matches('"').to_string();
                }
                if let Some(s) = l.strip_prefix("source = \"") {
                    source = s.trim_end_matches('"').to_string();
                }
            }
        }
    }
    let rev = source.rsplit('#').next().unwrap_or("").to_string();
    let git = source
        .trim_start_matches("git+")
        .split(['?', '#'])
        .next()
        .unwrap_or("")
        .to_string();
    assert!(
        !version.is_empty() && rev.len() == 40,
        "Cargo.lock does not pin dogwood-local-engine at a git rev"
    );
    println!("cargo:rustc-env=DLE_VERSION={version}");
    println!("cargo:rustc-env=DLE_REV={rev}");
    println!("cargo:rustc-env=DLE_GIT={git}");
}
