"""Binary sensors for QiYi Smart Cube."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import QiYiCubeConfigEntry
from .entity import QiYiCubeEntity, with_english_ids

CONNECTED = BinarySensorEntityDescription(
    key="connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)
SOLVED = BinarySensorEntityDescription(key="solved", translation_key="solved")
SOLVING = BinarySensorEntityDescription(key="solving", translation_key="solving")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: QiYiCubeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        with_english_ids(
            "binary_sensor",
            [
                QiYiConnectedSensor(coordinator, CONNECTED),
                QiYiSolvedSensor(coordinator, SOLVED),
                QiYiSolvingSensor(coordinator, SOLVING),
            ],
        )
    )


class QiYiConnectedSensor(QiYiCubeEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool:
        return self.coordinator.data.connected


class QiYiSolvedSensor(QiYiCubeEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.solved


class QiYiSolvingSensor(QiYiCubeEntity, BinarySensorEntity):
    """A real solve is in progress (scrambled, inspected, now solving)."""

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.solving
