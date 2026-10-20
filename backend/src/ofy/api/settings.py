from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ofy.config import PASSWORD_MASK, Settings
from ofy.db import load_settings, save_settings
from ofy.download.paths import TemplateError, validate_template

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _masked(settings: Settings) -> Settings:
    """The server is reachable on the network without login: never hand out the SSH password."""
    return settings.model_copy(update={"sync_password": PASSWORD_MASK if settings.sync_password else ""})


@router.get("")
def get_settings() -> Settings:
    return _masked(load_settings())


@router.put("")
def put_settings(new: Settings) -> Settings:
    try:
        validate_template(new.path_template)
    except TemplateError as e:
        raise HTTPException(400, f"Invalid path template: {e}") from e
    if new.sync_password == PASSWORD_MASK:
        new = new.model_copy(update={"sync_password": load_settings().sync_password})
    saved = save_settings(new)
    from ofy.jobs import queue

    queue.wake()
    return _masked(saved)
