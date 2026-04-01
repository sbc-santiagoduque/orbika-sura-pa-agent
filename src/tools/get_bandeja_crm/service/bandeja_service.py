class BandejaService:
    """
    Prioriza los casos de la bandeja CRM antes de pasarlos al agente.

    Regla de negocio:
    1. Casos con sla_alert=True van primero (riesgo de incumplimiento).
    2. Dentro de cada grupo, el más antiguo en la bandeja (fecha_recepcion
       menor) va antes — FIFO para evitar que casos esperen indefinidamente.
    3. prioridad es consecutivo desde 1 para facilitar la vista del analista.
    """

    def priorizar(self, casos: list[dict]) -> list[dict]:
        """
        Recibe la lista cruda del scraper y devuelve una nueva lista ordenada
        con el campo ``prioridad`` añadido (1 = más urgente).

        Args:
            casos: Lista de dicts con al menos las claves
                   ``sla_alert`` (bool) y ``fecha_recepcion`` (ISO 8601 str).

        Returns:
            Lista ordenada con ``prioridad`` 1-based añadida a cada elemento.
        """
        if not casos:
            return []

        ordenados = sorted(
            casos,
            # Tupla de ordenación: (0 si sla_alert else 1, fecha_recepcion)
            # — sla_alert=True baja a 0 → va primero
            # — dentro del mismo grupo, fecha_recepcion ascendente
            key=lambda c: (0 if c["sla_alert"] else 1, c["fecha_recepcion"]),
        )

        return [
            {**caso, "prioridad": idx + 1}
            for idx, caso in enumerate(ordenados)
        ]
