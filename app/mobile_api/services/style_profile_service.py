from __future__ import annotations

from app.database.db import (
    get_default_style_profile,
    get_style_profile,
    list_style_profiles,
    set_default_style_profile,
)
from app.mobile_api import dependencies


class StyleProfileService:
    def __init__(self):
        self.db_path = dependencies.get_db_path()

    def list_profiles(self) -> list[dict]:
        return list_style_profiles(self.db_path)

    def get_profile(self, profile_id: str) -> dict | None:
        return get_style_profile(self.db_path, profile_id)

    def get_default(self) -> dict | None:
        return get_default_style_profile(self.db_path)

    def set_default(self, profile_id: str) -> dict | None:
        if not set_default_style_profile(self.db_path, profile_id):
            return None
        return self.get_default()
