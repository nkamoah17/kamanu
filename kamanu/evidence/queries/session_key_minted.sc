// Premise query session_key_minted: The session key is minted by the server, never taken from the caller.
//
// A site is a session key given a value: an assignment to a name, attribute or string key with
// session and key, id or token in it, such a keyword argument, or such a parameter (always bad);
// and, whatever it is assigned to, a read x[...] or x.get(...) of the caller's value under a string
// key with session in it (always bad). Good when every value that can reach a session key is made
// of uuid.uuid4 or secrets calls, string constants, + and str(), through locals assigned only so.
// Witness: each minting line.
//
// A fact asserts the premise of the whole repository: it is written only when there is a site and
// every site is good. See lib/premises.sc.
//> using file lib/premises.sc

// What may establish the premise: a construct a witness can match, and what must be true for that
// match to imply the premise. A witness of any other shape is a pattern and no more. The same
// table is MANIFEST in kamanu/evidence/premises.py, which reads no file.
val MANIFEST: Map[String, List[String]] = Map(
  "library_mint_in_local" -> List(
    "The names secrets and uuid are the standard library's modules at run time",
    "The caller cannot predict or set what the operating system's random source returns",
    "Nothing replaces the key between the line that mints it and the engine that counts over it"))

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  Premises.report("session_key_minted", out, Premises.sessionKeyMinted(cpg), MANIFEST)
}
