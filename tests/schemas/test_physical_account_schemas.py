"""Unit tests for physical account and reconciliation Pydantic schemas."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.schemas.physical_account import (
    PhysicalAccountCreate,
    PhysicalAccountShareRead,
    ReconciliationRequest,
    ReconciliationResponse,
)


def test_reconciliation_request_valid() -> None:
    """Verify ReconciliationRequest with valid submitted_balance and optional notes."""
    req = ReconciliationRequest(
        submitted_balance=Decimal("1234.56"),
        notes="Interest payment true-up",
    )
    assert req.submitted_balance == Decimal("1234.56")
    assert req.notes == "Interest payment true-up"


def test_reconciliation_request_without_notes() -> None:
    """Verify ReconciliationRequest defaults notes to None when omitted."""
    req = ReconciliationRequest(submitted_balance=Decimal("0.00"))
    assert req.submitted_balance == Decimal("0.00")
    assert req.notes is None


def test_reconciliation_request_invalid_precision() -> None:
    """Verify ReconciliationRequest rejects decimal values with more than 2 decimal places."""
    with pytest.raises(ValidationError):
        ReconciliationRequest(submitted_balance=Decimal("100.999"))


def test_reconciliation_request_notes_too_long() -> None:
    """Verify ReconciliationRequest rejects notes exceeding 255 characters."""
    with pytest.raises(ValidationError):
        ReconciliationRequest(
            submitted_balance=Decimal("100.00"),
            notes="X" * 256,
        )


def test_reconciliation_response_model() -> None:
    """Verify ReconciliationResponse serialization and attributes."""
    event_id = uuid.uuid4()
    account_id = uuid.uuid4()
    tx_id = uuid.uuid4()
    now = datetime.now(UTC)

    resp = ReconciliationResponse(
        reconciliation_event_id=event_id,
        physical_account_id=account_id,
        previous_balance=Decimal("1000.00"),
        submitted_balance=Decimal("1050.00"),
        calculated_drift=Decimal("50.00"),
        transaction_id=tx_id,
        deficit_warning=False,
        timestamp=now,
    )

    assert resp.reconciliation_event_id == event_id
    assert resp.physical_account_id == account_id
    assert resp.previous_balance == Decimal("1000.00")
    assert resp.submitted_balance == Decimal("1050.00")
    assert resp.calculated_drift == Decimal("50.00")
    assert resp.transaction_id == tx_id
    assert resp.deficit_warning is False
    assert resp.timestamp == now


def test_physical_account_create_schema() -> None:
    """Verify PhysicalAccountCreate schema attributes and that owner_id is not accepted."""
    inst_id = uuid.uuid4()
    payload = PhysicalAccountCreate(
        name="Vault",
        institution_id=inst_id,
        tax_wrapper="NONE",
        currency="GBP",
    )
    assert payload.name == "Vault"
    assert payload.institution_id == inst_id
    assert not hasattr(payload, "owner_id")


def test_physical_account_share_read_schema() -> None:
    """Verify PhysicalAccountShareRead schema contains both created_at and updated_at."""
    now = datetime.now(UTC)
    share = PhysicalAccountShareRead(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        email="collab@example.com",
        first_name="Jane",
        last_name="Doe",
        role="CO_OWNER",
        created_at=now,
        updated_at=now,
    )
    assert share.created_at == now
    assert share.updated_at == now
    assert share.role == "CO_OWNER"
