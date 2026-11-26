// Shared reading of a Python code property graph for the six premise queries of task E2.
//
// Each query script in kamanu/evidence/queries/ includes this file and calls one of the six
// functions at the end of it. A function lists every site of its premise in the repository, each
// judged good or bad, and report() writes the witnesses only when there is a site and every site
// is good. One bad site, or a construct this file cannot read, silences the query for the whole
// repository: there is no fact that says a premise failed, and silence is read as failure.
//
// The rule behind every function is the same: sites are found liberally, on the raw graph, and a
// site is good only when it has one of a few shapes read exactly. Anything else is bad. So a
// shape this file does not know costs a missing fact, never a false one, within the vocabulary
// the gate's docstring fixes (a tool is known by its name; Python has no types to read).
//
// What the graph does not hold, and how it is got:
//   await     pysrc2cpg erases it. The text before an expression's column, on its line, is read
//             from the source under META_DATA.ROOT; an expression is awaited when that text ends
//             in the word await, after any opening parentheses. A string or a comment that holds
//             the word is not before any expression, so it is not an await.
//   with      lowers to a Block of temporaries (manager_tmp...) around a TRY whose FINALLY calls
//             __exit__. Read back here as a With.
//   for       lowers to a Block around a WHILE on iteratorNonEmptyOrException. Read back as a Loop
//             whose header is the iterable.
//   raising   the CFG has no edge for an exception raised by a call, so nothing here that needs
//             exception paths uses the CFG: those paths are walked on the statement tree.
//
// What a fact says about itself (task T5). A match is a pattern, not a proof. Some matches are also
// of a construct: a shape whose objects this file can name (a lock that is threading.Lock(), bound
// once), and which implies the premise under assumptions a reader can check. The query's script
// lists those assumptions, its manifest; a witness of a listed construct carries "construct" and
// "assumptions" on its fact, and any other witness carries neither. A construct never makes a site
// good or bad: it changes no fact's place, only what the fact says.
//
// Diagnostics: when KAMANU_QUERY_SITES names a directory, every site with its verdict and reason
// is written to <directory>/<query>.sites.jsonl. This never changes the answer in `out`.

import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.codepropertygraph.generated.nodes
import io.shiftleft.semanticcpg.language._
import java.nio.file.{Files, Paths}
import scala.collection.mutable

object Premises {

  // ---------------- what a query reports ----------------
  final case class Witness(file: String, line: Int, subject: String, construct: Option[String] = None)
  final case class Site(file: String, line: Int, what: String, good: Boolean, why: String, witnesses: List[Witness])

  def bad(file: String, n: nodes.AstNode, what: String, why: String): Site =
    Site(file, lineOf(n), what, false, why, Nil)

  def good(file: String, n: nodes.AstNode, what: String, witnesses: List[Witness]): Site =
    if (witnesses.isEmpty) Site(file, lineOf(n), what, false, "no witness line", Nil)
    else Site(file, lineOf(n), what, true, "", witnesses)

  /** manifest: construct -> the assumptions under which it implies the query's premise. */
  def report(query: String, out: String, sites: List[Site], manifest: Map[String, List[String]]): Unit = {
    val proven = sites.nonEmpty && sites.forall(_.good)
    val rows =
      if (!proven) Nil
      else sites.flatMap(_.witnesses).distinct.map { w =>
        val row = ujson.Obj("file" -> w.file, "line" -> w.line, "subject" -> w.subject)
        for (c <- w.construct; assumptions <- manifest.get(c) if assumptions.nonEmpty) {
          row("construct") = c
          row("assumptions") = ujson.Arr.from(assumptions.map(ujson.Str(_)))
        }
        row.toString
      }
    Files.write(Paths.get(out), rows.map(_ + "\n").mkString.getBytes("UTF-8"))
    sys.env.get("KAMANU_QUERY_SITES").filter(_.nonEmpty).foreach { dir =>
      val lines = sites.map { s =>
        ujson.Obj("file" -> s.file, "line" -> s.line, "what" -> s.what, "good" -> s.good, "why" -> s.why,
                  "witnesses" -> ujson.Arr.from(s.witnesses.map(w => ujson.Arr(w.file, w.line)))).toString
      }
      Files.write(Paths.get(dir).resolve(query + ".sites.jsonl"), lines.map(_ + "\n").mkString.getBytes("UTF-8"))
    }
  }

  // ---------------- the source text, for await ----------------
  final class Source(cpg: Cpg) {
    private val root = cpg.metaData.root.headOption.getOrElse("")
    private val cache = mutable.Map[String, IndexedSeq[String]]()

    def lines(file: String): IndexedSeq[String] = cache.getOrElseUpdate(file, {
      val path = Paths.get(root).resolve(file)
      if (!Files.isRegularFile(path)) throw new IllegalStateException(s"premises: cannot read the source of $file under $root")
      new String(Files.readAllBytes(path), "UTF-8").split("\n", -1).toIndexedSeq.map(_.stripSuffix("\r"))
    })

    /** The text on n's line before n's column, or None when the graph gives no place for n. */
    def before(file: String, n: nodes.AstNode): Option[String] =
      for {
        line <- n.lineNumber.map(_.intValue)
        col  <- n.columnNumber.map(_.intValue)
        text <- lines(file).lift(line - 1)
        if col >= 1 && col - 1 <= text.length
      } yield text.substring(0, col - 1)

    private val AwaitEnd = "(?:^|[^A-Za-z0-9_])await$".r

    def awaited(file: String, n: nodes.AstNode): Boolean = before(file, n).exists { text =>
      var t = text.replaceAll("\\s+$", "")
      while (t.endsWith("(")) t = t.dropRight(1).replaceAll("\\s+$", "")
      AwaitEnd.findFirstIn(t).isDefined
    }

    /** The text on n's line before n, for `async with` and `async for`. */
    def precededBy(file: String, n: nodes.AstNode, words: String): Boolean =
      before(file, n).exists(t => t.replaceAll("\\s+", " ").trim.endsWith(words))
  }

  // ---------------- names ----------------
  val Ident = "[A-Za-z_][A-Za-z0-9_]*".r

  def words(id: String): Seq[String] =
    id.split("_").toSeq.flatMap(_.split("(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")).map(_.toLowerCase).filter(_.nonEmpty)

  def stripStrings(text: String): String = text.replaceAll("\"(?:[^\"\\\\]|\\\\.)*\"|'(?:[^'\\\\]|\\\\.)*'", "\"\"")

  def textWords(text: String): Seq[String] = Ident.findAllIn(stripStrings(text)).toSeq.flatMap(words)

  val ToolWords = Set("tool", "tools", "gateway")
  val ApproverWords = Set("approver", "approval", "approve", "ask")
  val CounterWords = Set("ledger", "quota", "budget", "spend", "counter")
  val LockWords = Set("lock", "mutex", "semaphore")

  def lineOf(n: nodes.AstNode): Int = n.lineNumber.map(_.intValue).getOrElse(0)

  // ---------------- calls ----------------
  def isOp(c: nodes.Call): Boolean = c.name.startsWith("<operator>")

  /** A call the source wrote: not an operator, not the frontend's own unnamed or dunder call. */
  def isSourceCall(c: nodes.Call): Boolean = !isOp(c) && c.name.nonEmpty && !c.name.matches("__.*__")

  /** The callee as written: the call's code up to the argument list that closes it. */
  def callee(c: nodes.Call): String = {
    val code = c.code
    var depth = 0
    var start = -1
    var quote: Char = 0
    var i = 0
    while (i < code.length) {
      val ch = code(i)
      if (quote != 0) { if (ch == '\\') i += 1 else if (ch == quote) quote = 0 }
      else if (ch == '"' || ch == '\'') quote = ch
      else if (ch == '(' || ch == '[' || ch == '{') { if (depth == 0 && ch == '(') start = i; depth += 1 }
      else if (ch == ')' || ch == ']' || ch == '}') depth -= 1
      i += 1
    }
    (if (start >= 0) code.substring(0, start) else code).replaceAll("\\s+", "")
  }

  def pathWords(c: nodes.Call): Seq[String] = textWords(callee(c))

  /** The receiver as written, for a.b.f(x): a.b. */
  def receiver(c: nodes.Call): Option[String] = {
    val t = callee(c)
    val i = t.lastIndexOf('.')
    if (i > 0) Some(t.substring(0, i)) else None
  }

  def isToolCall(c: nodes.Call): Boolean = isSourceCall(c) && pathWords(c).exists(ToolWords)
  def isApproverCall(c: nodes.Call): Boolean = isSourceCall(c) && pathWords(c).exists(ApproverWords)

  /** The arguments that are not the callee or the receiver. */
  def args(c: nodes.Call): List[nodes.Expression] =
    c.astChildren.collect { case e: nodes.Expression if e.order >= 1 && e.argumentIndex != 0 => e }.l

  def positional(c: nodes.Call): List[nodes.Expression] = args(c).filter(_.argumentIndex >= 1).sortBy(_.argumentIndex)
  def keyword(c: nodes.Call, name: String): Option[nodes.Expression] = args(c).find(_.argumentName.contains(name))
  def argAt(c: nodes.Call, index: Int): Option[nodes.Expression] =
    c.astChildren.collect { case e: nodes.Expression if e.argumentIndex == index && e.order >= 1 => e }.headOption

  def isAssign(c: nodes.Call): Boolean = c.name == "<operator>.assignment"
  def isAssignFamily(c: nodes.Call): Boolean = c.name.startsWith("<operator>.assignment")

  def ancestors(n: nodes.AstNode): List[nodes.AstNode] = {
    val out = mutable.ListBuffer[nodes.AstNode]()
    var cur = n
    while (!cur.isInstanceOf[nodes.Method]) { cur = cur.astParent; out += cur }
    out.toList
  }

  /** n and what lies under it in the AST, without entering a nested function or class: a module's
    * AST holds its functions, and a function's holds its closures, which are methods of their own. */
  def under(n: nodes.AstNode): List[nodes.AstNode] = {
    val out = mutable.ListBuffer[nodes.AstNode]()
    val stack = mutable.Stack[nodes.AstNode](n)
    while (stack.nonEmpty) {
      val cur = stack.pop()
      out += cur
      cur.astChildren.foreach {
        case _: nodes.Method | _: nodes.TypeDecl =>
        case k => stack.push(k)
      }
    }
    out.toList
  }

  def calls(n: nodes.AstNode): List[nodes.Call] = under(n).collect { case c: nodes.Call => c }
  def idents(n: nodes.AstNode): List[nodes.Identifier] = under(n).collect { case i: nodes.Identifier => i }

  // ---------------- methods, files, constants ----------------
  final case class Fn(method: nodes.Method, file: String)

  def methods(cpg: Cpg): List[Fn] =
    cpg.method.l.flatMap { m =>
      m.file.name.headOption.filter(f => f.nonEmpty && f != "<unknown>" && !m.isExternal).map(f => Fn(m, f))
    }

  def params(m: nodes.Method): Set[String] = m.parameter.name.toSet

  /** (method, assignment) for every assignment-family call whose target is the identifier name. */
  def defsOf(m: nodes.Method, name: String): List[nodes.Call] =
    calls(m).filter(c => isAssignFamily(c) && argAt(c, 1).exists { case i: nodes.Identifier => i.name == name; case _ => false })

  val Number = "^(?:[0-9][0-9_]*(?:\\.[0-9_]*)?|\\.[0-9]+)(?:[eE][-+]?[0-9]+)?$".r

  def isNumber(e: nodes.Expression): Boolean = e match {
    case l: nodes.Literal => Number.findFirstIn(l.code).isDefined
    case _ => false
  }

  final class Constants(units: List[Fn]) {
    private val byFile = units.groupBy(_.file)
    private val cache = mutable.Map[String, Set[String]]()

    /** Names bound once in the whole file, at module level, to a number. */
    def numbers(file: String): Set[String] = cache.getOrElseUpdate(file, {
      val us = byFile.getOrElse(file, Nil)
      val defs = us.flatMap(u => calls(u.method).filter(isAssignFamily).flatMap { c =>
        argAt(c, 1).collect { case i: nodes.Identifier => (i.name, u.method.name, c) }
      })
      defs.groupBy(_._1).collect {
        case (name, List((_, "<module>", c))) if isAssign(c) && argAt(c, 2).exists(isNumber) => name
      }.toSet
    })

    /** A number written in the source, or a module constant bound to one. Never a parameter. */
    def limit(e: nodes.Expression, u: Fn): Boolean = e match {
      case i: nodes.Identifier =>
        numbers(u.file).contains(i.name) && !params(u.method).contains(i.name) &&
          (u.method.name == "<module>" || defsOf(u.method, i.name).isEmpty)
      case other => isNumber(other)
    }

    /** Arithmetic on limits: what range() may be given. */
    def constant(e: nodes.Expression, u: Fn): Boolean = e match {
      case c: nodes.Call if Set("<operator>.addition", "<operator>.subtraction", "<operator>.multiplication",
                                "<operator>.minus", "<operator>.plus")(c.name) =>
        val as = args(c)
        as.nonEmpty && as.forall(constant(_, u))
      case other => limit(other, u)
    }
  }

  // ---------------- what a name is, for the constructs ----------------
  /** Reads what a name is bound to, over the whole repository, and answers only where nothing the
    * graph shows could bind it to something else. It cannot see setattr, globals() or exec: what
    * it cannot see is what the manifests' assumptions are about. */
  final class Names(cpg: Cpg, units: List[Fn]) {
    private val assigned = units.flatMap(u => calls(u.method).filter(isAssignFamily).flatMap(c => argAt(c, 1).map(t => (u, c, t))))
    private val binds: Map[(String, String), List[(Fn, nodes.Call)]] = assigned.collect {
      // The frontend binds each builtin a module uses to __builtins__ itself.
      case (u, c, i: nodes.Identifier) if !argAt(c, 2).exists(_.code.startsWith("__builtins__.")) => ((u.file, i.name), (u, c))
    }.groupMap(_._1)(_._2)
    private val fields: List[(String, String)] = assigned.collect {
      case (_, _, t: nodes.Call) if t.name == "<operator>.fieldAccess" =>
        (t.code.replaceAll("\\s+", ""), t.astChildren.collect { case f: nodes.FieldIdentifier => f.canonicalName }.headOption.getOrElse(""))
    }
    private val paramsIn: Map[String, Set[String]] = units.groupBy(_.file).map { case (f, us) => f -> us.flatMap(u => params(u.method)).toSet }
    private val stars: Set[String] = binds.keySet.collect { case (f, "*") => f }
    private val modules: Set[String] = cpg.file.name.l.flatMap(_.split("[/\\\\]")).map(_.stripSuffix(".py")).toSet

    private def open(file: String, name: String): Boolean = !stars(file) && !paramsIn.getOrElse(file, Set.empty[String])(name)
    private def field(name: String): Boolean = fields.exists(_._2 == name)

    /** name is `import name`, bound no other way in the file, no module of the repository, and
      * nothing in the repository assigns to one of its attributes. */
    def module(file: String, name: String): Boolean =
      open(file, name) && !modules(name) && !fields.exists(_._1.startsWith(name + ".")) && {
        val defs = binds.getOrElse((file, name), Nil)
        defs.nonEmpty && defs.forall { case (_, c) => isAssign(c) && argAt(c, 2).exists {
          case i: nodes.Call => i.name == "<operator>.import" && i.code.replaceAll("\\s+", " ").trim == s"import $name"
          case _ => false
        } }
      }

    /** The one value name is bound to in its file, at module level; None when anything else may set it. */
    def once(file: String, name: String): Option[nodes.Expression] =
      if (!open(file, name) || field(name)) None
      else binds.getOrElse((file, name), Nil) match {
        case List((u, c)) if u.method.name == "<module>" && isAssign(c) => argAt(c, 2)
        case _ => None
      }

    /** name is Python's own: nothing in the file binds it. */
    def builtin(file: String, name: String): Boolean = open(file, name) && !binds.contains((file, name))

    /** The call a module-level name is bound to, as written, when it is a function of a library module. */
    def madeBy(file: String, name: String): Option[nodes.Call] = once(file, name).collect {
      case c: nodes.Call if isSourceCall(c) && module(file, callee(c).takeWhile(_ != '.')) => c
    }

    /** A finite number written in the source, or a module constant only ever bound to one. */
    def number(file: String, e: nodes.Expression): Boolean = e match {
      case i: nodes.Identifier => once(file, i.name).exists { case l: nodes.Literal => number(file, l); case _ => false }
      case l: nodes.Literal => isNumber(l) && scala.util.Try(l.code.replace("_", "").toDouble).toOption.exists(x => !x.isInfinite)
      case _ => false
    }
  }

  /** The name an expression is, when it is a bare name. */
  def bareName(text: String): Option[String] = Some(text.trim).filter(Ident.pattern.matcher(_).matches)

  // ---------------- statements, read back from the lowering ----------------
  sealed trait St { def node: nodes.AstNode }
  final case class SExpr(node: nodes.Expression) extends St
  final case class SIf(node: nodes.ControlStructure, cond: nodes.Expression, thn: List[St], els: List[St]) extends St
  final case class SLoop(node: nodes.AstNode, loop: nodes.ControlStructure, isFor: Boolean, header: nodes.AstNode,
                         body: List[St], orElse: List[St]) extends St
  final case class STry(node: nodes.ControlStructure, body: List[St], handlers: List[(nodes.ControlStructure, List[St])],
                        orElse: List[St], fin: Option[List[St]]) extends St
  final case class SWith(node: nodes.Block, manager: nodes.Expression, body: List[St], bodyNode: nodes.AstNode) extends St
  final case class SReturn(node: nodes.Return) extends St
  final case class SJump(node: nodes.ControlStructure, isContinue: Boolean) extends St
  final case class SRaise(node: nodes.Call) extends St
  final case class SUnknown(node: nodes.AstNode) extends St

  def kids(n: nodes.AstNode): List[nodes.AstNode] =
    n.astChildren.l.filterNot(k => k.isInstanceOf[nodes.Local]).sortBy(_.order)

  private def ctype(n: nodes.AstNode): String = n match {
    case cs: nodes.ControlStructure => cs.controlStructureType
    case _ => ""
  }

  def withManager(b: nodes.Block): Option[nodes.Expression] = kids(b).headOption.collect {
    case c: nodes.Call if isAssign(c) && argAt(c, 1).exists { case i: nodes.Identifier => i.name.startsWith("manager_tmp"); case _ => false } =>
      argAt(c, 2)
  }.flatten

  /** For a for-loop lowering: (the WHILE, the iterable). */
  def forParts(b: nodes.Block): Option[(nodes.ControlStructure, nodes.Expression)] = kids(b) match {
    case List(init: nodes.Call, loop: nodes.ControlStructure)
        if isAssign(init) && loop.controlStructureType == "WHILE" &&
           kids(loop).headOption.exists(k => k.isInstanceOf[nodes.Unknown] && k.code == "iteratorNonEmptyOrException") =>
      argAt(init, 2) match {
        case Some(inner: nodes.Block) =>
          kids(inner).headOption.collect { case c: nodes.Call if isAssign(c) => argAt(c, 2) }.flatten.map(it => (loop, it))
        case _ => None
      }
    case _ => None
  }

  def seq(n: nodes.AstNode): List[St] = n match {
    case b: nodes.Block => block(b)
    case other => st(other)
  }

  def block(b: nodes.Block): List[St] =
    withManager(b) match {
      case Some(manager) =>
        kids(b).collectFirst { case t: nodes.ControlStructure if t.controlStructureType == "TRY" => t } match {
          case Some(t) => kids(t).headOption match {
            case Some(body: nodes.Block) => List(SWith(b, manager, block(body), body))
            case _ => List(SUnknown(b))
          }
          case None => List(SUnknown(b))
        }
      case None =>
        forParts(b) match {
          case Some((loop, iterable)) =>
            kids(loop) match {
              case _ :: (body: nodes.Block) :: rest =>
                kids(body) match {
                  case target :: stmts if target.code.contains("__next__") =>
                    List(SLoop(b, loop, true, iterable, stmts.flatMap(st), rest.headOption.map(seq).getOrElse(Nil)))
                  case _ => List(SUnknown(b))
                }
              case _ => List(SUnknown(b))
            }
          case None => kids(b).flatMap(st)
        }
    }

  def st(n: nodes.AstNode): List[St] = n match {
    case b: nodes.Block => block(b)
    case cs: nodes.ControlStructure =>
      val ks = kids(cs)
      cs.controlStructureType match {
        case "IF" => ks match {
          case (cond: nodes.Expression) :: thn :: rest => List(SIf(cs, cond, seq(thn), rest.headOption.map(seq).getOrElse(Nil)))
          case _ => List(SUnknown(cs))
        }
        case "WHILE" => ks match {
          case (cond: nodes.Expression) :: body :: rest if !cond.isInstanceOf[nodes.Unknown] =>
            List(SLoop(cs, cs, false, cond, seq(body), rest.headOption.map(seq).getOrElse(Nil)))
          case _ => List(SUnknown(cs))
        }
        case "TRY" => ks match {
          case (body: nodes.Block) :: parts if parts.forall(p => Set("CATCH", "ELSE", "FINALLY")(ctype(p))) =>
            val handlers = parts.collect { case p: nodes.ControlStructure if p.controlStructureType == "CATCH" => (p, kids(p).flatMap(seq)) }
            val orElse = parts.filter(p => ctype(p) == "ELSE").flatMap(p => kids(p).flatMap(seq))
            val fin = parts.find(p => ctype(p) == "FINALLY").map(p => kids(p).flatMap(seq))
            List(STry(cs, block(body), handlers, orElse, fin))
          case _ => List(SUnknown(cs))
        }
        case "BREAK" => List(SJump(cs, false))
        case "CONTINUE" => List(SJump(cs, true))
        case _ => List(SUnknown(cs))
      }
    case r: nodes.Return => List(SReturn(r))
    case c: nodes.Call if c.name == "<operator>.raise" => List(SRaise(c))
    case e: nodes.Expression => List(SExpr(e))
    case other => List(SUnknown(other))
  }

  def body(m: nodes.Method): List[St] = block(m.block)

  /** Every statement, depth first, with the statement lists that hold it. */
  def everyList(stmts: List[St]): List[List[St]] = stmts :: stmts.flatMap {
    case SIf(_, _, t, e) => everyList(t) ++ everyList(e)
    case SLoop(_, _, _, _, b, e) => everyList(b) ++ everyList(e)
    case STry(_, b, hs, e, f) => everyList(b) ++ hs.flatMap(h => everyList(h._2)) ++ everyList(e) ++ f.toList.flatMap(everyList)
    case SWith(_, _, b, _) => everyList(b)
    case _ => Nil
  }

  def everySt(stmts: List[St]): List[St] = everyList(stmts).flatten

  // =====================================================================================
  // session_key_minted
  // =====================================================================================
  def isSessionName(name: String): Boolean = {
    val ws = words(name)
    ws.contains("session") && ws.exists(Set("key", "id", "token"))
  }

  def targetName(e: nodes.Expression): Option[String] = e match {
    case i: nodes.Identifier => Some(i.name)
    case c: nodes.Call if c.name == "<operator>.fieldAccess" =>
      c.astChildren.collect { case f: nodes.FieldIdentifier => f.canonicalName }.headOption
    case c: nodes.Call if c.name == "<operator>.indexAccess" =>
      argAt(c, 2).collect { case l: nodes.Literal if l.code.matches("^[rbuRBU]?[\"'].*[\"']$") => l.code.replaceAll("^[rbuRBU]?[\"']+|[\"']+$", "") }
    case _ => None
  }

  def isMint(c: nodes.Call): Boolean = {
    val name = callee(c)
    (name == "uuid.uuid4" || name == "uuid4") && args(c).isEmpty ||
      name.matches("secrets\\.[A-Za-z_][A-Za-z0-9_]*") && args(c).forall(_.isInstanceOf[nodes.Literal])
  }

  /** The mints a value is made of, or None when anything else can reach it. */
  def minted(e: nodes.Expression, u: Fn, seen: Set[String]): Option[List[nodes.Call]] = e match {
    case l: nodes.Literal => Some(Nil)
    case i: nodes.Identifier =>
      if (seen(i.name) || params(u.method).contains(i.name)) None
      else {
        val defs = defsOf(u.method, i.name)
        if (defs.isEmpty || !defs.forall(isAssign)) None
        else {
          val parts = defs.map(d => argAt(d, 2).flatMap(minted(_, u, seen + i.name)))
          if (parts.forall(_.isDefined)) Some(parts.flatten.flatten) else None
        }
      }
    case c: nodes.Call if c.name == "<operator>.fieldAccess" =>
      val field = c.astChildren.collect { case f: nodes.FieldIdentifier => f.canonicalName }.headOption
      if (field.contains("hex")) argAt(c, 1).flatMap(minted(_, u, seen)) else None
    case c: nodes.Call if c.name == "<operator>.addition" =>
      val parts = args(c).map(minted(_, u, seen))
      if (parts.nonEmpty && parts.forall(_.isDefined)) Some(parts.flatten.flatten) else None
    case c: nodes.Call if isMint(c) => Some(List(c))
    case c: nodes.Call if callee(c) == "str" && args(c).size == 1 && positional(c).size == 1 =>
      minted(positional(c).head, u, seen)
    case _ => None
  }

  /** A mint of at least 16 random bytes by a library function. */
  def strongMint(c: nodes.Call, f: String, names: Names): Boolean = isMint(c) && (callee(c) match {
    case "uuid.uuid4" => names.module(f, "uuid")
    case "secrets.token_hex" | "secrets.token_bytes" | "secrets.token_urlsafe" =>
      names.module(f, "secrets") && (args(c) match {
        case Nil => true
        case List(l: nodes.Literal) => l.code.matches("[0-9]{1,4}") && l.code.toInt >= 16
        case _ => false
      })
    case _ => false
  })

  /** The value is a strong mint as written, through .hex, str() and a constant prefix or suffix: no name in between. */
  def mintedHere(e: nodes.Expression, f: String, names: Names): Boolean = e match {
    case c: nodes.Call if isMint(c) => strongMint(c, f, names)
    case c: nodes.Call if c.name == "<operator>.fieldAccess" => argAt(c, 1).exists(mintedHere(_, f, names))
    case c: nodes.Call if c.name == "<operator>.addition" =>
      val (plain, rest) = args(c).partition(_.isInstanceOf[nodes.Literal])
      rest.nonEmpty && rest.forall(mintedHere(_, f, names))
    case c: nodes.Call if callee(c) == "str" && names.builtin(f, "str") => positional(c).headOption.exists(mintedHere(_, f, names))
    case _ => false
  }

  /** The construct library_mint_in_local: a local of a function, which no setattr can reach, bound to a library mint. */
  def mintConstruct(at: nodes.AstNode, value: Option[nodes.Expression], u: Fn, names: Names): Option[String] = at match {
    case c: nodes.Call if isAssign(c) && !u.method.name.startsWith("<") && argAt(c, 1).exists(_.isInstanceOf[nodes.Identifier]) &&
        value.exists(mintedHere(_, u.file, names)) => Some("library_mint_in_local")
    case _ => None
  }

  def sessionKeyMinted(cpg: Cpg): List[Site] = {
    val units = methods(cpg)
    val names = new Names(cpg, units)
    units.flatMap { u =>
      val f = u.file
      def judge(at: nodes.AstNode, what: String, value: Option[nodes.Expression]): Site =
        value.flatMap(minted(_, u, Set.empty)) match {
          case Some(mints) if mints.nonEmpty =>
            val construct = mintConstruct(at, value, u, names)
            good(f, at, what, mints.map(m => Witness(f, lineOf(m), s"$what minted by ${m.code}", construct)))
          case Some(_) => bad(f, at, what, "a constant, not minted")
          case None => bad(f, at, what, "a value the server did not mint can reach it")
        }
      val assigned = calls(u.method).filter(isAssignFamily).flatMap { c =>
        argAt(c, 1).flatMap(targetName).filter(isSessionName).map { name =>
          if (isAssign(c)) judge(c, s"session key $name", argAt(c, 2))
          else bad(f, c, s"session key $name", "an augmented assignment")
        }
      }
      val keywords = under(u.method).collect {
        case e: nodes.Expression if e.argumentName.exists(isSessionName) => judge(e, s"session key ${e.argumentName.get}", Some(e))
      }.l
      val parameters = u.method.parameter.l.filter(p => isSessionName(p.name)).map(p => bad(f, p, s"session key ${p.name}", "a parameter"))
      // Whatever it is assigned to: a read of the caller's value under a key that names a session.
      val callerReads = calls(u.method).flatMap { c =>
        val read: Option[(String, nodes.Expression)] =
          if (c.name == "<operator>.indexAccess" && !isAssignTarget(c)) for (b <- argAt(c, 1); k <- argAt(c, 2)) yield (b.code, k)
          else if (isSourceCall(c) && c.name == "get") for (r <- receiver(c); k <- positional(c).headOption) yield (r, k)
          else None
        read.collect {
          case (base, key) if stringValue(key).exists(_.toLowerCase.contains("session")) && fromCaller(base, u) =>
            bad(f, c, s"read of ${c.code}", "the caller's session value")
        }
      }
      assigned ++ keywords ++ parameters ++ callerReads
    }
  }

  def isAssignTarget(c: nodes.Call): Boolean = c.astParent match {
    case p: nodes.Call => isAssignFamily(p) && argAt(p, 1).exists(_.id == c.id)
    case _ => false
  }

  /** The text of a string literal, without its quotes and prefix. */
  def stringValue(e: nodes.Expression): Option[String] = e match {
    case l: nodes.Literal if l.code.matches("(?s)^[rbuRBUfF]{0,2}[\"'].*[\"']$") =>
      Some(l.code.replaceAll("^[rbuRBUfF]{0,2}[\"']+|[\"']+$", ""))
    case _ => None
  }

  /** The first name of an expression's text, and whether a call follows it at once. */
  def rootOf(text: String): Option[(String, Boolean)] = {
    val t = text.replaceAll("\\s+", "")
    Ident.findPrefixOf(t).map(id => (id, t.drop(id.length).startsWith("(")))
  }

  /** May the value under base come from the caller? Only a value the function built itself from a
    * bare call or a literal does not. */
  def fromCaller(base: String, u: Fn): Boolean = rootOf(base) match {
    case None => base.trim.startsWith("(") || !base.trim.matches("^[\\[{\"'].*")
    case Some((_, true)) => false
    case Some((name, false)) =>
      if (params(u.method).contains(name) || name == "self") true
      else {
        val defs = defsOf(u.method, name)
        defs.isEmpty || defs.exists(d => !isAssign(d) || argAt(d, 2).forall { v =>
          val code = v.code.trim
          !(code.startsWith("{") || code.startsWith("[") || rootOf(code).exists { case (n, call) => call && !n.contains(".") && !params(u.method).contains(n) })
        })
      }
  }

  // =====================================================================================
  // check_act_atomic
  // =====================================================================================
  val Reads = Set("get", "read", "total", "value")
  val Writes = Set("put", "set", "add", "write", "incr", "incrby", "decr", "decrby")
  val PureOps = Set("assignment", "addition", "subtraction", "multiplication", "division", "floorDiv", "modulo",
                    "exponentiation", "minus", "plus", "logicalNot", "logicalAnd", "logicalOr", "lessThan", "greaterThan",
                    "lessEqualsThan", "greaterEqualsThan", "equals", "notEquals", "is", "isNot", "in", "notIn",
                    "fieldAccess", "indexAccess", "tupleLiteral", "listLiteral", "dictLiteral", "setLiteral",
                    "conditional", "pass", "assignmentPlus", "assignmentMinus", "assignmentMultiplication",
                    "assignmentDivision").map("<operator>." + _)

  def counterKey(text: String): Option[String] = {
    val t = text.replaceAll("\\s+", "")
    if (textWords(t).exists(CounterWords)) Some(t) else None
  }

  final case class Access(node: nodes.Call, key: String)

  def accesses(u: Fn): (List[Access], List[Access]) = {
    val cs = calls(u.method)
    val reads = mutable.ListBuffer[Access]()
    val writes = mutable.ListBuffer[Access]()
    cs.foreach { c =>
      if (isSourceCall(c) && Reads(c.name)) receiver(c).flatMap(counterKey).foreach(k => reads += Access(c, k))
      if (isSourceCall(c) && Writes(c.name)) receiver(c).flatMap(counterKey).foreach(k => writes += Access(c, k))
      if (isAssignFamily(c)) argAt(c, 1).foreach {
        case ia: nodes.Call if ia.name == "<operator>.indexAccess" =>
          argAt(ia, 1).flatMap(b => counterKey(b.code)).foreach { k =>
            writes += Access(c, k)
            if (!isAssign(c)) reads += Access(ia, k)       // c[k] += v reads c[k] first
          }
        case _ =>
      }
      if (c.name == "<operator>.indexAccess") {
        val target = c.astParent match {
          case p: nodes.Call => isAssignFamily(p) && argAt(p, 1).exists(_.id == c.id)
          case _ => false
        }
        if (!target) argAt(c, 1).flatMap(b => counterKey(b.code)).foreach(k => reads += Access(c, k))
      }
    }
    (reads.toList, writes.toList)
  }

  /** The same counter, however it is reached: self.ledger and ledger are one. */
  def counterName(key: String): String = key.replaceAll("\\s+", "").stripPrefix("self.")

  /** Whatever the receivers are named: (reads, writes) as (call, key expression text). */
  def keyedAccesses(u: Fn): (List[(nodes.Call, String)], List[(nodes.Call, String)]) = {
    val reads = mutable.ListBuffer[(nodes.Call, String)]()
    val writes = mutable.ListBuffer[(nodes.Call, String)]()
    calls(u.method).foreach { c =>
      if (isSourceCall(c) && receiver(c).isDefined) {
        val key = positional(c).headOption.map(_.code.replaceAll("\\s+", ""))
        if (KeyReads(c.name)) key.foreach(k => reads += ((c, k)))
        if (KeyWrites(c.name)) key.foreach(k => writes += ((c, k)))
      }
      if (c.name == "<operator>.indexAccess") argAt(c, 2).foreach { k =>
        val key = k.code.replaceAll("\\s+", "")
        if (isAssignTarget(c)) {
          writes += ((c, key))
          if (!c.astParent.asInstanceOf[nodes.Call].name.equals("<operator>.assignment")) reads += ((c, key))
        } else reads += ((c, key))
      }
    }
    (reads.toList, writes.toList)
  }

  val KeyReads = Set("get", "read", "total", "value")
  val KeyWrites = Set("set", "put", "write", "add", "incr", "incrby", "decr", "decrby")
  val AtomicWrites = Set("add", "incr", "incrby", "decr", "decrby")

  val RedisClients = Set("redis.Redis", "redis.StrictRedis", "redis.from_url", "redis.Redis.from_url")
  val RedisIncrements = Set("incr", "incrby", "decr", "decrby")

  /** The construct redis_increment: the counter is a module-level name bound once to a redis-py client. */
  def incrementConstruct(c: nodes.Call, f: String, names: Names): Option[String] =
    if (!RedisIncrements(c.name)) None
    else receiver(c).flatMap(bareName).flatMap(names.madeBy(f, _)).filter(m => RedisClients(callee(m))).map(_ => "redis_increment")

  def checkActAtomic(cpg: Cpg): List[Site] = {
    val units = methods(cpg)
    val names = new Names(cpg, units)
    units.flatMap { u =>
      val f = u.file
      val (reads, writes) = accesses(u)
      val readNames = reads.map(r => counterName(r.key)).toSet
      val counterSites = writes.map { w =>
        val what = s"write of ${w.key}"
        val c = w.node
        if (isAssignFamily(c)) bad(f, c, what, if (isAssign(c)) "an absolute write by subscript" else "an augmented assignment: a read and a write")
        else if (!AtomicWrites(c.name)) bad(f, c, what, s"an absolute write, ${c.name}")
        else if (readNames(counterName(w.key))) bad(f, c, what, "a read of the counter in the same function: two operations")
        else good(f, c, what, List(Witness(f, lineOf(c), s"$what, one atomic operation that answers with the count", incrementConstruct(c, f, names))))
      }
      // A call on a counter that is neither a read nor a write this query knows.
      val known = (reads ++ writes).map(_.node.id).toSet
      val strange = calls(u.method).filter(c => isSourceCall(c) && !known(c.id) && receiver(c).flatMap(counterKey).isDefined)
        .map(c => bad(f, c, s"call ${c.code}", "a call on a counter that is neither a known read nor a known write"))
      // Whatever the names: a read and a write of the same key in one function.
      val (kr, kw) = keyedAccesses(u)
      val readKeys = kr.map(_._2).toSet
      val pairs = kw.collect { case (c, k) if readKeys(k) => bad(f, c, s"write of key $k", "a read of the same key in the same function: two operations") }
      counterSites ++ strange ++ pairs
    }
  }

  // =====================================================================================
  // release_post_dominates
  // =====================================================================================
  def isLockWith(manager: nodes.Expression): Boolean = textWords(manager.code).exists(LockWords)

  def releasePostDominates(cpg: Cpg): List[Site] = {
    val units = methods(cpg)
    releaseSites(units, new Names(cpg, units)) ++ lockOrder(units)
  }

  /** A lock by its receiver as written: self.x and x are one lock. */
  def lockName(text: String): String = text.replaceAll("\\s+", "").stripPrefix("self.")

  def isAcquire(c: nodes.Call): Boolean = isSourceCall(c) && c.name == "acquire" && receiver(c).isDefined
  def isRelease(c: nodes.Call, lock: String): Boolean =
    isSourceCall(c) && c.name == "release" && receiver(c).exists(r => lockName(r) == lock)

  /** "No lock is held forever": two locks taken one inside the other in both orders, anywhere in the
    * repository, through calls to its own functions too, are a bad site. */
  def lockOrder(units: List[Fn]): List[Site] = {
    val byName: Map[String, List[Fn]] = units.groupBy(_.method.name)
    // The functions of the repository a call may reach: by its bare name, or a method on self.
    def targets(c: nodes.Call): List[Fn] =
      if (!isSourceCall(c)) Nil
      else receiver(c) match {
        case None | Some("self") => byName.getOrElse(c.name, Nil)
        case _ => Nil
      }
    def direct(u: Fn): Set[String] = {
      val withs = under(u.method).collect { case b: nodes.Block => b }.l.flatMap(withManager).filter(isLockWith).map(m => lockName(m.code))
      val acquires = calls(u.method).filter(isAcquire).flatMap(receiver).map(lockName)
      (withs ++ acquires).toSet
    }
    // Every lock a function takes, itself or through the functions it calls: a fixpoint.
    val takes = mutable.Map[Long, Set[String]]() ++ units.map(u => u.method.id -> direct(u))
    var changed = true
    while (changed) {
      changed = false
      units.foreach { u =>
        val more = calls(u.method).flatMap(targets).flatMap(t => takes.getOrElse(t.method.id, Set.empty[String])).toSet
        val now = takes(u.method.id) ++ more
        if (now != takes(u.method.id)) { takes(u.method.id) = now; changed = true }
      }
    }
    // (outer, inner, file, line): inner taken while outer is held.
    val nested = mutable.ListBuffer[(String, String, String, Int)]()
    units.foreach { u =>
      val f = u.file
      def taking(n: nodes.AstNode, held: List[String]): Unit =
        if (held.nonEmpty) calls(n).foreach { c =>
          val inner = (if (isAcquire(c)) receiver(c).map(lockName).toSet else Set.empty[String]) ++
            targets(c).flatMap(t => takes.getOrElse(t.method.id, Set.empty[String]))
          for (h <- held; i <- inner) nested += ((h, i, f, lineOf(c)))
        }
      def walk(stmts: List[St], held0: List[String]): Unit = {
        var held = held0
        var rest = stmts
        while (rest.nonEmpty) {
          val s = rest.head
          rest = rest.tail
          s match {
            case SWith(b, m, body, _) =>
              if (isLockWith(m)) {
                val l = lockName(m.code)
                held.foreach(h => nested += ((h, l, f, lineOf(b))))
                walk(body, l :: held)
              } else { taking(m, held); walk(body, held) }
            case SExpr(c: nodes.Call) if isAcquire(c) =>
              val l = lockName(receiver(c).get)
              taking(c, held)
              rest match {
                case (t: STry) :: after if t.fin.exists(fin => fin.headOption.exists { case SExpr(r: nodes.Call) => isRelease(r, l); case _ => false }) =>
                  walk(List(t), l :: held)
                  rest = after
                case _ => held = l :: held
              }
            case SExpr(c: nodes.Call) if isSourceCall(c) && c.name == "release" =>
              receiver(c).map(lockName).foreach(l => held = held.filterNot(_ == l))
              taking(c, held)
            case SIf(_, cond, t, e) => taking(cond, held); walk(t, held); walk(e, held)
            case SLoop(_, _, _, header, b, e) => taking(header, held); walk(b, held); walk(e, held)
            case STry(_, b, hs, e, fin) => walk(b, held); hs.foreach(h => walk(h._2, held)); walk(e, held); fin.foreach(walk(_, held))
            case other => taking(other.node, held)
          }
        }
      }
      walk(body(u.method), Nil)
    }
    val pairs = nested.map(n => (n._1, n._2)).toSet
    nested.toList.collect {
      case (a, b, f, line) if a == b || pairs((b, a)) =>
        Site(f, line, s"$b taken inside $a", false, if (a == b) "a lock taken while it is held" else s"$a and $b are taken in both orders", Nil)
    }.distinct
  }

  /** The construct threading_lock_with: a with on a module-level name bound once to threading.Lock(). */
  def lockConstruct(manager: nodes.Expression, f: String, names: Names): Option[String] = manager match {
    case i: nodes.Identifier => names.madeBy(f, i.name).filter(m => callee(m) == "threading.Lock" && args(m).isEmpty).map(_ => "threading_lock_with")
    case _ => None
  }

  def releaseSites(units: List[Fn], names: Names): List[Site] =
    units.flatMap { u =>
      val f = u.file
      val tree = body(u.method)
      val goodAcquires: Set[Long] = everyList(tree).flatMap { list =>
        list.zip(list.drop(1)).collect {
          case (SExpr(a: nodes.Call), STry(_, _, _, _, Some(fin))) if a.name == "acquire" && isSourceCall(a) && receiver(a).isDefined &&
              (fin.headOption match {
                case Some(SExpr(r: nodes.Call)) => r.name == "release" && isSourceCall(r) && receiver(r) == receiver(a)
                case _ => false
              }) => a.id
        }
      }.toSet
      val acquires = calls(u.method).filter(c => isSourceCall(c) && c.name == "acquire").map { a =>
        val what = s"acquire of ${receiver(a).getOrElse(a.code)}"
        if (goodAcquires(a.id)) good(f, a, what, List(Witness(f, lineOf(a), s"$what, released in the finally that follows it")))
        else bad(f, a, what, "not followed at once by a try whose finally first releases it")
      }
      val withs = under(u.method).collect { case b: nodes.Block => b }.l.flatMap(b => withManager(b).map(m => (b, m)))
        .filter { case (_, m) => isLockWith(m) }
        .map { case (b, m) => good(f, b, s"with ${m.code}", List(Witness(f, lineOf(b), s"with ${m.code}", lockConstruct(m, f, names)))) }
      acquires ++ withs
    }

  // =====================================================================================
  // await_has_timeout
  // =====================================================================================
  // Modules whose functions do not wait on anything outside the process, or end on their own.
  val QuietModules = Set("asyncio", "uuid", "secrets", "hashlib", "hmac", "itertools", "functools", "math", "json",
                         "re", "random", "logging", "collections", "typing", "dataclasses", "string", "time", "datetime",
                         "decimal", "enum", "copy", "base64", "operator", "statistics")
  // Calls that block until something outside answers, whatever their receiver.
  def isBlockingLibrary(name: String): Boolean =
    name.startsWith("requests.") || name.startsWith("httpx.") || name == "urllib.request.urlopen" ||
      name == "socket.create_connection" || name.matches("subprocess\\.(run|call|check_call|check_output)")
  // What an awaitable passed to them is waited on through.
  val Wrappers = Set("wait_for", "gather", "shield", "create_task", "ensure_future")

  def awaitHasTimeout(cpg: Cpg): List[Site] = {
    val src = new Source(cpg)
    val units = methods(cpg)
    val consts = new Constants(units)
    val names = new Names(cpg, units)
    val byName: Map[String, List[Fn]] = units.groupBy(_.method.name)
    /** The construct asyncio_wait_for: the library's own wait_for, with a finite limit nothing else sets. */
    def waitConstruct(c: nodes.Call, f: String): Option[String] =
      if (callee(c) == "asyncio.wait_for" && names.module(f, "asyncio") &&
          keyword(c, "timeout").orElse(positional(c).lift(1)).exists(names.number(f, _))) Some("asyncio_wait_for") else None
    units.flatMap { u =>
      val f = u.file
      val all = under(u.method)
      val ps = params(u.method)
      // The awaited expressions: the outermost expression that starts just after the word await.
      val awaitedAt = all.collect { case e: nodes.Expression if !e.isInstanceOf[nodes.Block] && src.awaited(f, e) => e }
      val outer = awaitedAt.filter { e =>
        e.astParent match {
          case p: nodes.Expression => !(p.lineNumber == e.lineNumber && p.columnNumber == e.columnNumber && awaitedAt.exists(_.id == p.id))
          case _ => true
        }
      }
      val outerIds = outer.map(_.id).toSet
      val awaitedNames = outer.collect { case i: nodes.Identifier => i.name }.toSet
      def timeoutBlock(e: nodes.AstNode): Boolean = {
        val chain = ancestors(e)
        (e :: chain).zip(chain).zip(chain.drop(1)).exists {
          case ((inner, t: nodes.ControlStructure), b: nodes.Block) =>
            t.controlStructureType == "TRY" && kids(t).headOption.exists(_.id == inner.id) &&
              withManager(b).exists {
                case c: nodes.Call => callee(c) == "asyncio.timeout" && positional(c).size == 1 && consts.limit(positional(c).head, u)
                case _ => false
              }
          case _ => false
        }
      }
      def wrapper(c: nodes.Call): Boolean = isSourceCall(c) && Wrappers(c.name)
      def limited(c: nodes.Call): Boolean =
        keyword(c, "timeout").orElse(if (c.name == "wait_for") positional(c).lift(1) else None).exists(consts.limit(_, u))

      // Is the value of a name possibly something from outside the function?
      def outsideName(name: String, seen: Set[String]): Boolean =
        if (ps.contains(name) || name == "self") true
        else if (seen(name)) false
        else {
          val defs = defsOf(u.method, name)
          if (defs.isEmpty) !QuietModules(name)
          else defs.exists(d => !isAssign(d) || argAt(d, 2).exists(v => outsideRoot(v.code, seen + name)))
        }
      def outsideRoot(text: String, seen: Set[String]): Boolean = rootOf(text) match {
        case Some((name, false)) => outsideName(name, seen)
        case Some((name, true)) => ps.contains(name)
        case None => false
      }
      // A call that can block: on an outside object, or of a blocking library. Not a builtin, not a
      // function of the repository, not a call on a value the function made itself.
      def mayBlock(c: nodes.Call): Boolean = isSourceCall(c) && {
        val name = callee(c)
        isBlockingLibrary(name) || (receiver(c) match {
          case None => ps.contains(name)
          case Some("self") => !byName.contains(c.name)
          case Some(r) => outsideRoot(r, Set.empty)
        })
      }
      // Is the call's value waited on: awaited itself, through a wrapper, or through a local that is awaited?
      def waitedOn(c: nodes.Call): Boolean =
        outerIds(c.id) || (c.astParent match {
          case p: nodes.Call if wrapper(p) =>
            if (p.name == "wait_for") positional(p).headOption.exists(_.id == c.id) else positional(p).exists(_.id == c.id)
          case p: nodes.Call if isAssign(p) && argAt(p, 2).exists(_.id == c.id) =>
            argAt(p, 1).exists { case i: nodes.Identifier => awaitedNames(i.name); case _ => false }
          case _ => false
        })

      val awaits = outer.flatMap { e =>
        val what = s"await ${e.code}"
        e match {
          case c: nodes.Call if callee(c) == "asyncio.sleep" && positional(c).size == 1 && args(c).size == 1 &&
              consts.limit(positional(c).head, u) => None
          case c: nodes.Call if c.name == "wait_for" && callee(c).endsWith("wait_for") && limited(c) &&
              positional(c).nonEmpty && args(c).filterNot(_.id == positional(c).head.id).forall(a => calls(a).forall(k => !isSourceCall(k))) =>
            Some(good(f, e, what, List(Witness(f, lineOf(e), s"$what, with a limit on the wait", waitConstruct(c, f)))))
          case c: nodes.Call if isSourceCall(c) && !wrapper(c) && limited(c) =>
            Some(good(f, e, what, List(Witness(f, lineOf(e), s"$what, with its own timeout"))))
          case _ if timeoutBlock(e) => Some(good(f, e, what, List(Witness(f, lineOf(e), s"$what, in a timeout block"))))
          case _ => Some(bad(f, e, what, "no limit on this wait"))
        }
      }
      val plain = calls(u.method).filter(c => mayBlock(c) && !waitedOn(c)).map { c =>
        val what = s"call ${c.code}"
        if (limited(c) && c.name != "wait_for") good(f, c, what, List(Witness(f, lineOf(c), s"$what, with its own timeout")))
        else bad(f, c, what, "a call that can block, with no limit")
      }
      // async for on something outside also waits on it.
      val asyncFors = everySt(body(u.method)).collect {
        case SLoop(n, _, true, it, _, _) if src.lines(f).lift(lineOf(n) - 1).exists(_.trim.startsWith("async for")) =>
          bad(f, n, s"async for over ${it.code}", "an async for: each step is a wait")
      }
      awaits ++ plain ++ asyncFors
    }
  }

  // =====================================================================================
  // retry_bounded
  // =====================================================================================
  /** n += c, or n = n + c, with c a positive number written in the source. */
  def increment(e: nodes.AstNode, n: String): Boolean = {
    def positive(x: Option[nodes.Expression]) = x.exists(v => isNumber(v) && scala.util.Try(v.code.replace("_", "").toDouble > 0).getOrElse(false))
    def isN(x: Option[nodes.Expression]) = x.exists { case i: nodes.Identifier => i.name == n; case _ => false }
    e match {
      case c: nodes.Call if c.name == "<operator>.assignmentPlus" => isN(argAt(c, 1)) && positive(argAt(c, 2))
      case c: nodes.Call if isAssign(c) && isN(argAt(c, 1)) => argAt(c, 2) match {
        case Some(add: nodes.Call) if add.name == "<operator>.addition" =>
          isN(argAt(add, 1)) && positive(argAt(add, 2)) || positive(argAt(add, 1)) && isN(argAt(add, 2))
        case _ => false
      }
      case _ => false
    }
  }

  final case class Flow(normal: Set[Boolean], back: Set[Boolean], raised: Set[Boolean], unknown: Boolean) {
    def ++(o: Flow) = Flow(normal ++ o.normal, back ++ o.back, raised ++ o.raised, unknown || o.unknown)
  }
  val NoFlow = Flow(Set.empty, Set.empty, Set.empty, false)

  /** On every path through stmts from states, is n raised? Exceptions may leave any statement. */
  def flow(stmts: List[St], states: Set[Boolean], n: String): Flow =
    stmts.foldLeft(Flow(states, Set.empty, Set.empty, false)) { (acc, s) =>
      if (acc.normal.isEmpty) acc
      else {
        val r = step(s, acc.normal, n)
        Flow(r.normal, acc.back ++ r.back, acc.raised ++ r.raised, acc.unknown || r.unknown)
      }
    }

  def step(s: St, in: Set[Boolean], n: String): Flow = s match {
    case SExpr(e) => Flow(if (increment(e, n)) Set(true) else in, Set.empty, in, false)
    case SIf(_, _, t, e) => flow(t, in, n) ++ flow(e, in, n) ++ Flow(Set.empty, Set.empty, in, false)
    case SLoop(_, _, _, _, _, _) => Flow(in, Set.empty, in, false)     // a def of n inside it is refused elsewhere
    case STry(_, b, hs, e, fin) =>
      val inBody = flow(b, in, n)
      val handled = hs.map(h => flow(h._2, inBody.raised, n)).foldLeft(NoFlow)(_ ++ _)
      val orElse = flow(e, inBody.normal, n)
      val before = Flow(orElse.normal ++ handled.normal, inBody.back ++ orElse.back ++ handled.back,
                        inBody.raised ++ handled.raised ++ orElse.raised, inBody.unknown || handled.unknown || orElse.unknown)
      fin match {
        case None => before
        case Some(f) =>
          val all = before.normal ++ before.back ++ before.raised
          val through = flow(f, all, n)
          Flow(flow(f, before.normal, n).normal, flow(f, before.back, n).normal ++ through.back,
               flow(f, before.raised, n).normal ++ through.raised, before.unknown || through.unknown)
      }
    case SWith(_, _, b, _) =>
      val r = flow(b, in, n)
      Flow(r.normal ++ r.raised, r.back, in ++ r.raised, r.unknown)    // __exit__ may swallow an exception
    case SReturn(_) => Flow(Set.empty, Set.empty, in, false)
    case SRaise(_) => Flow(Set.empty, Set.empty, in, false)
    case SJump(_, true) => Flow(Set.empty, in, Set.empty, false)
    case SJump(_, false) => Flow(Set.empty, Set.empty, Set.empty, false)
    case SUnknown(_) => Flow(in, in, in, true)
  }

  /** The construct range_of_numbers: a for over the builtin range of numbers written in the header. */
  def loopConstruct(l: SLoop, f: String, names: Names): Option[String] = l.header match {
    case c: nodes.Call if l.isFor && callee(c) == "range" && names.builtin(f, "range") && args(c).nonEmpty &&
        args(c).forall { case n: nodes.Literal => n.code.matches("[0-9]{1,4}"); case _ => false } => Some("range_of_numbers")
    case _ => None
  }

  def retryBounded(cpg: Cpg): List[Site] = {
    val units = methods(cpg)
    val consts = new Constants(units)
    val names = new Names(cpg, units)
    units.flatMap { u =>
      val f = u.file
      val loops = everySt(body(u.method)).collect { case l: SLoop => l }
      def why(l: SLoop): Option[String] =
        if (l.isFor) l.header match {
          case c: nodes.Call if callee(c) == "range" && args(c).nonEmpty && args(c).forall(a => a.argumentIndex >= 1 && consts.constant(a, u)) => None
          case _ => Some(s"for over ${l.header.code}, not over a range of constants")
        }
        else l.header match {
          case c: nodes.Call if Set("<operator>.lessThan", "<operator>.lessEqualsThan")(c.name) =>
            (argAt(c, 1), argAt(c, 2)) match {
              case (Some(v: nodes.Identifier), Some(bound)) if consts.constant(bound, u) =>
                val name = v.name
                val inLoop = (l.body ++ l.orElse).flatMap(s => calls(s.node)).filter(c => isAssignFamily(c) &&
                  argAt(c, 1).exists { case i: nodes.Identifier => i.name == name; case _ => false })
                val nestedDefs = everySt(l.body).collect { case inner: SLoop => inner }.exists(inner =>
                  calls(inner.node).exists(c => isAssignFamily(c) && argAt(c, 1).exists { case i: nodes.Identifier => i.name == name; case _ => false }))
                if (inLoop.exists(c => !increment(c, name))) Some(s"$name is set in the loop other than by a rise")
                else if (nestedDefs) Some(s"$name changes in a nested loop")
                else {
                  val r = flow(l.body, Set(false), name)
                  if (r.unknown) Some("a statement this query cannot read")
                  else if ((r.normal ++ r.back).contains(false)) Some(s"a path around the loop does not raise $name")
                  else None
                }
              case _ => Some(s"while ${c.code}, not a counter under a constant")
            }
          case other => Some(s"while ${other.code}")
        }
      val verdicts: Map[Long, (SLoop, Option[String])] = loops.map(l => l.loop.id -> (l, why(l))).toMap
      // Every WHILE in the raw graph, so that a loop the statement tree did not read is not missed.
      val whiles = under(u.method).collect { case cs: nodes.ControlStructure if cs.controlStructureType == "WHILE" => cs }.l
      def region(w: nodes.ControlStructure): nodes.AstNode = verdicts.get(w.id).map(_._1.node).getOrElse(w)
      // Whatever the call is named: a try in the loop around a call, whose handler can come back round.
      def comesBack(w: nodes.ControlStructure): Boolean = verdicts.get(w.id) match {
        case Some((l, _)) => everySt(l.body ++ l.orElse).exists {
          case STry(_, b, hs, _, _) => b.exists(s => calls(s.node).exists(isSourceCall)) && hs.exists { h =>
            val (normal, cont) = ends(h._2); normal || cont }
          case _ => false
        }
        // A loop the statement tree did not read: any try with a handler in it may come back round.
        case None => under(w).exists {
          case cs: nodes.ControlStructure => cs.controlStructureType == "TRY" && kids(cs).exists(k => ctype(k) == "CATCH")
          case _ => false
        }
      }
      whiles.filter(w => calls(region(w)).exists(isToolCall) || comesBack(w)).map { w =>
        val r = region(w)
        val what = s"loop on line ${lineOf(r)}"
        val nested = whiles.filter(o => o.id != w.id && under(r).exists(_.id == o.id))
        verdicts.get(w.id) match {
          case None => bad(f, r, what, "a loop this query cannot read")
          case Some((_, Some(reason))) => bad(f, r, what, reason)
          case Some((l, None)) =>
            // The nested loops are part of the bound, so each must be of the construct too.
            val construct = (l :: nested.flatMap(o => verdicts.get(o.id).map(_._1))).map(loopConstruct(_, f, names))
              .reduce((a, b) => if (b.isDefined) a else None)
            nested.find(o => verdicts.get(o.id).forall(_._2.isDefined)) match {
              case Some(o) => bad(f, r, what, s"the loop nested on line ${lineOf(o)} may be endless")
              case None => good(f, r, what, List(Witness(f, lineOf(r), s"$what, bounded", construct)))
            }
        }
      }
    }
  }

  // =====================================================================================
  // status_before_retry
  // =====================================================================================
  def isStatus(c: nodes.Call): Boolean = isSourceCall(c) && words(c.name).contains("status")
  def isRefund(c: nodes.Call): Boolean = isSourceCall(c) && words(c.name).contains("refund")
  /** A refund, a tool call, or (whatever its name) the call the try made, made again. */
  def isAction(c: nodes.Call, again: Set[String]): Boolean = isRefund(c) || (isToolCall(c) || isSourceCall(c) && again(callee(c))) && !isStatus(c)
  def acts(stmts: List[St], again: Set[String]): Boolean = stmts.exists(s => calls(s.node).exists(c => isAction(c, again)))

  /** (may end normally, may continue the enclosing loop). Unknown statements may do both. */
  def ends(stmts: List[St]): (Boolean, Boolean) =
    stmts.foldLeft((true, false)) { case ((normal, cont), s) =>
      if (!normal) (normal, cont)
      else {
        val (n2, c2) = endsOne(s)
        (n2, cont || c2)
      }
    }

  def endsOne(s: St): (Boolean, Boolean) = s match {
    case SReturn(_) | SRaise(_) => (false, false)
    case SJump(_, isContinue) => (false, isContinue)
    case SIf(_, _, t, e) => val (a, b) = ends(t); val (c, d) = ends(e); (a || c, b || d)
    case STry(_, b, hs, e, fin) =>
      val parts = (b :: e :: fin.toList) ++ hs.map(_._2)
      val all = parts.map(ends)
      val finEnds = fin.forall(f => ends(f)._1)
      ((ends(b)._1 || hs.exists(h => ends(h._2)._1)) && finEnds, all.exists(_._2))
    case SWith(_, _, b, _) => (true, ends(b)._2)
    case SLoop(_, _, _, _, _, _) => (true, false)
    case SUnknown(_) => (true, true)
    case SExpr(_) => (true, false)
  }

  def statusBeforeRetry(cpg: Cpg): List[Site] =
    methods(cpg).flatMap { u =>
      val f = u.file
      val visited = mutable.Set[Long]()
      def walk(stmts: List[St], inLoop: Boolean): List[Site] = stmts.flatMap {
        case t @ STry(cs, b, hs, e, fin) =>
          visited += cs.id
          // Whatever its name: any call the try body makes.
          val again = b.flatMap(s => calls(s.node)).filter(c => isSourceCall(c) && !isStatus(c)).map(callee).toSet
          val around = b.exists(s => calls(s.node).exists(isSourceCall))
          val here = if (!around) Nil else hs.flatMap { case (catchNode, h) =>
            val (normal, cont) = ends(h)
            val site = acts(h, again) || inLoop && (normal || cont)
            if (!site) None else Some(judgeHandler(f, catchNode, b, h, inLoop, again))
          } ++ fin.filter(x => around && acts(x, again)).map(x => bad(f, cs, s"finally on line ${lineOf(cs)}", "a finally that retries or refunds")).toList
          here ++ walk(b, inLoop) ++ hs.flatMap(h => walk(h._2, inLoop)) ++ walk(e, inLoop) ++ fin.toList.flatMap(walk(_, inLoop))
        case SIf(_, _, t, e) => walk(t, inLoop) ++ walk(e, inLoop)
        case SLoop(_, _, _, _, b, e) => walk(b, true) ++ walk(e, inLoop)
        case SWith(_, _, b, _) => walk(b, inLoop)
        case _ => Nil
      }
      val found = walk(body(u.method), false)
      // Every try with a handler in the raw graph, so that one the statement tree did not read is not missed.
      val missed = under(u.method).collect {
        case cs: nodes.ControlStructure if cs.controlStructureType == "TRY" && !visited(cs.id) &&
            kids(cs).exists(k => ctype(k) == "CATCH") && calls(cs).exists(isSourceCall) =>
          bad(f, cs, s"try on line ${lineOf(cs)}", "a try this query cannot read")
      }.l
      found ++ missed
    }

  /** The construct status_of_the_same_call: the try makes one call, and the handler asks its receiver
    * about its first argument, a name nothing in the handler or the try sets. */
  def statusConstruct(q: nodes.Call, tried: List[St], h: List[St]): Option[String] =
    tried.flatMap(s => calls(s.node)).filter(isSourceCall) match {
      case List(c) =>
        val same = for {
          r <- receiver(c); s <- receiver(q) if r == s && bareName(r).isDefined
          a <- positional(c).headOption.collect { case i: nodes.Identifier => i.name }
          b <- positional(q).headOption.collect { case i: nodes.Identifier => i.name } if a == b
        } yield Set(r, a)
        val set = (tried ++ h).flatMap(s => calls(s.node)).filter(isAssignFamily).flatMap(argAt(_, 1))
          .collect { case i: nodes.Identifier => i.name }.toSet
        same.filter(ns => ns.intersect(set).isEmpty).map(_ => "status_of_the_same_call")
      case _ => None
    }

  def judgeHandler(f: String, catchNode: nodes.ControlStructure, tried: List[St], h: List[St], inLoop: Boolean, again: Set[String]): Site = {
    val what = s"handler on line ${lineOf(catchNode)}"
    // The status query comes first, and an if on its answer comes next (or holds it).
    val decision: Option[(nodes.Call, SIf, List[St])] = h match {
      case SExpr(a: nodes.Call) :: (i: SIf) :: rest if isAssign(a) =>
        (argAt(a, 1), argAt(a, 2)) match {
          case (Some(v: nodes.Identifier), Some(q: nodes.Call)) if isStatus(q) && !calls(q).exists(c => isAction(c, again)) &&
              idents(i.cond).exists(_.name == v.name) => Some((q, i, rest))
          case _ => None
        }
      case (i: SIf) :: rest =>
        calls(i.cond).find(isStatus).map(q => (q, i, rest))
      case _ => None
    }
    decision match {
      case None => bad(f, catchNode, what, "the handler does not start by asking the status")
      case Some((q, i, rest)) =>
        if (calls(i.cond).exists(c => isAction(c, again))) bad(f, catchNode, what, "the test itself retries or refunds")
        else {
          val (restNormal, restCont) = ends(rest)
          val restActs = acts(rest, again) || inLoop && (restNormal || restCont)
          def never(branch: List[St]): Boolean = {
            val (normal, cont) = ends(branch)
            !acts(branch, again) && !(inLoop && cont) && (!normal || !restActs)
          }
          if (never(i.thn) || never(i.els))
            good(f, catchNode, what, List(Witness(f, lineOf(q), s"status ${q.code} decides the retry or refund", statusConstruct(q, tried, h))))
          else bad(f, catchNode, what, "the retry or refund happens whatever the status says")
        }
    }
  }
}
