// Premise query status_before_retry: An error handler queries status before a retry or a refund.
//
// A site is a handler of a try around any call that refunds, calls a tool, makes the try's own call
// again (whatever its name), or lets the enclosing loop retry. Good when it starts with
// state = <status query> and an if on state, or an if on a status query, and one branch of that if
// can neither retry nor refund. Witness: the status query.
//
// A fact asserts the premise of the whole repository: it is written only when there is a site and
// every site is good. See lib/premises.sc.
//> using file lib/premises.sc

// What may establish the premise: a construct a witness can match, and what must be true for that
// match to imply the premise. A witness of any other shape is a pattern and no more. The same
// table is MANIFEST in kamanu/evidence/premises.py, which reads no file.
val MANIFEST: Map[String, List[String]] = Map(
  "status_of_the_same_call" -> List(
    "The service's status answer includes every call it had accepted when it was asked",
    "The service does not accept a call after it has answered that the call was not made",
    "The state the handler tests for is the one the service gives a call it accepted"))

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  Premises.report("status_before_retry", out, Premises.statusBeforeRetry(cpg), MANIFEST)
}
