"""Written for KAMANU gate T9: the smallest MCP server over stdio that the gate's servers need.

Newline-delimited JSON-RPC 2.0: initialize, notifications/initialized, ping, tools/list (with pages),
tools/call. The names are those of the Python SDK (a decorator .tool(), a parameter annotated Context).
The session is the transport's: the token in the environment of the process, looked up in auth.json.
"""
import inspect
import json
import os
import sys


class Session:
    def __init__(self, tenant, user):
        self.tenant = tenant
        self.user = user


class Context:
    def __init__(self, session):
        self.session = session


class RpcError(Exception):
    def __init__(self, message, data=None):
        super().__init__(message)
        self.data = data


class Invalid(Exception):
    pass


JSON_TYPES = {str: "string", int: "integer", bool: "boolean", list: "array", dict: "object"}


def check(value, schema, where):
    kind = schema.get("type")
    good = {"string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "array": lambda v: isinstance(v, list), "object": lambda v: isinstance(v, dict)}
    if kind in good and not good[kind](value):
        raise Invalid(f"{where} must be a JSON {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise Invalid(f"{where} is not one of its choices")
    if kind == "array" and "items" in schema:
        for item in value:
            check(item, schema["items"], where)
    if kind == "object":
        for name in schema.get("required", []):
            if name not in value:
                raise Invalid(f"{where} needs {name}")
        for name, item in value.items():
            if name not in schema.get("properties", {}):
                raise Invalid(f"{where} does not know {name}")
            check(item, schema["properties"][name], name)


class MCP:
    def __init__(self, name, page=50, chatty=False):
        self.name = name
        self.page = page
        self.chatty = chatty
        self.tools = {}

    def tool(self, name=None, schema=None):
        def register(fn):
            properties, required, context = {}, [], None
            for p in inspect.signature(fn).parameters.values():
                if p.annotation is Context:
                    context = p.name
                    continue
                properties[p.name] = (schema or {}).get(p.name) or {"type": JSON_TYPES[p.annotation]}
                if p.annotation is list and "items" not in properties[p.name]:
                    properties[p.name]["items"] = {"type": "string"}
                if p.default is inspect.Parameter.empty:
                    required.append(p.name)
            self.tools[name or fn.__name__] = (fn, context, {"type": "object", "properties": properties,
                                                             "required": required})
            return fn
        return register

    def call(self, params, session):
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in self.tools:
            raise Invalid(f"no tool {name}")
        fn, context, schema = self.tools[name]
        check(args, schema, "arguments")
        if context:
            args = {**args, context: Context(session)}
        try:
            out = fn(**args)
        except RpcError:
            raise
        except Exception as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        if isinstance(out, dict):
            return out
        return {"content": [{"type": "text", "text": out}]}

    def answer(self, message, session):
        method, params = message.get("method"), message.get("params") or {}
        if method == "initialize":
            return {"protocolVersion": params.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
                    "serverInfo": {"name": self.name, "version": "0"}}
        if method == "ping":
            return {}
        if method == "tools/list":
            start = int(params.get("cursor") or 0)
            names = list(self.tools)
            out = {"tools": [{"name": n, "description": "", "inputSchema": self.tools[n][2]}
                             for n in names[start:start + self.page]]}
            if start + self.page < len(names):
                out["nextCursor"] = str(start + self.page)
            return out
        if method == "tools/call":
            if session is None:
                raise Invalid("not signed in")
            return self.call(params, session)
        raise Invalid(f"no method {method}")

    def run(self):
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        token = os.environ.get("CONNECTOR_TOKEN", "")
        with open(os.path.join(os.environ["CONNECTOR_DATA"], "auth.json"), encoding="utf-8") as f:
            who = json.load(f).get(token)
        session = Session(who["tenant"], who["user"]) if who else None
        for line in sys.stdin:
            if not line.strip():
                continue
            message = json.loads(line)
            if "id" not in message or "method" not in message:
                continue
            reply = {"jsonrpc": "2.0", "id": message["id"]}
            try:
                reply["result"] = self.answer(message, session)
            except Invalid as e:
                reply["error"] = {"code": -32602, "message": str(e)}
            except RpcError as e:
                reply["error"] = {"code": -32000, "message": str(e), "data": e.data}
            if os.environ.get("CONNECTOR_LOG"):
                with open(os.environ["CONNECTOR_LOG"], "a", encoding="utf-8") as f:
                    f.write(json.dumps({"token": token, "message": message, "reply": reply}, ensure_ascii=False) + "\n")
            if self.chatty:
                print(json.dumps({"jsonrpc": "2.0", "method": "notifications/message",
                                  "params": {"level": "info", "data": "working"}}), flush=True)
            print(json.dumps(reply, ensure_ascii=False), flush=True)
