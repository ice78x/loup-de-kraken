"""Tests critiques du risk_manager (taille de position)."""
import pytest

from kraken_assistant.risk.position_sizing import SizingInput, compute_position


def base(**kw):
    d = dict(capital_eur=90.0, risk_percent=1.0, entry=100.0, stop_loss=98.0, direction="LONG",
             take_profits=[103.0, 106.0, 110.0], lot_decimals=8, allowed_leverages=list(range(1, 11)),
             max_leverage=10)
    d.update(kw)
    return SizingInput(**d)


def test_exemple_cahier_des_charges_sans_frais():
    # Capital 90 €, risque 1 % = 0,90 €, SL à 2 % → perte au SL ≈ 0,90 €
    p = compute_position(base())
    assert p.ok
    assert p.risk_amount_eur == pytest.approx(0.90)
    assert p.estimated_loss_at_sl_eur == pytest.approx(0.90, abs=1e-6)
    assert p.position_size == pytest.approx(0.45, abs=1e-8)       # 0.90 / 2
    assert p.notional_eur == pytest.approx(45.0, abs=1e-6)
    assert p.leverage == 1                                         # 45 € < 90 € : pas besoin de levier


def test_frais_inclus_dans_la_perte():
    p = compute_position(base(fee_rate_pct=0.4))
    assert p.ok
    assert p.estimated_loss_at_sl_eur <= 0.90 + 1e-9
    assert p.estimated_loss_at_sl_eur == pytest.approx(0.90, abs=0.001)
    assert p.position_size < 0.45                                  # la taille baisse pour absorber les frais


def test_le_levier_ne_change_jamais_le_risque():
    # SL serré → gros notionnel → levier nécessaire, mais la perte au SL reste 0,90 €
    tight = compute_position(base(stop_loss=99.8))                # SL à 0,2 %
    assert tight.ok
    assert tight.notional_eur == pytest.approx(450.0, rel=1e-6)
    assert tight.leverage == 5                                     # 450 / 90 = 5
    assert tight.estimated_loss_at_sl_eur == pytest.approx(0.90, abs=1e-6)
    assert tight.margin_required_eur == pytest.approx(90.0, rel=1e-6)
    forced = compute_position(base(stop_loss=99.8, leverage=10))
    assert forced.estimated_loss_at_sl_eur == pytest.approx(tight.estimated_loss_at_sl_eur)
    assert forced.position_size == tight.position_size             # taille identique quel que soit le levier
    assert forced.margin_required_eur == pytest.approx(45.0, rel=1e-6)


def test_jamais_capital_fois_levier():
    p = compute_position(base(stop_loss=99.8, leverage=10))
    assert p.estimated_loss_at_sl_eur < 90 * 10 * 0.01
    assert p.estimated_loss_at_sl_eur == pytest.approx(0.90, abs=1e-6)


def test_short():
    p = compute_position(base(direction="SHORT", entry=14.25, stop_loss=14.70, take_profits=[13.9, 13.4, 12.8]))
    assert p.ok
    assert p.estimated_loss_at_sl_eur == pytest.approx(0.90, abs=1e-4)
    assert p.r_multiples == [pytest.approx(0.78, abs=0.01), pytest.approx(1.89, abs=0.01), pytest.approx(3.22, abs=0.01)]


def test_niveaux_incoherents_refuses():
    assert not compute_position(base(stop_loss=101)).ok                        # LONG avec SL au-dessus
    assert not compute_position(base(direction="SHORT", stop_loss=98, take_profits=[])).ok
    assert not compute_position(base(take_profits=[106, 103])).ok              # TP mal ordonnés


def test_taille_minimale_kraken():
    p = compute_position(base(ordermin=1.0))  # taille permise 0,45 < minimum 1
    assert not p.ok
    assert "minimale" in p.errors[0]
    assert p.min_risk_required_eur == pytest.approx(2.0, abs=1e-6)


def test_arrondi_vers_le_bas():
    p = compute_position(base(lot_decimals=1))
    assert p.position_size == pytest.approx(0.4)                   # 0,45 arrondi à 0,4 (jamais 0,5)
    assert p.estimated_loss_at_sl_eur <= 0.90


def test_conversion_devise():
    # instrument coté en USD : 1 USD = 0,9 € → risque 0,90 € = 1 USD
    p = compute_position(base(eur_per_quote=0.9))
    assert p.position_size == pytest.approx(0.5, abs=1e-8)
    assert p.estimated_loss_at_sl_eur == pytest.approx(0.90, abs=1e-6)


def test_marge_insuffisante_reduit_la_taille():
    p = compute_position(base(stop_loss=99.95, max_leverage=10, allowed_leverages=[1, 2, 3]))
    assert p.ok
    assert p.leverage == 3
    assert p.notional_eur <= 270 + 1e-6
    assert p.estimated_loss_at_sl_eur < 0.90                       # risque réel plus faible, jamais plus élevé
    assert p.warnings


def test_sl_trop_large_pour_levier_sur():
    # SL à 30 % : aucun levier > 1 n'est sûr ; seul x1 reste possible
    p = compute_position(base(stop_loss=70.0, take_profits=[140, 170, 200], allowed_leverages=[2, 3, 5]))
    assert not p.ok


def test_spot_short_sans_marge_impossible():
    p = compute_position(base(direction="SHORT", stop_loss=102, take_profits=[97, 94, 90], allowed_leverages=[]))
    assert not p.ok


def test_profits_tp_repartis():
    p = compute_position(base())
    # 0,45 × 30 % × 3 = 0,405 ; 0,45 × 40 % × 6 = 1,08 ; 0,45 × 30 % × 10 = 1,35
    assert p.estimated_profit_tp_eur == [pytest.approx(0.405), pytest.approx(1.08), pytest.approx(1.35)]
    assert p.r_multiples == [1.5, 3.0, 5.0]
