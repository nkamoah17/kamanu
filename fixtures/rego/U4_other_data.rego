# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/external-data/index.md#option-3-bundle-api (any data document a bundle carries)
# The cap comes from a document the kernel does not have. Cap is in the policy text.
package kamanu.spend

import rego.v1

default allow := false

# unsupported
allow if {
	sum([e.amt | some e in data.kamanu.events; e.kind == "request"]) <= data.budgets[input.key]
}
