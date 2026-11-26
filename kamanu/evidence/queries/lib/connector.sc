// Shared reading of an MCP server's code property graph for task T9: where the identity that scopes a
// data access comes from, and which accesses reach a tool's answer. Python and JavaScript. Used by
// identity_provenance.sc and tenant_sinks.sc of kamanu/evidence/queries/ and of queries_js/.
//
// The method is one abstract evaluator. A value is what an expression can be, and an expression is
// evaluated in a frame: a function and the calls that led to it from one tool's handler. So a helper
// two tools call is read twice, once with each caller's arguments, and a name never decides anything.
//
//   handler    the frame a tool starts in; its parameters are the sources (argument, or the context)
//   reach      every function a handler calls, at any depth, each in its own frame
//   access     a call that reads data (kindOf), with the values that scope it
//   answer     what the handler returns, and what any frame raises; an access reaches the answer when
//              evaluating the answer meets that access in that frame
//
// Definitions are found by walking the control flow backwards from the use, so a name bound again
// before the use has only its last binding. A container is read by key where the key is a literal.
// An access's result carries the origins of the values that scoped it, so a value looked up by an
// argument is still the argument's.
//
// What it does not know is never session. A value that can also be something opaque (an environment
// variable, an object the repository does not build, a call it cannot follow with nothing traced in
// its arguments) is not a session value. Not seen at all: code reached by dynamic dispatch, by
// inheritance or through a framework's dependency injection, and a tool registered in another way than
// handlers reads. A function that runs inside itself is entered once. A default value of a parameter is
// opaque, because pysrc2cpg leaves it out of the graph.
//
// Diagnostics: KAMANU_CONNECTOR_TRACE names a file the frames and values are appended to.

import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.codepropertygraph.generated.nodes.*
import io.shiftleft.semanticcpg.language.*
import java.nio.file.{Files, Paths, StandardOpenOption}
import scala.collection.mutable
import scala.util.Try

object Connector {
  // ---------------- values ----------------
  final case class Place(file: String, line: Int) { override def toString: String = s"$file:$line" }

  sealed trait Base
  final case class Src(kind: String, at: Place) extends Base            // session, argument or constant
  final case class Lit(at: Place) extends Base                          // a literal
  case object Other extends Base                                        // anything else
  case object Ctx extends Base                                          // Python's context object
  case object Extra extends Base                                        // JavaScript's second parameter
  final case class Rec(node: Long, frame: String) extends Base          // a tuple, list, dict or object literal
  final case class Obj(cls: String, call: Long, frame: String) extends Base
  final case class Keyed(key: String, v: V) extends Base                // what one key or field was set to
  final case class Acc(call: Long, frame: String) extends Base          // an access's result
  final case class Mod(method: Long) extends Base                       // a file of the repository
  final case class Fn(method: Long, frame: String) extends Base         // a function
  final case class Cls(name: String) extends Base                       // a class of the repository
  final case class Stmt(call: Long) extends Base                        // JavaScript: a prepared statement
  case object Http extends Base                                         // Python: a client of an HTTP library

  // steps: the lines where a call took the value into the next function. plain: it was only named,
  // bound, passed and read as a field on the way.
  final case class V(base: Base, steps: List[Place], plain: Boolean)
  type Vs = Set[V]
  val nothing: Vs = Set.empty
  val other: Vs = Set(V(Other, Nil, false))

  final case class Frame(key: String, method: Method, call: Option[Call], parent: Option[Frame], lex: Option[Frame],
                         self: Vs, bound: Option[Int => Vs], sure: Boolean, root: Boolean) {
    lazy val chain: List[Frame] = parent.map(_.chain).getOrElse(Nil) :+ this
  }
  final case class Access(call: Call, kind: String, frame: Frame, options: List[List[Vs]])
  final case class Tool(name: String, method: Method, frame: Frame)
  final case class Verdict(identity: String, source: Option[V], at: Option[Place])
  final case class Row(tool: String, kind: String, verdict: Verdict, access: Place, path: List[String],
                       construct: Option[String], answered: Boolean)
  final case class Target(method: Method, self: Vs, lex: Option[Frame], sure: Boolean, obj: Option[Obj] = None)

  sealed trait Def
  final case class Strong(e: AstNode) extends Def                                // the name was bound to it
  final case class Weak(e: AstNode, key: Option[Option[String]]) extends Def     // it was put in: under a key, or anyhow
  final case class Ran(c: Call) extends Def                                      // Python: the cursor ran this statement

  // ---------------- the vocabulary ----------------
  val AccountName = "(?i).*(tenant|user|account|owner).*".r
  val PyMutators = Set("append", "extend", "add", "insert", "update", "setdefault", "appendleft", "put", "write")
  val JsMutators = Set("push", "unshift", "add", "set", "append", "splice")
  val Flat = Set("join", "normpath", "abspath", "realpath", "joinpath", "resolve", "normalize", "Path", "PurePath",
                 "URL", "str", "String", "expanduser", "fspath", "toString")
  val OnReceiver = Set("joinpath", "resolve", "toString", "expanduser")
  val HttpVerbs = Set("get", "post", "put", "patch", "delete", "head", "options", "request", "stream")
  val Sql = "(?is)^[a-z]{0,2}[\"'`]{1,3}\\s*(select|insert|update|delete|with|replace|create|pragma)\\b.*".r
  val HttpClient = "(?s)(httpx\\.(Async)?Client|requests\\.[sS]ession|aiohttp\\.ClientSession)\\(.*".r
  val ContextType = "(?s)(.*[^A-Za-z0-9_])?Context([^A-Za-z0-9_].*)?".r
  val Generated = Set("<body>", "<fakeNew>", "<metaClassCallHandler>", "<metaClassAdapter>")
  val Transparent = Set("await", "expressionList", "cast", "formattedValue", "iterator", "starredUnpack").map("<operator>." + _)
  val Containers = Set("tupleLiteral", "listLiteral", "setLiteral", "dictLiteral").map("<operator>." + _)
  val Opaque = Set("equals", "notEquals", "lessThan", "greaterThan", "lessEqualsThan", "greaterEqualsThan", "logicalNot", "not", "in",
    "notIn", "is", "isNot", "instanceOf", "typeOf", "delete", "alloc", "import", "void").map("<operator>." + _)
  val Steps = 6000000
  val MostFrames = 60000
}

class Connector(cpg: Cpg) {
  import Connector.*

  private val language: String = cpg.metaData.language.l.mkString.toUpperCase
  private val js: Boolean = language.contains("JAVASCRIPT") || language.contains("JSSRC")
  private val sep: String = if (js) ":" else "."
  private val rootDir: String = cpg.metaData.root.l.headOption.getOrElse("").replace("\\", "/").stripSuffix("/")

  // ---------------- one memo for every recursive question ----------------
  // A question met again while it is being answered gives its least answer, and no answer that
  // depended on that is remembered, except the outermost one's.
  private var level = 0
  private var lowest = Int.MaxValue
  private var budget = Steps
  private class Memo[K, T](least: T) {
    private val done = mutable.HashMap[K, T]()
    private val active = mutable.HashMap[K, Int]()
    def apply(k: K)(compute: => T): T = done.get(k) match {
      case Some(v) => v
      case None => active.get(k) match {
        case Some(d) => lowest = math.min(lowest, d); least
        case None =>
          budget -= 1
          if (budget < 0) throw new RuntimeException("connector: this repository takes too many steps to evaluate")
          level += 1
          val d = level
          val before = lowest
          lowest = Int.MaxValue
          active(k) = d
          val v = try compute finally { active -= k; level -= 1 }
          if (lowest >= d) { done(k) = v; lowest = before } else lowest = math.min(lowest, before)
          v
      }
    }
  }

  // ---------------- the graph ----------------
  private def fileOf(m: Method): String = {
    val f = m.filename.replace("\\", "/")
    if (rootDir.nonEmpty && f.startsWith(rootDir + "/")) f.drop(rootDir.length + 1) else f
  }
  private val internal: List[Method] = cpg.method.l.filter(m => !m.isExternal && {
    val f = fileOf(m); f.endsWith(".py") || f.matches(".*\\.([cm]?[jt]s|[jt]sx)")
  })
  private val byId: Map[Long, Method] = internal.map(m => m.id -> m).toMap
  private val byFull: Map[String, List[Method]] = internal.groupBy(_.fullName)
  private val modules: List[Method] = internal.filter(m => m.name == "<module>" || m.name == ":program")
  private val moduleIds: Set[Long] = modules.map(_.id).toSet
  private val moduleOf: Map[String, Method] = modules.map(m => fileOf(m) -> m).toMap
  private val functions: List[Method] = internal.filterNot(m => Generated(m.name) || moduleIds(m.id))
  private val sameFile: Map[String, List[Method]] = functions.groupBy(fileOf)
  private def classOf(full: String): String = full.take(math.max(0, full.lastIndexOf(sep)))
  private def isCtor(m: Method): Boolean = m.name == "__init__" || m.name == "<init>"
  private val classNames: Set[String] =
    (functions.filter(isCtor) ++ internal.filter(_.name == "<body>")).map(m => classOf(m.fullName)).toSet

  private def lineOf(n: AstNode): Int = n.lineNumber.getOrElse(0)
  private def place(n: AstNode, m: Method): Place = Place(fileOf(m), lineOf(n))
  private def parentNode(n: AstNode): Option[AstNode] = n._astIn.collect { case a: AstNode => a }.l.headOption
  private val lexicals = mutable.HashMap[Long, Option[Method]]()
  /** The function (or file) a function is written in. A class's body is not one. */
  private def lexicalParent(m: Method): Option[Method] = lexicals.getOrElseUpdate(m.id, {
    var n = parentNode(m)
    while (n.exists { case p: Method => Generated(p.name); case _ => true }) n = n.flatMap(parentNode)
    n.collect { case p: Method => p }
  })
  private def moduleFor(m: Method): Option[Method] = moduleOf.get(fileOf(m))

  private val ownCalls = mutable.HashMap[Long, List[Call]]()
  private def callsOf(m: Method): List[Call] =
    ownCalls.getOrElseUpdate(m.id, m.cfgNode.collect { case c: Call => c }.l.sortBy(c => (lineOf(c), c.columnNumber.getOrElse(0), c.order, c.id)))
  private val kidsMemo = mutable.HashMap[Long, List[AstNode]]()
  private def children(n: AstNode): List[AstNode] = kidsMemo.getOrElseUpdate(n.id, n.astChildren.l.sortBy(_.order))
  private def isOp(c: Call): Boolean = c.name.startsWith("<operator>")
  private def isRead(c: Call): Boolean = c.name == "<operator>.fieldAccess" || c.name == "<operator>.indexAccess"
  /** The expression called: a name or a field access. Both front ends give it no argument index. */
  private def calleeExpr(c: Call): Option[AstNode] =
    if (isOp(c) && c.name != "<operator>.new") None
    else children(c).collectFirst { case e: Expression if e.argumentIndex < 0 && e.argumentName.isEmpty => e }
  private def receiver(c: Call): Option[AstNode] =
    calleeExpr(c).collect { case f: Call if f.name == "<operator>.fieldAccess" => f }.flatMap(arg(_, 1))
  private def field(c: Call): String = children(c).collectFirst { case i: FieldIdentifier => i.canonicalName }.getOrElse("")
  private def nameOf(c: Call): String =
    if (c.name.nonEmpty) c.name else calleeExpr(c) match {
      case Some(f: Call) if f.name == "<operator>.fieldAccess" => field(f)
      case Some(i: Identifier) => i.name
      case _ => ""
    }
  private def arg(c: Call, i: Int): Option[AstNode] = children(c).collectFirst { case e: Expression if e.argumentIndex == i => e }
  private def named(c: Call): List[(String, Expression)] =
    children(c).collect { case e: Expression if e.argumentName.isDefined => (e.argumentName.get, e) }
  private def positional(c: Call): List[Expression] =
    children(c).collect { case e: Expression if e.argumentIndex >= 1 && e.argumentName.isEmpty => e }.sortBy(_.argumentIndex)
  private def allArgs(c: Call): List[Expression] = positional(c) ++ named(c).map(_._2)
  private def unquote(code: String): String =
    code.replaceAll("^[a-zA-Z]{0,2}(\"\"\"|'''|\"|'|`)", "").replaceAll("(\"\"\"|'''|\"|'|`)$", "")
  private def params(m: Method): List[MethodParameterIn] = m.parameter.l.sortBy(_.index)
  /** A call of a plain name. jssrc2cpg gives a call of a global (fetch) no expression for what is called. */
  private def bare(c: Call): Boolean = calleeExpr(c) match {
    case Some(_: Identifier) => true
    case None => c.code.startsWith(c.name + "(")
    case _ => false
  }
  private def recvName(c: Call): String = receiver(c).map(_.code).getOrElse("")
  /** An index as a key: a literal's text, None where it is computed. */
  private def accessKey(c: Call): Option[String] =
    if (c.name == "<operator>.fieldAccess") Some(field(c)) else arg(c, 2).collect { case l: Literal => unquote(l.code) }
  private def isNamed(n: Option[AstNode], name: String): Boolean = n match {
    case Some(i: Identifier) => i.name == name
    case _ => false
  }
  /** The right-hand sides a name is bound to anywhere in a function. */
  private def bindings(m: Method, name: String): List[AstNode] =
    callsOf(m).filter(c => c.name == "<operator>.assignment" && isNamed(arg(c, 1), name)).flatMap(c => arg(c, 2))
  private def returnsOf(m: Method): List[AstNode] = m.cfgNode.collect { case r: Return => r }.l.flatMap(children)
  private def node(id: Long): Option[AstNode] = cpg.all.id(id).collect { case a: AstNode => a }.l.headOption
  private val nodes = mutable.HashMap[Long, AstNode]()
  private def known[T <: AstNode](n: T): T = { nodes(n.id) = n; n }
  private def nodeOf(id: Long): Option[AstNode] = nodes.get(id).orElse(node(id))

  // ---------------- imports ----------------
  private def clean(p: String): String = p.split("/").foldLeft(List[String]()) {
    case (acc, "" | ".") => acc
    case (acc, "..") => acc.dropRight(1)
    case (acc, s) => acc :+ s
  }.mkString("/")
  private def dirOf(file: String): String = if (file.contains("/")) file.take(file.lastIndexOf('/')) else ""

  /** The file of the repository an import names, when there is exactly one. */
  private def moduleNamed(from: String, spec: String): Option[Method] = {
    val dir = dirOf(from)
    if (js) {
      if (!spec.startsWith(".")) None
      else {
        val base = clean(dir + "/" + spec)
        val stem = base.replaceAll("\\.[cm]?[jt]sx?$", "")
        val ends = List("js", "ts", "mjs", "cjs", "jsx", "tsx", "mts", "cts")
        (base :: ends.flatMap(e => List(s"$stem.$e", s"$base.$e", s"$base/index.$e"))).flatMap(moduleOf.get).headOption
      }
    } else {
      val dots = spec.takeWhile(_ == '.').length
      val rest = spec.drop(dots).replace(".", "/")
      def at(p: String): Option[Method] =
        moduleOf.get(p + ".py").orElse(moduleOf.get(if (p.isEmpty) "__init__.py" else p + "/__init__.py"))
      val up = dir.split("/").filter(_.nonEmpty).toList
      if (dots > 0) at(clean((up.dropRight(dots - 1) :+ rest).mkString("/")))
      else if (rest.isEmpty) None
      else up.inits.map(d => at(clean((d :+ rest).mkString("/")))).collectFirst { case Some(m) => m }.orElse(
        modules.filter(m => fileOf(m).endsWith(s"/$rest.py") || fileOf(m).endsWith(s"/$rest/__init__.py")) match {
          case List(m) => Some(m)
          case _ => None
        })
    }
  }
  /** What an imported name is: a file of the repository, or a name in one. */
  private def imported(m: Method, rhs: AstNode): Option[(Method, Option[String])] = rhs match {
    case c: Call if c.name == "<operator>.import" || c.name == "import" =>
      val ls = c.argument.l.sortBy(_.argumentIndex).map(_.code)
      (ls.headOption.getOrElse(""), ls.lift(1).getOrElse("")) match {
        case ("", n) => moduleNamed(fileOf(m), n).map(_ -> None)
        case (from, n) =>
          moduleNamed(fileOf(m), if (from.endsWith(".")) from + n else from + "." + n).map(_ -> None)
            .orElse(moduleNamed(fileOf(m), from).map(_ -> Some(n)))
      }
    case c: Call if c.name == "require" =>
      arg(c, 1).collect { case l: Literal => unquote(l.code) }.flatMap(moduleNamed(fileOf(m), _)).map(_ -> None)
    case c: Call if c.name == "<operator>.fieldAccess" =>
      arg(c, 1).collect { case r: Call if r.name == "require" => r }.flatMap(imported(m, _)).map(x => (x._1, Some(field(c))))
    case _ => None
  }

  // ---------------- frames ----------------
  private val frames = mutable.HashMap[String, Frame]()
  private def keep(f: Frame): Frame = frames.getOrElseUpdate(f.key, f)
  private def moduleFrame(m: Method): Frame = keep(Frame(s"m${m.id}", m, None, None, None, nothing, None, true, false))
  /** A function whose caller is not known: its parameters are opaque. */
  private def looseFrame(m: Method, tag: String, self: Vs, lex: Option[Frame]): Frame =
    keep(Frame(s"$tag${m.id}", m, None, None, lex, self, Some(_ => other), false, false))
  /** The frame of m called by c from f; None where m is already running. */
  private def enter(c: Call, m: Method, f: Frame, self: Vs, lex: Option[Frame], bound: Option[Int => Vs], sure: Boolean): Option[Frame] = {
    val key = s"${f.key}>${c.id}:${m.id}"
    frames.get(key).orElse {
      if (f.chain.exists(_.method.id == m.id)) None
      else {
        if (frames.size > MostFrames) throw new RuntimeException("connector: too many ways to call the functions of this repository")
        Some(keep(Frame(key, m, Some(c), Some(f), lex, self, bound, sure && f.sure, false)))
      }
    }
  }

  // ---------------- resolution ----------------
  private def methodsOfClass(cls: String, name: String): List[Method] =
    byFull.getOrElse(cls + sep + name, Nil).filterNot(m => Generated(m.name))
  private def ctorOf(cls: String): Option[Method] = methodsOfClass(cls, if (js) "<init>" else "__init__").headOption

  private val targets = new Memo[(Long, String), List[Target]](Nil)
  private def resolve(c: Call, f: Frame): List[Target] =
    if (isOp(c) && c.name != "<operator>.new" || c.name == "require" || c.name == "import") Nil
    else targets((c.id, f.key))(resolve0(c, f))

  private def resolve0(c: Call, f: Frame): List[Target] = {
    val name = nameOf(c)
    val callee = calleeExpr(c)
    val recv = receiver(c)
    // an object of the repository settles what its method is
    val objs = recv.toList.flatMap(r => eval(r, f)).collect { case V(o: Obj, _, _) => o }.distinct
    val byObject = objs.flatMap(o => methodsOfClass(o.cls, name).map(m => Target(m, Set(V(o, Nil, true)), None, objs.size == 1))).distinctBy(_.method.id)
    if (byObject.nonEmpty) return byObject
    // then what the called expression evaluates to
    val values = callee match {
      case Some(e: Expression) => eval(e, f).toList
      case _ => Nil
    }
    val byValue = values.flatMap(v => v.base match {
      case Fn(m, lex) => byId.get(m).toList.map(x => Target(x, selfFor(recv, f, x, frames.get(lex)), frames.get(lex), true))
      case Cls(n) => ctorOf(n).toList.map { x => val o = made(n, c, f); Target(x, Set(V(o, Nil, true)), None, true, Some(o)) }
      case _ => Nil
    }).distinctBy(_.method.id)
    if (byValue.nonEmpty) return byValue
    // then what the front end's call graph says, for functions of that name, the nearest first
    val graph = c.callee(NoResolve).l.filter(m => byId.contains(m.id) && !Generated(m.name) && !moduleIds(m.id))
      .filter(m => m.name == name || isCtor(m) && name.nonEmpty).distinctBy(_.id)
    val here = graph.filter(m => dirOf(fileOf(m)) == dirOf(fileOf(f.method)))
    val near = if (here.nonEmpty) here else graph
    near.map { m =>
      if (isCtor(m)) { val o = made(classOf(m.fullName), c, f); Target(m, Set(V(o, Nil, true)), None, near.size == 1, Some(o)) }
      else {
        val lex = lexicalParent(m).flatMap(p => f.chain.reverse.find(_.method.id == p.id))
        Target(m, selfFor(recv, f, m, lex), lex, near.size == 1)
      }
    }
  }
  private def made(cls: String, c: Call, f: Frame): Obj = { known(c); Obj(cls, c.id, f.key) }
  private def selfFor(recv: Option[AstNode], f: Frame, m: Method, lex: Option[Frame]): Vs = {
    val got = recv.map(eval(_, f)).getOrElse(nothing).filter(_.base.isInstanceOf[Obj])
    val cls = classOf(m.fullName)
    if (got.nonEmpty) got
    else if (classNames(cls)) Set(V(Obj(cls, -1, f.key), Nil, false))
    else lex.map(_.self).getOrElse(nothing)
  }

  /** The frames a call leads into. */
  private val entered = new Memo[(Long, String), List[Frame]](Nil)
  private def into(c: Call, f: Frame): List[Frame] = if (isOp(c) && c.name != "<operator>.new") Nil else entered((c.id, f.key)) {
    val ts = resolve(c, f)
    if (ts.nonEmpty) ts.flatMap(t => enter(c, t.method, f, t.self, t.lex, None, t.sure && ts.size == 1))
    else {
      // a function handed to a call that is not the repository's may be called by it, with what the
      // call was made on or with
      val args = allArgs(c)
      val fns = args.flatMap(a => eval(a, f).toList.collect { case V(Fn(m, lex), _, _) => (a.id, m, lex) }).distinctBy(_._2)
      fns.flatMap { case (a, m, lex) =>
        byId.get(m).flatMap { x =>
          val l = frames.get(lex)
          val supplied = (_: Int) => blur(norm(receiver(c).toList.flatMap(r => collapse(eval(r, f))) ++
            args.filterNot(_.id == a).flatMap(r => collapse(eval(r, f))) ++
            (if (kindOf(c, f).isDefined) List(V(Acc(c.id, f.key), Nil, false)) else Nil)))
          enter(c, x, f, l.map(_.self).getOrElse(nothing), l, Some(supplied), false)
        }
      }
    }
  }

  // ---------------- values: helpers ----------------
  private def norm(vs: Iterable[V]): Vs = {
    val s = vs.toSet
    if (s.size < 2) s
    else s.groupBy(_.base).values.map(g => if (g.size == 1) g.head else g.minBy(v => (v.steps.size, !v.plain, v.steps.mkString(" ")))).toSet
  }
  private def step(vs: Vs, p: Place): Vs = norm(vs.map(v => v.copy(steps = v.steps :+ p)))
  private def blur(vs: Vs): Vs = vs.map(_.copy(plain = false))
  private def after(vs: Iterable[V], v: V): Iterable[V] =
    if (v.steps.isEmpty) vs else vs.map(y => y.copy(steps = y.steps ++ v.steps.filterNot(y.steps.contains)))
  /** The parts of a computation: what is in them that matters, or nothing known. */
  private def mixed(vs: Iterable[V]): Vs = {
    val real = vs.filter(v => v.base.isInstanceOf[Src] || v.base.isInstanceOf[Acc])
    if (real.isEmpty) other else blur(norm(real))
  }
  /** A value as a whole: a container is everything in it. */
  private def collapse(vs: Vs, depth: Int = 0): Vs = norm(vs.flatMap { v =>
    def under(x: Iterable[V]): Iterable[V] = after(blur(collapse(x.toSet, depth + 1)), v)
    v.base match {
      case _: Src | _: Lit | Other | _: Acc => List(v)
      case _ if depth > 12 => other
      case Rec(n, fk) =>
        val in = entries(n, frames(fk)).flatMap(_._2())
        if (in.isEmpty) other else under(in)
      case Keyed(_, x) => under(List(x))
      case Obj(_, call, fk) =>
        val in = for (c <- nodeOf(call).toList.collect { case x: Call => x }; f <- frames.get(fk).toList; a <- allArgs(c); z <- eval(a, f)) yield z
        if (in.isEmpty) other else under(in)
      case _ => other
    }
  })
  /** The entries of a container literal: key (None where not a literal) and value. */
  private def entries(id: Long, f: Frame): List[(Option[String], () => Vs)] = nodeOf(id) match {
    case Some(b: Block) =>
      val kids = children(b).filterNot(_.isInstanceOf[Local])
      val tmp = kids.lastOption.collect { case i: Identifier => i.name }.getOrElse("")
      kids.dropRight(1).flatMap {
        case c: Call if c.name == "<operator>.assignment" => arg(c, 1) match {
          case Some(t: Call) if isRead(t) => arg(c, 2).toList.map(r => (accessKey(t), () => eval(r, f)))
          case _ => Nil
        }
        case c: Call => allArgs(c).filterNot(_.code == tmp).map(e => (None: Option[String], () => eval(e, f)))
        case _ => Nil
      }
    case Some(c: Call) => positional(c).zipWithIndex.map {
      case (s: Call, _) if s.name == "<operator>.starredUnpack" => (None, () => norm(positional(s).flatMap(x => collapse(eval(x, f)))))
      case (e, i) => (Some(i.toString), () => eval(e, f))
    }
    case _ => Nil
  }
  /** One key of a value. None: some key. */
  private def read(vs: Vs, key: Option[String], at: Place): Vs = norm(vs.flatMap { v =>
    v.base match {
      case Ctx => List(V(Src("session", at), v.steps, v.plain))
      case Extra => if (key.contains("authInfo")) List(V(Src("session", at), v.steps, v.plain)) else other
      case _: Src | _: Acc => List(v)
      case Keyed(k, x) => if (key.isEmpty || k.isEmpty || key.contains(k)) after(List(x), v) else Nil
      case Rec(n, fk) =>
        val es = entries(n, frames(fk))
        // the last entry of that key, and whatever is spread in after it (or anywhere, where there is none)
        val from = math.max(0, es.lastIndexWhere(e => e._1.isDefined && e._1 == key))
        val got = if (key.isEmpty) es.flatMap(_._2()) else es.drop(from).flatMap { case (k, e) =>
          if (k == key) e().toList else if (k.isEmpty) read(e(), key, at).toList else Nil
        }
        if (got.isEmpty) other else after(got, v)
      case o: Obj => key.map(k => after(fieldOf(o, k), v)).getOrElse(other)
      case Mod(m) => key.flatMap(k => byId.get(m).map(x => global(x, k))).getOrElse(other)
      case Cls(n) => key.toList.flatMap(k => methodsOfClass(n, k)).map(m => V(Fn(m.id, ""), Nil, true))
      case _ => other
    }
  })

  /** What a field of an object of the repository holds: what its class and its constructor's call give it. */
  private val fields = new Memo[(Obj, String), Vs](nothing)
  private def fieldOf(o: Obj, name: String): Vs = fields((o, name)) {
    val self: Vs = Set(V(o, Nil, true))
    val call = nodeOf(o.call).collect { case c: Call => c }
    val at = frames.get(o.frame)
    val own = functions.filter(m => classOf(m.fullName) == o.cls)
    val set = for {
      m <- own
      a <- callsOf(m) if a.name == "<operator>.assignment"
      t <- arg(a, 1).toList.collect { case x: Call if x.name == "<operator>.fieldAccess" && field(x) == name => x }
      if arg(t, 1).exists { case i: Identifier => params(m).headOption.exists(_.name == i.name); case _ => false }
      r <- arg(a, 2).toList
    } yield {
      val built = if (isCtor(m)) for (c <- call; y <- at; z <- enter(c, m, y, self, None, None, true)) yield z else None
      eval(r, built.getOrElse(keep(Frame(s"f${m.id}@${o.call}@${o.frame}", m, None, None, None, self, Some(_ => other), false, false))))
    }
    // a class with no constructor of its own is built from the names of its fields (a dataclass)
    val supplied = if (ctorOf(o.cls).isDefined) Nil else for (c <- call.toList; y <- at.toList; (n, e) <- named(c) if n == name) yield eval(e, y)
    val all = norm(set.flatten ++ supplied.flatten ++ methodsOfClass(o.cls, name).map(m => V(Fn(m.id, ""), Nil, true)))
    if (all.isEmpty) other else all
  }

  /** A name at the top of a file of the repository. */
  private val globals = new Memo[(Long, String), Vs](nothing)
  private def global(m: Method, name: String): Vs = globals((m.id, name)) {
    val fr = moduleFrame(m)
    val cls = m.fullName + sep + name
    val here = sameFile.getOrElse(fileOf(m), Nil).filter(x => x.name == name && lexicalParent(x).exists(_.id == m.id) && !classNames(classOf(x.fullName)))
    if (classNames(cls)) Set(V(Cls(cls), Nil, true))
    else if (here.nonEmpty) here.map(x => V(Fn(x.id, fr.key), Nil, true)).toSet
    else {
      val out = norm(bindings(m, name).flatMap { r =>
        imported(m, r) match {
          case Some((x, None)) => Set(V(Mod(x.id), Nil, true))
          case Some((x, Some("default"))) => exported(x)
          case Some((x, Some(n))) => global(x, n)
          case None => r match {
            case l: Literal => if (AccountName.matches(name)) Set(V(Src("constant", place(l, m)), Nil, true)) else other
            case e => eval(e, fr).map(v => if (v.base.isInstanceOf[Lit]) V(Other, Nil, false) else v)
          }
        }
      })
      if (out.isEmpty) other else out
    }
  }
  /** JavaScript: what a file exports as its default. */
  private def exported(m: Method): Vs = {
    val sets = callsOf(m).filter(c => c.name == "<operator>.assignment" && arg(c, 1).exists(t => t.code == "exports.default" || t.code == "module.exports"))
    val got = norm(sets.flatMap(c => arg(c, 2)).flatMap(e => eval(e, moduleFrame(m))))
    if (got.isEmpty) Set(V(Mod(m.id), Nil, true)) else got
  }

  // ---------------- names ----------------
  private def mutators: Set[String] = if (js) JsMutators else PyMutators
  private val defsMemo = mutable.HashMap[(Long, String), (List[Def], Boolean)]()
  /** The definitions of a name (or a field chain, as written) that reach a node of its function, and
    * whether the function's start reaches it with none in between. */
  private def defs(at: CfgNode, name: String): (List[Def], Boolean) = defsMemo.getOrElseUpdate((at.id, name), {
    val out = mutable.ListBuffer[Def]()
    var entry = false
    val seen = mutable.HashSet[Long]()
    val work = mutable.Queue[CfgNode]()
    def back(n: CfgNode): Unit = {
      val ps = n.cfgPrev.l
      if (ps.isEmpty) entry = true
      ps.foreach(p => if (seen.add(p.id)) work.enqueue(p))
    }
    back(at)
    while (work.nonEmpty) {
      val n = work.dequeue()
      var stop = false
      n match {
        case _: Method => entry = true; stop = true
        case c: Call if c.name.startsWith("<operator>.assignment") => arg(c, 1) match {
          case Some(t) if t.code == name =>
            if (c.name == "<operator>.assignment") { arg(c, 2).foreach(r => out += Strong(r)); stop = true }
            else arg(c, 2).foreach(r => out += Weak(r, None))
          case Some(t: Call) if isRead(t) && arg(t, 1).exists(_.code == name) => arg(c, 2).foreach(r => out += Weak(r, Some(accessKey(t))))
          case _ =>
        }
        case c: Call if !isOp(c) && receiver(c).exists(_.code == name) =>
          if (!js && (c.name == "execute" || c.name == "executemany") && positional(c).nonEmpty) { out += Ran(c); stop = true }
          else if (mutators(nameOf(c))) allArgs(c).foreach(a => out += Weak(a, None))
        case _ =>
      }
      if (!stop) back(n)
    }
    (out.toList.distinct, entry)
  })
  private def weakly(ds: List[Def], f: Frame): List[V] = ds.flatMap {
    case Weak(e, None) => eval(e, f).toList
    case Weak(e, Some(k)) => eval(e, f).toList.map(v => V(Keyed(k.getOrElse(""), v), Nil, v.plain))
    case Ran(c) => eval(c, f).toList
    case _ => Nil
  }
  private def lookup(i: Identifier, f: Frame): Vs = {
    val (ds, entry) = defs(i, i.name)
    val strong = ds.collect { case Strong(e) => eval(e, f) }.flatten
    norm(strong ++ weakly(ds, f) ++ (if (entry) outer(i.name, f, strong.nonEmpty) else nothing))
  }

  /** A name a function has not bound before the use: a parameter, the enclosing function's, or the file's. */
  private def outer(name: String, f: Frame, boundHere: Boolean): Vs = params(f.method).find(_.name == name) match {
    case Some(p) => paramValue(p, f)
    case None if boundHere => nothing
    case None if moduleIds(f.method.id) => global(f.method, name)
    case None => lexicalParent(f.method) match {
      case Some(up) if !moduleIds(up.id) =>
        f.lex.filter(_.method.id == up.id).orElse(f.chain.reverse.find(_.method.id == up.id)) match {
          case Some(h) =>
            // the enclosing function's bindings of it, wherever they are
            val put = callsOf(up).filter(c => !isOp(c) && receiver(c).exists(_.code == name) && mutators(nameOf(c))).flatMap(allArgs)
            val nested = sameFile.getOrElse(fileOf(up), Nil).filter(x => x.name == name && lexicalParent(x).exists(_.id == up.id))
            val here = norm((bindings(up, name) ++ put).flatMap(b => eval(b, h)) ++ nested.map(x => V(Fn(x.id, h.key), Nil, true)))
            if (here.nonEmpty) here else outer(name, h, false)
          case None => moduleFor(f.method).map(global(_, name)).getOrElse(other)
        }
      case _ => moduleFor(f.method).map(global(_, name)).getOrElse(other)
    }
  }

  private val texts = mutable.HashMap[String, Vector[String]]()
  private def text(file: String): Vector[String] =
    texts.getOrElseUpdate(file, Try(Files.readString(Paths.get(rootDir, file)).linesIterator.toVector).getOrElse(Vector()))
  /** Python: whether the parameter is annotated Context, in its type or (Optional[Context]) its text. */
  private def isContext(p: MethodParameterIn, m: Method): Boolean = ContextType.matches(p.typeFullName) || {
    val line = text(fileOf(m)).lift(lineOf(p) - 1).getOrElse("")
    ("\\b" + java.util.regex.Pattern.quote(p.name) + "\\s*:\\s*([^=]*)").r.findFirstMatchIn(line).exists { x =>
      var depth = 0
      ContextType.matches(x.group(1).takeWhile { ch =>
        if (ch == '[' || ch == '(') depth += 1
        if (ch == ']' || ch == ')') depth -= 1
        depth > 0 || depth == 0 && ch != ','
      })
    }
  }
  private def paramValue(p: MethodParameterIn, f: Frame): Vs = {
    val cls = classOf(f.method.fullName)
    if (p.index == 0) {
      if (f.self.nonEmpty) f.self
      else if (!js && classNames(cls)) Set(V(Obj(cls, -1, f.key), Nil, false))
      else other
    } else if (f.root) {
      if (js && p.index == 2) Set(V(Extra, Nil, true))
      else if (!js && isContext(p, f.method)) Set(V(Ctx, Nil, true))
      else Set(V(Src("argument", Place(fileOf(f.method), p.lineNumber.getOrElse(lineOf(f.method)))), Nil, true))
    } else (f.call, f.parent) match {
      case (Some(c), Some(up)) =>
        val vs = f.bound match {
          case Some(b) => b(p.index)
          case None => argsFor(p, c) match {
            case Nil => other
            case es => norm(es.flatMap { case (e, whole) => if (whole) eval(e, up) else collapse(eval(e, up)) })
          }
        }
        step(vs, place(c, up.method))
      case _ => f.bound.map(_(p.index)).getOrElse(other)
    }
  }
  /** The expressions of a call that a parameter takes; false where it takes part of one. */
  private def argsFor(p: MethodParameterIn, c: Call): List[(Expression, Boolean)] = {
    val byName = named(c).collect { case (n, e) if n == p.name => e }
    val (spread, plain) = positional(c).partition { case x: Call => x.name == "<operator>.starredUnpack" || x.name == "<operator>.spread"; case _ => false }
    val variadic = p.code.startsWith("...") || p.code.startsWith("*")
    if (byName.nonEmpty) byName.map((_, true))
    else if (variadic) (positional(c).filter(_.argumentIndex >= p.index) ++ (if (js) Nil else named(c).map(_._2))).map((_, false))
    else plain.filter(_.argumentIndex == p.index) match {
      case Nil => spread.filter(_.argumentIndex <= p.index).map((_, false))
      case es => es.map((_, true))
    }
  }

  // ---------------- the evaluator ----------------
  private val values = new Memo[(Long, String), Vs](nothing)
  private def eval(n: AstNode, f: Frame): Vs = n match {
    case l: Literal => Set(V(Lit(place(l, f.method)), Nil, true))
    case _: Expression | _: ControlStructure => values((n.id, f.key))(norm(eval0(n, f)))
    case _ => other
  }
  private def eval0(n: AstNode, f: Frame): Iterable[V] = n match {
    case i: Identifier => lookup(i, f)
    case r: MethodRef => byFull.getOrElse(r.methodFullName, Nil).headOption.map(m => V(Fn(m.id, f.key), Nil, true)) match {
      case Some(v) => List(v)
      case None => other
    }
    case b: Block => block(b, f)
    case c: Call => call(c, f)
    case x: AstNode => val ks = children(x); if (ks.isEmpty) other else ks.flatMap(eval(_, f))
  }
  private def block(b: Block, f: Frame): Vs = {
    val kids = children(b).filterNot(_.isInstanceOf[Local])
    val built = kids.collectFirst { case c: Call if c.name == "<operator>.new" => c }
    kids.lastOption match {
      case Some(i: Identifier) if isContainer(kids.dropRight(1), i.name) => known(b); Set(V(Rec(b.id, f.key), Nil, true))
      case Some(_: Identifier) if built.isDefined => eval(built.get, f)
      case Some(e) => eval(e, f)
      case None => other
    }
  }
  /** Whether a block is the lowering of a dict or object literal: keys put one by one into a temporary. */
  private def isContainer(kids: List[AstNode], tmp: String): Boolean = kids.forall {
    case c: Call if c.name == "<operator>.assignment" => arg(c, 1).exists {
      case t: Call if isRead(t) => arg(t, 1).exists(_.code == tmp)
      case i: Identifier => i.name == tmp && arg(c, 2).exists { case x: Call => x.name == "<operator>.dictLiteral"; case _ => false }
      case _ => false
    }
    case c: Call => c.name == "<operator>.spread" || c.name == "<operator>.dictUnpack" || c.name == "update" && recvName(c) == tmp
    case _ => false
  }
  private def call(c: Call, f: Frame): Iterable[V] = c.name match {
    case "<operator>.assignment" => arg(c, 2).map(eval(_, f)).getOrElse(other)
    case "<operator>.fieldAccess" | "<operator>.indexAccess" => readCall(c, f)
    case "<operator>.conditional" => List(2, 3).flatMap(arg(c, _)).flatMap(eval(_, f))
    case "<operator>.logicalOr" | "<operator>.logicalAnd" | "<operator>.elvis" => allArgs(c).flatMap(eval(_, f))
    case n if Transparent(n) => allArgs(c).lastOption.map(eval(_, f)).getOrElse(other)
    case n if Containers(n) => known(c); Set(V(Rec(c.id, f.key), Nil, true))
    case n if Opaque(n) => other
    case "<operator>.new" => result(c, f)
    case n if n.startsWith("<operator>") => mixed(allArgs(c).flatMap(a => collapse(eval(a, f))))
    case _ => result(c, f)
  }
  private def readCall(c: Call, f: Frame): Vs = {
    // a field written as a chain (self.cur) may have been bound in this function
    val ds = if (c.name == "<operator>.fieldAccess") defs(c, c.code)._1 else Nil
    val local = ds.collect { case Strong(e) => eval(e, f) }.flatten ++ weakly(ds, f)
    norm(local ++ arg(c, 1).map(b => read(eval(b, f), accessKey(c), place(c, f.method))).getOrElse(other))
  }
  /** The value of a call: of the functions it runs, or of what it was given. */
  private def result(c: Call, f: Frame): Iterable[V] = {
    val name = nameOf(c)
    kindOf(c, f) match {
      case Some(a) =>
        known(c)
        return Set(V(Acc(c.id, f.key), Nil, true)) ++ blur(norm(a.options.flatten.flatten.filter(_.base.isInstanceOf[Src])))
      case None =>
    }
    if (js && name == "prepare" && positional(c).nonEmpty && receiver(c).isDefined) { known(c); return Set(V(Stmt(c.id), Nil, true)) }
    if (!js && HttpClient.matches(c.code)) return Set(V(Http, Nil, true))
    // a with statement's enter(): the manager itself
    if (!js && c.name.isEmpty && c.code.startsWith("enter_tmp")) return arg(c, 0).map(eval(_, f)).getOrElse(other)
    val ts = resolve(c, f)
    val objs = ts.flatMap(_.obj)
    if (objs.nonEmpty) return objs.map(o => V(o, Nil, true))
    if (ts.nonEmpty) { val got = into(c, f).flatMap(returned); return if (got.isEmpty) other else got }
    val classes = calleeExpr(c).toList.flatMap(e => eval(e, f)).collect { case V(Cls(n), _, _) => n }
    if (classes.nonEmpty) return classes.map(n => V(made(n, c, f), Nil, true))
    val on = receiver(c).map(eval(_, f)).getOrElse(nothing)
    if (name == "get" && on.exists(v => v.base.isInstanceOf[Rec] || v.base.isInstanceOf[Keyed]))
      positional(c).headOption match {
        case Some(l: Literal) => return read(on, Some(unquote(l.code)), place(c, f.method)) ++ positional(c).drop(1).flatMap(eval(_, f))
        case _ =>
      }
    if (js && c.name == "<operator>.new" && calleeExpr(c).exists(_.code == "Promise")) return mixed(into(c, f).flatMap(settled).flatMap(v => collapse(Set(v))))
    // not the repository's: what it was made on, what it was given, and what a function given to it returns
    mixed(collapse(on) ++ allArgs(c).flatMap(a => collapse(eval(a, f))) ++ collapse(into(c, f).flatMap(returned).toSet))
  }
  /** What a Promise's function hands to its own parameters (resolve and reject), itself or in a callback. */
  private def settled(g: Frame): List[V] = {
    val names = params(g.method).filter(_.index > 0).map(_.name).toSet
    def under(h: Frame, seen: Set[String]): List[V] =
      callsOf(h.method).filter(c => bare(c) && names(nameOf(c))).flatMap(c => allArgs(c).flatMap(eval(_, h))) ++
        callsOf(h.method).flatMap(into(_, h)).filter(x => !seen(x.key) && lexicalParent(x.method).exists(_.id == h.method.id)).flatMap(x => under(x, seen + x.key))
    under(g, Set(g.key))
  }
  private def returned(g: Frame): List[V] = returnsOf(g.method).flatMap(eval(_, g))

  // ---------------- accesses ----------------
  private val kinds = new Memo[(Long, String), Option[Access]](None)
  private def kindOf(c: Call, f: Frame): Option[Access] =
    if (isOp(c)) None else kinds((c.id, f.key))(if (js) jsKind(c, f) else pyKind(c, f))
  private def ownFunction(c: Call, f: Frame): Boolean = bare(c) && calleeExpr(c).exists(e => eval(e, f).exists(_.base.isInstanceOf[Fn]))

  private def pyKind(c: Call, f: Frame): Option[Access] = {
    val args = positional(c)
    val byName = named(c).toMap
    lazy val recv = receiver(c)
    c.name match {
      case "execute" | "executemany" if args.nonEmpty && recv.isDefined =>
        val bound = args.drop(1) ++ List("params", "parameters", "seq_of_parameters").flatMap(byName.get)
        Some(Access(c, "database", f, cross(bound.map(elements(_, f, 0)))))
      case "fetch" | "fetchrow" | "fetchval" if args.nonEmpty && recv.isDefined && Sql.matches(args.head.code) =>
        Some(Access(c, "database", f, cross(args.drop(1).map(elements(_, f, 0)))))
      case "open" if args.nonEmpty && (bare(c) && !ownFunction(c, f) || Set("io", "aiofiles", "codecs")(recvName(c))) =>
        Some(Access(c, "file", f, pieces(args.head, f, 0)))
      case "read_text" | "read_bytes" if recv.isDefined => Some(Access(c, "file", f, pieces(recv.get, f, 0)))
      case "urlopen" if args.nonEmpty => Some(Access(c, "request", f, pieces(args.head, f, 0)))
      case v if HttpVerbs(v) && args.nonEmpty && recv.isDefined &&
        (Set("requests", "httpx")(recvName(c)) || eval(recv.get, f).exists(_.base == Http)) =>
        (if (v == "request" || v == "stream") args.lift(1) else args.headOption).map(u =>
          Access(c, "request", f, cross(pieces(u, f, 0) :: byName.get("params").toList.map(elements(_, f, 0)))))
      case _ => None
    }
  }
  private def jsKind(c: Call, f: Frame): Option[Access] = {
    val args = positional(c)
    lazy val recv = receiver(c)
    c.name match {
      case "all" | "get" | "run" | "iterate" | "each" if recv.isDefined && eval(recv.get, f).exists(_.base.isInstanceOf[Stmt]) =>
        Some(Access(c, "database", f, cross(args.map(elements(_, f, 0)))))
      case "query" | "execute" | "all" | "get" | "run" | "each" if recv.isDefined && args.headOption.exists(sql(_, f)) && resolve(c, f).isEmpty =>
        Some(Access(c, "database", f, cross(args.drop(1).map(elements(_, f, 0)))))
      case "readFileSync" | "readFile" | "createReadStream" if args.nonEmpty && !ownFunction(c, f) =>
        Some(Access(c, "file", f, pieces(args.head, f, 0)))
      case "fetch" if bare(c) && args.nonEmpty && !ownFunction(c, f) => Some(Access(c, "request", f, pieces(args.head, f, 0)))
      case v if HttpVerbs(v) && recvName(c) == "axios" && args.nonEmpty => Some(Access(c, "request", f, pieces(args.head, f, 0)))
      case _ => None
    }
  }
  /** Whether an expression is the text of a statement, here or (a wrapper's parameter) at its caller. */
  private def sql(a: AstNode, f: Frame, depth: Int = 0): Boolean = isSql(a) || depth < 6 && (a match {
    case i: Identifier => sites(i, f).exists(_.exists { case (e, g, _) => sql(e, g, depth + 1) })
    case _ => false
  })
  private def isSql(a: AstNode): Boolean = a match {
    case l: Literal => Sql.matches(l.code)
    case x: Call if x.name == "<operator>.addition" => arg(x, 1).exists(isSql)
    case x: Call if x.name == "<operator>.formatString" => children(x).headOption.exists { case l: Literal => Sql.matches("\"" + unquote(l.code)); case _ => false }
    case _ => false
  }

  /** Every way to take one option of each part, as lists of scoping values. Too many: each part whole. */
  private def cross(parts: List[List[List[Vs]]]): List[List[Vs]] =
    if (parts.map(_.size.toLong).product > 32) List(parts.map(p => norm(p.flatten.flatten)))
    else parts.foldLeft(List(List[Vs]()))((acc, p) => for (a <- acc; b <- p) yield a ++ b)

  /** A name's definitions as expressions, here, in the enclosing function or at the caller. None where
    * it is not that simple. */
  private def sites(i: Identifier, f: Frame): Option[List[(AstNode, Frame, Option[Place])]] = {
    val (ds, entry) = defs(i, i.name)
    val here = ds.collect { case Strong(e) => (e, f, None: Option[Place]) }
    if (here.size != ds.size) None
    else if (!entry) Some(here).filter(_.nonEmpty)
    else if (here.nonEmpty && !params(f.method).exists(_.name == i.name)) Some(here)
    else above(i.name, f).map(here ++ _)
  }
  private def above(name: String, f: Frame): Option[List[(AstNode, Frame, Option[Place])]] =
    (params(f.method).find(_.name == name), f.call, f.parent) match {
      case (Some(p), Some(c), Some(up)) if p.index > 0 && !f.root && f.bound.isEmpty => argsFor(p, c) match {
        case List((e, true)) => Some(List((e, up, Some(place(c, up.method)))))
        case _ => None
      }
      case (None, _, _) =>
        val up = lexicalParent(f.method).filterNot(m => moduleIds(m.id))
        up.flatMap(m => f.lex.filter(_.method.id == m.id)).flatMap { h =>
          // one binding in the enclosing function, and nothing put into it
          val put = callsOf(h.method).exists(c => !isOp(c) && receiver(c).exists(_.code == name) && mutators(nameOf(c)))
          bindings(h.method, name) match {
            case Nil => above(name, h)
            case List(e) if !put && !params(h.method).exists(_.name == name) => Some(List((e, h, None)))
            case _ => None
          }
        }
      case _ => None
    }
  private def follow(i: Identifier, f: Frame)(more: (AstNode, Frame) => List[List[Vs]]): Option[List[List[Vs]]] =
    sites(i, f).map(_.flatMap { case (e, g, at) => at.map(p => more(e, g).map(_.map(step(_, p)))).getOrElse(more(e, g)) })

  /** The parameters bound to a statement: each element of a container, or the value itself. */
  private def elements(n: AstNode, f: Frame, depth: Int): List[List[Vs]] = {
    def whole = List(List(collapse(eval(n, f))))
    def each(id: Long) = List(entries(id, f).map(e => collapse(e._2())))
    n match {
      case _ if depth > 24 => whole
      case c: Call if Containers(c.name) => known(c); each(c.id)
      case b: Block if eval(b, f).exists { case V(Rec(id, _), _, _) => id == b.id; case _ => false } => each(b.id)
      case b: Block if js && b.code.startsWith("[") =>
        List(children(b).collect { case c: Call if nameOf(c) == "push" => allArgs(c) }.flatten.map(a => collapse(eval(a, f))))
      case i: Identifier => follow(i, f)((e, g) => elements(e, g, depth + 1)).getOrElse(whole)
      case _ => whole
    }
  }
  /** The pieces of a path or URL. A literal is none. */
  private def pieces(n: AstNode, f: Frame, depth: Int): List[List[Vs]] = {
    def whole = List(List(collapse(eval(n, f))))
    def all(ns: List[AstNode]) = cross(ns.filterNot(_.isInstanceOf[Literal]).map(pieces(_, f, depth + 1)))
    n match {
      case _ if depth > 24 => whole
      case _: Literal => List(Nil)
      case c: Call if Set("addition", "formatString", "formattedValue", "division").map("<operator>." + _)(c.name) => all(allArgs(c))
      case c: Call if c.name == "<operator>.await" => all(allArgs(c))
      case c: Call if c.name == "<operator>.conditional" => List(2, 3).flatMap(arg(c, _)).flatMap(pieces(_, f, depth + 1))
      case c: Call if !isOp(c) || c.name == "<operator>.new" =>
        val ts = resolve(c, f)
        if (kindOf(c, f).isDefined) whole
        else if (ts.nonEmpty) {
          val rs = if (ts.exists(_.obj.isDefined)) Nil else into(c, f).flatMap(g => returnsOf(g.method).map((_, g)))
          if (rs.isEmpty) whole else rs.flatMap { case (e, g) => pieces(e, g, depth + 1) }
        }
        else if (Flat(nameOf(c)) || c.name == "<operator>.new" && calleeExpr(c).exists(_.code == "URL"))
          all(receiver(c).filter(_ => OnReceiver(nameOf(c)) && allArgs(c).size <= 1 && !js).toList ++ allArgs(c))
        else whole
      case b: Block => children(b).collectFirst { case c: Call if c.name == "<operator>.new" => c }.map(pieces(_, f, depth + 1)).getOrElse(whole)
      case i: Identifier => follow(i, f)((e, g) => pieces(e, g, depth + 1)).getOrElse(whole)
      case _ => whole
    }
  }

  /** The identity that scopes an access, by its scoping values. */
  private def verdict(a: Access): Verdict = {
    // an access's result is no origin of its own: what scoped it is beside it
    val options = a.options.map(_.map(_.filterNot(_.base.isInstanceOf[Acc])).filter(_.nonEmpty))
    def is(kind: String)(v: V): Boolean = v.base match { case Src(k, _) => k == kind; case _ => false }
    def spot(v: V): Option[Place] = v.base match { case Src(_, p) => Some(p); case Lit(p) => Some(p); case _ => None }
    def session(vs: Vs): Boolean = vs.forall(is("session"))
    def least(vs: Vs): Option[V] = vs.toList.sortBy(v => (v.steps.size, v.base.toString, v.steps.mkString(" "))).headOption
    def first(p: V => Boolean): Option[V] = options.flatten.map(_.filter(p)).find(_.nonEmpty).flatMap(least)
    if (options.forall(_.exists(session))) {
      val v = options.head.find(session).flatMap(least)
      Verdict("session", v, v.flatMap(spot))
    } else first(is("argument")) match {
      case Some(v) => Verdict("argument", Some(v), spot(v))
      case None => first(v => is("constant")(v) || a.kind == "database" && v.base.isInstanceOf[Lit]) match {
        case Some(v) => Verdict("constant", Some(v), spot(v))
        case None => Verdict("none", None, None)
      }
    }
  }

  // ---------------- tools ----------------
  private def rootFrame(m: Method, host: Frame): Frame = {
    val cls = classOf(m.fullName)
    val self: Vs = if (!js && classNames(cls)) Set(V(Obj(cls, -1, host.key), Nil, false)) else nothing
    keep(Frame(s"t${m.id}@${host.key}", m, None, None, Some(host), self, None, true, true))
  }
  private def hostFrame(m: Method): Frame =
    if (moduleIds(m.id)) moduleFrame(m) else looseFrame(m, "h", nothing, lexicalParent(m).map(hostFrame))
  private def lastName(n: AstNode): String = n match {
    case i: Identifier => i.name
    case c: Call if c.name == "<operator>.fieldAccess" => field(c)
    case _ => ""
  }
  private def handlers: List[Tool] = (if (js) jsHandlers else pyHandlers).distinctBy(t => (t.name, t.method.id))

  /** @mcp.tool() def f is f = mcp.tool()(def f); @mcp.tool def f is f = mcp.tool(def f). */
  private def pyHandlers: List[Tool] = internal.filterNot(m => Generated(m.name) && m.name != "<body>").flatMap { m =>
    callsOf(m).filterNot(isOp).flatMap { c =>
      val maker: Option[Option[Call]] = calleeExpr(c) match {
        case Some(d: Call) if !isOp(d) => Some(Some(d)).filter(_ => nameOf(d) == "tool")
        case Some(d) if lastName(d) == "tool" => Some(None)
        case _ => None
      }
      for (d <- maker.toList; a <- arg(c, 1).toList; fn <- decorated(a, hostFrame(m)).take(1)) yield {
        val supplied = d.toList.flatMap(x => named(x).collectFirst { case ("name", l: Literal) => l.code }.orElse(positional(x).headOption.collect { case l: Literal => l.code }))
        Tool(supplied.headOption.map(unquote).getOrElse(fn.name), fn, rootFrame(fn, hostFrame(m)))
      }
    }
  }
  private def decorated(a: AstNode, host: Frame): List[Method] = {
    val refs = a.ast.collect { case r: MethodRef => r }.l.flatMap(r => byFull.getOrElse(r.methodFullName, Nil).headOption)
    val named = a match {
      case i: Identifier => lookup(i, host).toList.collect { case V(Fn(x, _), _, _) => byId.get(x) }.flatten
      case _ => Nil
    }
    (refs ++ named).filterNot(_.name.startsWith("<lambda>"))
  }
  /** server.tool("name", ..., handler), and registerTool. */
  private def jsHandlers: List[Tool] = internal.flatMap { m =>
    callsOf(m).filter(c => (c.name == "tool" || c.name == "registerTool") && receiver(c).isDefined && positional(c).size >= 2).flatMap { c =>
      // where the handler was written: a wrapper's inner function has the wrapper's frame
      val fns = eval(positional(c).last, hostFrame(m)).toList.collect { case V(Fn(x, lex), _, _) => byId.get(x).map((_, frames.getOrElse(lex, hostFrame(m)))) }.flatten
      for (n <- List(positional(c).head).collect { case l: Literal => unquote(l.code) }; (fn, host) <- fns.sortBy(_._2.key).take(1))
        yield Tool(n, fn, rootFrame(fn, host))
    }
  }

  // ---------------- what the two queries say ----------------
  /** Every frame a tool's handler leads into, its own first. */
  private def reach(t: Tool): List[Frame] = {
    val out = mutable.LinkedHashMap[String, Frame]()
    def go(f: Frame): Unit = if (!out.contains(f.key)) {
      out(f.key) = f
      callsOf(f.method).foreach(c => into(c, f).foreach(go))
    }
    go(t.frame)
    out.values.toList
  }
  private def raised(f: Frame): List[AstNode] =
    if (js) f.method.ast.collect { case t: ControlStructure if t.controlStructureType == "THROW" && t.method.id == f.method.id => t }.l
    else callsOf(f.method).filter(_.name == "<operator>.raise").flatMap(allArgs)

  private def rows(manifest: Map[String, List[String]]): List[Row] = handlers.sortBy(t => (t.name, fileOf(t.method), lineOf(t.method))).flatMap { t =>
    val fs = reach(t)
    val accesses = fs.flatMap(f => callsOf(f.method).flatMap(c => kindOf(c, f)))
    val said = returned(t.frame) ++ fs.flatMap(f => raised(f).flatMap(eval(_, f)))
    val answered = collapse(said.toSet).collect { case V(Acc(c, k), _, _) => (c, k) }
    trace(t, fs, accesses, answered)
    accesses.groupBy(_.call.id).toList.flatMap { case (_, same) =>
      val judged = same.map(a => (a, verdict(a), answered((a.call.id, a.frame.key))))
      val order = List("argument", "constant", "none", "session")
      def row(xs: List[(Access, Verdict, Boolean)], sink: Boolean): Row = {
        val (a, v, _) = xs.minBy { case (x, y, _) => (order.indexOf(y.identity), x.frame.chain.size, x.frame.key) }
        Row(t.name, a.kind, v, place(a.call, a.frame.method), path(t, a, v),
          if (same.size == 1) construct(a).filter(manifest.contains) else None, sink)
      }
      val open = judged.filter(j => j._3 && j._2.identity != "session")
      row(judged, false) :: (if (open.isEmpty) Nil else List(row(open, true)))
    }
  }
  private def path(t: Tool, a: Access, v: Verdict): List[String] = {
    val end = place(a.call, a.frame.method)
    val (start, between) = (v.source, v.at) match {
      case (Some(s), Some(p)) => (p, s.steps)
      case _ => (Place(fileOf(t.method), lineOf(t.method)), a.frame.chain.drop(1).map(f => place(f.call.get, f.parent.get.method)))
    }
    (start :: (between :+ end)).foldLeft(List[Place]())((acc, p) => if (acc.lastOption.contains(p)) acc else acc :+ p).map(_.toString)
  }

  /** The construct an access and its origins are of, where every object on the way can be named. */
  private def construct(a: Access): Option[String] = {
    def once(name: String, starts: String, imports: String): Boolean = moduleFor(a.frame.method).exists { m =>
      val again = (m :: sameFile.getOrElse(fileOf(m), Nil)).map(x => callsOf(x).count(c => c.name.startsWith("<operator>.assignment") && arg(c, 1).exists(_.code == name))).sum
      bindings(m, name).exists(_.code.startsWith(starts)) && again == 1 && !params(a.frame.method).exists(_.name == name) &&
        text(fileOf(m)).exists(l => l.trim.matches(imports))
    }
    def plain = a.frame.sure && a.options.size == 1 && a.options.head.forall(_.forall(_.plain))
    if (a.kind != "database" || !plain) None
    else if (!js) (receiver(a.call), positional(a.call).headOption) match {
      case (Some(r: Identifier), Some(s: Literal)) if Sql.matches(s.code) && once(r.name, "sqlite3.connect(", "import sqlite3") => Some("sqlite3_literal_statement")
      case _ => None
    }
    else receiver(a.call).toList.flatMap(r => eval(r, a.frame)).collect { case V(Stmt(p), _, _) => nodeOf(p) }.flatten match {
      case List(p: Call) => (receiver(p), positional(p).headOption) match {
        case (Some(r: Identifier), Some(s: Literal)) if Sql.matches(s.code) &&
          once(r.name, "new DatabaseSync(", "import \\{ DatabaseSync \\} from [\"']node:sqlite[\"'];?") => Some("node_sqlite_literal_statement")
        case _ => None
      }
      case _ => None
    }
  }

  private def trace(t: Tool, fs: List[Frame], as: List[Access], answered: Set[(Long, String)]): Unit =
    sys.env.get("KAMANU_CONNECTOR_TRACE").foreach { p =>
      val out = new StringBuilder(s"tool ${t.name} ${fileOf(t.method)}:${lineOf(t.method)}\n")
      fs.foreach(f => out.append(s"  frame ${f.chain.map(_.method.name).mkString(" > ")} sure=${f.sure}\n"))
      as.foreach(a => out.append(s"  access ${place(a.call, a.frame.method)} ${a.kind} ${verdict(a)} answered=${answered((a.call.id, a.frame.key))} ${a.options}\n"))
      Files.write(Paths.get(p), out.toString.getBytes("UTF-8"), StandardOpenOption.CREATE, StandardOpenOption.APPEND)
    }

  def write(out: String, sinks: Boolean, manifest: Map[String, List[String]]): Unit = {
    val lines = rows(manifest).filter(_.answered == sinks).map { r =>
      val subject = ujson.Obj("tool" -> r.tool, "kind" -> r.kind, "identity" -> r.verdict.identity)
      if (sinks) subject("path") = ujson.Arr.from(r.path.map(ujson.Str(_)))
      else subject("source") = r.verdict.at.map(p => ujson.Str(p.toString)).getOrElse(ujson.Null)
      val rec = ujson.Obj("file" -> r.access.file, "line" -> r.access.line, "subject" -> subject.toString)
      r.construct.foreach { c => rec("construct") = c; rec("assumptions") = ujson.Arr.from(manifest(c).map(ujson.Str(_))) }
      rec.toString
    }
    Files.write(Paths.get(out), lines.distinct.sorted.map(_ + "\n").mkString.getBytes("UTF-8"))
  }
}
