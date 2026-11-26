// Shared reading of a JavaScript or TypeScript code property graph (jssrc2cpg) for the six premise
// queries of task E8.
//
// Each query script in kamanu/evidence/queries_js/ includes this file and calls one of the six
// functions at the end. A function lists every site of its premise in the repository, each judged
// good or bad, and report() writes the witnesses only when there is a site and every site is good.
// One bad site, or a construct this file cannot read, silences the query for the whole repository:
// there is no fact that says a premise failed, and silence is read as failure.
//
// The rule behind every function is the one of E2: sites are found liberally, and a site is good
// only when it has one of a few shapes read exactly. Anything else is bad. So a shape this file
// does not know costs a missing fact, never a false one, within the vocabulary of the gate.
//
// The graph is first read back into a small syntax tree (E for expressions, S for statements),
// which undoes what jssrc2cpg lowers:
//   object literal  a Block of `_tmp.key = value` assignments ending in `_tmp`     -> Obj
//   array literal   a Block of `_tmp = __ecma.Array.factory()` and `_tmp.push(x)`  -> Arr
//   new C(args)     a Block of `_tmp = .alloc` and an <operator>.new call          -> New
//   a.f().g()       the receiver of g is `(_tmp = a.f())`                          -> Field(Call)
//   Promise.race    a call with no callee node, its full name Promise.race         -> Field(Id)
//   String(x)       a call with no callee node, its full name String               -> Id
//   await x         kept, as <operator>.await                                      -> Await
//   catch (e)       a Block whose first child is the identifier e                  -> Handler
// Anything else that this reading does not know becomes Other, and every check treats Other as
// unknown: never a mint, never a limit, never a bound.
//
// What the graph says that is not code: an interface's or a type literal's methods are METHOD
// nodes whose body Block has no line. They are left out everywhere. A function declaration is
// also an assignment `function f = <METHOD_REF>` in the file's :program method; that is how a
// call f(...) is tied to a function of the repository.
//
// Closures: a function written inside another can change its variables and make its calls. So a
// variable is tied to one value only when no function inside reassigns it (allDefs), and a retry,
// a refund or a counter read inside a callback counts where the callback is written (deepCalls).
//
// Diagnostics: when KAMANU_QUERY_SITES names a directory, every site with its verdict and reason
// is written to <directory>/<query>.sites.jsonl. This never changes the answer in `out`.

import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.codepropertygraph.generated.nodes
import io.shiftleft.semanticcpg.language._
import java.nio.file.{Files, Paths}
import scala.collection.mutable

object PremisesJs {

  // ---------------- what a query reports ----------------
  final case class Witness(file: String, line: Int, subject: String)
  final case class Site(file: String, line: Int, what: String, good: Boolean, why: String, witnesses: List[Witness])

  def lineOf(n: nodes.AstNode): Int = n.lineNumber.map(_.intValue).getOrElse(0)
  def colOf(n: nodes.AstNode): Int = n.columnNumber.map(_.intValue).getOrElse(0)
  def pos(n: nodes.AstNode): (Int, Int) = (lineOf(n), colOf(n))
  def before(a: nodes.AstNode, b: nodes.AstNode): Boolean = Ordering[(Int, Int)].lt(pos(a), pos(b))
  def short(text: String): String = text.replaceAll("\\s+", " ").take(160)

  def badSite(f: String, n: nodes.AstNode, what: String, why: String): Site = Site(f, lineOf(n), what, false, why, Nil)

  def goodSite(f: String, n: nodes.AstNode, what: String, witnesses: List[Witness]): Site =
    if (witnesses.isEmpty || witnesses.exists(_.line <= 0)) Site(f, lineOf(n), what, false, "no witness line", Nil)
    else Site(f, lineOf(n), what, true, "", witnesses)

  def report(query: String, out: String, sites: List[Site]): Unit = {
    val proven = sites.nonEmpty && sites.forall(_.good)
    val rows =
      if (!proven) Nil
      else sites.flatMap(_.witnesses).distinct.map(w => ujson.Obj("file" -> w.file, "line" -> w.line, "subject" -> w.subject).toString)
    Files.write(Paths.get(out), rows.map(_ + "\n").mkString.getBytes("UTF-8"))
    sys.env.get("KAMANU_QUERY_SITES").filter(_.nonEmpty).foreach { dir =>
      val lines = sites.map { s =>
        ujson.Obj("file" -> s.file, "line" -> s.line, "what" -> s.what, "good" -> s.good, "why" -> s.why,
                  "witnesses" -> ujson.Arr.from(s.witnesses.map(w => ujson.Arr(w.file, w.line)))).toString
      }
      Files.write(Paths.get(dir).resolve(query + ".sites.jsonl"), lines.map(_ + "\n").mkString.getBytes("UTF-8"))
    }
  }

  // ---------------- the syntax tree read back from the graph ----------------
  sealed trait E { def n: nodes.AstNode }
  final case class Id(name: String, n: nodes.AstNode) extends E
  final case class Lit(text: String, n: nodes.AstNode) extends E
  final case class Field(obj: E, name: String, n: nodes.AstNode) extends E
  final case class Index(obj: E, key: E, n: nodes.AstNode) extends E
  final case class Call(callee: E, args: List[E], n: nodes.AstNode) extends E
  final case class New(ctor: E, args: List[E], n: nodes.AstNode) extends E
  final case class Await(e: E, n: nodes.AstNode) extends E
  final case class Obj(entries: List[(String, E)], n: nodes.AstNode) extends E
  final case class Arr(elems: List[E], n: nodes.AstNode) extends E
  final case class Fn(method: Option[nodes.Method], n: nodes.AstNode) extends E
  final case class Op(op: String, args: List[E], n: nodes.AstNode) extends E
  final case class Assign(op: String, target: E, value: E, n: nodes.AstNode) extends E
  final case class Other(n: nodes.AstNode) extends E

  sealed trait S { def n: nodes.AstNode }
  final case class Blk(body: List[S], n: nodes.AstNode) extends S
  final case class Ex(e: E, n: nodes.AstNode) extends S
  final case class If(cond: E, thenS: S, elseS: Option[S], n: nodes.AstNode) extends S
  final case class While(cond: E, body: S, n: nodes.AstNode) extends S
  final case class DoWhile(body: S, cond: E, n: nodes.AstNode) extends S
  final case class For(init: List[S], cond: Option[E], update: List[S], body: S, n: nodes.AstNode) extends S
  final case class Try(body: S, handler: Option[Handler], fin: Option[S], n: nodes.AstNode) extends S
  final case class Handler(param: Option[String], body: List[S], n: nodes.AstNode)
  final case class Switch(on: E, cases: List[Case], n: nodes.AstNode) extends S
  final case class Case(test: Option[E], body: List[S])
  final case class Return(e: Option[E], n: nodes.AstNode) extends S
  final case class Throw(e: Option[E], n: nodes.AstNode) extends S
  final case class Jump(kind: String, n: nodes.AstNode) extends S
  final case class Unread(n: nodes.AstNode) extends S

  def isOp(c: nodes.Call): Boolean = c.name.startsWith("<operator>")
  def opName(c: nodes.Call): String = c.name.stripPrefix("<operator>.")

  def argIndex(n: nodes.AstNode): Int = n match {
    case e: nodes.Expression => e.argumentIndex
    case _                   => -1
  }

  /** The children that are code, in order. */
  def kids(n: nodes.AstNode): List[nodes.AstNode] =
    n.astChildren.l.filter {
      case _: nodes.Local | _: nodes.Modifier | _: nodes.MethodReturn | _: nodes.MethodParameterIn |
           _: nodes.MethodParameterOut | _: nodes.TypeDecl | _: nodes.Method | _: nodes.Import | _: nodes.Annotation => false
      case _ => true
    }.sortBy(_.order)

  val TmpName = "_tmp_\\d+".r

  def isTmp(e: E): Boolean = e match {
    case Id(name, _) => TmpName.matches(name)
    case _           => false
  }

  final class Reader(byFullName: Map[String, nodes.Method]) {
    def expr(n: nodes.AstNode): E = n match {
      case i: nodes.Identifier => Id(i.name, i)
      case l: nodes.Literal    => Lit(l.code, l)
      case r: nodes.MethodRef  => Fn(byFullName.get(r.methodFullName), r)
      case c: nodes.Call       => call(c)
      case b: nodes.Block      => blockExpr(b)
      case other               => Other(other)
    }

    /** The receiver chain of a.f() is lowered through `(_tmp = a)`: read it back as a. */
    private def unwrap(n: nodes.AstNode): E = expr(n) match {
      case Assign("assignment", t, v, _) if isTmp(t) => v
      case e                                         => e
    }

    private def call(c: nodes.Call): E = {
      val ks = kids(c)
      if (isOp(c)) opName(c) match {
        case "fieldAccess" =>
          (ks.headOption, ks.lift(1)) match {
            case (Some(o), Some(f: nodes.FieldIdentifier)) => Field(unwrap(o), f.canonicalName, c)
            case _                                         => Other(c)
          }
        case "indexAccess" if ks.size == 2 => Index(unwrap(ks(0)), expr(ks(1)), c)
        case "await" if ks.size == 1       => Await(expr(ks(0)), c)
        case op if op.startsWith("assignment") && ks.size == 2 => Assign(op, expr(ks(0)), expr(ks(1)), c)
        case "new" =>
          ks.find(k => k.order == 1 && argIndex(k) == -1) match {
            case Some(ctor) => New(expr(ctor), ks.filter(k => argIndex(k) >= 1).sortBy(argIndex).map(expr), c)
            case None       => Other(c)
          }
        case op => Op(op, ks.sortBy(k => (argIndex(k), k.order)).map(expr), c)
      }
      else {
        val args = ks.filter(k => argIndex(k) >= 1).sortBy(argIndex).map(expr)
        val callee = ks.find(k => k.order == 1 && argIndex(k) == -1) match {
          case Some(k) => unwrap(k)
          case None if c.methodFullName.matches("[A-Za-z_$][\\w$]*(\\.[A-Za-z_$][\\w$]*)+") && c.methodFullName.endsWith("." + c.name) =>
            val parts = c.methodFullName.split("\\.").toList
            parts.tail.foldLeft(Id(parts.head, c): E)((o, p) => Field(o, p, c))
          case None if IdentRe.matches(c.name) && c.methodFullName == c.name => Id(c.name, c)   // String(x), Number(x)
          case None => Other(c)
        }
        if (c.name.isEmpty) Other(c) else Call(callee, args, c)
      }
    }

    private def blockExpr(b: nodes.Block): E = {
      val ks = kids(b)
      ks.lastOption match {
        case Some(last: nodes.Identifier) if TmpName.matches(last.name) && ks.size >= 2 =>
          val tmp = last.name
          val body = ks.init.map(expr)
          def onTmp(e: E) = e match { case Id(`tmp`, _) => true; case _ => false }
          body match {
            case Assign("assignment", Id(`tmp`, _), v, _) :: rest if (v.n match {
                  case f: nodes.Call => f.name == "__ecma.Array.factory"
                  case _             => false
                }) =>
              val pushes = ks.init.drop(1)
              val elems = pushes.map {
                case p: nodes.Call if p.name.isEmpty && kids(p).exists(k => argIndex(k) == 1) =>
                  Some(expr(kids(p).filter(k => argIndex(k) == 1).head))
                case _ => None
              }
              if (elems.forall(_.isDefined)) Arr(elems.flatten, b) else Other(b)
            case List(Assign("assignment", Id(`tmp`, _), Op("alloc", _, _), _), nw: New) => New(nw.ctor, nw.args, b)
            case entries if entries.forall {
                  case Assign("assignment", Field(o, _, _), _, _) => onTmp(o)
                  case _                                          => false
                } =>
              Obj(entries.collect { case Assign(_, Field(_, key, _), v, _) => key -> v }, b)
            case _ => Other(b)
          }
        case _ => Other(b)
      }
    }

    // ---------- statements ----------
    def stmt(n: nodes.AstNode): S = n match {
      case b: nodes.Block => Blk(kids(b).map(stmt), b)
      case r: nodes.Return => Return(kids(r).headOption.map(expr), r)
      case cs: nodes.ControlStructure => control(cs)
      case e: nodes.Expression => Ex(expr(e), e)
      case other => Unread(other)
    }

    private def control(cs: nodes.ControlStructure): S = {
      val ks = kids(cs)
      cs.controlStructureType match {
        case "IF" if ks.size >= 2 => If(expr(ks(0)), stmt(ks(1)), ks.lift(2).map(stmt), cs)
        case "WHILE" if ks.size == 2 => While(expr(ks(0)), stmt(ks(1)), cs)
        case "DO" if ks.size == 2 => DoWhile(stmt(ks(0)), expr(ks(1)), cs)
        case "FOR" if ks.size == 4 =>
          def part(k: nodes.AstNode): List[S] = k match {
            case b: nodes.Block if kids(b).isEmpty => Nil
            case b: nodes.Block                    => kids(b).map(stmt)
            case other                             => List(stmt(other))
          }
          val cond = ks(1) match {
            case b: nodes.Block if kids(b).isEmpty => None
            case k                                 => Some(expr(k))
          }
          For(part(ks(0)), cond, part(ks(2)), stmt(ks(3)), cs)
        case "TRY" =>
          val body = ks.headOption.map(stmt).getOrElse(Unread(cs))
          val handler = ks.collectFirst { case h: nodes.ControlStructure if h.controlStructureType == "CATCH" => h }.map(catchOf)
          val fin = ks.collectFirst { case f: nodes.ControlStructure if f.controlStructureType == "FINALLY" => f }
            .map(f => kids(f).headOption.map(stmt).getOrElse(Unread(f)))
          if (ks.headOption.exists(_.isInstanceOf[nodes.ControlStructure])) Unread(cs) else Try(body, handler, fin, cs)
        case "SWITCH" if ks.size == 2 =>
          ks(1) match {
            case b: nodes.Block =>
              val cases = mutable.ListBuffer[Case]()
              var current: Option[(Option[E], mutable.ListBuffer[S])] = None
              var expectTest = false
              var ok = true
              kids(b).foreach {
                case j: nodes.JumpTarget =>
                  current.foreach { case (t, body) => cases += Case(t, body.toList) }
                  if (j.code.trim.startsWith("default")) { current = Some((None, mutable.ListBuffer())); expectTest = false }
                  else if (j.code.trim.startsWith("case")) { current = None; expectTest = true }
                  else ok = false
                case k if expectTest =>
                  current = Some((Some(expr(k)), mutable.ListBuffer())); expectTest = false
                case k =>
                  current match {
                    case Some((_, body)) => body += stmt(k)
                    case None            => ok = false
                  }
              }
              current.foreach { case (t, body) => cases += Case(t, body.toList) }
              if (ok && !expectTest) Switch(expr(ks(0)), cases.toList, cs) else Unread(cs)
            case _ => Unread(cs)
          }
        case "THROW" => Throw(ks.headOption.map(expr), cs)
        case "CONTINUE" => Jump("continue", cs)
        case "BREAK" => Jump("break", cs)
        case _ => Unread(cs)
      }
    }

    private val CatchParam = "(?s)catch\\s*\\(\\s*([A-Za-z_$][\\w$]*)\\s*(?::[^)]*)?\\)\\s*\\{.*".r

    private def catchOf(h: nodes.ControlStructure): Handler = {
      val body = kids(h).headOption match {
        case Some(b: nodes.Block) => kids(b)
        case _                    => Nil
      }
      h.code match {
        case CatchParam(name) =>
          body match {
            case (i: nodes.Identifier) :: rest if i.name == name => Handler(Some(name), rest.map(stmt), h)
            case _                                                 => Handler(Some(name), body.map(stmt), h)
          }
        case _ => Handler(None, body.map(stmt), h)
      }
    }
  }

  // ---------------- walking the tree ----------------
  /** e and every expression under it, without entering a function. */
  def subE(e: E): List[E] = e :: (e match {
    case Field(o, _, _)     => subE(o)
    case Index(o, k, _)     => subE(o) ++ subE(k)
    case Call(c, as, _)     => subE(c) ++ as.flatMap(subE)
    case New(c, as, _)      => subE(c) ++ as.flatMap(subE)
    case Await(x, _)        => subE(x)
    case Obj(es, _)         => es.flatMap(kv => subE(kv._2))
    case Arr(xs, _)         => xs.flatMap(subE)
    case Op(_, as, _)       => as.flatMap(subE)
    case Assign(_, t, v, _) => subE(t) ++ subE(v)
    case _                  => Nil
  })

  def childStmts(s: S): List[S] = s match {
    case Blk(b, _)              => b
    case If(_, t, e, _)         => t :: e.toList
    case While(_, b, _)         => List(b)
    case DoWhile(b, _, _)       => List(b)
    case For(i, _, u, b, _)     => i ++ u ++ List(b)
    case Try(b, h, f, _)        => b :: h.toList.flatMap(_.body) ++ f.toList
    case Switch(_, cs, _)       => cs.flatMap(_.body)
    case _                      => Nil
  }

  def ownExprs(s: S): List[E] = s match {
    case Ex(e, _)           => List(e)
    case If(c, _, _, _)     => List(c)
    case While(c, _, _)     => List(c)
    case DoWhile(_, c, _)   => List(c)
    case For(_, c, _, _, _) => c.toList
    case Switch(o, cs, _)   => o :: cs.flatMap(_.test)
    case Return(e, _)       => e.toList
    case Throw(e, _)        => e.toList
    case _                  => Nil
  }

  def allStmts(s: S): List[S] = s :: childStmts(s).flatMap(allStmts)
  def allExprs(s: S): List[E] = allStmts(s).flatMap(ownExprs).flatMap(subE)
  def allExprs(ss: List[S]): List[E] = ss.flatMap(allExprs)
  def calls(s: S): List[Call] = allExprs(s).collect { case c: Call => c }
  def calls(ss: List[S]): List[Call] = ss.flatMap(calls)
  def hasUnread(s: S): Boolean = allStmts(s).exists(_.isInstanceOf[Unread])

  // ---------------- names ----------------
  val IdentRe = "[A-Za-z_$][A-Za-z0-9_$]*".r

  def words(id: String): Seq[String] =
    id.split("[_\\-$]").toSeq.flatMap(_.split("(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")).map(_.toLowerCase).filter(_.nonEmpty)

  def stripStrings(text: String): String =
    text.replaceAll("\"(?:[^\"\\\\]|\\\\.)*\"|'(?:[^'\\\\]|\\\\.)*'|`(?:[^`\\\\]|\\\\.)*`", "\"\"")

  def textWords(text: String): Seq[String] = IdentRe.findAllIn(stripStrings(text)).toSeq.flatMap(words)

  val ToolWords = Set("tool", "tools", "gateway")
  val CounterWords = Set("ledger", "quota", "budget", "spend", "counter")
  val SettledWords = Set("settled", "succeeded", "completed", "paid", "success")

  /** The dotted names of an expression as written: this.paymentGateway.charge. Unknown parts give
    * the words of their code, so that a site is never missed for want of a reading. */
  def pathNames(e: E): List[String] = e match {
    case Id(n, _)       => List(n)
    case Field(o, f, _) => pathNames(o) :+ f
    case Call(c, _, _)  => pathNames(c)
    case Index(o, _, _) => pathNames(o)
    case Await(x, _)    => pathNames(x)
    case other          => IdentRe.findAllIn(stripStrings(other.n.code)).toList
  }

  def pathWords(c: Call): Seq[String] = pathNames(c.callee).flatMap(words)

  /** The callee as written, for telling one callee from another. */
  def render(e: E): String = e match {
    case Id(n, _)       => n
    case Field(o, f, _) => render(o) + "." + f
    case Lit(t, _)      => t
    case other          => short(other.n.code)
  }

  def lastName(e: E): Option[String] = e match {
    case Id(n, _)       => Some(n)
    case Field(_, f, _) => Some(f)
    case _              => None
  }

  def method(c: Call): Option[String] = c.callee match {
    case Field(_, f, _) => Some(f)
    case Id(n, _)       => Some(n)
    case _              => None
  }

  def receiver(c: Call): Option[E] = c.callee match {
    case Field(o, _, _) => Some(o)
    case _              => None
  }

  def isToolCall(c: Call): Boolean = pathWords(c).exists(ToolWords)

  def strValue(e: E): Option[String] = e match {
    case Lit(t, _) if t.length >= 2 && "\"'`".contains(t.head) && t.last == t.head => Some(t.substring(1, t.length - 1))
    case _ => None
  }

  def isStrLit(e: E): Boolean = strValue(e).isDefined

  def sameText(a: E, b: E): Boolean = a.n.code.replaceAll("\\s+", "") == b.n.code.replaceAll("\\s+", "")

  // ---------------- functions, files, bindings ----------------
  final case class Fun(method: nodes.Method, file: String, body: S, params: List[String]) {
    lazy val exprs: List[E] = allExprs(body)
    lazy val stmts: List[S] = allStmts(body)
    lazy val callList: List[Call] = exprs.collect { case c: Call => c }

    /** The graph under what the reading could not take apart (Other, Unread), nested functions
      * left out: a site in there must silence the query, never be missed. */
    lazy val raw: List[nodes.AstNode] =
      method.astChildren.collect { case b: nodes.Block => b }.l.flatMap(rawSub)

    lazy val unreadRaw: List[nodes.AstNode] =
      (stmts.collect { case u: Unread => u.n } ++ exprs.collect { case o: Other => o.n }).flatMap(rawSub)
  }

  def rawSub(n: nodes.AstNode): List[nodes.AstNode] =
    n :: n.astChildren.l.filterNot(_.isInstanceOf[nodes.Method]).flatMap(rawSub)

  def rawCallNamed(n: nodes.AstNode, names: String => Boolean): Boolean = n match {
    case c: nodes.Call => names(c.name)
    case _             => false
  }

  def rawControl(n: nodes.AstNode, types: Set[String]): Boolean = n match {
    case cs: nodes.ControlStructure => types(cs.controlStructureType)
    case _                          => false
  }

  def unreadSite(fun: Fun, what: String, pred: nodes.AstNode => Boolean): Option[Site] =
    fun.unreadRaw.find(pred).map(n => badSite(fun.file, n, what, s"code this query does not read: ${short(n.code).take(80)}"))

  final class Program(cpg: Cpg) {
    val byFullName: Map[String, nodes.Method] = cpg.method.l.map(m => m.fullName -> m).toMap
    val reader = new Reader(byFullName)

    private def bodyBlock(m: nodes.Method): Option[nodes.Block] = m.astChildren.collect { case b: nodes.Block => b }.headOption

    /** Every function the source wrote, the file's top level (:program) included. Interface and
      * type literal members have a body with no line, and are left out; so has :program, which is
      * kept by its name. */
    val funs: List[Fun] = cpg.method.l.filterNot(_.isExternal).flatMap { m =>
      val file = m.filename
      bodyBlock(m) match {
        case Some(b) if (b.lineNumber.isDefined || m.name == ":program") && file.nonEmpty && file != "<unknown>" =>
          val ps = m.parameter.l.sortBy(_.index).filter(_.index >= 1).map(_.name)
          Some(Fun(m, file, reader.stmt(b), ps))
        case _ => None
      }
    }.sortBy(f => (f.file, lineOf(f.method), colOf(f.method), f.method.fullName))

    val byMethod: Map[String, Fun] = funs.map(f => f.method.fullName -> f).toMap

    def programOf(file: String): Option[Fun] = funs.find(f => f.file == file && f.method.name == ":program")

    /** The functions whose body holds fun, by full name. */
    def enclosing(fun: Fun): List[Fun] = {
      val full = fun.method.fullName
      funs.filter(o => o.method.fullName != full && full.startsWith(o.method.fullName + ":"))
    }

    def scopeParams(fun: Fun): Set[String] = (fun :: enclosing(fun)).flatMap(_.params).toSet

    private val DeclRe = "(?s)^\\s*(?:export\\s+)?(?:const|let|var)\\s+([A-Za-z_$][\\w$]*).*".r

    def declared(a: Assign): Option[String] = a.n.code match {
      case DeclRe(name) => Some(name)
      case _            => None
    }

    def isDecl(a: Assign): Boolean = a.target match {
      case Id(n, _) => declared(a).contains(n)
      case _        => false
    }

    /** Assignments to the plain name `name` in fun's own body, not in nested functions. */
    def defsIn(fun: Fun, name: String): List[Assign] =
      fun.exprs.collect { case a @ Assign(_, Id(`name`, _), _, _) => a }

    /** Names a function or one around it declares or takes, so that a module binding is hidden. */
    def shadowed(fun: Fun, name: String): Boolean =
      scopeParams(fun).contains(name) ||
        (fun :: enclosing(fun)).filterNot(_.method.name == ":program").exists(f => defsIn(f, name).nonEmpty)

    /** Every assignment to `name` anywhere in a file, in every function of it. */
    def fileAssigns(file: String, name: String): List[Assign] =
      funs.filter(_.file == file).flatMap(f => defsIn(f, name))

    /** Module constants: `const NAME = <number>` at a file's top level, never assigned again. */
    def moduleNumber(fun: Fun, name: String): Option[Double] =
      if (shadowed(fun, name)) None
      else programOf(fun.file).flatMap { p =>
        fileAssigns(fun.file, name) match {
          case List(a @ Assign("assignment", _, Lit(t, _), _)) if defsIn(p, name).contains(a) && a.n.code.trim.startsWith("const ") ||
              defsIn(p, name).contains(a) && a.n.code.trim.startsWith("export const ") =>
            number(t)
          case _ => None
        }
      }

    def number(text: String): Option[Double] =
      if (text.matches("\\d+(\\.\\d+)?") || text.matches("\\d+(_\\d+)+")) Some(text.replace("_", "").toDouble) else None

    /** A positive number literal, or a module constant bound to one. */
    def positiveNumber(fun: Fun, e: E): Boolean = e match {
      case Lit(t, _) => number(t).exists(_ > 0)
      case Id(n, _)  => moduleNumber(fun, n).exists(_ > 0)
      case _         => false
    }

    def numberish(fun: Fun, e: E): Boolean = e match {
      case Lit(t, _) => number(t).isDefined
      case Id(n, _)  => moduleNumber(fun, n).isDefined
      case _         => false
    }

    /** A name that no code of the file binds: a global such as crypto, setTimeout, AbortSignal. */
    def global(fun: Fun, name: String): Boolean =
      !shadowed(fun, name) && fileAssigns(fun.file, name).isEmpty && !funs.exists(f => f.file == fun.file && f.params.contains(name))

    /** Top-level bindings `var x = require("m").y` (an ES import) and `var x = require("m")`. */
    def imported(fun: Fun, name: String): Option[(String, Option[String])] =
      if (shadowed(fun, name)) None
      else programOf(fun.file).flatMap { p =>
        fileAssigns(fun.file, name) match {
          case List(a) if defsIn(p, name).contains(a) =>
            a.value match {
              case Field(Call(Id("require", _), List(m), _), y, _) => strValue(m).map(_ -> Some(y))
              case Call(Id("require", _), List(m), _)              => strValue(m).map(_ -> None)
              case _                                               => None
            }
          case _ => None
        }
      }

    /** The function of the repository a call f(...) names: a function declared in the same file. */
    def callee(fun: Fun, c: Call): Option[Fun] = c.callee match {
      case Id(name, _) if !scopeParams(fun).contains(name) =>
        programOf(fun.file).flatMap { p =>
          fileAssigns(fun.file, name) match {
            case List(Assign("assignment", _, Fn(Some(m), _), _)) => byMethod.get(m.fullName)
            case _                                               => None
          }
        }
      case _ => None
    }

    /** The function a function value names: an arrow or function expression, or a declared function. */
    def fnValue(e: E): Option[Fun] = e match {
      case Fn(Some(m), _) => byMethod.get(m.fullName)
      case _              => None
    }

    def returns(fun: Fun): List[Return] = allStmts(fun.body).collect { case r: Return => r }

    /** The functions written inside fun, at any depth. */
    def nested(fun: Fun): List[Fun] = funs.filter(_.method.fullName.startsWith(fun.method.fullName + ":"))

    /** Assignments to `name` in fun and in every function written inside it: a closure can change
      * a variable of the function around it. */
    def allDefs(fun: Fun, name: String): List[Assign] = defsIn(fun, name) ++ nested(fun).flatMap(defsIn(_, name))

    /** The calls in ss and in every function value written in ss, at any depth: a callback's call is
      * made too (setTimeout(() => tool.charge(k)), arr.map(k => ledger.get(k))). */
    def deepCalls(ss: List[S], seen: Set[String] = Set()): List[Call] = {
      val fns = allExprs(ss).collect { case f: Fn => f }.flatMap(fnValue).filterNot(g => seen(g.method.fullName))
      calls(ss) ++ fns.flatMap(g => deepCalls(List(g.body), seen ++ fns.map(_.method.fullName)))
    }

    def topStmts(fun: Fun): List[S] = fun.body match {
      case Blk(b, _) => b
      case s         => List(s)
    }
  }

  // ======================= session_key_minted =======================
  val SessionPartWords = Set("key", "id", "token")

  def isSessionName(name: String): Boolean = {
    val ws = words(name)
    ws.contains("session") && ws.exists(SessionPartWords)
  }

  def sessionKeyMinted(cpg: Cpg): List[Site] = {
    val p = new Program(cpg)
    val sites = mutable.ListBuffer[Site]()

    val Mints = Set("randomUUID", "randomBytes")
    val CryptoModules = Set("node:crypto", "crypto")

    def mintCall(fun: Fun, c: Call): Boolean = c.callee match {
      case Id(x, _) =>
        p.imported(fun, x).exists { case (m, y) => CryptoModules(m) && y.exists(Mints) }
      case Field(Id(x, _), f, _) if Mints(f) =>
        p.imported(fun, x).exists { case (m, y) => CryptoModules(m) && y.isEmpty } ||
          (x == "crypto" && f == "randomUUID" && p.global(fun, "crypto"))
      case _ => false
    }

    /** The mint calls that make e minted, or None when e is not minted. */
    def minted(fun: Fun, e: E, seen: Set[String]): Option[List[Call]] = e match {
      case c: Call if mintCall(fun, c) => Some(List(c))
      case Call(Field(recv, _, _), args, _) if args.forall(a => isStrLit(a) || a.isInstanceOf[Lit]) =>
        minted(fun, recv, seen)
      case Op("addition", List(a, b), _) =>
        (minted(fun, a, seen), minted(fun, b, seen)) match {
          case (Some(x), Some(y))              => Some(x ++ y)
          case (Some(x), None) if isStrLit(b)  => Some(x)
          case (None, Some(y)) if isStrLit(a)  => Some(y)
          case _                               => None
        }
      case Id(v, _) if !seen(v) && !p.scopeParams(fun).contains(v) =>
        p.allDefs(fun, v) match {
          case List(a @ Assign("assignment", _, value, _)) if p.isDecl(a) => minted(fun, value, seen + v)
          case _                                                         => None
        }
      case _ => None
    }

    /** A generator: a function value every return of which is minted. */
    def generated(fn: Fun): Option[List[Call]] = {
      val rs = p.returns(fn)
      val ms = rs.map(r => r.e.flatMap(x => minted(fn, x, Set())))
      if (rs.nonEmpty && ms.forall(_.isDefined) && !hasUnread(fn.body)) Some(ms.flatten.flatten) else None
    }

    def judgeValue(fun: Fun, at: nodes.AstNode, what: String, value: E): Site = {
      val mints = value match {
        case f: Fn => p.fnValue(f).flatMap(generated)
        case v     => minted(fun, v, Set())
      }
      mints match {
        case Some(cs) => goodSite(fun.file, at, what, cs.map(c => Witness(fun.file, lineOf(c.n), s"$what minted by ${short(c.n.code)}")))
        case None     => badSite(fun.file, at, what, "a value that is not minted on the server")
      }
    }

    /** A local session key with no declaring value must be given one on every path: an if with an
      * else, each branch assigning it at its top. */
    def everyPath(fun: Fun, name: String, defs: List[Assign]): Boolean =
      defs.exists(p.isDecl) || p.topStmts(fun).exists {
        case If(_, t, Some(e), _) =>
          def direct(s: S): List[Assign] = (s match { case Blk(b, _) => b; case o => List(o) }).collect {
            case Ex(a @ Assign(_, Id(`name`, _), _, _), _) => a
          }
          val d = direct(t) ++ direct(e)
          direct(t).nonEmpty && direct(e).nonEmpty && defs.forall(x => d.exists(_.n.id == x.n.id))
        case _ => false
      }

    def callerRoot(fun: Fun, e: E): Boolean = {
      val ps = p.scopeParams(fun) - "this"
      def root(x: E): Boolean = x match {
        case Id(n, _)       => ps.contains(n)
        case Field(o, _, _) => root(o)
        case Index(o, _, _) => root(o)
        case _              => false
      }
      root(e)
    }

    def hasSession(s: String): Boolean = s.toLowerCase.contains("session")

    for (fun <- p.funs) {
      sites ++= unreadSite(fun, "session code", {
        case i: nodes.Identifier      => isSessionName(i.name)
        case f: nodes.FieldIdentifier => isSessionName(f.canonicalName)
        case l: nodes.Literal         => hasSession(l.code)
        case _                        => false
      })
      if (fun.method.name != ":program")
        fun.params.filter(isSessionName).foreach { name =>
          sites += badSite(fun.file, fun.method, s"session key parameter $name", "a parameter is the caller's value")
        }
      fun.exprs.foreach {
        case a @ Assign(op, target, value, n) if lastName(target).exists(isSessionName) && (target match {
              case Id(_, _) | Field(_, _, _) => true
              case _                         => false
            }) =>
          val what = s"session key ${render(target)}"
          if (op != "assignment") sites += badSite(fun.file, n, what, "not a plain assignment")
          else {
            val site = judgeValue(fun, n, what, value)
            target match {
              case Id(name, _) if site.good && !everyPath(fun, name, p.defsIn(fun, name)) =>
                sites += badSite(fun.file, n, what, "not given a value on every path")
              case _ => sites += site
            }
          }
        case Obj(entries, n) =>
          entries.filter(kv => isSessionName(kv._1)).foreach { case (key, value) =>
            sites += judgeValue(fun, n, s"session key $key in an object", value)
          }
        case Field(x, name, n) if isSessionName(name) && callerRoot(fun, x) =>
          sites += badSite(fun.file, n, s"read of ${render(x)}.$name", "a session value read from the caller")
        case Index(x, key, n) if strValue(key).exists(hasSession) && callerRoot(fun, x) =>
          sites += badSite(fun.file, n, s"read of ${short(n.code)}", "a session value read from the caller")
        case c @ Call(Field(x, m, _), args, n) if Set("get", "header")(m) && args.headOption.flatMap(strValue).exists(hasSession) &&
              callerRoot(fun, x) =>
          sites += badSite(fun.file, n, s"read of ${short(n.code)}", "a session value read from the caller")
        case _ =>
      }
    }
    sites.toList
  }

  // ======================= check_act_atomic =======================
  val Reads = Set("get", "read", "total", "value")
  val AbsWrites = Set("set", "put", "write")
  val AtomicWrites = Set("incr", "incrBy", "incrby", "add", "decr", "decrBy", "decrby")
  val PairWrites = Set("set", "put", "write", "incr", "incrBy", "incrby", "add")

  def checkActAtomic(cpg: Cpg): List[Site] = {
    val p = new Program(cpg)
    val sites = mutable.ListBuffer[Site]()

    def counter(c: Call): Boolean = receiver(c).flatMap(lastName).exists(n => words(n).exists(CounterWords))

    for (fun <- p.funs) {
      sites ++= unreadSite(fun, "counter code", n => rawCallNamed(n, x => Reads(x) || AbsWrites(x) || AtomicWrites(x)))
      val cs = fun.callList
      val deep = p.deepCalls(List(fun.body))
      val counterReads = deep.filter(c => counter(c) && method(c).exists(Reads))
      val unread = hasUnread(fun.body)
      cs.foreach { c =>
        val m = method(c).getOrElse("")
        if (counter(c) && (AbsWrites(m) || AtomicWrites(m))) {
          val what = s"counter write ${render(c.callee)}"
          if (AbsWrites(m)) sites += badSite(fun.file, c.n, what, "an absolute write")
          else if (counterReads.nonEmpty) sites += badSite(fun.file, c.n, what, s"a read of the counter in the same function: ${short(counterReads.head.n.code)}")
          else if (unread) sites += badSite(fun.file, c.n, what, "a function this query cannot read whole")
          else sites += goodSite(fun.file, c.n, what, List(Witness(fun.file, lineOf(c.n), s"$what, one atomic operation that answers with the count")))
        }
      }
      for {
        g <- deep if method(g).contains("get") && receiver(g).isDefined && g.args.nonEmpty
        w <- deep if method(w).exists(PairWrites) && receiver(w).isDefined && w.args.nonEmpty && sameText(g.args.head, w.args.head)
      } sites += badSite(fun.file, w.n, s"read-then-write of ${short(g.args.head.n.code)}", s"${short(g.n.code)} then ${short(w.n.code)}")
    }
    sites.toList
  }

  // ======================= release_post_dominates =======================
  def lockName(e: E): String = render(e).stripPrefix("this.")

  def releasePostDominates(cpg: Cpg): List[Site] = {
    val p = new Program(cpg)
    val sites = mutable.ListBuffer[Site]()
    // (outer, inner) -> where the inner lock is taken while the outer is held
    val edges = mutable.LinkedHashMap[(String, String), (String, nodes.AstNode)]()
    def edge(outer: String, inner: String, file: String, at: nodes.AstNode): Unit =
      if (!edges.contains(outer -> inner)) edges(outer -> inner) = (file, at)

    def isAcquire(c: Call) = method(c).contains("acquire") && receiver(c).isDefined
    def isRunExclusive(c: Call) = method(c).contains("runExclusive") && receiver(c).isDefined

    /** The locks a region takes: acquires and runExclusives in it, and through calls of functions
      * of the repository, the locks those take. */
    def takenIn(fun: Fun, ss: List[S], seen: Set[String]): Set[String] =
      calls(ss).flatMap { c =>
        val own = if (isAcquire(c) || isRunExclusive(c)) receiver(c).map(lockName).toSet else Set[String]()
        val viaFn = c.args.collect { case f: Fn => f }.flatMap(f => p.fnValue(f)).flatMap(g =>
          if (seen(g.method.fullName)) Set[String]() else takenIn(g, List(g.body), seen + g.method.fullName))
        val viaCall = (p.callee(fun, c).toList ++ thisCallee(fun, c)).flatMap(g =>
          if (seen(g.method.fullName)) Set[String]() else takenIn(g, List(g.body), seen + g.method.fullName))
        own ++ viaFn ++ viaCall
      }.toSet

    def thisCallee(fun: Fun, c: Call): List[Fun] = c.callee match {
      case Field(Id("this", _), name, _) =>
        val cls = fun.method.fullName.split(":").dropRight(1).mkString(":")
        p.funs.filter(g => g.method.name == name && g.method.fullName.startsWith(cls + ":"))
      case _ => Nil
    }

    def releases(s: S, rel: Option[String], lock: String): Boolean = s match {
      case Ex(Call(Id(r, _), _, _), _) => rel.contains(r)
      case Ex(c @ Call(Field(o, "release", _), _, _), _) => lockName(o) == lock
      case _ => false
    }

    def blocks(s: S): List[List[S]] = allStmts(s).collect { case Blk(b, _) => b }

    for (fun <- p.funs) {
      sites ++= unreadSite(fun, "lock code", n => rawCallNamed(n, x => x == "acquire" || x == "runExclusive"))
      // every acquire, wherever it stands
      calls(fun.body).foreach { c =>
        if (isRunExclusive(c)) {
          val lock = receiver(c).map(lockName).getOrElse("")
          val held = c.args.collect { case f: Fn => f }.flatMap(f => p.fnValue(f))
          held.foreach(g => takenIn(g, List(g.body), Set(g.method.fullName)).foreach(inner => edge(lock, inner, fun.file, c.n)))
          sites += goodSite(fun.file, c.n, s"runExclusive on $lock", List(Witness(fun.file, lineOf(c.n), s"${short(c.n.code.takeWhile(_ != '('))}, released by runExclusive")))
        }
      }
      val placed = mutable.Set[Long]()
      blocks(fun.body).foreach { b =>
        b.zipWithIndex.foreach { case (s, i) =>
          val found: Option[(Option[String], Call)] = s match {
            case Ex(Assign("assignment", Id(r, _), Await(c: Call, _), _), _) if isAcquire(c) => Some((Some(r), c))
            case Ex(Await(c: Call, _), _) if isAcquire(c)                                    => Some((None, c))
            case _                                                                           => None
          }
          found.foreach { case (rel, c) =>
            placed += c.n.id
            val lock = receiver(c).map(lockName).getOrElse("")
            val what = s"acquire of $lock"
            b.lift(i + 1) match {
              case Some(t @ Try(body, handler, Some(fin), _)) if (fin match {
                    case Blk(first :: _, _) => releases(first, rel, lock)
                    case other              => releases(other, rel, lock)
                  }) && !hasUnread(t) =>
                val region = body :: handler.toList.flatMap(_.body)
                takenIn(fun, region, Set(fun.method.fullName)).foreach(inner => edge(lock, inner, fun.file, c.n))
                sites += goodSite(fun.file, c.n, what, List(Witness(fun.file, lineOf(c.n), s"$what, released in the finally that follows it")))
              case _ =>
                sites += badSite(fun.file, c.n, what, "the next statement is not a try whose finally releases it first")
            }
          }
        }
      }
      calls(fun.body).filter(c => isAcquire(c) && !placed(c.n.id)).foreach { c =>
        sites += badSite(fun.file, c.n, s"acquire ${short(c.n.code)}", "an acquire this query does not read")
      }
    }
    // kit 2: no lock is held forever. Two locks taken one inside the other in both orders (or one
    // inside itself) is a cycle of the nesting order.
    val names = edges.keys.flatMap(e => List(e._1, e._2)).toSet
    val reach = mutable.Map[String, Set[String]]()
    names.foreach { a =>
      val seen = mutable.Set[String]()
      val stack = mutable.Stack[String](a)
      while (stack.nonEmpty) {
        val x = stack.pop()
        edges.keys.filter(_._1 == x).map(_._2).foreach(y => if (seen.add(y)) stack.push(y))
      }
      reach(a) = seen.toSet
    }
    val cyclic = names.filter(a => reach(a).contains(a))
    edges.foreach { case ((a, b), (file, at)) =>
      if (cyclic(a) && cyclic(b) && reach(b).contains(a))
        sites += badSite(file, at, s"$b taken while $a is held", s"locks taken in both orders: ${cyclic.toList.sorted.mkString(", ")}")
    }
    sites.toList
  }

  // ======================= await_has_timeout =======================
  val SyncCalls = Set("execSync", "execFileSync", "spawnSync")

  def awaitHasTimeout(cpg: Cpg): List[Site] = {
    val p = new Program(cpg)
    val sites = mutable.ListBuffer[Site]()

    def abortTimeout(fun: Fun, e: E): Boolean = e match {
      case Call(Field(Id("AbortSignal", _), "timeout", _), List(n), _) => p.global(fun, "AbortSignal") && p.positiveNumber(fun, n)
      case _ => false
    }

    def limited(fun: Fun, c: Call): Boolean = c.args.exists {
      case a if abortTimeout(fun, a) => true
      case Obj(entries, _) =>
        entries.exists {
          case ("signal", v)  => abortTimeout(fun, v)
          case ("timeout", v) => p.positiveNumber(fun, v)
          case _              => false
        }
      case _ => false
    }

    def isPromise(fun: Fun, e: E, name: String) = e match {
      case Call(Field(Id("Promise", _), `name`, _), List(_), _) => p.global(fun, "Promise")
      case _                                                    => false
    }

    def bodyCall(fn: Fun): Option[Call] = p.topStmts(fn) match {
      case List(Ex(c: Call, _))           => Some(c)
      case List(Return(Some(c: Call), _)) => Some(c)
      case _                              => None
    }

    /** setTimeout(cb, delay) from the global timers, cb calling one of the given settle functions. */
    def settledBy(fn: Fun, c: Call, delay: E => Boolean): Boolean = c match {
      case Call(Id("setTimeout", _), List(cb, d), _) if p.global(fn, "setTimeout") && delay(d) =>
        val settle = fn.params.toSet
        cb match {
          case Id(r, _) => settle(r)
          case f: Fn =>
            p.fnValue(f).flatMap(bodyCall).exists {
              case Call(Id(r, _), _, _) => settle(r)
              case _                    => false
            }
          case _ => false
        }
      case _ => false
    }

    /** new Promise(r => setTimeout(r, n)), n a number: a sleep that ends on its own. */
    def sleep(fun: Fun, e: E): Boolean = e match {
      case New(Id("Promise", _), List(f: Fn), _) if p.global(fun, "Promise") =>
        p.fnValue(f).exists(fn => bodyCall(fn).exists(c => settledBy(fn, c, d => p.numberish(fun, d))))
      case Call(Id(x, _), List(n), _) =>
        p.imported(fun, x).exists { case (m, y) => Set("node:timers/promises", "timers/promises")(m) && y.contains("setTimeout") } &&
          p.numberish(fun, n)
      case _ => false
    }

    /** A call of a function of the repository that returns a new Promise settled by setTimeout
      * after its parameter, given a positive number there. */
    def timer(fun: Fun, e: E): Boolean = e match {
      case c: Call =>
        p.callee(fun, c).exists { g =>
          p.topStmts(g) match {
            case List(Return(Some(New(Id("Promise", _), List(f: Fn), _)), _)) if p.global(g, "Promise") =>
              p.fnValue(f).exists { fn =>
                bodyCall(fn).exists { sc =>
                  settledBy(fn, sc, {
                    case Id(param, _) =>
                      val i = g.params.indexOf(param)
                      i >= 0 && !p.defsIn(g, param).nonEmpty && c.args.lift(i).exists(a => p.positiveNumber(fun, a))
                    case _ => false
                  })
                }
              }
            case _ => false
          }
        }
      case _ => false
    }

    def judgeCall(fun: Fun, c: Call): Boolean =
      if (isPromise(fun, c, "race")) c.args.head match {
        case Arr(xs, _) => xs.exists(x => timer(fun, x))
        case _          => false
      }
      else if (isPromise(fun, c, "all")) c.args.head match {
        case Arr(xs, _) => xs.nonEmpty && xs.forall { case x: Call => limited(fun, x) && !isPromise(fun, x, "race") && !isPromise(fun, x, "all"); case _ => false }
        case _          => false
      }
      else limited(fun, c)

    for (fun <- p.funs) {
      allExprs(fun.body).foreach {
        case Await(inner, n) =>
          val what = s"await ${short(inner.n.code).take(80)}"
          inner match {
            case x if sleep(fun, x) => // a sleep that ends is no site
            case c: Call =>
              if (judgeCall(fun, c)) sites += goodSite(fun.file, n, what, List(Witness(fun.file, lineOf(c.n), s"$what, with a limit")))
              else sites += badSite(fun.file, n, what, "a wait with no limit")
            case Id(v, _) =>
              val held = p.allDefs(fun, v) match {
                case List(a @ Assign("assignment", _, c: Call, _)) if p.isDecl(a) && !p.scopeParams(fun).contains(v) => Some(c)
                case _                                                                                              => None
              }
              held match {
                case Some(c) if judgeCall(fun, c) => sites += goodSite(fun.file, n, what, List(Witness(fun.file, lineOf(n), s"$what, with a limit")))
                case _                            => sites += badSite(fun.file, n, what, "a wait on a value this query cannot tie to a limited call")
              }
            case _ => sites += badSite(fun.file, n, what, "a wait on something this query does not read")
          }
        case c: Call if method(c).exists(SyncCalls) =>
          val what = s"blocking call ${render(c.callee)}"
          val ok = c.args.exists {
            case Obj(entries, _) => entries.exists { case (k, v) => k == "timeout" && p.positiveNumber(fun, v) }
            case _               => false
          }
          if (ok) sites += goodSite(fun.file, c.n, what, List(Witness(fun.file, lineOf(c.n), s"$what, with a timeout")))
          else sites += badSite(fun.file, c.n, what, "a blocking call with no timeout")
        case _ =>
      }
      sites ++= unreadSite(fun, "wait", n => rawCallNamed(n, x => x == "<operator>.await" || SyncCalls(x)))
      // for await (x of it) waits on an iterator, and may leave no <operator>.await to find
      fun.raw.find(n => n.code.matches("(?s)for\\s+await\\b.*")).foreach { n =>
        sites += badSite(fun.file, n, "for await", "a wait on an iterator, with no limit this query reads")
      }
    }
    sites.toList
  }

  // ======================= retry_bounded =======================
  def retryBounded(cpg: Cpg): List[Site] = {
    val p = new Program(cpg)
    val sites = mutable.ListBuffer[Site]()

    def loops(s: S): List[S] = allStmts(s).filter {
      case _: While | _: DoWhile | _: For => true
      case _                              => false
    }

    def loopBody(l: S): S = l match {
      case While(_, b, _)     => b
      case DoWhile(b, _, _)   => b
      case For(_, _, _, b, _) => b
      case other              => other
    }

    /** Every assignment, ++ or -- of the name, in the statements given and in functions in them. */
    def touches(fun: Fun, ss: List[S], name: String): List[E] = {
      val own = allExprs(ss).filter {
        case Assign(_, Id(`name`, _), _, _) => true
        case Op(op, List(Id(`name`, _)), _) => op.contains("Increment") || op.contains("Decrement")
        case _                              => false
      }
      val nested = allExprs(ss).collect { case f: Fn => f }.flatMap(f => p.fnValue(f)).flatMap(g => touches(g, List(g.body), name))
      own ++ nested
    }

    def raise(e: E, name: String): Boolean = e match {
      case Op(op, List(Id(`name`, _)), _) => op == "postIncrement" || op == "preIncrement"
      case Assign("assignmentPlus", Id(`name`, _), Lit("1", _), _) => true
      case _ => false
    }

    def bound(fun: Fun, cond: E, name: String): Boolean = cond match {
      case Op("lessThan" | "lessEqualsThan", List(Id(`name`, _), b), _) => p.numberish(fun, b)
      case _                                                            => false
    }

    def numberInit(e: E): Boolean = e match {
      case Lit(t, _) => t.matches("\\d+")
      case _         => false
    }

    /** Why the loop is not of a bounded shape, or None when it is. */
    def unbounded(fun: Fun, l: S): Option[String] = {
      val nested = loops(loopBody(l)).filterNot(_ eq l)
      val shape: Option[String] = l match {
        case For(List(Ex(a @ Assign("assignment", Id(i, _), init, _), _)), Some(cond), List(Ex(step, _)), body, _)
            if p.isDecl(a) && numberInit(init) && bound(fun, cond, i) && raise(step, i) =>
          if (touches(fun, List(body), i).nonEmpty) Some(s"$i is assigned in the body") else None
        case While(cond @ Op(_, List(Id(n, _), _), _), body, _) if bound(fun, cond, n) && !p.scopeParams(fun).contains(n) =>
          val first = body match {
            case Blk(b, _) => b.headOption
            case o         => Some(o)
          }
          val init = p.defsIn(fun, n).filter(a => p.isDecl(a))
          if (!first.exists { case Ex(e, _) => raise(e, n); case _ => false }) Some(s"$n is not raised first on every pass")
          else if (!(init.size == 1 && numberInit(init.head.value) && before(init.head.n, l.n))) Some(s"$n does not start at a number")
          else if (touches(fun, List(fun.body), n).size != 2) Some(s"$n is assigned elsewhere")
          else None
        case _ => Some("not a bounded loop shape")
      }
      shape.orElse(nested.collectFirst(Function.unlift((x: S) => unbounded(fun, x).map(w => s"a loop inside it: $w"))))
        .orElse(if (hasUnread(l)) Some("code this query does not read") else None)
    }

    for (fun <- p.funs) sites ++= unreadSite(fun, "loop", n => rawControl(n, Set("WHILE", "FOR", "DO", "TRY")))
    for (fun <- p.funs; l <- loops(fun.body)) {
      val body = loopBody(l)
      val tool = calls(l).exists(isToolCall)
      val tries = allStmts(body).exists { case Try(_, Some(_), _, _) => true; case _ => false }
      if (tool || tries || hasUnread(l)) {
        val what = s"loop ${short(l.n.code).take(60)}"
        unbounded(fun, l) match {
          case None      => sites += goodSite(fun.file, l.n, what, List(Witness(fun.file, lineOf(l.n), s"$what, bounded")))
          case Some(why) => sites += badSite(fun.file, l.n, what, why)
        }
      }
    }
    sites.toList
  }

  // ======================= status_before_retry =======================
  def statusBeforeRetry(cpg: Cpg): List[Site] = {
    val p = new Program(cpg)
    val sites = mutable.ListBuffer[Site]()

    def isStatus(c: Call) = method(c).exists(n => words(n).contains("status"))
    def isRefund(c: Call) = method(c).exists(n => words(n).contains("refund"))

    def exits(s: S): Boolean = s match {
      case _: Return | _: Throw   => true
      case Blk(b, _)              => b.lastOption.exists(exits)
      case If(_, t, Some(e), _)   => exits(t) && exits(e)
      case _                      => false
    }

    def exitsAll(ss: List[S]): Boolean = ss.lastOption.exists(exits)

    def jumps(ss: List[S]): Boolean = ss.flatMap(allStmts).exists { case Jump("continue", _) => true; case _ => false }

    def settledTest(cond: E, v: String, equal: Boolean): Boolean = {
      val ops = if (equal) Set("equals", "strictEquals") else Set("notEquals", "strictNotEquals")
      cond match {
        case Op(op, List(Id(`v`, _), l), _) if ops(op) => strValue(l).exists(SettledWords)
        case Op(op, List(l, Id(`v`, _)), _) if ops(op) => strValue(l).exists(SettledWords)
        case _                                         => false
      }
    }

    /** Why the retries or refunds of the handler are not all on the side where v is not settled. */
    def unguarded(rest: List[S], v: String, retry: Call => Boolean, inLoop: Boolean): Option[String] = {
      var guarded = false
      def retries(ss: List[S]) = p.deepCalls(ss).exists(retry) || (inLoop && jumps(ss))
      for (s <- rest) {
        if (!guarded) s match {
          case If(cond, t, None, _) if settledTest(cond, v, equal = true) && exits(t) && !retries(List(t)) => guarded = true
          case If(cond, t, e, _) if settledTest(cond, v, equal = false) =>
            if (e.exists(x => retries(List(x)))) return Some("a retry where the status is settled")
          case Switch(Id(`v`, _), cases, _) if cases.exists(c => c.test.flatMap(strValue).exists(SettledWords)) =>
            val settled = cases.filter(c => c.test.flatMap(strValue).exists(SettledWords))
            if (!settled.forall(c => exitsAll(c.body) && !retries(c.body))) return Some("a settled case that goes on")
            guarded = true
          case other if retries(List(other)) => return Some(s"a retry or refund before the status decides: ${short(other.n.code).take(80)}")
          case _ =>
        }
      }
      if (inLoop && !guarded && !exitsAll(rest)) Some("the loop comes back round whatever the status says") else None
    }

    def tries(s: S, inLoop: Boolean): List[(Try, Boolean)] = s match {
      case t: Try => (t, inLoop) :: childStmts(t).flatMap(tries(_, inLoop))
      case While(_, b, _) => tries(b, true)
      case DoWhile(b, _, _) => tries(b, true)
      case For(i, _, u, b, _) => (i ++ u).flatMap(tries(_, inLoop)) ++ tries(b, true)
      case other => childStmts(other).flatMap(tries(_, inLoop))
    }

    for (fun <- p.funs) sites ++= unreadSite(fun, "handler", n => rawControl(n, Set("TRY")))
    for (fun <- p.funs; (t, inLoop) <- tries(fun.body, false); h <- t.handler) {
      val tried = calls(t.body).filterNot(c => isStatus(c))
      val names = tried.map(c => render(c.callee)).toSet
      def retry(c: Call) = names.contains(render(c.callee)) || isRefund(c)
      val afterIds = {
        val inside = (allExprs(t.body) ++ allExprs(h.body) ++ t.fin.toList.flatMap(allExprs)).map(_.n.id).toSet
        calls(fun.body).filter(c => !inside(c.n.id) && before(t.n, c.n) && names.contains(render(c.callee)))
      }
      val site = tried.nonEmpty && (p.deepCalls(h.body).exists(retry) || afterIds.nonEmpty || (inLoop && !exitsAll(h.body)))
      if (site) {
        val what = s"handler around ${tried.map(c => render(c.callee)).distinct.mkString(", ").take(80)}"
        h.body match {
          case Ex(Assign("assignment", Id(v, _), Await(q: Call, _), _), _) :: rest if isStatus(q) =>
            val reassigned = p.allDefs(fun, v).size != 1
            val why =
              if (afterIds.nonEmpty) Some(s"a retry after the handler: ${short(afterIds.head.n.code)}")
              else if (reassigned) Some(s"$v is assigned again")
              else if (hasUnread(t)) Some("code this query does not read")
              else unguarded(rest, v, retry, inLoop)
            why match {
              case None => sites += goodSite(fun.file, h.n, what, List(Witness(fun.file, lineOf(q.n), s"status ${short(q.n.code)} decides the retry or refund")))
              case Some(w) => sites += badSite(fun.file, h.n, what, w)
            }
          case _ => sites += badSite(fun.file, h.n, what, "the handler does not ask the status first")
        }
      }
    }
    sites.toList
  }
}
