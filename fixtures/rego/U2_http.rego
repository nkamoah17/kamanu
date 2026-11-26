# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/external-data/index.md#option-5-pull-data-during-evaluation (http.send during evaluation)
# The total comes from a server during evaluation, not from the view.
package kamanu.spend

import rego.v1

default allow := false

# unsupported
allow if {
	ledger := http.send({"method": "get", "url": "https://ledger.example/spent"})
	ledger.body.total + input.amt <= 100
}
