from fastapi import APIRouter, HTTPException, status

from stustapay.core.http.auth_user import CurrentAuthToken
from stustapay.core.http.context import ContextTillService
from stustapay.core.http.normalize_data import NormalizedList, normalize_list
from stustapay.core.schema.till import NewTillButton, TillButton

router = APIRouter(
    prefix="/till-buttons",
    tags=["till-buttons"],
    responses={404: {"description": "Not found"}},
)


@router.get("", response_model=NormalizedList[TillButton, int])
async def list_till_buttons(token: CurrentAuthToken, till_service: ContextTillService, node_id: int):
    return normalize_list(await till_service.layout.list_buttons(token=token, node_id=node_id))


@router.post("", response_model=NewTillButton)
async def create_till_button(
    button: NewTillButton, token: CurrentAuthToken, till_service: ContextTillService, node_id: int
):
    return await till_service.layout.create_button(token=token, button=button, node_id=node_id)


@router.get("/{button_id}", response_model=TillButton)
async def get_till_button(button_id: int, token: CurrentAuthToken, till_service: ContextTillService, node_id: int):
    till = await till_service.layout.get_button(token=token, button_id=button_id, node_id=node_id)
    if till is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return till


@router.post("/{button_id}", response_model=TillButton)
async def update_till_button(
    button_id: int,
    button: NewTillButton,
    token: CurrentAuthToken,
    till_service: ContextTillService,
    node_id: int,
):
    till = await till_service.layout.update_button(token=token, button_id=button_id, button=button, node_id=node_id)
    if till is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return till


@router.delete("/{button_id}")
async def delete_till_button(button_id: int, token: CurrentAuthToken, till_service: ContextTillService, node_id: int):
    deleted = await till_service.layout.delete_button(token=token, button_id=button_id, node_id=node_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
