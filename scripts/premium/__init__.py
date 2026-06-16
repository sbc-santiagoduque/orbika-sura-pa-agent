"""Premium RPA package — Oracle Forms automation for Sura Panamá."""
from premium.common import log, set_notifier, screenshot, find_on_screen, T, CAPTURES_DIR, validate_templates
from premium.exceptions import (
    ClaimAlreadyExistsError,
    DuplicateClaimError,
    IncidentOutOfCoverageError,
    UnauthorizedError,
    FieldValidationError,
)
from premium.mappers import incident_type_to_code, coverage_to_code

__all__ = [
    "log", "set_notifier", "screenshot", "find_on_screen", "T",
    "CAPTURES_DIR", "validate_templates",
    "ClaimAlreadyExistsError", "DuplicateClaimError",
    "IncidentOutOfCoverageError", "UnauthorizedError", "FieldValidationError",
    "incident_type_to_code", "coverage_to_code",
]
