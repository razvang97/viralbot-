import os
import time
import json
import requests
import schedule
import anthropic
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]
ELEVENLABS_KEY  = os.environ["ELEVENLABS_API_KEY"]
ELEVENLABS_VOICE= os.environ.get("ELEVENLABS_VOICE_ID", "ErXwobaYiN019PkySvjV")  # Antoni - masculine
RUNWAY_KEY      = os.environ["RUNWAY_API_KEY"]
PUBLER_KEY      = os.environ["PUBLER_API_KEY"]
PUBLER_PROFILES = os.environ["PUBLER_PROFILE_IDS"]  # "id1,id2" (TikTok + Instagram)

# 5 video topics per day - rotates through finance angles
DAILY_TOPICS = [
    "shocking money fact most people don't know",
    "biggest money mistake young people make",
    "how rich people think about money differently",
    "simple investing habit that builds wealth",
    "financial freedom tip under 60 seconds",
]

POST_TIMES = ["07:00", "10:00", "13:00", "17:00", "20:00"]

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# ─── STEP 1: GENERATE SCRIPT ──────────────────────────────
def generate_script(topic: str) -> dict:
    print(f"[{datetime.now()}] Generating script for: {topic}")
    
    response = anthropic_client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""You are a viral finance content creator for TikTok and Instagram Reels.
            
Write a script about: {topic}

Rules:
- Duration: 45-55 seconds when spoken
- Hook in first 3 seconds (shocking, controversial, or curiosity-triggering)
- Use simple language, short sentences
- End with a strong CTA: "Follow for daily money tips"
- NO filler words, every sentence must hit hard

Also provide:
- Video description (under 150 chars) with 1-2 emojis
- 10 hashtags optimized for finance niche

Respond in JSON format:
{{
  "script": "full script here",
  "description": "caption here",
  "hashtags": "#tag1 #tag2 ...",
  "visual_prompt": "cinematic 9:16 vertical video scene description for AI video generation, 3-4 sentences, no text overlays, photorealistic"
}}"""
        }]
    )
    
    raw = response.content[0].text
    # Clean JSON if wrapped in markdown
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()
    
    data = json.loads(raw)
    print(f"  ✅ Script generated ({len(data['script'])} chars)")
    return data

# ─── STEP 2: GENERATE VOICE ───────────────────────────────
def generate_voice(script: str, output_path: str) -> str:
    print(f"  🎙️ Generating voice...")
    
    response = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE}",
        headers={
            "xi-api-key": ELEVENLABS_KEY,
            "Content-Type": "application/json"
        },
        json={
            "text": script,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.85,
                "style": 0.3,
                "use_speaker_boost": True
            }
        }
    )
    
    if response.status_code != 200:
        raise Exception(f"ElevenLabs error: {response.text}")
    
    with open(output_path, "wb") as f:
        f.write(response.content)
    
    print(f"  ✅ Voice saved: {output_path}")
    return output_path

# ─── STEP 3: GENERATE VIDEO (RUNWAY) ──────────────────────
def get_unsplash_image() -> str:
    """Download stock image and convert to base64 for Runway"""
    import base64
    image_url = "https://images.unsplash.com/photo-1579621970563-ebec7560ff3e?w=720&h=1280&fit=crop"
    response = requests.get(image_url)
    b64 = base64.b64encode(response.content).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"

def generate_video(visual_prompt: str, output_path: str) -> str:
    print(f"  🎬 Generating video with Runway ML...")
    
    headers = {
        "Authorization": f"Bearer {RUNWAY_KEY}",
        "Content-Type": "application/json",
        "X-Runway-Version": "2024-11-06"
    }
    
    # Get free stock image for Runway input
    print(f"  🖼️ Getting stock image...")
    image_b64 = get_unsplash_image()
    print(f"  ✅ Image ready as base64")
    
    create_resp = requests.post(
        "https://api.dev.runwayml.com/v1/image_to_video",
        headers=headers,
        json={
            "model": "gen4_turbo",
            "promptImage": image_b64,
            "promptText": visual_prompt + " Cinematic motion. Photorealistic.",
            "ratio": "720:1280",
            "duration": 10,
        }
    )
    
    if create_resp.status_code not in [200, 201]:
        raise Exception(f"Runway create error: {create_resp.text}")
    
    task_id = create_resp.json().get("id")
    print(f"  ⏳ Runway task ID: {task_id} — waiting for render...")
    
    # Poll for completion
    for attempt in range(60):  # max 10 minutes
        time.sleep(10)
        status_resp = requests.get(
            f"https://api.dev.runwayml.com/v1/tasks/{task_id}",
            headers=headers
        )
        status_data = status_resp.json()
        status = status_data.get("status")
        
        if status == "SUCCEEDED":
            video_url = status_data["output"][0]
            print(f"  ✅ Video ready: {video_url}")
            
            # Download video
            video_resp = requests.get(video_url)
            with open(output_path, "wb") as f:
                f.write(video_resp.content)
            print(f"  ✅ Video saved: {output_path}")
            return output_path
            
        elif status == "FAILED":
            raise Exception(f"Runway generation failed: {status_data}")
        
        print(f"  ⏳ Status: {status} ({attempt+1}/60)")
    
    raise Exception("Runway timeout after 10 minutes")

# ─── STEP 4: MERGE AUDIO + VIDEO ──────────────────────────
def merge_audio_video(video_path: str, audio_path: str, output_path: str) -> str:
    print(f"  🎞️ Merging audio + video...")
    import subprocess
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-map", "0:v:0",
        "-map", "1:a:0",
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"FFmpeg error: {result.stderr}")
    
    print(f"  ✅ Final video: {output_path}")
    return output_path

# ─── STEP 5: POST TO TIKTOK + INSTAGRAM ───────────────────
def post_video(video_path: str, description: str, hashtags: str, schedule_time: str = None) -> bool:
    print(f"  📤 Posting to TikTok + Instagram via Publer...")
    
    profile_ids = [p.strip() for p in PUBLER_PROFILES.split(",")]
    caption = f"{description}\n\n{hashtags}"
    
    headers = {"Authorization": f"Bearer {PUBLER_KEY}"}
    
    # Upload video file first
    with open(video_path, "rb") as f:
        upload_resp = requests.post(
            "https://app.publer.io/api/v1/media/upload",
            headers=headers,
            files={"file": (os.path.basename(video_path), f, "video/mp4")}
        )
    
    if upload_resp.status_code not in [200, 201]:
        raise Exception(f"Publer upload error: {upload_resp.text}")
    
    media_id = upload_resp.json().get("id") or upload_resp.json().get("media_id")
    print(f"  ✅ Media uploaded: {media_id}")
    
    # Create post for each profile (TikTok + Instagram)
    for profile_id in profile_ids:
        post_data = {
            "profile_ids": [profile_id],
            "text": caption,
            "media_ids": [media_id],
        }
        
        if schedule_time:
            post_data["scheduled_at"] = schedule_time
        
        post_resp = requests.post(
            "https://app.publer.io/api/v1/post",
            headers={**headers, "Content-Type": "application/json"},
            json=post_data
        )
        
        if post_resp.status_code not in [200, 201]:
            print(f"  ⚠️ Publer post error for {profile_id}: {post_resp.text}")
        else:
            print(f"  ✅ Posted to profile: {profile_id}")
    
    return True

# ─── MAIN PIPELINE ────────────────────────────────────────
def create_and_post_video(topic_index: int):
    topic = DAILY_TOPICS[topic_index % len(DAILY_TOPICS)]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_path = f"/tmp/video_{timestamp}"
    
    print(f"\n{'='*50}")
    print(f"🚀 Starting pipeline for video {topic_index+1}/5")
    print(f"Topic: {topic}")
    print(f"{'='*50}")
    
    try:
        # Step 1: Script
        content = generate_script(topic)
        
        # Step 2: Voice
        audio_path = generate_voice(content["script"], f"{base_path}_audio.mp3")
        
        # Step 3: Video
        video_raw_path = generate_video(content["visual_prompt"], f"{base_path}_raw.mp4")
        
        # Step 4: Merge
        final_video = merge_audio_video(video_raw_path, audio_path, f"{base_path}_final.mp4")
        
        # Step 5: Post
        post_video(final_video, content["description"], content["hashtags"])
        
        # Cleanup temp files
        for f in [audio_path, video_raw_path]:
            if os.path.exists(f):
                os.remove(f)
        
        print(f"\n✅ VIDEO {topic_index+1} COMPLETE & POSTED!")
        
    except Exception as e:
        print(f"\n❌ ERROR on video {topic_index+1}: {e}")
        # Continue to next video even if one fails

# ─── SCHEDULER ────────────────────────────────────────────
def setup_schedule():
    for i, post_time in enumerate(POST_TIMES):
        schedule.every().day.at(post_time).do(create_and_post_video, topic_index=i)
        print(f"  📅 Scheduled video {i+1} at {post_time}")

if __name__ == "__main__":
    print("🤖 Viral Finance Bot — Starting...")
    print(f"📅 Schedule: {', '.join(POST_TIMES)}")
    
    setup_schedule()
    
    # Run first video immediately on startup
    print("\n🚀 Running first video immediately...")
    create_and_post_video(0)
    
    print("\n✅ Bot is running! Waiting for scheduled times...")
    print("Press Ctrl+C to stop.\n")
    
    while True:
        schedule.run_pending()
        time.sleep(30)
