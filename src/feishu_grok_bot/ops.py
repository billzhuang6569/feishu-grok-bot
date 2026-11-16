"""Health and bounded reconnect policy; no probes and no implicit sends."""
from dataclasses import dataclass


@dataclass
class Health:
    process: bool = False
    local_bus: bool = False
    upstream_at: float | None = None
    e2e_at: float | None = None

    def snapshot(self, now, ttl=120):
        def freshness(at):
            return 'unknown' if at is None else ('recent_observation' if 0 <= now-at < ttl else 'stale')
        return dict(process='alive' if self.process else 'stopped',
                    local_bus='ready' if self.local_bus else 'disconnected',
                    upstream=freshness(self.upstream_at), e2e=freshness(self.e2e_at))


@dataclass
class Recovery:
    failures: int = 0
    maximum: int = 5

    def disconnected(self, health):
        health.local_bus = False
        self.failures += 1
        return None if self.failures > self.maximum else min(2 ** (self.failures-1), 30)

    def stable(self):
        self.failures = 0
