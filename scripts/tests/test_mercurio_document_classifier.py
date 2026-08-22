from pathlib import Path

import app.run_presentacion_asistida as runner


def classify(
    filename,
):
    return (
        runner
        .classify_documento_mercurio(
            Path(
                filename
            )
        )
    )


def test_tasa_790_052_uses_observed_mercurio_code_51():
    assert (
        classify(
            "Tasa 790 codigo 052.pdf"
        )
        == "51"
    )


def test_tasa_filename_uses_code_51():
    assert (
        classify(
            "justificante_tasa.pdf"
        )
        == "51"
    )


def test_790_filename_uses_code_51():
    assert (
        classify(
            "modelo_790.pdf"
        )
        == "51"
    )


def test_052_filename_uses_code_51():
    assert (
        classify(
            "modelo_052_pagado.pdf"
        )
        == "51"
    )


def test_generic_justificante_is_not_assumed_to_be_tax():
    assert (
        classify(
            "justificante_presentacion.pdf"
        )
        == "999"
    )


def test_generic_pago_is_not_assumed_to_be_tax():
    assert (
        classify(
            "pago.pdf"
        )
        == "999"
    )


def test_pasaporte_classification_remains_unchanged():
    assert (
        classify(
            "pasaporte_cliente.pdf"
        )
        == "1"
    )
