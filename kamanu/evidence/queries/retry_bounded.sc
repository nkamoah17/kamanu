// Premise query retry_bounded: Every retry loop around a tool call is bounded.
//
// A site is a loop with a tool call in it, or, whatever the call is named, a loop with a try around
// a call whose handler can come back round. Good when it is a for over range() of constants, or
// while n < constant where n rises by a positive number on every path back around the loop,
// exceptions included, and is set no other way in it; and no loop nested in it may be endless.
// Witness: the loop line.
//
// A fact asserts the premise of the whole repository: it is written only when there is a site and
// every site is good. See lib/premises.sc.
//> using file lib/premises.sc

// What may establish the premise: a construct a witness can match, and what must be true for that
// match to imply the premise. A witness of any other shape is a pattern and no more. The same
// table is MANIFEST in kamanu/evidence/premises.py, which reads no file.
val MANIFEST: Map[String, List[String]] = Map(
  "range_of_numbers" -> List(
    "The name range is Python's builtin at run time",
    "No call in the loop's body starts the function that holds the loop again"))

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  Premises.report("retry_bounded", out, Premises.retryBounded(cpg), MANIFEST)
}
