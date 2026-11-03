from typing import Protocol
from .models import DomainError


class AIProvider(Protocol):
    """Optional future provider. Call only after explicit preview and consent."""
    name: str
    async def suggest(self, approved_text: str) -> str: ...


class DisabledAI:
    name = "Aucun fournisseur connecté"

    async def suggest(self, approved_text):
        raise DomainError("L'IA externe est désactivée. Aucun contenu n'a été envoyé.")


def manual_template(partner, intent, date, terms):
    """Deterministic writing aid; intentionally not presented as an AI response."""
    opening = {"Proposer": "Je vous propose un échange de visibilité entre nos canaux.",
               "Négocier": "Merci pour votre proposition. Voici les conditions que je souhaite vous proposer.",
               "Refuser": "Merci pour votre proposition. Je ne souhaite pas donner suite à cet échange."}[intent]
    return f"Bonjour {partner or 'à vous'},\n\n{opening}" + (f"\n\nDate envisagée : {date}\nConditions à confirmer : {terms or '[à compléter]'}\n\nMerci de confirmer les textes, les canaux et la durée de maintien avant tout accord." if intent != "Refuser" else "") + "\n\nBonne journée."

