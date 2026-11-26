# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/policy-language.md#built-in-functions (time.now_ns)
# A day window read from the clock. Kernel views have no timestamps and no clock.
package kamanu.spend

import rego.v1

default allow := false

# unsupported
allow if {
	since := time.now_ns() - 86400000000000
	sum([e.amt | some e in data.kamanu.events; e.kind == "request"; e.ts > since]) <= 100
}
