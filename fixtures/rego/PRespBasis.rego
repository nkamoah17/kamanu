# kernel: PRespBasis
# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/policy-language.md#array-comprehensions (an array keeps equal amounts apart)
# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/policy-language.md#default-keyword (deny unless a rule says otherwise)
# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/external-data/index.md#option-3-bundle-api (the event log is data replicated by a bundle)
# Completed responses only, plus this request's amount.
package kamanu.spend

import rego.v1

default allow := false

spent := sum([e.amt | some e in data.kamanu.events; e.kind == "response"])

allow if spent + input.amt <= 100
