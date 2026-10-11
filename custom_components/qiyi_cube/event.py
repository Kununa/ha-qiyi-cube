"""Move event entity for QiYi Smart Cube."""

from __future__ import annotations

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import QiYiCubeConfigEntry
from .entity import QiYiCubeEntity, with_english_ids
from .protocol import MOVES

MOVE = EventEntityDescription(
    key="move",
    translation_key="move",
    event_types=list(MOVES.values()),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: QiYiCubeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        with_english_ids("event", [QiYiMoveEvent(entry.runtime_data, MOVE)])
    )


class QiYiMoveEvent(QiYiCubeEntity, EventEntity):
    """Fires once per face turn; event_type is the move (e.g. "R'")."""

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_move_listener(self._on_move))

    @callback
    def _on_move(self, move: str, solved: bool) -> None:
        self._trigger_event(move, {"solved": solved})
        self.async_write_ha_state()
