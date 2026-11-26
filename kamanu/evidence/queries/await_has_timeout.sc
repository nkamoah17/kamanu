// Premise query await_has_timeout: Every wait ends: each await, and each call that can block, has a limit.
//
// A site is a wait: an await on any expression (asyncio.sleep of a constant excepted), an async
// for, and a plain call that can block whose value is not awaited (requests.*, httpx.*, urlopen,
// socket.create_connection, subprocess.run and kin, and any call on a parameter, a module-level
// name or an attribute of self that is not a function of the repository). Good when the wait is
// asyncio.wait_for(x, limit), the call itself with timeout=limit, or lies in an async with
// asyncio.timeout(limit) block, and the limit is a number or a module constant bound to one.
// Witness: the awaited or called line.
//
// A fact asserts the premise of the whole repository: it is written only when there is a site and
// every site is good. See lib/premises.sc.
//> using file lib/premises.sc

// What may establish the premise: a construct a witness can match, and what must be true for that
// match to imply the premise. A witness of any other shape is a pattern and no more. The same
// table is MANIFEST in kamanu/evidence/premises.py, which reads no file.
val MANIFEST: Map[String, List[String]] = Map(
  "asyncio_wait_for" -> List(
    "The name asyncio is the standard library's module at run time",
    "The awaited operation ends when it is cancelled, and does not swallow the cancellation",
    "No synchronous call blocks the event loop, the one that makes the awaited operation included"))

@main def exec(cpgFile: String, out: String) = {
  importCpg(cpgFile)
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  Premises.report("await_has_timeout", out, Premises.awaitHasTimeout(cpg), MANIFEST)
}
