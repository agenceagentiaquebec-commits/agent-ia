# main.py
# Agent vocal Emily - version PRO (barge-in, silence, flux complet)

from fastapi import FastAPI, Request
from fastapi.responses import Response, FileResponse, JSONResponse
import os
import threading

from state import get_state, set_last_audio, set_pending_audio, reset_silence, increment_silence
from audio import generate_audio
from llm import analyze_message, generate_final_summary
from sheets import find_client, append_call
from utils import clean_text, normalize_phone, log

app = FastAPI()

# --------------------------------------------------------------
# 1. Endpoint principal : /voice
# --------------------------------------------------------------

@app.post("/voice")
async def voice(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid")
    speech = clean_text(form.get("SpeechResult") or "")
    log(f"SpeechResult: {speech}")

    if not call_sid:
        return Response(status_code=400, content="Missing CallSid")
    
    state = get_state(call_sid)

# --------------------------------------------------------------
# CAS A = Nouvel appel (intro)
# --------------------------------------------------------------
    if not state["conversation_history"] and not speech:
        intro = "Bonjour, ici Emily, assistante virtuelle des Contructions P. Gendreau. Comment puis-je vous aider aujourd'hui ?"
        audio_path = generate_audio(intro)
        set_last_audio(call_sid, audio_path)
        state["is_playing"] = True

        return Response(content=f"""
<Response>
    <Gather input="speech" speechTimeout="auto" actionOnEmptyResult="true" bargeIn="true" action="/voice" method="POST">
        <Play>https://{os.getenv('PUBLIC_HOST')}/voice-file?call_sid={call_sid}</Play>
    </Gather>
</Response>
""", media_type="application/xml")
    
    # ----------------------------------------------------------
    # CAS B - Silence (SpeechResult absent)
    # ----------------------------------------------------------
    if not speech:
        silence_count = increment_silence(call_sid)

        if silence_count == 1:
            text = "Êtes-vous toujours là ? Je vous écoute."
        elif silence_count == 2:
            text = "Vu qu'il semble que vous ne soyez plus là ou que la ligne soit mauvaise, veuillez nous rappeler à un meilleur moment."
        else:
            return Response(content="""
<Response>
    <Hangup/>
</Response>
""", media_type="application/xml")
        
        audio_path = generate_audio(text)
        set_last_audio(call_sid, audio_path)
        state["is_playing"] = True

        return Response(content=f"""
<Response>
    <Gather input="speech" speechTimeout="auto" actionOnEmptyResult="true" bargeIn="true" action="/voice" method="POST">
        <Play>https://{os.getenv('PUBLIC_HOST')}/voice-file?call_sid={call_sid}</Play>
    </Gather>
</Response>
""", media_type="application/xml")
    
    # ----------------------------------------------------------
    # CAS C - L'utilisateur parle (interruption ou reponse)
    # ----------------------------------------------------------

    reset_silence(call_sid)
    state["is_playing"] = False

    # Analyse LLM
    analysis = analyze_message(speech, state["extracted_info"])

    # Mise à jour des infos extraites
    for k, v in analysis["extracted_info"].items():
        if v:
            state["extracted_info"][k] = v

    state["intent"] = analysis["intent"]
    state["conversation_history"].append({"user": speech, "analysis": analysis})

    # Reconnaissance client
    nom = state["extracted_info"].get("nom")
    prenom = state["extracted_info"].get("prenom")
    tel = normalize_phone(state["extracted_info"].get("telephone", ""))

    if nom and prenom and tel:
        found = find_client(nom, prenom, tel)
        if found:
            state["recognized_client"] = found

    # Génération audio de la réponse
    reply = analysis["final_reply"]
    audio_path = generate_audio(reply)
    set_last_audio(call_sid, audio_path)
    state["is_playing"] = True

    return Response(content=f"""
<Response>
    <Gather input="speech" speechTimeout="auto" actionOnEmptyResult="true" bargeIn="true" action="/voice" method="POST">
        <Play>https://{os.getenv('PUBLIC_HOST')}/voice-file?call_sid={call_sid}</Play>
    </Gather>
</Response>
""", media_type="application/xml")

# --------------------------------------------------------------
# 2. Endpoint /voice-file (stream audio)
# --------------------------------------------------------------

@app.get("/voice-file")
def voice_file(call_sid: str):
    state = get_state(call_sid)
    last = state["last_audio"]

    if last and os.path.exists(last):
        return FileResponse(last, media_type="audio/wav")
    
    return Response("No audio", status_code=200)

# --------------------------------------------------------------
# 3. Fin d'appel (Twilio webhook)
# --------------------------------------------------------------

@app.post("/call-status")
async def call_status(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid")
    status = form.get("CallStatus")

    if not call_sid:
        return Response(status_code=400)
    
    state = get_state(call_sid)

    if status == "completed" and not state["final_summary_generated"]:
        summary = generate_final_summary(state["extracted_info"], state["intent"])
        category = summary.get("intent_principale", "Information")
        client_type = "Régulier" if state["recognized_client"] else "Nouveau"
        append_call(state["extracted_info"], category, client_type)
        state["final_summary_generated"] = True

    return Response(status_code=200)

# --------------------------------------------------------------
# 4. Endpoint test
# --------------------------------------------------------------

@app.get("/")
def root():
    return {"status": "Emily backend OK"}