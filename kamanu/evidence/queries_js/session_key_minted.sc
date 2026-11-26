// Premise query session_key_minted (JavaScript and TypeScript): Every session key is minted on the server: no value of the caller's reaches one.
//
// A site is a session key given a value (a variable, property, object key or parameter whose name
// has session and one of key, id or token in it), and a value read from the caller under a session
// key name (req.headers["mcp-session-id"], req.get("session"), req.body.sessionId). Good when each
// value given is randomUUID or randomBytes of node:crypto (or crypto.randomUUID), a method of its
// answer, or a constant joined to one, on every path. Witness: the line of the minting call.
//
// A fact asserts the premise of the whole repository: it is written only when there is a site and
// every site is good. See lib/premises_js.sc.
//> using file lib/premises_js.sc

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  PremisesJs.report("session_key_minted", out, PremisesJs.sessionKeyMinted(cpg))
}
