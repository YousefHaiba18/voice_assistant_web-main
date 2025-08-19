from flask import Flask, request, send_file, render_template_string
from flask_socketio import SocketIO, emit, join_room, leave_room
import whisper
import tempfile
import os
import asyncio
import edge_tts
import base64

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

model = whisper.load_model("base")
VOICE = "en-US-AriaNeural"

# Store connected devices by room
rooms = {}

@app.route("/")
def index():
    return render_template_string(open("static/index.html", encoding="utf-8").read())

@app.route("/upload", methods=["POST"])
def upload():
    if "audio" not in request.files:
        return "No audio", 400
    
    room_id = request.form.get("room_id", "default")
    temp_audio_path = None
    tts_path = None
    
    try:
        audio = request.files["audio"]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
            temp_audio_path = temp_audio.name
            audio.save(temp_audio_path)
        
        # Transcribe the audio
        result = model.transcribe(temp_audio_path)
        text = result["text"]
        print(f"Transcript: {text}")
        
        # Generate TTS audio
        tts_path = asyncio.run(text_to_speech(text))
        
        # Read the audio file and encode it as base64
        with open(tts_path, "rb") as audio_file:
            audio_data = base64.b64encode(audio_file.read()).decode()
        
        # Send audio to speaker devices in the same room
        socketio.emit('play_audio', {
            'audio_data': audio_data,
            'transcript': text
        }, room=room_id)
        
        return {"status": "Audio sent to speakers", "transcript": text}
        
    except Exception as e:
        print(f"Error in upload: {e}")
        return {"status": "Error processing audio", "error": str(e)}, 500
        
    finally:
        # Clean up temp files with error handling
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.unlink(temp_audio_path)
            except PermissionError:
                print(f"Warning: Could not delete temp audio file {temp_audio_path}")
        
        if tts_path and os.path.exists(tts_path):
            try:
                os.unlink(tts_path)
            except PermissionError:
                print(f"Warning: Could not delete TTS file {tts_path}")

async def text_to_speech(text):
    communicate = edge_tts.Communicate(text, VOICE)
    out_path = tempfile.mktemp(suffix=".mp3")
    await communicate.save(out_path)
    return out_path

@socketio.on('join_room')
def on_join(data):
    room_id = data['room_id']
    device_type = data['device_type']  # 'microphone' or 'speaker'
    
    join_room(room_id)
    
    if room_id not in rooms:
        rooms[room_id] = {'microphones': [], 'speakers': []}
    
    if device_type == 'microphone':
        rooms[room_id]['microphones'].append(request.sid)
    elif device_type == 'speaker':
        rooms[room_id]['speakers'].append(request.sid)
    
    print(f"Device {request.sid} joined room {room_id} as {device_type}")
    emit('room_status', {
        'room_id': room_id,
        'microphones': len(rooms[room_id]['microphones']),
        'speakers': len(rooms[room_id]['speakers'])
    }, room=room_id)

@socketio.on('leave_room')
def on_leave(data):
    room_id = data['room_id']
    leave_room(room_id)
    
    if room_id in rooms:
        if request.sid in rooms[room_id]['microphones']:
            rooms[room_id]['microphones'].remove(request.sid)
        if request.sid in rooms[room_id]['speakers']:
            rooms[room_id]['speakers'].remove(request.sid)
    
    print(f"Device {request.sid} left room {room_id}")

@socketio.on('disconnect')
def on_disconnect():
    # Clean up user from all rooms
    for room_id in rooms:
        if request.sid in rooms[room_id]['microphones']:
            rooms[room_id]['microphones'].remove(request.sid)
        if request.sid in rooms[room_id]['speakers']:
            rooms[room_id]['speakers'].remove(request.sid)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001, debug=True)