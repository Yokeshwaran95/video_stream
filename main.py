from fastapi import FastAPI, WebSocket
from aiortc import RTCPeerConnection, VideoStreamTrack, RTCSessionDescription,MediaStreamTrack, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaRecorder
import av
import google.generativeai as genai
import os

app = FastAPI()
pcs = set()

# Configure Gemini AI
genai.configure(api_key="YOUR_GEMINI_API_KEY")

ice_servers = [
    RTCIceServer(urls="stun:stun.l.google.com:19302"),  # Google STUN server
    RTCIceServer(urls="stun:stun1.l.google.com:19302")  # Example TURN server
]
configuration = RTCConfiguration(iceServers=ice_servers)

class EmptyVideoTrack(MediaStreamTrack):
    kind = "video"

    async def recv(self):
        return None

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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for WebRTC signaling and processing"""
    await websocket.accept()

    pc = RTCPeerConnection()
    pcs.add(pc)
    empty_video = EmptyVideoTrack()
    pc.addTrack(empty_video)

    @pc.on("track")
    async def on_track(track):
        if track.kind == "video":
            recorder = MediaRecorder("output.mp4")
            recorder.addTrack(track)
            await recorder.start()

            while True:
                frame = await track.recv()
                response = await process_frame(frame)

                # Send AI response back to frontend
                await websocket.send_json({"response": response})

    @pc.on("icecandidate")
    async def on_icecandidate(candidate):
        if candidate:
            await websocket.send_json({"candidate": candidate.to_dict()})

    try:

        if not any(sender.track == empty_video for sender in pc.getSenders()):
            pc.addTrack(empty_video)
        data = await websocket.receive_json()
        offer = data.get("offer")

        if offer:
            rtc_offer = RTCSessionDescription(sdp=offer["sdp"], type=offer["type"])
            await pc.setRemoteDescription(rtc_offer)  # ✅ Set only once

            answer = await pc.createAnswer()
            answer.sdp = fix_sdp(answer.sdp)
            await pc.setLocalDescription(answer)

            await websocket.send_json({
                    "answer": {
                        "sdp": pc.localDescription.sdp,
                        "type": pc.localDescription.type
                    }
                })

    # except Exception as e:
    #     print(f"WebRTC error: {e}")
    finally:
        await pc.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
