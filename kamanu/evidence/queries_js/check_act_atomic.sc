// Premise query check_act_atomic (JavaScript and TypeScript): Each check and act on a counter is one atomic operation.
//
// A site is each write of a counter (a receiver with ledger, quota, budget, spend or counter in its
// last name) and each x.get(K) then y.set(K, ...) pair on any receiver. Good when the write is
// incr, incrBy, add, decr, decrBy (or their lowercase kin) and the function reads no counter.
// Witness: the line of each good write.
//
// A fact asserts the premise of the whole repository: it is written only when there is a site and
// every site is good. See lib/premises_js.sc.
//> using file lib/premises_js.sc

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  PremisesJs.report("check_act_atomic", out, PremisesJs.checkActAtomic(cpg))
}
