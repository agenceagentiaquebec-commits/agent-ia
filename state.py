# state.py
# Gestion propre de l'état par appel (CallSid)

from datetime import datetime
# Mémoire en RAM (Cloud Run garde l'état tant que l'instance vit)
CALL_STATE = {}

def get_state(call_sid: str):
    """Retourne l'état du call_sid ou le crée s'il n'existe pas."""
    if call_sid not in CALL_STATE:
        CALL_STATE[call_sid] = {
            "silence_count": 0,
            "is_playing": False,
            "Last_audio": None,
            "pending_audio": None,
            "conversation_history": [],
            "extracted_info": {
                "nom": None,
                "prenom": None,
                "adresse": None,
                "ville": None,
                "code_postal": None,
                "telephone": None,
                "raison_appel": None,
                "budget": None
            },
            "intent": None,
            "recognized_client": None,
            "call_started_at": datetime.utcnow().isoformat(),
            "final_summary_generated": False
        }
    return CALL_STATE[call_sid]

def set_last_audio(call_sid: str, path: str):
    state = get_state(call_sid)
    state["last_audio"] = path

def set_pending_audio(call_sid: str, path: str | None):
    state = get_state(call_sid)
    state["pending_audio"] = path

def reset_silence(call_sid: str):
    state = get_state(call_sid)
    state["silence_count"] = 0

def increment_silence(call_sid: str):
    state = get_state(call_sid)
    state["silence_count"] += 1
    return state["silence_count"]