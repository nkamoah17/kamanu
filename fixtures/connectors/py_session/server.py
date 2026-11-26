"""Written for KAMANU gate T9: an MCP server that scopes each tool by the session's identity."""
from minimcp import MCP, Context

import store

mcp = MCP("by-session")


@mcp.tool()
def list_invoices(ctx: Context) -> str:
    owner = ctx.session.tenant
    found = store.invoices_of(owner)
    return found


@mcp.tool()
def read_note(ctx: Context) -> str:
    return store.note_of(ctx.session.tenant)


@mcp.tool()
def show_profile(ctx: Context, greeting: str = "profile") -> str:
    text = store.profile_of(ctx.session.tenant)
    return greeting + ": " + text


if __name__ == "__main__":
    mcp.run()
