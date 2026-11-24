"""Signed version-vector observations. A max vector alone is NOT a causal snapshot."""

from dataclasses import asdict, dataclass, field

from recovery.crypto import canonical, sign, verify


@dataclass(frozen=True)
class Checkpoint:
    epoch: int
    cut: dict[str, int]
    org_id: str
    sig: str
    chain_id: str = ""
    receipts: list[dict] = field(default_factory=list)
    state_digest: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)

        # Protobuf Struct transports JSON numbers as doubles. Accept only exact integers.
        def integer(value):
            if type(value) is float and value.is_integer() and abs(value) <= 2**53:
                return int(value)
            return value

        data["epoch"] = integer(data.get("epoch"))
        if isinstance(data.get("cut"), dict):
            data["cut"] = {k: integer(v) for k, v in data["cut"].items()}
        cp = cls(**data)
        _validate(cp)
        return cp


def _validate(cp):
    if not isinstance(cp.org_id, str) or not cp.org_id:
        raise ValueError("org_id required")
    if type(cp.epoch) is not int or cp.epoch < 1:
        raise ValueError("positive epoch required")
    if not isinstance(cp.chain_id, str) or not isinstance(cp.cut, dict):
        raise TypeError("invalid checkpoint scope")
    if not isinstance(cp.state_digest, str):
        raise TypeError("invalid state digest")
    if not isinstance(cp.receipts, list) or any(not isinstance(r, dict) for r in cp.receipts):
        raise TypeError("invalid receipt manifest")
    if cp.org_id not in cp.cut or any(
        not isinstance(k, str) or not k or type(v) is not int or v < 0 for k, v in cp.cut.items()
    ):
        raise ValueError("invalid version vector")


def _body(cp):
    return canonical({k: v for k, v in cp.to_dict().items() if k != "sig"})


def compute_cut(stores):
    """Sample local counters; does not freeze distributed stores."""
    return {org: store.version for org, store in stores.items()}


def make_checkpoint(priv, org_id, epoch, cut, chain_id="", receipts=None, state_digest=""):
    cp = Checkpoint(epoch, dict(cut), org_id, "", chain_id, list(receipts or []), state_digest)
    _validate(cp)
    return Checkpoint(
        epoch, dict(cut), org_id, sign(priv, _body(cp)), chain_id, cp.receipts, state_digest
    )


def verify_checkpoint(pub, cp):
    try:
        _validate(cp)
        return verify(pub, _body(cp), cp.sig)
    except (ValueError, TypeError, AttributeError):
        return False


def dominant_cut(cuts):
    """Component-wise join of observations, never proof of causal consistency."""
    result = {}
    for cp in cuts:
        _validate(cp)
        for org, version in cp.cut.items():
            result[org] = max(result.get(org, 0), version)
    return result
