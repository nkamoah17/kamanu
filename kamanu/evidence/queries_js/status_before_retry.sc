// Premise query status_before_retry (JavaScript and TypeScript): No retry or refund without first asking the status.
//
// A site is a handler around a call that calls it again or refunds, or that lets the loop around
// it retry. Good when the handler first awaits a call with status in its last name into a const,
// and that answer, compared with a settled literal (settled, succeeded, completed, paid, success),
// keeps every retry and refund on the side where it is not settled. Witness: the status query line.
//
// A fact asserts the premise of the whole repository: it is written only when there is a site and
// every site is good. See lib/premises_js.sc.
//> using file lib/premises_js.sc

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  PremisesJs.report("status_before_retry", out, PremisesJs.statusBeforeRetry(cpg))
}
