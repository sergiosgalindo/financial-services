from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.models.database import (
    evaluate_credit_scoring_and_originate_loan,
    get_account_statement_from_db,
    get_db,
    list_customers_overview,
    process_ivr_validation_in_db,
    reconcile_payment_in_db,
    simulate_loan_in_db,
)
from app.models.schemas import (
    IVRValidationRequest,
    LoanSimulationRequest,
    LoanSimulationResponse,
    PaymentWebhookRequest,
)

router = APIRouter(prefix="/v1", tags=["Fintech Core Use Cases (CU-01..CU-04)"])


@router.get("/customers")
def list_customers_endpoint(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    return list_customers_overview(db)


@router.post("/loans/simulate", response_model=LoanSimulationResponse)
def simulate_loan_endpoint(
    payload: LoanSimulationRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return simulate_loan_in_db(
            db=db,
            user_identifier=payload.user_id,
            product_type=payload.product_type,
            requested_amount=payload.requested_amount,
            term_months=payload.term_months,
            term_days=payload.term_days,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/loans/originate")
def originate_loan_endpoint(
    payload: LoanSimulationRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return evaluate_credit_scoring_and_originate_loan(
            db=db,
            user_identifier=payload.user_id,
            product_type=payload.product_type,
            requested_amount=payload.requested_amount,
            term_months=payload.term_months,
            term_days=payload.term_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/security/ivr-validation")
def ivr_validation_endpoint(
    payload: IVRValidationRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return process_ivr_validation_in_db(
            db=db,
            user_identifier=payload.user_id,
            contract_id=payload.contract_id,
            validation_result=payload.validation_result,
            otp_code=payload.otp_code,
            call_sid=payload.call_sid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/accounts/{user_id}/statement")
def account_statement_endpoint(
    user_id: str,
    dispute_amount: Optional[float] = Query(default=None, ge=0),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return get_account_statement_from_db(
            db=db,
            user_identifier=user_id,
            register_dispute_amount=dispute_amount,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/payments/reconcile")
def reconcile_payment_endpoint(
    payload: PaymentWebhookRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return reconcile_payment_in_db(
            db=db,
            user_identifier=payload.user_id,
            amount=payload.amount,
            payment_method=payload.payment_method,
            bank_reference=payload.bank_reference,
            is_early_payoff=payload.is_early_payoff,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
