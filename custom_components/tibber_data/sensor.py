"""Tibber data"""
import logging
from typing import cast
import datetime

import tibber
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SENSORS, TIBBER_APP_SENSORS
from .data_coordinator import TibberDataCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass: HomeAssistant, _, async_add_entities, config):
    """Set up the Tibber sensor."""
    hass.data[DOMAIN] = {}
    dev = []
    for home in hass.data["tibber"].get_homes(only_active=True):
        home = cast(tibber.TibberHome, home)
        if not home.info:
            await home.update_info()
        coordinator = TibberDataCoordinator(
            hass, home, config.get("email"), config.get("password")
        )
        await coordinator.async_request_refresh()
        for entity_description in SENSORS:
            if (
                entity_description.key in ("daily_cost_with_subsidy",)
                and not home.has_real_time_consumption
            ):
                continue

            if (
                entity_description.key in ("production_profit_month",)
                and not home.has_production
            ):
                continue

            if entity_description.key in ("production_profit_day",) and (
                not home.has_production or not home.has_real_time_consumption
            ):
                continue

            dev.append(TibberDataSensor(coordinator, entity_description))

        if config.get("password"):
            for entity_description in TIBBER_APP_SENSORS:
                dev.append(TibberDataSensor(coordinator, entity_description))
            for (
                chargers_entity_descritpions
            ) in coordinator.chargers_entity_descriptions:
                dev.append(TibberDataSensor(coordinator, chargers_entity_descritpions))

    async_add_entities(dev)


class TibberDataSensor(SensorEntity, CoordinatorEntity["TibberDataCoordinator"]):
    """Representation of a Tibber sensor."""

    def __init__(self, coordinator, entity_description):
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.tibber_home.home_id}_{entity_description.key}"
        )
        if entity_description.native_unit_of_measurement is None:
            if entity_description.device_class == SensorDeviceClass.MONETARY:
                self._attr_native_unit_of_measurement = coordinator.tibber_home.currency
            else:
                self._attr_native_unit_of_measurement = (
                    coordinator.tibber_home.price_unit
                )

    @property
    def _attr_name(self):
        """Return the name of the sensor."""
        _name = self.coordinator.data.get(f"{self.entity_description.key}_name")
        if _name:
            return _name
        return f"{self.entity_description.name} {self.coordinator.tibber_home.address1}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.entity_description.key == "est_current_price_with_subsidy":
            price = self.coordinator.get_price_at(dt_util.now())
            if self.coordinator.data.get("est_subsidy") is not None:
                native_value = price - self.coordinator.data["est_subsidy"]
            else:
                native_value = None
        elif self.entity_description.key == "grid_price":

            self._attr_extra_state_attributes = {}
            local_today = []
            local_raw_today = []
            local_tomorrow = []
            local_raw_tomorrow = []
            priceinfo = self.coordinator.data.get("hourly_prices", {})
            # check if data has grid prices and add to attributes if available
            if (priceinfo[1]["gridPrice"]):
                for entry in priceinfo:
                    if (dt_util.parse_datetime(entry["time"]).date() == dt_util.now().date() ):
                        local_today.append(entry["gridPrice"])
                        local_raw_today.append({"time":entry["time"],"gridPrice":entry["gridPrice"]})
                    if (dt_util.parse_datetime(entry["time"]).date() == (dt_util.now().date() + datetime.timedelta(days=1)) ):
                        local_tomorrow.append(entry["gridPrice"])
                        local_raw_tomorrow.append({"time":entry["time"],"gridPrice":entry["gridPrice"]})
                
                self._attr_extra_state_attributes["today"] = local_today
                self._attr_extra_state_attributes["raw_today"] = local_raw_today
                if (len(local_tomorrow) > 0):
                    self._attr_extra_state_attributes["tomorrow_valid"] = True
                else:
                    self._attr_extra_state_attributes["tomorrow_valid"] = False
                    _LOGGER.debug("No priceinfo for tomorrow")
                self._attr_extra_state_attributes["tomorrow"] = local_tomorrow
                self._attr_extra_state_attributes["raw_tomorrow"] = local_raw_tomorrow
            else:
                _LOGGER.debug("No grid price available")
            
            native_value = self.coordinator.data.get(
                self.entity_description.key, {}
            ).get(dt_util.now().replace(minute=0, second=0, microsecond=0))
        elif self.entity_description.key == "total_price_with_subsidy":
            if self.coordinator.data.get("est_subsidy") is not None:
                grid_price = self.coordinator.data.get("grid_price", {}).get(
                    dt_util.now().replace(minute=0, second=0, microsecond=0)
                )
                if grid_price is None:
                    return
                price = self.coordinator.get_price_at(dt_util.now())
                native_value = (
                    grid_price + price - self.coordinator.data["est_subsidy"]
                )
            else:
                native_value = None
                
        elif self.entity_description.key == "energy_price":
            
            self._attr_extra_state_attributes = {}
            
            priceinfo = self.coordinator.data.get("hourly_prices", {})
            # find current price
            now_hour = dt_util.now().replace(minute=0, second=0, microsecond=0)
            for i in priceinfo:
                if dt_util.parse_datetime(i["time"]) == now_hour:
                    native_value = i["total"]
            
            local_today = []
            local_raw_today = []
            local_tomorrow = []
            local_raw_tomorrow = []

            for entry in priceinfo:
                if (dt_util.parse_datetime(entry["time"]).date() == dt_util.now().date() ):
                    local_today.append(entry["total"])
                    local_raw_today.append({"time":entry["time"],"total":entry["total"]})
                if (dt_util.parse_datetime(entry["time"]).date() == (dt_util.now().date() + datetime.timedelta(days=1)) ):
                    local_tomorrow.append(entry["total"])
                    local_raw_tomorrow.append({"time":entry["time"],"total":entry["total"]})

            self._attr_extra_state_attributes["today"] = local_today
            self._attr_extra_state_attributes["raw_today"] = local_raw_today
            if (len(local_tomorrow) > 0):
                self._attr_extra_state_attributes["tomorrow_valid"] = True
                
            else:
                self._attr_extra_state_attributes["tomorrow_valid"] = False
                _LOGGER.debug("No priceinfo for tomorrow")
            self._attr_extra_state_attributes["tomorrow"] = local_tomorrow
            self._attr_extra_state_attributes["raw_tomorrow"] = local_raw_tomorrow
        
        elif self.entity_description.key == "total_price":
            
            self._attr_extra_state_attributes = {}
            native_value = None
            
            priceinfo = self.coordinator.data.get("hourly_prices", {})
            # check if data has grid prices and add to attributes if available
            if (priceinfo[1]["gridPrice"]):
                # find current price
                now_hour = dt_util.now().replace(minute=0, second=0, microsecond=0)
                for i in priceinfo:
                    if dt_util.parse_datetime(i["time"]) == now_hour:
                        native_value = round(i["total"] + i["gridPrice"], 4)
                
                local_today = []
                local_raw_today = []
                local_tomorrow = []
                local_raw_tomorrow = []
                for entry in priceinfo:
                    if (dt_util.parse_datetime(entry["time"]).date() == dt_util.now().date() ):
                        local_today.append(round(entry["total"] + entry["gridPrice"], 4))
                        local_raw_today.append({"time":entry["time"],"total_with_gridPrice":round(entry["total"] + entry["gridPrice"], 4)})
                    if (dt_util.parse_datetime(entry["time"]).date() == (dt_util.now().date() + datetime.timedelta(days=1)) ):
                        local_tomorrow.append(round(entry["total"] + entry["gridPrice"], 4))
                        local_raw_tomorrow.append({"time":entry["time"],"total_with_gridPrice":round(entry["total"] + entry["gridPrice"], 4)})
                
                self._attr_extra_state_attributes["today"] = local_today
                self._attr_extra_state_attributes["raw_today"] = local_raw_today
                if (len(local_tomorrow) > 0):
                    self._attr_extra_state_attributes["tomorrow_valid"] = True
                else:
                    self._attr_extra_state_attributes["tomorrow_valid"] = False
                    _LOGGER.debug("No priceinfo for tomorrow")
                self._attr_extra_state_attributes["tomorrow"] = local_tomorrow
                self._attr_extra_state_attributes["raw_tomorrow"] = local_raw_tomorrow
            else:
                _LOGGER.debug("No grid price available, no total price to add")
 
        else:
            native_value = self.coordinator.data.get(self.entity_description.key)

        self._attr_native_value = (
            round(native_value, 2) if native_value else native_value
        )
        if self.entity_description.key == "peak_consumption":
            self._attr_extra_state_attributes = self.coordinator.data.get(
                "peak_consumption_attrs"
            )

        self.async_write_ha_state()
