"""Written for KAMANU gate T9: an MCP server that scopes each tool by an argument of the call."""
from minimcp import MCP

import store

mcp = MCP("by-argument")


@mcp.tool()
def list_invoices(user_id: str) -> str:
    found = store.invoices_of(user_id)
    return found


@mcp.tool()
def read_note(workspace: str) -> str:
    return store.note_of(workspace)


@mcp.tool()
def show_profile(tenant: str) -> str:
    text = store.profile_of(tenant)
    return "profile: " + text


if __name__ == "__main__":
    mcp.run()
