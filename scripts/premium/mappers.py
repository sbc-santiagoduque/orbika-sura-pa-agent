"""Mapping helpers: DatosReclamo fields → Oracle Forms codes."""


def incident_type_to_code(incident_type: str) -> str:
    """Convert DatosSiniestro.tipo to the numeric code used in the Oracle Forms LOV."""
    t = (incident_type or "").lower()
    if "colisi" in t or "vuelco" in t:
        return "30"
    if "robo" in t or "hurto" in t:
        return "20"
    if "incendio" in t:
        return "910"
    if "comprensivo" in t:
        return "40"
    return "30"


def coverage_to_code(coverage: str) -> str:
    """Convert DatosPoliza.cobertura to the code used in the Reserves table."""
    c = (coverage or "").upper()
    if "COLISI" in c or "VUELCO" in c:
        return "E"
    if "ROBO" in c or "HURTO" in c:
        return "HUR"
    if "INCENDIO" in c:
        return "INC"
    if "COMPRENSIVO" in c:
        return "D"
    if "PROPIEDAD" in c or "AJENA" in c:
        return "B"
    return "E"
