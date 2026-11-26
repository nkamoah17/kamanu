# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/policy-language.md#references (a reference to an absent field is undefined)
# A kernel request is {tool, amt, key}, so a role is a field it does not have. OPA would
# read that as undefined and deny, which is a guess about a request it never saw.
package kamanu.spend

import rego.v1

default allow := false

# unsupported
allow if {
	input.principal.role == "treasurer"
}
