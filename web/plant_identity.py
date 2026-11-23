"""Public plant tool identity and the immutable native receipt compatibility reader."""
PUBLIC_PRODUCER = 'plantismash-2.0.4-clusterweave-extras-v3'
LEGACY_PRODUCER = 'plantismash-2.0.4-private-repeat2'
SUPPORTED_PRODUCERS = frozenset((PUBLIC_PRODUCER, LEGACY_PRODUCER))


def public_producer(value):
    if value not in SUPPORTED_PRODUCERS:
        raise ValueError('Unknown plant scientific producer')
    return PUBLIC_PRODUCER


def matching_producers(left, right):
    return left in SUPPORTED_PRODUCERS and right in SUPPORTED_PRODUCERS
