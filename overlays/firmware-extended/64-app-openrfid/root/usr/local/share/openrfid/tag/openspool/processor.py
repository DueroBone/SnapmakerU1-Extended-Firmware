from filament import GenericFilament
from reader.scan_result import ScanResult
from tag.ndef_tag_processor import NdefRecord, NdefTagProcessor
import json
from . import constants as Constants
import requests

# Adapted from https://github.com/paxx12/SnapmakerU1-Extended-Firmware/blob/3c97d1d80309d817ad37f2daac8e436712cc7865/overlays/firmware-extended/13-rfid-support/root/home/lava/klipper/klippy/extras/filament_protocol_ndef.py


class OpenspoolTagProcessor(NdefTagProcessor):
    def __init__(self, config: dict):
        super().__init__(config)

    def process_ndef(
        self, scan_result: ScanResult, ndef_records: list[NdefRecord]
    ) -> GenericFilament | None:
        for record in ndef_records:
            if record.mime_type == "application/json":
                parse = self.__openspool_parse_payload(record.payload)

                if parse is not None:
                    return parse

        self.logger.error(
            "OpenSpool processing failed: No valid OpenSpool NDEF record found"
        )
        return None



    def __openspool_parse_payload(self, payload : bytes) -> GenericFilament | None:
        if payload is None or not isinstance(payload, (bytes, bytearray)):
            self.logger.error("OpenSpool payload parsing failed: Invalid payload parameter")
            return None

        try:
            payload_str = payload.decode("utf-8")
            data = json.loads(payload_str)

            if not isinstance(data, dict):
                self.logger.error(
                    f"OpenSpool payload parsing failed: JSON data is not a dict, got {type(data)}"
                )
                return None

            if data.get("protocol") != "openspool":
                self.logger.error(
                    f"OpenSpool payload parsing failed: Invalid protocol '{data.get('protocol')}', expected 'openspool'"
                )
                return None

            brand = data.get("brand", "Generic")

            # Default values come from the OpenSpool payload
            main_type = data.get("type", "PLA").upper()
            subtype = data.get("subtype", "")
            color_hex = self.__parse_color_hex(data.get("color_hex", "FFFFFF"))

            try:
                diameter_mm = float(data.get("diameter", 1.75))
            except (ValueError, TypeError):
                diameter_mm = 1.75

            try:
                weight_grams = int(data.get("weight", 1000))
            except (ValueError, TypeError):
                weight_grams = 1000

            min_temp = int(data.get("min_temp", 0))
            max_temp = int(data.get("max_temp", 0))

            self.logger.debug("Custom function running")

            # Pull filament information from Spoolman
            if brand.lower() == "spoolman":
                try:
                    spool_id = data.get("spool_id")
                    if spool_id is None:
                        raise ValueError("Missing spool_id")

                    response = requests.get(
                        f"http://dueroserver.tail5c1e21.ts.net:7912/api/v1/spool/{spool_id}",
                        timeout=3,
                    )
                    response.raise_for_status()

                    spool_data = response.json()

                    filament = spool_data.get("filament")
                    if not isinstance(filament, dict):
                        raise ValueError("Missing filament object")

                    vendor = filament.get("vendor", {})
                    brand = vendor.get("name", "Generic")

                    main_type = str(
                        filament.get("material", main_type)
                    ).upper()

                    subtype = filament.get("name", subtype)

                    color_hex = self.__parse_color_hex(
                        filament.get("color_hex", "FFFFFF")
                    )

                    try:
                        diameter_mm = float(
                            filament.get("diameter", diameter_mm)
                        )
                    except (ValueError, TypeError):
                        pass

                    try:
                        weight_grams = int(
                            round(float(filament.get("weight", weight_grams)))
                        )
                    except (ValueError, TypeError):
                        pass

                except Exception as e:
                    self.logger.error(
                        f"Spoolman loading data failed: {str(e)}"
                    )
                    return None

            alpha = max(
                0x00,
                min(0xFF, int(data.get("alpha", "FF"), 16))
            )
            color_argb = (alpha << 24) | color_hex

            if max_temp < min_temp:
                self.logger.error(
                    "OpenSpool payload parsing failed: Invalid temperature values"
                )
                return None

            if main_type in Constants.FILAMENT_TYPE_TO_EXTENDED_DATA:
                extra_data = Constants.FILAMENT_TYPE_TO_EXTENDED_DATA[main_type]
                bed_temp_c = extra_data.bed_temp_c
                drying_temp_c = extra_data.drying_temp_c
                drying_time_hours = extra_data.drying_time_hours
            else:
                bed_temp_c = 0.0
                drying_temp_c = 0.0
                drying_time_hours = 0.0

            return GenericFilament(
                source_processor=self.name,
                unique_id=GenericFilament.generate_unique_id(
                    "OpenSpool",
                    brand,
                    main_type,
                    subtype,
                    color_argb,
                ),
                manufacturer=brand,
                type=main_type,
                modifiers=[subtype] if subtype else [],
                colors=[color_argb],
                diameter_mm=diameter_mm,
                weight_grams=weight_grams,
                hotend_min_temp_c=min_temp,
                hotend_max_temp_c=max_temp,
                bed_temp_c=bed_temp_c,
                drying_temp_c=drying_temp_c,
                drying_time_hours=drying_time_hours,
                manufacturing_date="0001-01-01",
            )

        except json.JSONDecodeError as e:
            self.logger.exception(
                "OpenSpool payload parsing failed: Invalid JSON: %s",
                str(e),
            )
            return None

        except Exception as e:
            self.logger.exception(
                "OpenSpool payload parsing failed: %s",
                str(e),
            )
            return None