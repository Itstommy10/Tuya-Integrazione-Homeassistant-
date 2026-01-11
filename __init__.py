"""Support for Tuya Smart devices."""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from tuya_sharing import (
    CustomerDevice,
    Manager,
    SharingDeviceListener,
    SharingTokenListener,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import dispatcher_send

from .const import (
    CONF_ENDPOINT,
    CONF_TERMINAL_ID,
    CONF_TOKEN_INFO,
    CONF_USER_CODE,
    DOMAIN,
    LOGGER,
    PLATFORMS,
    TUYA_CLIENT_ID,
    TUYA_DISCOVERY_NEW,
    TUYA_HA_SIGNAL_UPDATE_ENTITY,
)

# Suppress logs from the library, it logs unneeded on error
logging.getLogger("tuya_sharing").setLevel(logging.CRITICAL)

type TuyaConfigEntry = ConfigEntry[HomeAssistantTuyaData]


class HomeAssistantTuyaData(NamedTuple):
    """Tuya data stored in the Home Assistant data object."""

    manager: Manager
    listener: SharingDeviceListener


def _create_manager(entry: TuyaConfigEntry, token_listener: TokenListener) -> Manager:
    """Create a Tuya Manager instance."""
    return Manager(
        TUYA_CLIENT_ID,
        entry.data[CONF_USER_CODE],
        entry.data[CONF_TERMINAL_ID],
        entry.data[CONF_ENDPOINT],
        entry.data[CONF_TOKEN_INFO],
        token_listener,
    )


# def patch_tuya_sharing():
#     """Applica patch a tuya_sharing per supportare DP 19"""
    
#     # Salva il metodo originale
#     original_on_device_report = Manager._on_device_report
    
#     def patched_on_device_report(self, device_id: str, status: list[dict]):
#         """Versione patchata che accetta il DP 19"""
        
#         # Per il dispositivo specifico, aggiungi il mapping DP 19 prima di processare
#         if device_id == "bffeaed51892c5c7bdxrae":
#             device = self.device_map.get(device_id)
#             if device:
#                 # Aggiungi work_state alla mappatura se non esiste
#                 if hasattr(device, 'status_range'):
#                     if 19 not in device.status_range:
#                         device.status_range[19] = "work_state"
#                         LOGGER.info(f"Added DP 19 mapping for device {device_id}")
                
#                 # Processa i dati in arrivo e aggiungi il code se manca
#                 for item in status:
#                     if isinstance(item, dict) and item.get('dpId') == 19:
#                         # Il problema è che il manager cerca il code ma trova solo dpId
#                         # Aggiungiamolo manualmente
#                         if 'code' not in item:
#                             item['code'] = 'work_state'
#                         LOGGER.info(f"DP 19 received: {item.get('value')}")
        
#         # Chiama il metodo originale
#         return original_on_device_report(self, device_id, status)
    

#     Manager._on_device_report = patched_on_device_report
#     LOGGER.info("Applied tuya_sharing monkey patch for DP 19")


"""
Funzione completa async_setup_entry con patch per DP 19
Inserisci questo codice nel tuo __init__.py
"""

import logging
from tuya_sharing import Manager, CustomerDevice, DeviceFunction

LOGGER = logging.getLogger(__name__)


def patch_tuya_sharing():
    """Applica patch a tuya_sharing per supportare DP 19"""
    
    # Salva il metodo originale
    original_on_device_report = Manager._on_device_report
    
    def patched_on_device_report(self, device_id: str, status: list[dict]):
        """Versione patchata che accetta il DP 19"""
        
        # Per il dispositivo specifico, aggiungi il mapping DP 19 prima di processare
        if device_id == "bffeaed51892c5c7bdxrae":
            device = self.device_map.get(device_id)
            if device:
                # Aggiungi work_state alla mappatura se non esiste
                if hasattr(device, 'status_range'):
                    if 19 not in device.status_range:
                        device.status_range[19] = "work_state"
                        LOGGER.info(f"Added DP 19 mapping for device {device_id}")
                
                # Processa i dati in arrivo
                for item in status:
                    if isinstance(item, dict) and item.get('dpId') == 19:
                        # Aggiungi il code se manca
                        if 'code' not in item:
                            item['code'] = 'work_state'
                        
                        work_state_value = item.get('value')
                        LOGGER.info(f"DP 19 received: {work_state_value}")
                        
                        # IMPORTANTE: Aggiorna direttamente lo status del dispositivo
                        # Questo deve essere fatto PRIMA di chiamare il metodo originale
                        device.status['work_state'] = work_state_value
                        LOGGER.info(f"Updated device.status['work_state'] to: {work_state_value}")
        
        # Chiama il metodo originale
        return original_on_device_report(self, device_id, status)
    

    Manager._on_device_report = patched_on_device_report
    LOGGER.info("Applied tuya_sharing monkey patch for DP 19")


async def async_setup_entry(hass: HomeAssistant, entry: TuyaConfigEntry) -> bool:
    """Async setup hass config entry."""
    
    # ===== PATCH TUYA_SHARING PER DP 19 =====
    patch_tuya_sharing()
    # =========================================
    
    token_listener = TokenListener(hass, entry)

    # Move to executor as it makes blocking call to import_module
    # with args ('.system', 'urllib3.contrib.resolver')
    manager = await hass.async_add_executor_job(_create_manager, entry, token_listener)

    listener = DeviceListener(hass, manager)
    manager.add_device_listener(listener)

    # Get all devices from Tuya
    try:
        await hass.async_add_executor_job(manager.update_device_cache)
    except Exception as exc:
        # While in general, we should avoid catching broad exceptions,
        # we have no other way of detecting this case.
        if "sign invalid" in str(exc):
            msg = "Authentication failed. Please re-authenticate"
            raise ConfigEntryAuthFailed(msg) from exc
        raise

    # ===== CONFIGURA IL DISPOSITIVO PER DP 19 =====
    dev_id = "bffeaed51892c5c7bdxrae"
    if dev_id in manager.device_map:
        device = manager.device_map[dev_id]
        
        # Aggiungi la funzione work_state
        if "work_state" not in device.function:
            device.function["work_state"] = DeviceFunction(
                code='work_state',
                type='Enum',
                values='{"range":["heating","stop","idle"]}'
            )
            LOGGER.info(f"Added work_state function to device {dev_id}")
        
        # Aggiungi il mapping DP 19 -> work_state
        if hasattr(device, 'status_range'):
            device.status_range[19] = "work_state"
            LOGGER.info(f"Mapped DP 19 to work_state for device {dev_id}")
        
        # Inizializza lo stato
        if "work_state" not in device.status:
            device.status["work_state"] = "stop"
            LOGGER.info(f"Initialized work_state for device {dev_id}")
    else:
        LOGGER.error(f"Device {dev_id} not found in device_map")
    # ===============================================

    # Connection is successful, store the manager & listener
    entry.runtime_data = HomeAssistantTuyaData(manager=manager, listener=listener)

    # Cleanup device registry
    await cleanup_device_registry(hass, manager)

    # Register known device IDs
    device_registry = dr.async_get(hass)
    for device in manager.device_map.values():
        LOGGER.debug(
            "Register device %s (online: %s): %s (function: %s, status range: %s)",
            device.id,
            device.online,
            device.status,
            device.function,
            device.status_range,
        )
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, device.id)},
            manufacturer="Tuya",
            name=device.name,
            # Note: the model is overridden via entity.device_info property
            # when the entity is created. If no entities are generated, it will
            # stay as unsupported
            model=f"{device.product_name} (unsupported)",
            model_id=device.product_id,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # If the device does not register any entities, the device does not need to subscribe
    # So the subscription is here
    await hass.async_add_executor_job(manager.refresh_mq)
    return True


async def cleanup_device_registry(hass: HomeAssistant, device_manager: Manager) -> None:
    """Remove deleted device registry entry if there are no remaining entities."""
    device_registry = dr.async_get(hass)
    for dev_id, device_entry in list(device_registry.devices.items()):
        for item in device_entry.identifiers:
            if item[0] == DOMAIN and item[1] not in device_manager.device_map:
                device_registry.async_remove_device(dev_id)
                break


async def async_unload_entry(hass: HomeAssistant, entry: TuyaConfigEntry) -> bool:
    """Unloading the Tuya platforms."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        tuya = entry.runtime_data
        if tuya.manager.mq is not None:
            tuya.manager.mq.stop()
        tuya.manager.remove_device_listener(tuya.listener)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: TuyaConfigEntry) -> None:
    """Remove a config entry.

    This will revoke the credentials from Tuya.
    """
    manager = Manager(
        TUYA_CLIENT_ID,
        entry.data[CONF_USER_CODE],
        entry.data[CONF_TERMINAL_ID],
        entry.data[CONF_ENDPOINT],
        entry.data[CONF_TOKEN_INFO],
    )
    await hass.async_add_executor_job(manager.unload)


class DeviceListener(SharingDeviceListener):
    """Device Update Listener."""

    def __init__(
        self,
        hass: HomeAssistant,
        manager: Manager,
    ) -> None:
        """Init DeviceListener."""
        self.hass = hass
        self.manager = manager

    def update_device(
        self,
        device: CustomerDevice,
        updated_status_properties: list[str] | None = None,
        dp_timestamps: dict | None = None,
    ) -> None:
        """Update device status with optional DP timestamps."""
        LOGGER.debug(
            "Received update for device %s (online: %s): %s"
            " (updated properties: %s, dp_timestamps: %s)",
            device.id,
            device.online,
            device.status,
            updated_status_properties,
            dp_timestamps,
        )
        dispatcher_send(
            self.hass,
            f"{TUYA_HA_SIGNAL_UPDATE_ENTITY}_{device.id}",
            updated_status_properties,
            dp_timestamps,
        )

    def add_device(self, device: CustomerDevice) -> None:
        """Add device added listener."""
        # Ensure the device isn't present stale
        self.hass.add_job(self.async_remove_device, device.id)

        LOGGER.debug(
            "Add device %s (online: %s): %s (function: %s, status range: %s)",
            device.id,
            device.online,
            device.status,
            device.function,
            device.status_range,
        )

        dispatcher_send(self.hass, TUYA_DISCOVERY_NEW, [device.id])

    def remove_device(self, device_id: str) -> None:
        """Add device removed listener."""
        self.hass.add_job(self.async_remove_device, device_id)

    @callback
    def async_remove_device(self, device_id: str) -> None:
        """Remove device from Home Assistant."""
        LOGGER.debug("Remove device: %s", device_id)
        device_registry = dr.async_get(self.hass)
        device_entry = device_registry.async_get_device(
            identifiers={(DOMAIN, device_id)}
        )
        if device_entry is not None:
            device_registry.async_remove_device(device_entry.id)


class TokenListener(SharingTokenListener):
    """Token listener for upstream token updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: TuyaConfigEntry,
    ) -> None:
        """Init TokenListener."""
        self.hass = hass
        self.entry = entry

    def update_token(self, token_info: dict[str, Any]) -> None:
        """Update token info in config entry."""
        data = {
            **self.entry.data,
            CONF_TOKEN_INFO: {
                "t": token_info["t"],
                "uid": token_info["uid"],
                "expire_time": token_info["expire_time"],
                "access_token": token_info["access_token"],
                "refresh_token": token_info["refresh_token"],
            },
        }

        @callback
        def async_update_entry() -> None:
            """Update config entry."""
            self.hass.config_entries.async_update_entry(self.entry, data=data)

        self.hass.add_job(async_update_entry)
