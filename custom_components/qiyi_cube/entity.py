"""Base entity for QiYi Smart Cube."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.util import slugify

from .coordinator import QiYiCubeCoordinator


class QiYiCubeEntity(Entity):
    """Push-updated entity bound to one cube."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, coordinator: QiYiCubeCoordinator, description: EntityDescription
    ) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            name=coordinator.entry.title,
            manufacturer="QiYi",
            model=coordinator.entry.title.rsplit("-", 1)[0],
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


# Entity id suffixes that differ from the description key.
_OBJECT_IDS = {"connected": "connectivity"}


def with_english_ids[T: QiYiCubeEntity](domain: str, entities: Iterable[T]) -> list[T]:
    """Suggest entity ids from the (English) keys instead of translated names.

    Only affects entities that are not in the registry yet.
    """
    entities = list(entities)
    for entity in entities:
        key = entity.entity_description.key
        device = slugify(entity.coordinator.entry.title)
        entity.entity_id = f"{domain}.{device}_{_OBJECT_IDS.get(key, key)}"
    return entities
