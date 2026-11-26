// Premise query release_post_dominates: A release follows each acquire on every path, and no two locks are taken in both orders.
//
// A site is a call x.acquire(), or a with on a name with lock, mutex or semaphore in it. A with is
// good. An acquire is good when it is a statement followed at once by a try whose finally starts
// with x.release() on the same receiver. Also bad: two locks, named by receiver (self.x is x), taken
// one inside the other in both orders anywhere in the repository, nesting through calls to the
// repository's own functions included. Witness: the acquire or the with line.
//
// A fact asserts the premise of the whole repository: it is written only when there is a site and
// every site is good. See lib/premises.sc.
//> using file lib/premises.sc

// What may establish the premise: a construct a witness can match, and what must be true for that
// match to imply the premise. A witness of any other shape is a pattern and no more. The same
// table is MANIFEST in kamanu/evidence/premises.py, which reads no file.
val MANIFEST: Map[String, List[String]] = Map(
  "threading_lock_with" -> List(
    "The name threading is the standard library's module at run time",
    "The code run under the lock ends, by returning or by raising",
    "No thread or process is killed while it holds the lock"))

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  Premises.report("release_post_dominates", out, Premises.releasePostDominates(cpg), MANIFEST)
}
