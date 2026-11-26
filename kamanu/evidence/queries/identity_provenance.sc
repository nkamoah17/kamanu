// Connector query identity_provenance: where the identity that scopes a data access comes from.
//
// One record for each pair of a tool and a data access it reaches, at the access, with the subject
// {"tool", "kind", "identity", "source"}: kind is database, file or request, identity is session (the
// authenticated transport's), argument (the model's), constant or none, and source the line it comes
// from. A name decides nothing: what the caller passes does. See lib/connector.sc for the method.
//
// A fact of this query is no premise: it says argument where it sees one, and does not fall silent.
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
  new Connector(cpg).write(out, sinks = false, MANIFEST)
}
