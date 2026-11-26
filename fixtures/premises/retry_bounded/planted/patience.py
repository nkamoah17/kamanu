"""Part of the planted defect of retries.py: one more attempt for each failure.

Written for KAMANU task T5.
"""


def one_more():
    import retries
    retries.ATTEMPTS = retries.ATTEMPTS + 1
