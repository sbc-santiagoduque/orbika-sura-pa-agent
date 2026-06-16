"""
Decorador de reintento con backoff configurable para el pipeline nocturno.

Uso:
    @con_reintento(max_intentos=3, backoff=(5, 30, 120))
    def llamar_sic():
        ...

    # Con callback de log y excepción que NO debe reintentarse:
    @con_reintento(
        max_intentos=3,
        backoff=(5, 30),
        no_reintentar=(ReclamoExistenteError,),
        on_reintento=lambda n, exc: print(f"Reintento {n}: {exc}"),
    )
    def fase_b():
        ...
"""
import functools
import time
from typing import Callable, Tuple, Type


class RetryAgotadoError(Exception):
    """Lanzada cuando se agotan todos los reintentos."""

    def __init__(self, causa: Exception, intentos: int):
        super().__init__(f"Agotados {intentos} intentos. Última causa: {causa}")
        self.causa    = causa
        self.intentos = intentos


def con_reintento(
    max_intentos: int = 3,
    backoff: Tuple[float, ...] = (5, 30, 120),
    no_reintentar: Tuple[Type[Exception], ...] = (),
    on_reintento: Callable[[int, Exception], None] | None = None,
):
    """
    Decorador de reintento con backoff.

    Args:
        max_intentos:   Número máximo de intentos (incluyendo el primero).
        backoff:        Segundos de espera entre intentos. Si hay menos valores
                        que reintentos, se usa el último valor para los restantes.
        no_reintentar:  Tipos de excepción que NO deben reintentarse (re-lanza inmediato).
        on_reintento:   Callback(intento, excepcion) llamado antes de cada espera.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ultima_exc: Exception | None = None
            for intento in range(1, max_intentos + 1):
                try:
                    return func(*args, **kwargs)
                except no_reintentar:
                    raise
                except Exception as exc:
                    ultima_exc = exc
                    if intento == max_intentos:
                        break
                    if on_reintento:
                        on_reintento(intento, exc)
                    espera = backoff[min(intento - 1, len(backoff) - 1)]
                    time.sleep(espera)
            raise RetryAgotadoError(ultima_exc, max_intentos)
        return wrapper
    return decorator
