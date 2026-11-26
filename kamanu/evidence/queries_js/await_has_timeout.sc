// Premise query await_has_timeout (JavaScript and TypeScript): Every wait ends: each await, and each blocking child_process call, has a limit.
//
// A site is an await on any call, or on a local holding one, and a call of execSync, execFileSync
// or spawnSync. Good when the call is given AbortSignal.timeout(n), {signal: AbortSignal.timeout(n)}
// or {timeout: n}, n a positive number or a module constant bound to one; or the await is on a
// Promise.race with a timer of the repository among its elements; or on a Promise.all of limited
// calls. A sleep of a number (new Promise(r => setTimeout(r, n))) ends and is no site. Witness: the
// awaited or called line.
//
// A fact asserts the premise of the whole repository: it is written only when there is a site and
// every site is good. See lib/premises_js.sc.
//> using file lib/premises_js.sc

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  PremisesJs.report("await_has_timeout", out, PremisesJs.awaitHasTimeout(cpg))
}
