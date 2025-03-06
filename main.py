from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from aiortc import RTCPeerConnection, VideoStreamTrack, RTCSessionDescription,MediaStreamTrack, RTCConfiguration, RTCIceServer
from aiortc.contrib.signaling import BYE, TcpSocketSignaling

from aiortc.contrib.media import MediaRecorder
import av
import cv2
# import google.generativeai as genai
import os

app = FastAPI()
pcs = set()

# Configure Gemini AI
# genai.configure(api_key="YOUR_GEMINI_API_KEY")

class WebRTCSignaling:
    def __init__(self):
        self.clients = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.clients.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        self.clients.remove(websocket)
        await websocket.close()

    async def send_to_all(self, message: dict):
        for client in self.clients:
            await client.send_json(message)

signaling = WebRTCSignaling()

 
class VideoTrack(MediaStreamTrack):
    def __init__(self):
        super().__init__()
        self._paused = False

    async def recv(self):
        if not self._paused:
            frame = await self._generate_frame()  # Replace with your video source (e.g., camera)
            return frame
        return None

    async def _generate_frame(self):
        self.cap = cv2.VideoCapture(0)
        # Capture frame from the video stream
        ret, frame = self.cap.read()
        
        if not ret:
            print("Failed to grab frame")
            return None

        # Here you can process the frame (e.g., apply filters, add text, etc.)
        # For now, we just return the frame as-is
        return frame

def fix_sdp(sdp):
    """Ensure SDP has valid media and directions"""
    if "m=video" not in sdp:
        sdp += "\nm=video 9 UDP/TLS/RTP/SAVPF 96\n"  # ✅ Add video section if missing
        sdp += "a=sendrecv\n"  # ✅ Add valid direction

    return sdp


async def process_frame(frame):
    """Send frame to Gemini AI and return response"""
    try:
        # Convert frame to bytes
        frame_bytes = frame.to_image().tobytes()

        # Send to Gemini AI
        response = genai.generate_text("Describe the image", frame_bytes)
        return response.text
    except Exception as e:
        return str(e)


async def create_peer_connection():

    stun_server = RTCIceServer(urls=["stun:openrelay.metered.ca:80"])

    turn_server = RTCIceServer(
        urls=["turn:openrelay.metered.ca:443", "turn:openrelay.metered.ca:80","turn:openrelay.metered.ca:443?transport=tcp"],
        username="openrelayproject",
        credential="openrelayproject"
    )

    # Create RTCConfiguration
    rtc_config = RTCConfiguration(iceServers=[stun_server, turn_server])

    # Creating a peer connection with ICE configuration
    peer_connection = RTCPeerConnection(configuration=rtc_config)

    @peer_connection.on("icecandidate")
    def on_icecandidate(candidate):
        if candidate:
            # Send the ICE candidate to the other peer via signaling
            pass

    @peer_connection.on("iceconnectionstatechange")
    def on_iceconnectionstatechange():
        print("ICE Connection State:", peer_connection.iceConnectionState)

    return peer_connection

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await signaling.connect(websocket)
    try:
        while True:
            message = await websocket.receive_json()
            if "offer" in message:
                offer = RTCSessionDescription(sdp=message["offer"], type="offer")

                # Create a new peer connection
                peer_connection = await create_peer_connection()

                # Set the offer received from the client
                await peer_connection.setRemoteDescription(offer)

                # Create an answer to send back to the client
                answer = await peer_connection.createAnswer()
                await peer_connection.setLocalDescription(answer)

                # Send back the answer (SDP) to the client
                await signaling.send_to_all({
                    "answer": answer.sdp
                })

                # Add a video track to the peer connection (you can replace it with a real camera stream)
                video_track = VideoTrack()
                peer_connection.addTrack(video_track)
            
            elif "candidate" in message:
                # Add ICE candidates to the peer connection
                candidate = message["candidate"]
                await peer_connection.addIceCandidate(candidate)

    except WebSocketDisconnect:
        print("Client disconnected")
        await signaling.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
