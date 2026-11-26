//! The cross-check (R17b, kit r17b-gate): the vendor's parser, dogwood_syntax at the rev the harness pins.
//! The hot path parses with the hand-written parser; before the binary gives an inside reading of a file
//! it asks the vendor's grammar too, and a file the vendor's parser rejects is a miss (never an inside
//! reading). The bulk modes (--corpus, --bench) print no reading and do not ask it.

pub fn accepts(text: &str) -> bool {
    dogwood_syntax::parse_document(text).is_ok()
}
