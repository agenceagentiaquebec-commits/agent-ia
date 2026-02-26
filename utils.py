# utils.py
# Fonctions utilitaires : nettoyage texte, normalisation téléphone, logs

import re

# ------------------------------------------------------------
# Nettoyage du texte utilisateur
# ------------------------------------------------------------

def clean_text(text: str) -> str:
    """
    Nettoie un texte :
    - supprime espaces multiples
    - supprime caractères parasites
    - normalise les apostrophes
    """
    if not text:
        return ""
    
    text = text.replace("’", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

# ------------------------------------------------------------
# Normalisation du numéro de téléphone
# ------------------------------------------------------------

def normalize_phone(phone: str) -> str:
    """
    Normalise un numéro de téléphone :
    - garde uniquement les chiffres
    - format 10 chiffres (Québec)
    """
    if not phone:
        return ""
    
    digits = re.sub(r"\D", "", phone)

    # Si numéro nord-américain avec +1
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    # Si pas 10 chiffres -> on retourne tel quel
    return digits if len(digits) == 10 else phone

# ------------------------------------------------------------
# log simple (console)
# ------------------------------------------------------------

def log(msg: str):
    """Affiche un message propre dans les logs Cloud Run."""
    print(f"[Emily]{msg}")