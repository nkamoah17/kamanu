# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/policy-language.md#built-in-functions (rand.intn)
# Permit is a function of (view, r). A draw is not.
package kamanu.spend

import rego.v1

default allow := false

# unsupported
allow if {
	rand.intn("spend", 100) < 50
}
