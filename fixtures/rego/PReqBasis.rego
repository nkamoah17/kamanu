# kernel: PReqBasis
# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/policy-language.md#array-comprehensions (an array keeps equal amounts apart)
# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/policy-language.md#default-keyword (deny unless a rule says otherwise)
# source: https://github.com/open-policy-agent/opa/blob/v1.22.2/docs/docs/external-data/index.md#option-3-bundle-api (the event log is data replicated by a bundle)
# The log is data.kamanu.events and the request is input. data, not input, is what makes
# the decision stale: OPA reads the bundle it last downloaded.
package kamanu.spend

import rego.v1

default allow := false

spent := sum([e.amt | some e in data.kamanu.events; e.kind == "request"])

allow if spent <= 100
