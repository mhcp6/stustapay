from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from stustapay.core.http.auth_user import CurrentAuthToken
from stustapay.core.http.context import ContextAccountService
from stustapay.core.schema.account import Account

router = APIRouter(
    prefix="",
    tags=["accounts"],
    responses={404: {"description": "Not found"}},
)


@router.get("/system-accounts", response_model=list[Account])
async def list_system_accounts(token: CurrentAuthToken, account_service: ContextAccountService):
    return await account_service.list_system_accounts(token=token)


class FindAccountPayload(BaseModel):
    search_term: str


@router.post("/accounts/find-accounts", response_model=list[Account])
async def find_accounts(token: CurrentAuthToken, account_service: ContextAccountService, payload: FindAccountPayload):
    return await account_service.find_accounts(token=token, search_term=payload.search_term)


@router.get("/accounts/{account_id}", response_model=Account)
async def get_account(token: CurrentAuthToken, account_service: ContextAccountService, account_id: int):
    account = await account_service.get_account(token=token, account_id=account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return account


class UpdateBalancePayload(BaseModel):
    new_balance: float


@router.post("/accounts/{account_id}/update-balance")
async def update_balance(
    token: CurrentAuthToken, account_service: ContextAccountService, account_id: int, payload: UpdateBalancePayload
):
    await account_service.update_account_balance(token=token, account_id=account_id, new_balance=payload.new_balance)


class UpdateVoucherAmountPayload(BaseModel):
    new_voucher_amount: int


@router.post("/accounts/{account_id}/update-voucher-amount")
async def update_voucher_amount(
    token: CurrentAuthToken,
    account_service: ContextAccountService,
    account_id: int,
    payload: UpdateVoucherAmountPayload,
):
    await account_service.update_account_vouchers(
        token=token, account_id=account_id, new_voucher_amount=payload.new_voucher_amount
    )


class UpdateTagUidPayload(BaseModel):
    new_tag_uid: int


@router.post("/accounts/{account_id}/update-tag_uid")
async def update_tag_uid(
    token: CurrentAuthToken,
    account_service: ContextAccountService,
    account_id: int,
    payload: UpdateTagUidPayload,
):
    success = await account_service.switch_account_tag_uid_admin(
        token=token, account_id=account_id, new_user_tag_uid=payload.new_tag_uid
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
