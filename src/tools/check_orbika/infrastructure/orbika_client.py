"""
Cliente HTTP para la API de Orbika (Liferay JSONWS).

Endpoint: POST https://orbika.subocol.com/api/jsonws/invoke
Body:     application/x-www-form-urlencoded
          cmd=<json>&p_auth=<token>

Auth:     Cookies de sesion Liferay + p_auth token CSRF.
"""
import json
import logging

import requests

from src.shared.orbika.orbika_session import OrbikaSession

logger = logging.getLogger(__name__)

_ORBIKA_BASE_URL = "https://orbika.subocol.com"
_INVOKE_URL      = f"{_ORBIKA_BASE_URL}/api/jsonws/invoke"
_ASEGURADORA     = "Sura Panama"


class OrbikaClient:
    def __init__(self, session: OrbikaSession):
        self._session = session

    def listar_avisos(self, placa: str) -> list[dict]:
        """
        Busca todos los avisos en Orbika para una placa dada
        (como asegurado o como tercero).

        Args:
            placa: Numero de placa del vehiculo (ej. "422644")

        Returns:
            Lista de avisos. Lista vacia si no hay resultados.
        """
        cookies, p_auth = self._session.load()

        cmd = {
            "/adminAvisos.aviso/Listar-avisos-talleres": {
                "aseguradora": _ASEGURADORA,
                "cobertura": [],
                "regional": [],
                "estado": [],
                "taller": [],
                "tipofecha": None,
                "fechaini": None,
                "tipoVehiculo": [],
                "buscador": "placa",
                "valorBuscado": placa,
                "imprevistos": False,
            }
        }

        response = requests.post(
            _INVOKE_URL,
            data={"cmd": json.dumps(cmd), "p_auth": p_auth},
            cookies=cookies,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": _ORBIKA_BASE_URL,
                "Referer": f"{_ORBIKA_BASE_URL}/gestion-aviso",
            },
            timeout=15,
        )

        response.raise_for_status()
        data = response.json()

        # Liferay retorna {"exception": "..."} cuando la sesion expira
        if isinstance(data, dict) and "exception" in data:
            raise RuntimeError(
                f"Sesion Orbika invalida o expirada: {data['exception']}. "
                "Re-ejecutar scripts/capture_orbika_session.py"
            )

        return data if isinstance(data, list) else []
