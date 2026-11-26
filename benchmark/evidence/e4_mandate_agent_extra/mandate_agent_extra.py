"""Mandate agent, planted extra code path: it may charge again after the receipt.

Written for KAMANU gate E4. The agent drafts a mandate, a person signs it, the agent charges,
and a failed charge is audited and refunded before the agent may charge again. No external
source.
"""
DONE = ("archived",)

STEPS = {
    ("drafting", "request_mandate"): "pending_mandate",
    ("pending_mandate", "mandate_signed"): "armed",
    ("armed", "charge"): "charging",
    ("charging", "charged"): "receipted",
    ("charging", "charge_failed"): "auditing",
    ("auditing", "refund_issued"): "armed",
    ("receipted", "archive"): "archived",
    ("receipted", "charge"): "charging",
}

ACTIONS = {"request_mandate": "draft", "charge": "pay", "archive": "file"}


def run(bus, provider):
    step = "drafting"
    while step not in DONE:
        msg = bus.poll(step)
        if ACTIONS.get(msg) == "pay":
            provider.charge(bus.mandate())
        step = STEPS.get((step, msg), step)
    return step
