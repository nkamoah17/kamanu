// Premise query retry_bounded (JavaScript and TypeScript): Every retry loop is bounded.
//
// A site is a loop with a tool call in it, or with a try in it. Good when it is
// for (let i = n; i < bound; i++) with i never assigned in the body, or while (n < bound) with n
// starting at a number and raised first on every pass and nowhere else, bound a number or a module
// constant, and every loop inside it is good too. Witness: the loop line.
//
// A fact asserts the premise of the whole repository: it is written only when there is a site and
// every site is good. See lib/premises_js.sc.
//> using file lib/premises_js.sc

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  PremisesJs.report("retry_bounded", out, PremisesJs.retryBounded(cpg))
}
