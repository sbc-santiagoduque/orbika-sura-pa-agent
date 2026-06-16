"""
Tests para el decorador con_reintento.
"""
import pytest
from unittest.mock import MagicMock, patch

from src.shared.retry import con_reintento, RetryAgotadoError


class TestConReintento:
    def test_exito_en_primer_intento(self):
        llamadas = []
        @con_reintento(max_intentos=3, backoff=(0, 0))
        def fn():
            llamadas.append(1)
            return "ok"
        assert fn() == "ok"
        assert len(llamadas) == 1

    def test_reintenta_y_luego_exito(self):
        contador = {"n": 0}
        @con_reintento(max_intentos=3, backoff=(0, 0))
        def fn():
            contador["n"] += 1
            if contador["n"] < 3:
                raise ValueError("falla transitoria")
            return "ok"
        assert fn() == "ok"
        assert contador["n"] == 3

    def test_agota_intentos_lanza_retry_agotado(self):
        @con_reintento(max_intentos=3, backoff=(0, 0))
        def fn():
            raise RuntimeError("siempre falla")
        with pytest.raises(RetryAgotadoError) as exc_info:
            fn()
        assert "siempre falla" in str(exc_info.value)
        assert exc_info.value.intentos == 3

    def test_excepciones_excluidas_no_se_reintentan(self):
        contador = {"n": 0}
        @con_reintento(max_intentos=3, backoff=(0, 0), no_reintentar=(KeyError,))
        def fn():
            contador["n"] += 1
            raise KeyError("no reintentar")
        with pytest.raises(KeyError):
            fn()
        assert contador["n"] == 1

    def test_callback_en_cada_reintento(self):
        eventos = []
        @con_reintento(max_intentos=3, backoff=(0, 0),
                       on_reintento=lambda intento, exc: eventos.append(intento))
        def fn():
            raise ValueError("x")
        with pytest.raises(RetryAgotadoError):
            fn()
        assert eventos == [1, 2]

    def test_sleep_entre_intentos(self):
        with patch("src.shared.retry.time.sleep") as mock_sleep:
            @con_reintento(max_intentos=3, backoff=(5, 30))
            def fn():
                raise ValueError("x")
            with pytest.raises(RetryAgotadoError):
                fn()
            assert mock_sleep.call_args_list[0][0][0] == 5
            assert mock_sleep.call_args_list[1][0][0] == 30

    def test_nombre_funcion_preservado(self):
        @con_reintento(max_intentos=2, backoff=(0,))
        def mi_funcion():
            pass
        assert mi_funcion.__name__ == "mi_funcion"
