"""
Módulo de compatibilidade e acesso direto ao Backend Universal do Ducksvantage (backend.py).
Re-exporta HardwareBackend e os dicionários de mapeamento ACPI (incluindo 'max-power') de core.backend.
"""

from core.backend import (
    HardwareBackend,
    ACPI_PROFILE_MAP,
    ACPI_PROFILE_DETAILS,
)

__all__ = [
    "HardwareBackend",
    "ACPI_PROFILE_MAP",
    "ACPI_PROFILE_DETAILS",
]

