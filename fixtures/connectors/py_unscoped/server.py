"""Written for KAMANU gate T9: an MCP server whose tools answer with everyone's data."""
from minimcp import MCP, Context

import store

mcp = MCP("unscoped")


@mcp.tool()
def list_invoices(ctx: Context) -> str:
    found = store.invoices()
    return found


@mcp.tool()
def read_note() -> str:
    return store.notes()


@mcp.tool()
def show_profile(greeting: str = "profile") -> str:
    text = store.profiles()
    return greeting + ": " + text


if __name__ == "__main__":
    mcp.run()
