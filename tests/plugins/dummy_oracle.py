"""A minimal third-party oracle used to prove discovery by dotted path."""

from __future__ import annotations

from weftgate.change import Change
from weftgate.oracle import BaseOracle, Context, OracleAPI
from weftgate.types import Claim, Finding, Location


class DummyOracle(BaseOracle):
    name = "dummy"
    kinds: tuple[str, ...] = ("dummy_ref",)

    def extract(self, change: Change, ctx: Context) -> list[Claim]:
        claims: list[Claim] = []
        for region in change.added_regions():
            for lineno, text in region.lines():
                if "DUMMY:" in text:
                    subject = text.split("DUMMY:", 1)[1].strip()
                    claims.append(Claim("dummy_ref", subject, Location(region.file, lineno)))
        return claims

    def check(self, claim: Claim, ctx: Context) -> Finding:
        if claim.subject == "ok":
            return self.accept(claim, "dummy ok")
        return self.reject(claim, "dummy says no", ["ok"])


def register(api: OracleAPI) -> None:
    api.register_oracle(DummyOracle())


def register_twice(api: OracleAPI) -> None:
    api.register_oracle(DummyOracle())
    api.register_oracle(DummyOracle())


class NotAnOracle:
    name = "nope"


def register_bad(api: OracleAPI) -> None:
    api.register_oracle(NotAnOracle())  # type: ignore[arg-type]
