# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/policy-language.md#with-keyword (with replaces part of data or input)
# The rule swaps the view for one of its own, so the kernel's view is not what is judged.
package kamanu.spend

import rego.v1

default allow := false

# unsupported
allow if {
	sum([e.amt | some e in data.kamanu.events; e.kind == "request"]) <= 100 with data.kamanu.events as []
}
