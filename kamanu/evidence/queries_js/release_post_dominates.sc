// Premise query release_post_dominates (JavaScript and TypeScript): Every lock taken is released on every path.
//
// A site is an acquire() and a runExclusive(). Good when the acquire's statement is followed at
// once by a try whose finally releases that lock first (release() of the acquire's answer, or
// lock.release()), or it is a runExclusive; and no two locks are taken one inside the other in
// both orders. Witness: the acquire or runExclusive line.
//
// A fact asserts the premise of the whole repository: it is written only when there is a site and
// every site is good. See lib/premises_js.sc.
//> using file lib/premises_js.sc

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  PremisesJs.report("release_post_dominates", out, PremisesJs.releasePostDominates(cpg))
}
