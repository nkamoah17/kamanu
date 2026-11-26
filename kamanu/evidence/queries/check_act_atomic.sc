// Premise query check_act_atomic: The check reads the answer of one atomic write of the counter.
//
// A site is each write of a counter, a call on a counter that is neither a known read nor a known
// write, and, whatever the receivers are named, a write of a key that the same function also reads.
// Good only when the write is one atomic operation that answers with the count (add, incr, incrby,
// decr, decrby) and no read of that counter is in the function: a read then a write are two
// operations whatever lies between. Absolute writes and c[k] += v are bad. Witness: the write.
//
// A fact asserts the premise of the whole repository: it is written only when there is a site and
// every site is good. See lib/premises.sc.
//> using file lib/premises.sc

// What may establish the premise: a construct a witness can match, and what must be true for that
// match to imply the premise. A witness of any other shape is a pattern and no more. The same
// table is MANIFEST in kamanu/evidence/premises.py, which reads no file.
val MANIFEST: Map[String, List[String]] = Map(
  "redis_increment" -> List(
    "Redis runs one command at a time",
    "The name redis is the redis-py client at run time, and the server it reaches keeps every increment it has answered",
    "Every process counts the same budget under the same key of that server",
    "The check that admits a spend tests the answer of its own increment"))

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  Premises.report("check_act_atomic", out, Premises.checkActAtomic(cpg), MANIFEST)
}
