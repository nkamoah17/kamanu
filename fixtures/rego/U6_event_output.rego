# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/policy-language.md#references (a reference to an absent field is undefined)
# Kernel events have no outputs, so this sum would silently be empty.
package kamanu.spend

import rego.v1

default allow := false

# unsupported
allow if {
	sum([e.amt | some e in data.kamanu.events; e.kind == "response"; e.output.approved == true]) <= 100
}
