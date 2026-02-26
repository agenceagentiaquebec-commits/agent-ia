# sheets.py
# Gestion Google Sheets : recherche client, ajout ligne, mise à jour

import os
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_ID")
SHEET_TAB = os.getenv("GOOGLE_SHEETS_TAB", "Prospect")
SERVICE_ACCOUNT_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/secrets/service-account.json")

# --------------------------------------------------------------
# Connexion Google Sheets
# --------------------------------------------------------------

def sheets_service():
    """Retourne un client Google Sheets authentifié."""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_PATH,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)

# --------------------------------------------------------------
# Recherche stricte d'un client existant
# --------------------------------------------------------------

def find_client(nom: str, prenom: str, telephone: str):
    """
    Recherche stricte dans la feuille :
    - nom EXACT
    - prénom EXACT
    - Téléphone EXACT

    Retourne :
    {
        "row_index": int,
        "row": [...]
    }
    ou None si non trouvé.
    """

    try:
        service = sheets_service()
        RANGE = f"{SHEET_TAB}!A2:K"
        res = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE
        ).execute()

        rows = res.get("values", [])
        found = None

        for idx, row in enumerate(rows, start=2):
            r_nom = row[1].strip().lower() if len(row) > 1 else ""
            r_prenom = row[2].strip().lower() if len(row) > 2 else ""
            r_tel = row[6].strip() if len(row) > 6 else ""

            if r_nom == nom.lower() and r_prenom == prenom.lower() and r_tel == telephone:
                found = {"row_index": idx, "row": row}

        return found
    
    except Exception as e:
        print("Erreur find_client:", e)
        return None
    
# --------------------------------------------------------------
# Ajout d'un appel dans la feuille
# --------------------------------------------------------------

def append_call(extracted_info: dict, category: str, client_type: str):
    """
    Ajoute une nouvelle ligne dans Google Sheets.
    Ordre des colonnes :
    1. Date d'appel
    2. Nom
    3. Prénom
    4. Adresse
    5. Ville
    6. Code postal
    7. Téléphone
    8. Raison de l'appel
    9. Budget
    10. Catégorie
    11. Type de client
    """

    try:
        service = sheets_service()
        RANGE = f"{SHEET_TAB}!A:K"

        row = [
            datetime.utcnow().isoformat(),
            extracted_info.get("nom", ""),
            extracted_info.get("prenom", ""),
            extracted_info.get("adresse", ""),
            extracted_info.get("ville", ""),
            extracted_info.get("code_postal", ""),
            extracted_info.get("telephone", ""),
            extracted_info.get("raison_appel", ""),
            extracted_info.get("budget", ""),
            category,
            client_type
        ]

        body = {"values": [row]}

        result = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE,
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()

        return result.get("updates", {}).get("updatedRange")
    
    except Exception as e:
        print("Erreur append_call:", e)
        return None