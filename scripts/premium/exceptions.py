"""Custom exceptions for the Premium RPA pipeline."""


class ClaimAlreadyExistsError(Exception):
    """The form detected an existing claim for this policy/case."""


class DuplicateClaimError(Exception):
    """
    Oracle Forms warned about a duplicate claim for the same policy and
    incident date in the Endosos query. Skip — do not create a duplicate.
    """


class IncidentOutOfCoverageError(Exception):
    """
    Oracle Forms warned that the incident date falls outside the vehicle's
    coverage period. Requires manual review.
    """


class UnauthorizedError(Exception):
    """
    Oracle Forms showed an 'unauthorized' modal when attempting to save.
    The active user lacks permissions to create claims.
    """


class FieldValidationError(Exception):
    """
    Oracle Forms raised FRM-40202 ('Se debe ingresar al campo') while filling
    a form tab — a required field was left empty.
    The pipeline steps back one tab and retries (max 2 attempts).
    """
    def __init__(self, message: str, tab: str = ""):
        super().__init__(message)
        self.tab = tab  # "generals1", "generals2", "generals3", "reserves"
