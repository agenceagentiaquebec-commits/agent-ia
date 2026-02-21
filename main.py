# ---------------------------------------------------------
# IMPORTS + CHARGEMENT DU .ENV

# Coding :utf-8 

# ---------------------------------------------------------

"""
main.py
Version monolithique prête à déployer pour Emily.
Fonctionnalités :
- Gestion par CallSid (mémoire d'appel temporaire)
- Reconnaissance client stricte (Nom + Prénom + Téléphone) via Google sheets
- Une ligne par appel (historique complet)
- Répliques instantanées (pour éviter les silences)
- Génération asynchrone de la "vraie" réponse via OpenAI + ElevenLabs TTS
- Gestion des 4 cas d'appel (nouvel appel, utilisateur parle, silence, interruption)
- Reconfirmation finale et validation client
- Résumé final via OpenAI, sauvegarde et log quotidien
- Endpoint /daily-summary pour Cloud Scheduler (email quotidien via SendGrid)
- Endpoints de test pour Sheets et email
Remplace les variables d'environnement et l'ID de spreadsheet par les tiens.
"""

from fastapi import FastAPI, Request
from fastapi.responses import Response, FileResponse, JSONResponse
from dotenv import load_dotenv
from openai import OpenAI
from threading import Lock
import os
import requests
import json
import uuid
import subprocess
import threading
from datetime import datetime, date
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Charger ton fichier .env
load_dotenv()

ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1gp3__Q6uFn7psn9-wVIfy7gcYjTTMuQzkBUa4flRpiI")
SERVICE_ACCOUNT_PATH = os.getenv("SERVICE_ACCOUNT_PATH", "/secrets/service-account.json")


client = OpenAI(api_key=OPENAI_API_KEY)
app = FastAPI()

# ---------------------------------------------------------
# État par appel (mémoire temporaire)
# ---------------------------------------------------------
conversation_state = {}
CALL_LOG_FILE = "/tmp/call_log.json" # stockage simple pour résumé quotidien

def get_call_state(call_sid: str):
    if call_sid not in conversation_state:
        conversation_state[call_sid] = {
            "silence_count": 0,
            "is_playing_audio": False,
            "last_audio_file": None,
            "pending_audio_file": None,
            "instant_audio_file": f"/tmp/{call_sid}_instant.wav",
            "extracted_info": {}, # nom, prenom, telephone, adresse, ville, code_postal, raison_appel, budget
            "conversation_history": [],
            "intent": None,
            "call_started_at": datetime.utcnow().isoformat(),
            "final_summary_generated": False,
            "recognized_client": None # info client existant si trouvé
        }

    return conversation_state[call_sid]

def set_last_audio(call_sid: str, path: str):
    state = get_call_state(call_sid)
    state["last_audio_file"] = path

def set_pending_audio(call_sid: str, path: str | None):
    state = get_call_state(call_sid)
    state["pending_audio_file"] = path

# ---------------------------------------------------------
# Utilitaires audio (ElevenLabs + ffmpeg)
# ---------------------------------------------------------
def generate_wav_file(text: str, target_path: str | None = None):
    """
    Génère un wav via ElevenLabs et convertit en PCM 16kHz mono.
    Retourne le chemin du fichier final ou None.
    """
    if not ELEVEN_API_KEY or not ELEVEN_VOICE_ID:
        print("ElevenLabs non configuré")
        return None
    
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    headers = {"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"}
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "output_format": "wav",
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.3}
    }

    try:
        r = requests.post(url, json=data, headers=headers, timeout=30)
        if r.status_code != 200:
            print("Erreur ElevenLabs:", r.status_code, r.text)
            return None
        raw = f"/tmp/{uuid.uuid4()}_raw.wav"
        with open(raw, "wb") as f:
            f.write(r.content)
        final = target_path or f"/tmp/{uuid.uuid4()}.wav"
        ffmpeg_cmd = ["ffmpeg", "-y", "-i", raw, "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", final]
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return final
    except Exception as e:
        print("Erreur génération audio:", e)
        return None

# ---------------------------------------------------------
# Répliques instantanées (contextuelles)
# ---------------------------------------------------------    
 
def get_instant_reply(context: str = "default", silence_count: int = 0, state: dict | None = None) -> str:
    if context == "intro":
        return "Bonjour, ici Emily, assistante virtuelle des Constructions P Gendreau. Merci d'avoir appelé aujourd'hui. Comment puis-je vous aider?"
    if context == "thinking":
        # si on connaît le nom, personnaliser
        if state and state.get("extracted_info", {}).get("nom"):
            nom = state["extracted_info"].get("nom")
            return f"Très bien {nom}, je regarde ça pour vous..."
        return "Parfait, je regarde ça pour vous..."
    if context == "silence":
        if silence_count == 1:
            return "Êtes-vous toujours là ? Je vous écoute."
        elif silence_count ==2:
            return "Vu qu'il semble que vous ne soyez plus là ou que la ligne soit mauvaise, veuillez s'il vous plaît nous rappeler à un meilleur moment pour vous."
    return "Hum, parfait, bien reçu..."

# ---------------------------------------------------------
# OpenAI : analyse et résumé
# --------------------------------------------------------- 

def analyze_message(user_message: str, state: dict):
    """
    Demande au LLM d'analyser le message et de renvoyer un JSON strict.
    """
    prompt = f"""
Tu es Emily, agente virtuelle pour Construction P Gendreau.
État extrait: {json.dumps(state.get('extracted_info', {}), ensure_ascii=False)}
Utilisateur: "{user_message}"
Retourne STRICTEMENT un JSON valide 
IMPORTANT :
- Pas de ```json
- Pas de ```
- Pas de texte avant ou après
- Seulement du JSON valide

Le JSON doit contenir :
- intent
- extracted_info (nom, prenom, adresse, ville, code_postal, telephone, raison_appel, budget)
- missing_info (liste)
- next_question
- reformulation
- final_reply
"""
    
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es Emily. Réponds STRICTEMENT en JSON brut, sans texte additionnel."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        return resp.choices[0].message.content
    except Exception as e:
        print("Erreur OpenAI analyse:", e)
        return '{"final_reply":"Je suis désolée, une erreur est survenue.","extracted_info":{}}'

def generate_final_summary(state: dict):
    """
    Génère un résumé final structuré via OpenAI.
    """
    prompt = f"""
Tu es Emily. Voici les infos extraites: {json.dumps(state.get('extracted_info', {}),ensure_ascii=False)}
Génère STRICTEMENT un JSON avec:
- resume_conversationnel
- intent_principale
- actions_a_prendre
"""
    
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es Emily. Réponds STRICTEMENT en JSON brut."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        print("Erreur OpenAI résumé:", e)
        return {"resume_conversationnel": "Résumé indisponible", "intent_principale": state.get("intent", "inconnu"), "actions_a_prendre": "Vérifier manuellement."}
    
# ----------------------------------------------------------------------------------------
# Google Sheets : recherche et ajout (ordre des colonnes confirmé)
# Ordre des colonnes (en-têtes en première ligne) :
# 1 Date d'appel, 2 Nom, 3 Prénom, 4 Adresse, 5 Ville, 6 Code postal,
# 7 Numéro de téléphone, 8 Raison de l'appel, 9 Budget, 10 Catégorie, 11 Type de client
# -----------------------------------------------------------------------------------------
def sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_PATH,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)

def find_client_in_sheets(nom: str, prenom: str, telephone: str):
    """
    Recherche stricte (Nom EXACT, Prénom EXACT, Téléphone EXACT) dans la feuille.
    Retourne la dernière ligne trouvée (la plus récente) ou None.
    """
    try:
        service = sheets_service()
        RANGE = "Prospect!A2:K" # lire toutes les lignes (en-têtes en A1:K1)
        res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE).execute()
        rows = res.get("values", [])
        found = None
        for idx, row in enumerate(rows, start=2): # start=2 car on a sauté l'en-tête
            # protéger l'accès aux colonnes
            r_nom = row[1].strip() if len(row) > 1 else ""
            r_prenom = row[2].strip() if len(row) > 2 else ""
            r_tel = row[6].strip() if len(row) > 6 else ""
            if r_nom.lower() == (nom or "").lower() and r_prenom.lower() == (prenom or "").lower() and r_tel == (telephone or ""):
                # retourner la ligne complète et l'index
                found = {"row_index": idx, "row": row}
        return found
    except Exception as e:
        print("Erreur find_client_in_sheets:", e)
        return None

def append_call_row(extracted_info: dict, category: str, client_type: str):
    """
    Ajoute une nouvelle ligne (un appel) dans la feuille Prospect.
    Respecte l'ordre des colonnes confirmé.
    """

    try:
        service = sheets_service()
        RANGE = "Prospect!A:K"
        row = [
            datetime.utcnow().isoformat(), # Date d'appel
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
        res = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE,
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
        return res.get("updates", {}).get("updatedRange")
    except Exception as e:
        print("Erreur append_call_row:", e)
        return None
    
# ----------------------------------------------------------------------------------------
# Log d'appel local pour résumé quotidien
# -----------------------------------------------------------------------------------------
def append_call_log(call_sid: str, state: dict, summary: dict):
    entry = {
        "call_sid": call_sid,
        "date": date.today().isoformat(),
        "call_started_at": state.get("call_started_at"),
        "extracted_info": state.get("extracted_info", {}),
        "intent": state.get("intent"),
        "resume_conversationnel": summary.get("resume_conversationnel"),
        "intent_principale": summary.get("intent_principale"),
        "actions_a_prendre": summary.get("actions_a_prendre")
    }
    logs = []
    if os.path.exists(CALL_LOG_FILE):
        try:
            with open(CALL_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.loads(f)
        except Exception:
            logs = []
    logs.append(entry)
    try:
        with open(CALL_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Erreur append_call_log:", e)

# ----------------------------------------------------------------------------------------
# Email quotidien via SendGrid
# -----------------------------------------------------------------------------------------
def send_daily_email():
    today_str = date.today().isoformat()
    logs = []
    if os.path.exists(CALL_LOG_FILE):
        try:
            with open(CALL_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []
    todays = [l for l in logs if l.get("date") == today_str]
    nb = len(todays)
    intents = {}
    for c in todays:
        intents[c.get("intent_principale", "inconnu")] = intents.get(c.get("intent_principale", "inconnu"), 0) + 1
    intents_html = "<br>".join([f"{k}: {v}" for k, v in intents.items()])
    rows_html = ""
    for c in todays:
        info = c.get("extracted_info", {})
        rows_html += f"<tr><td>{c.get('call_sid')}</td><td>{info.get('nom','')} {info.get('prenom','')}</td><td>{c.get('intent_principale','')}</td><td>{c.get('resume_conversationnel','')}</td></tr>"
        
    html = f"""
    <h2>Récapitulatif des appels - {today_str}</h2>
    <p>Nombre d'appels: <b>{nb}</b></p>
    <p>Intentions principales:<br>{intents_html}</p>
    <table border="1" cellpadding="4"><tr><th>CallSid</th><th>Client</th><th>Intention</th><th>Résumé</th></tr>{rows_html}</table>
    """
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        msg = Mail(
            from_email=SENDGRID_FROM_EMAIL, 
            to_emails="agence.agent.ia.quebec@gmail.com", 
            subject=f"Récapitulatif appels {today_str}", 
            html_content=html
        )
        resp = sg.send(msg)
        print("Email quotidien envoyé:", resp.status_code)
        return True
    except Exception as e:
        print("Erreur send_daily_email:", e)
        return False
        
# ----------------------------------------------------------------------------------------
# Thread asynchrone : génération vraie réponse
# -----------------------------------------------------------------------------------------        
def background_generation(call_sid: str, user_message: str):
    state = get_call_state(call_sid)
    analysis_json = analyze_message(user_message, state)
    try:
        analysis = json.loads(analysis_json)
    except Exception:
        analysis = {"final_reply": "Je suis désolée, une erreur est survenue.", "extracted_info": {}}
    # Mettre à jour extracted_info
    extracted = analysis.get("extracted_info", {})
    # Normaliser clés (attendues)
    for k in ["nom", "prenom", "adresse", "ville", "code_postal", "telephone", "raison_appel", "budget"]:
        if extracted.get(k):
            state["extracted_info"][k] = extracted[k]
    state["intent"] = analysis.get("intent", state.get("intent"))
    state["conversation_history"].append({"user": user_message, "analysis": analysis})
    # Si on a nom+prenom+telephone, tenter reconnaissance client
    nom = state["extracted_info"].get("nom")
    prenom = state["extracted_info"].get("prenom")
    tel = state["extracted_info"].get("telephone")
    if nom and prenom and tel:
        found = find_client_in_sheets(nom, prenom, tel)
        if found:
            # récupérer la dernière ligne trouvée (historique)
            state["recognized_client"] = {
                "row_index": found["row_index"],
                "row": found["row"]
            }
    # Générer audio pour la vraie réponse
    final_reply = analysis.get("final_reply", "Je suis désolée, une erreur est survenue.")
    audio_path = generate_wav_file(final_reply)
    if audio_path:
        set_pending_audio(call_sid, audio_path)

# ----------------------------------------------------------------------------------------
# Endpoint Twilio /voice
# -----------------------------------------------------------------------------------------  
@app.post("/voice")
async def voice(request: Request):
    data = await request.form()
    call_sid = data.get("CallSid")
    user_message = (data.get("SpeechResult") or "").strip()
    call_status = data.get("CallStatus")
    if not call_sid:
        return Response(status_code=400, content="Missing CallSid")
    state = get_call_state(call_sid)
    # CAS 1 : Nouvel appel (pas d'historique et pas de speech)
    if state["conversation_history"] == [] and state["silence_count"] == 0 and user_message == "":
        intro = get_instant_reply(context="intro")
        instant_path = generate_wav_file(intro, target_path=state["instant_audio_file"])
        if instant_path:
            set_last_audio(call_sid, instant_path)
        state["is_playing_audio"] = True
        return Response(content=f"""<Response>
<Play>https://{os.getenv('PUBLIC_HOST') or 'emily-backend-v-996818120694.northamerica-northeast1.run.app'}/voice-file?call_sid={call_sid}</Play>
<Redirect>/listen</Redirect>
</Response>""", media_type="application/xml")
    # CAS 3 : Silence
    if user_message == "":
        state["silence_count"] += 1
        sc = state["silence_count"]
        if sc in (1,2):
            text = get_instant_reply(context="silence", silence_count=sc)
            p = generate_wav_file(text, target_path=state["instant_audio_file"])
            if p:
                set_last_audio(call_sid, p)
            state["is_playing_audio"] = True
            return Response(content=f"""<Response>
<Play>https://{os.getenv('PUBLIC_HOST') or 'emily-backend-v-996818120694.northamerica-northeast1.run.app'}/voice-file?call_sid={call_sid}</Play>
<Redirect>/listen</Redirect>
</Response>""", media_type="application/xml")
        # 3e silence -> fin d'appel + résumé + sauvegarde
        if sc >= 3:
            summary = generate_final_summary(state)
            # Déterminer catégorie via intent simple
            category = summary.get("intent_principale", "Information")
            # Type client
            client_type = "Régulier" if state.get("recognized_client") else "Nouveau"
            append_call_row(state.get("extracted_info", {}), category, client_type)
            append_call_log(call_sid, state, summary)
            state["final_summary_generated"] = True
            return Response(content="""<Response>
<Say language="fr-FR">Merci pour votre appel. Au revoir.</Say>
<Hangup/>
</Response>""", media_type="application/xml")
    # CAS 4 : Interruption (on parlait et l'utilisateur parle)
    if state["is_playing_audio"] and user_message != "":
        state["is_playing_audio"] = False
        instant_text = get_instant_reply(context="thinking", state=state)
        p = generate_wav_file(instant_text, target_path=state["instant_audio_file"])
        if p:
            set_last_audio(call_sid, p)
        # Lancer génération vraie réponse
        threading.Thread(target=background_generation, args=(call_sid, user_message)).start()
        return Response(content=f"""<Response>
<Play>https://{os.getenv('PUBLIC_HOST') or 'emily-backend-v-996818120694.northamerica-northeast1.run.app'}/voice-file?call_sid={call_sid}</Play>
<Redirect>/listen</Redirect>
</Response>""", media_type="application/xml")
    # CAS 2 : Utilisateur parle (tour normal)
    if user_message != "":
        state["silence_count"] = 0
        # Si une vraie réponse est prête -> jouer
        pending = state.get("pending_audio_file")
        if pending and os.path.exists(pending):
            set_last_audio(call_sid, pending)
            set_pending_audio(call_sid, None)
            state["is_playing_audio"] = True
            return Response(content=f"""<Response>
<Play>https://{os.getenv('PUBLIC_HOST') or 'emily-backend-v-996818120694.northamerica-northeast1.run.app'}/voice-file?call_sid={call_sid}</Play>
<Redirect>/listen</Redirect>
</Response>""", media_type="application/xml")
        # Sinon : instantané + lancer génération en arrière-plan
        instant_text = get_instant_reply(context="thinking", state=state)
        p = generate_wav_file(instant_text, target_path=state["instant_audio_file"])
        if p:
            set_last_audio(call_sid, p)
        threading.Thread(target=background_generation, args=(call_sid, user_message)).start()
        state["is_playing_audio"] = True
        return Response(content=f"""<Response>
Play>https://{os.getenv('PUBLIC_HOST') or 'emily-backend-v-996818120694.northamerica-northeast1.run.app'}/voice-file?call_sid={call_sid}</Play>
<Redirect>/listen</Redirect>
</Response>""", media_type="application/xml")
    # Fallback : retourner en écoute
    return Response(content="<Response><Redirect>/listen</Redirect></Response>", media_type="application/xml")

# ----------------------------------------------------------------------------------------
# Endpoint Twilio /listen (Twilio Gather)
# ----------------------------------------------------------------------------------------
@app.post("/listen")
async def listen():
    return Response(content="""<Response>
<Gather input="speech" language="fr-FR" action="/voice" method="POST" speechTimeout="auto" timeout="8" enhanced="true" speechModel="default"/>
</Response>""", media_type="application/xml")

# ----------------------------------------------------------------------------------------
# Endpoint /voice-file : renvoie le dernier audio pour le call_sid
# ----------------------------------------------------------------------------------------
@app.get("/voice-file")
def voice_file(call_sid: str):
    state = get_call_state(call_sid)
    last = state.get("last_audio_file")
    if last and os.path.exists(last):
        return FileResponse(last, media_type="audio/wav")
    # fallback instantané
    inst = state.get("instant_audio_file")
    if inst and os.path.exists(inst):
        return FileResponse(inst, media_type="audio/wav")
    return Response("No audio", status_code=200)

# ----------------------------------------------------------------------------------------
# Call status webhook (fin d'appel)
# ----------------------------------------------------------------------------------------
@app.post("/call-status")
async def call_status(request: Request):
    data = await request.form()
    call_sid = data.get("CallSid")
    call_status = data.get("CallStatus")
    if not call_sid:
        return Response(status_code=400)
    state = get_call_state(call_sid)
    if call_status == "completed" and not state.get("final_summary_generated"):
        summary = generate_final_summary(state)
        # Catégorie et type
        category = summary.get("intent_principale", "Information")
        client_type = "Régulier" if state.get("recognized_client") else "Nouveau"
        append_call_row(state.get("extracted_info", {}), category, client_type)
        append_call_log(call_sid, state, summary)
        state["final_summary_generated"] = True
    return Response(status_code=200)

# ----------------------------------------------------------------------------------------
# Endpoint daily-summary (Cloud Scheduler)
# ----------------------------------------------------------------------------------------
@app.get("/daily-summary")
def daily_summary():
    ok = send_daily_email()
    return JSONResponse({"status": "OK" if ok else "ERROR"})

# ----------------------------------------------------------------------------------------
# Endpoints de test (Sheets, Email)
# ----------------------------------------------------------------------------------------
@app.get("/test-sheets")
def test_sheets():
    try:
        service = sheets_service()
        res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range="A1:K1").execute()
        return {"status": "OK", "header": res.get("values", [])}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}
    
@app.get("/test-write")
def test_write():
    try:
        info = {"nom":"TestNom","prenom":"TestPrenom","adresse":"123","ville":"Ville","code_postal":"H0H0H0","telephone":"000","raison_appel":"Test","budget":"0","category":"Test","type":"Nouveau"}
        updated = append_call_row(info, "Test", "Nouveau")
        return {"status":"OK","updatedRange": updated}
    except Exception as e:
        return {"status":"ERROR","message": str(e)}
    
@app.get("/test-email")
def test_email():
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        message = Mail(from_email=SENDGRID_FROM_EMAIL, to_emails="agence.agent.ia.quebec@gmail.com", subject="Test d'envoi d'email depuis Emily", html_content="<h2>Test réussi</h2><p>Test.</p>")
        resp = sg.send(message)
        return {"status":"OK","sendgrid_status": resp.status_code}
    except Exception as e:
        return {"status":"ERROR","message": str(e)}
    
# ----------------------------------------------------------------------------------------
# Lancement local
# ----------------------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))