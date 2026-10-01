class DataUnavailable(Exception):
    """Donnée critique indisponible. Le système ne doit jamais la remplacer par une valeur inventée."""


class KrakenAPIError(DataUnavailable):
    """Erreur renvoyée par l'API Kraken (champ `error` non vide ou statut HTTP en erreur)."""

    def __init__(self, endpoint: str, errors: list[str] | str):
        self.endpoint = endpoint
        self.errors = errors if isinstance(errors, list) else [errors]
        super().__init__(f"{endpoint}: {', '.join(self.errors)}")


class AuthMissing(DataUnavailable):
    """Endpoint privé demandé sans clé API configurée."""


class LiveTradingDisabled(Exception):
    """Tentative d'ordre réel alors que le live n'est pas armé."""
