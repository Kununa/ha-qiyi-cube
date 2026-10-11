"""Sensors for QiYi Smart Cube."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol
from .coordinator import QiYiCubeConfigEntry
from .cube import CubeData
from .entity import QiYiCubeEntity, with_english_ids


@dataclass(frozen=True, kw_only=True)
class QiYiSensorDescription(SensorEntityDescription):
    value_fn: Callable[[CubeData], Any]
    attrs_fn: Callable[[CubeData], dict[str, Any] | None] | None = None
    attr_keys: tuple[str, ...] = ()  # restored while the cube is asleep


# Standard colour scheme; matches the user's cube (white up, green front, red right).
FACE_COLORS = {
    "U": "white", "R": "red", "F": "green", "D": "yellow", "L": "orange", "B": "blue"
}

SOLVE_ATTRS = ("tps", "scramble_moves", "scramble_distance", "inspection_seconds")


def _solve_attrs(d: CubeData) -> dict[str, Any] | None:
    if (r := d.last_solve) is None:
        return None
    return {
        "tps": r.tps,
        "scramble_moves": r.scramble_moves,
        "scramble_distance": r.scramble_distance,
        "inspection_seconds": r.inspection_seconds,
    }


FACELET_ATTRS = ("facelets", *(f"face_{f.lower()}" for f in protocol.FACES))


def _facelet_attrs(d: CubeData) -> dict[str, Any] | None:
    if d.facelets is None:
        return None
    faces = protocol.split_faces(d.facelets)
    return {"facelets": d.facelets} | {f"face_{f.lower()}": v for f, v in faces.items()}


SENSORS = (
    QiYiSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.battery,
    ),
    QiYiSensorDescription(
        key="last_move",
        translation_key="last_move",
        value_fn=lambda d: d.last_move,
    ),
    QiYiSensorDescription(
        key="moves_since_solved",
        translation_key="moves_since_solved",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.moves_since_solved,
    ),
    QiYiSensorDescription(
        key="last_solve_moves",
        translation_key="last_solve_moves",
        value_fn=lambda d: d.last_solve and d.last_solve.moves,
    ),
    QiYiSensorDescription(
        key="last_solve_duration",
        translation_key="last_solve_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda d: d.last_solve and d.last_solve.seconds,
        attrs_fn=_solve_attrs,
        attr_keys=SOLVE_ATTRS,
    ),
    QiYiSensorDescription(
        key="solved_faces",
        translation_key="solved_faces",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (
            None if d.facelets is None else protocol.solved_faces(d.facelets)
        ),
        attrs_fn=_facelet_attrs,
        attr_keys=FACELET_ATTRS,
    ),
    QiYiSensorDescription(
        key="moves_to_solve",
        translation_key="moves_to_solve",
        value_fn=lambda d: None if d.solution is None else len(d.solution),
        attrs_fn=lambda d: (
            None if d.solution is None else {"solution": " ".join(d.solution)}
        ),
        attr_keys=("solution",),
    ),
    QiYiSensorDescription(
        key="top_face",
        translation_key="top_face",
        device_class=SensorDeviceClass.ENUM,
        options=list(FACE_COLORS.values()),
        value_fn=lambda d: FACE_COLORS.get(d.top_face),
    ),
)

ORIENTATION = SensorEntityDescription(
    key="orientation",
    translation_key="orientation",
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: QiYiCubeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[QiYiCubeEntity] = [
        QiYiCubeSensor(coordinator, description) for description in SENSORS
    ]
    entities.append(QiYiOrientationSensor(coordinator, ORIENTATION))
    async_add_entities(with_english_ids("sensor", entities))


class QiYiCubeSensor(QiYiCubeEntity, RestoreSensor):
    """Cube sensor; restores its last value since the cube is usually asleep."""

    entity_description: QiYiSensorDescription
    _restored: Any = None
    _restored_attrs: dict[str, Any] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._restored = None
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._restored = last.native_value
        if (keys := self.entity_description.attr_keys) and (
            last_state := await self.async_get_last_state()
        ):
            self._restored_attrs = {
                k: v for k, v in last_state.attributes.items() if k in keys
            } or None

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value_fn(self.coordinator.data)
        return self._restored if value is None else value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if (attrs_fn := self.entity_description.attrs_fn) is None:
            return None
        attrs = attrs_fn(self.coordinator.data)
        return self._restored_attrs if attrs is None else attrs


class QiYiOrientationSensor(QiYiCubeEntity, SensorEntity):
    """Raw gyro quaternion (w, x, y, z) from the cube, at most once a second."""

    _unrecorded_attributes = frozenset({"w", "x", "y", "z"})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.async_add_orientation_listener(self.async_write_ha_state)
        )
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def native_value(self) -> str | None:
        q = self.coordinator.data.quaternion
        return None if q is None else ", ".join(f"{v:.3f}" for v in q)

    @property
    def extra_state_attributes(self) -> dict[str, float] | None:
        q = self.coordinator.data.quaternion
        return None if q is None else dict(zip("wxyz", q))
