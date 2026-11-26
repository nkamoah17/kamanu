// Connector query tenant_sinks: data accesses whose results reach a tool's answer without the session's identity.
//
// One record for each pair of a tool and a data access it reaches whose result reaches the tool's
// answer and whose identity is not session, at the access, with the subject {"tool", "kind",
// "identity", "path"}: the path goes from the source of the identity (for none, the handler) through
// each line where a call takes it into the next function, to the access. See lib/connector.sc.
//> using file lib/connector.sc

// What a fact may be established by: a shape whose objects the query can name, and what must be true for
// the fact to hold. The same table is IDENTITY in kamanu/evidence/premises.py, which reads no file.
val MANIFEST: Map[String, List[String]] = Map(
  "sqlite3_literal_statement" -> List(
    "The name sqlite3 is the standard library's module at run time, and the statement runs on the connection the file opened with it",
    "The SDK fills the parameter annotated Context from the transport and never from the arguments of the call",
    "Each call on the way to the access runs the one function the graph resolves it to",
    "Each bound value is compared with the column that names the tenant or the record, and the statement reads no other tenant's rows"))

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  new Connector(cpg).write(out, sinks = true, MANIFEST)
}
