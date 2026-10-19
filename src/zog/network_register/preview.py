"""Non-binding, read-only DNS reconciliation inspection for trusted consumers.

Preview is not a prepared operation or a write authorization. It never
changes ledger state or invokes provider mutation methods. Consumers must
still use the ordinary plan/prepare/apply lifecycle to publish records.
"""
from dataclasses import asdict, dataclass
import ipaddress

from .contracts import NetworkError
from .ledger import TERMINAL
from .models import Plan, RecordSnapshot, resource_uuid, revision, observation_name


@dataclass(frozen=True)
class PreviewRecord:
    record_id: str
    name: str
    type: str
    address: str | None
    ttl: int | None
    proxied: bool | None
    matches_last_applied: bool


@dataclass(frozen=True)
class ReconciliationPreview:
    """Stable serializable preview DTO. No credentials or provider comments."""

    owner_id: str
    binding_id: str
    resource_id: str
    provider: str
    zone_name: str
    hostname: str | None
    connection_revision: int
    binding_revision: int
    desired_revision: int
    desired: RecordSnapshot | None
    last_applied: RecordSnapshot | None
    outcome: str                     # candidate | no-op | blocked
    proposed_action: str             # create | update | delete | none
    reason: str                      # stable, sanitized machine reason
    authorized: bool | None          # True checked; False denied; None not checked
    observed_count: int | None       # None means no provider inventory was read
    observed: tuple[PreviewRecord, ...]
    schema: int = 1
    read_only: bool = True

    def to_dict(self):
        return asdict(self)


def _view(row, owned, before, matches):
    name = observation_name(row['name'])
    address = None
    if row['type'] == 'A' and isinstance(row.get('content'), str):
        try:
            address = str(ipaddress.IPv4Address(row['content']))
        except ipaddress.AddressValueError:
            pass
    ttl = row.get('ttl')
    proxied = row.get('proxied')
    return PreviewRecord(
        record_id=str(row['id']), name=name, type=row['type'],
        address=address, ttl=ttl if type(ttl) is int else None,
        proxied=proxied if type(proxied) is bool else None,
        matches_last_applied=bool(
            owned and before and owned.get('marker') and
            matches(row, before, owned['marker'], owned['record_id'])))


def inspect_reconciliation(engine, actor, owner_id, binding_id, resource_id,
                           desired, desired_revision, *, delete=False):
    """Return provider-backed inspection without preparing or dispatching.

    Only the authorized actor can inspect the binding. Candidate status is
    advisory: a later plan/prepare/apply MUST recheck authority, evidence,
    state revisions and actual provider records.
    """
    from .engine import matches
    resource_id = resource_uuid(resource_id)
    revision(desired_revision)
    if (type(delete) is not bool or (desired is None) != delete or
            (desired is not None and not isinstance(desired, RecordSnapshot))):
        raise ValueError('Supply desired A snapshot or explicit delete=True')

    c, b, owned = engine._context(actor, owner_id, binding_id, resource_id)
    before = RecordSnapshot(**owned['last_applied']) if owned else None
    hostname = (desired or before).name if (desired or before) else None
    seen = ()
    count = None

    def result(outcome, reason, action='none', authorized=None):
        return ReconciliationPreview(
            owner_id=owner_id, binding_id=b.id, resource_id=resource_id,
            provider=c.provider, zone_name=b.zone_name, hostname=hostname,
            connection_revision=c.revision, binding_revision=b.revision,
            desired_revision=desired_revision, desired=desired,
            last_applied=before, outcome=outcome, proposed_action=action,
            reason=reason, authorized=authorized, observed_count=count,
            observed=seen)

    def pending_operation():
        with engine.store.transaction():
            return any(
                row['binding_id'] == b.id and row['state'] not in TERMINAL
                for row in engine.store.all('operation'))

    if c.status != 'ready':
        return result('blocked', 'connection-not-ready')
    if b.status != 'ready':
        return result('blocked', 'binding-not-ready')
    if pending_operation():
        return result('blocked', 'pending-operation')
    if before and desired and before.name != desired.name:
        return result('blocked', 'rename-not-supported')
    if hostname is None:
        # Explicit delete for an unowned resource has no target to inspect.
        return result('no-op', 'not-managed')

    action = 'delete' if delete else 'update' if owned else 'create'
    plan = Plan(owner_id, b.id, resource_id, c.revision, b.revision,
                desired_revision, action, before, desired,
                owned['record_id'] if owned else None)

    try:
        engine.ledger._ready(c, b, plan)
    except NetworkError as error:
        return result('blocked', 'plan-' + error.code)
    try:
        engine._gate(c, b, resource_id, desired,
                     'unpublish' if delete else 'publish', desired_revision)
    except NetworkError as error:
        return result('blocked', 'publication-' + error.code, authorized=False)
    try:
        engine._gate(c, b, resource_id, None, 'inspect')
    except NetworkError as error:
        return result('blocked', 'inspection-' + error.code, authorized=False)

    try:
        rows = engine._inventory(engine.provider_factory(c), c, b, resource_id)
        direct = [
            row for row in rows
            if observation_name(row['name']) == hostname
            and row['type'] in ('A', 'CNAME', 'DNAME', 'NS')]
        count = len(direct)
        seen = tuple(_view(row, owned, before, matches) for row in direct[:20])
        relevant = engine._relevant(rows, hostname, b.zone_name)
    except NetworkError as error:
        return result('blocked', 'provider-' + error.code, authorized=True)

    # Provider network reads may have overlapped with a concurrent operation
    # or permission/configuration change; never issue a stale candidate.
    current_c, current_b, current_owned = engine._context(
        actor, owner_id, b.id, resource_id)
    if (current_c != c or current_b != b or current_owned != owned or
            pending_operation()):
        return result('blocked', 'scope-changed', authorized=True)
    # Read-only inventory is not a durable grant; recheck publisher evidence
    # after network IO so a changed authority gate cannot yield a candidate.
    try:
        engine._gate(c, b, resource_id, desired,
                     'unpublish' if delete else 'publish', desired_revision)
        engine._gate(c, b, resource_id, None, 'inspect')
    except NetworkError as error:
        return result('blocked', 'publication-' + error.code, authorized=False)

    if owned:
        if (not owned.get('marker') or len(relevant) != 1 or
                not matches(relevant[0], before, owned['marker'],
                            owned['record_id'])):
            return result('blocked', 'owned-record-drift', authorized=True)
    elif relevant:
        return result('blocked', 'unmanaged-record', authorized=True)

    if desired == before:
        return result('no-op', 'already-matches', authorized=True)
    return result('candidate', action + '-candidate', action, authorized=True)
