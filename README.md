# Tuya Custom Integration
Versione modificata dell'integrazione Tuya per Home Assistant.

## Installazione via HACS
1. Aggiungi questo URL come repository personalizzato.
2. Clicca su Installa.
3. Riavvia Home Assistant.

## COME FUNZIONA
1. per visualizzare "calore" sul termostato quando il riscaldamento si accende effettivamente (la fiamma che vedi nell'app Tuya), 
    devi abilitare le istruzioni DP in Tuya Developer (quelle standard sono abilitate di default), in modo che il campo WORK_STATE sia visibile.
2. Ho modificato i file init.py aggiungendo:
```
import logging
from tuya_sharing import Manager, CustomerDevice, DeviceFunction

LOGGER = logging.getLogger( nome )

def patch_tuya_sharing():
    """Applica patch a tuya_sharing per supportare DP 19 su tutti i dispositivi."""

    original_on_device_report = Manager._on_device_report

    def patched_on_device_report(self, device_id: str, status: list[dict]):
        device = self.device_map.get(device_id)
        if device:
            # Cerchiamo se nel report c'è il DP 19
            for item in status:
                if isinstance(item, dict) and item.get('dpId') == 19:
                    # Se il dispositivo non conosce ancora il mapping per il DP 19, aggiungiamolo
                    if hasattr(device, 'status_range') and 19 not in device.status_range:
                        device.status_range[19] = "work_state"

                    # Forza il 'code' a 'work_state' se manca
                    if 'code' not in item:
                        item['code'] = 'work_state'

                    # Aggiorna lo stato interno per riflettere il cambiamento immediatamente
                    work_state_value = item.get('value')
                    device.status['work_state'] = work_state_value
                    LOGGER.debug(f"DP 19 generic patch: Device {device_id} updated to {work_state_value}")

        return original_on_device_report(self, device_id, status)

    Manager._on_device_report = patched_on_device_report
    LOGGER.info("Applied generic tuya_sharing monkey patch for DP 19")
    
    
async def async_setup_entry(hass: HomeAssistant, entry: TuyaConfigEntry) -> bool:
"""Voce di configurazione hass per la configurazione asincrona."""

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

# ===== CONFIGURAZIONE GENERICA DISPOSITIVI PER DP 19 =====
# Cicliamo su tutti i dispositivi trovati nel manager
for device in manager.device_map.values():
    # Applichiamo la logica se il dispositivo è un termostato (wk) o se ha già work_state
    # Tuya usa spesso 'wk' per Wall Heaters e termostati
    if device.category == "wk" or "work_state" in device.status:

        # Aggiungi la funzione work_state se non definita nel cloud
        if "work_state" not in device.function:
            device.function["work_state"] = DeviceFunction(
                code='work_state',
                type='Enum',
                values='{"range":["heating","stop","idle"]}'
            )

        # Mappa il DP 19 al codice work_state nella struttura interna
        if hasattr(device, 'status_range'):
            device.status_range[19] = "work_state"

        # Inizializza lo stato se vuoto
        if "work_state" not in device.status:
            device.status["work_state"] = "stop"

        LOGGER.info(f"Enabled DP 19 support for device: {device.name} ({device.id})")
# =========================================================

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
```

il file climate.py:
```
from homeassistant.components.climate import ( SWING_BOTH, SWING_HORIZONTAL, SWING_OFF, SWING_ON, SWING_VERTICAL, ClimateEntity, ClimateEntityDescription, ClimateEntityFeature, HVACMode, HVACAction,  # <--- AGGIUNTO QUESTO )

`async def async_setup_entry(
hass: HomeAssistant,
entry: TuyaConfigEntry,
async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
"""Imposta dinamicamente il clima di Tuya tramite la scoperta di Tuya."""
manager = entry.runtime_data.manager

@callback
def async_discover_device(device_ids: list[str]) -> None:
    """Discover and add a discovered Tuya climate."""
    entities: list[TuyaClimateEntity] = []
    for device_id in device_ids:
        device = manager.device_map[device_id]
        if device and device.category in CLIMATE_DESCRIPTIONS:
            temperature_wrappers = _get_temperature_wrappers(
                device, hass.config.units.temperature_unit
            )
            entities.append(
                TuyaClimateEntity(
                    device,
                    manager,
                    CLIMATE_DESCRIPTIONS[device.category],
                    current_humidity_wrapper=_RoundedIntegerWrapper.find_dpcode(
                        device, DPCode.HUMIDITY_CURRENT
                    ),
                    current_temperature_wrapper=temperature_wrappers[0],
                    fan_mode_wrapper=DPCodeEnumWrapper.find_dpcode(
                        device,
                        (DPCode.FAN_SPEED_ENUM, DPCode.LEVEL, DPCode.WINDSPEED),
                        prefer_function=True,
                    ),
                    hvac_mode_wrapper=DPCodeEnumWrapper.find_dpcode(
                        device, DPCode.MODE, prefer_function=True
                    ),
                    set_temperature_wrapper=temperature_wrappers[1],
                    swing_wrapper=DPCodeBooleanWrapper.find_dpcode(
                        device, (DPCode.SWING, DPCode.SHAKE), prefer_function=True
                    ),
                    swing_h_wrapper=DPCodeBooleanWrapper.find_dpcode(
                        device, DPCode.SWITCH_HORIZONTAL, prefer_function=True
                    ),
                    swing_v_wrapper=DPCodeBooleanWrapper.find_dpcode(
                        device, DPCode.SWITCH_VERTICAL, prefer_function=True
                    ),
                    switch_wrapper=DPCodeBooleanWrapper.find_dpcode(
                        device, DPCode.SWITCH, prefer_function=True
                    ),
                    work_state_wrapper=DPCodeEnumWrapper.find_dpcode(
                        device, 
                        (DPCode.WORK_STATE), # Cerca tutti i possibili alias
                        prefer_function=True
                    ),
                    target_humidity_wrapper=_RoundedIntegerWrapper.find_dpcode(
                        device, DPCode.HUMIDITY_SET, prefer_function=True
                    ),
                    temperature_unit=temperature_wrappers[2],
                )
            )
    async_add_entities(entities)

async_discover_device([*manager.device_map])

entry.async_on_unload(
    async_dispatcher_connect(hass, TUYA_DISCOVERY_NEW, async_discover_device)
)`
```
```class TuyaClimateEntity(TuyaEntity, ClimateEntity):
"""Dispositivo climatico Tuya."""

_hvac_to_tuya: dict[str, str]
entity_description: TuyaClimateEntityDescription
_attr_name = None

def __init__(
    self,
    device: CustomerDevice,
    device_manager: Manager,
    description: TuyaClimateEntityDescription,
    *,
    current_humidity_wrapper: _RoundedIntegerWrapper | None,
    current_temperature_wrapper: DPCodeIntegerWrapper | None,
    fan_mode_wrapper: DPCodeEnumWrapper | None,
    hvac_mode_wrapper: DPCodeEnumWrapper | None,
    set_temperature_wrapper: DPCodeIntegerWrapper | None,
    swing_wrapper: DPCodeBooleanWrapper | None,
    swing_h_wrapper: DPCodeBooleanWrapper | None,
    swing_v_wrapper: DPCodeBooleanWrapper | None,
    switch_wrapper: DPCodeBooleanWrapper | None,
    target_humidity_wrapper: _RoundedIntegerWrapper | None,
    work_state_wrapper: DPCodeEnumWrapper | None, # <--- AGGIUNGI QUESTO
    temperature_unit: UnitOfTemperature,
) -> None:`
```
```
@Property
def hvac_mode(self) -> HVACMode | None:
"""Restituisci la modalità hvac."""
# Controllo dello switch fisico (se presente)
switch_status = self._read_wrapper(self._switch_wrapper)
if switch_status is False:
return HVACMode.OFF

    # Se non c'è un wrapper per il modo, ma lo switch è ON
    if self._hvac_mode_wrapper is None:
        if switch_status is True:
            return self.entity_description.switch_only_hvac_mode
        return None

    # Leggiamo lo stato dal cloud
    hvac_status = self._read_wrapper(self._hvac_mode_wrapper)
    
    # Se il cloud dice 'off' o è vuoto (None), ma lo switch non è esplicitamente False
    if hvac_status is None or hvac_status == "off":
        # Se lo switch non esiste o è True, forziamo HEAT per evitare che sparisca
        return HVACMode.HEAT
        
    return TUYA_HVAC_TO_HA.get(hvac_status, HVACMode.HEAT)`
```
```
@Property
def hvac_action(self) -> HVACAction | None:
"""Restituisce l'azione HVAC corrente."""
if not self.device.status.get(DPCode.SWITCH, False):
return HVACAction.OFF

    # Usa work_state se disponibile (DP 19)
    if DPCode.WORK_STATE in self.device.status:
        work_state = self.device.status[DPCode.WORK_STATE]
        if work_state == "heating":
            return HVACAction.HEATING
        elif work_state == "cooling":
            return HVACAction.COOLING
        elif work_state == "idle":
            return HVACAction.IDLE

    
    return HVACAction.IDLE

@property
def preset_mode(self) -> str | None:
    """Return preset mode."""
    if self._hvac_mode_wrapper is None:
        return None

    mode = self._read_wrapper(self._hvac_mode_wrapper)
    if mode in TUYA_HVAC_TO_HA:
        return None

    return mode
```

In const.py, aggiungi nella classe DPCode(StrEnum)::
```
    WORK_STATE_E = "work_state_e" WORK_STATE = "work_state"
```

- aggiunta implemnetazione anche per la category cs che si basa sul power e non sullo status
- aggiunta implementazione di un action che controlla il repo ufficiale e notifica quali file sono stati cambiati per aver la custom integration sempre aggiornata