import os
import json
import time
import uuid
import requests
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, jsonify
from instagrapi import Client

app = Flask(__name__)

QUEUE_FILE = "queue.json"
SESSION_FILE = "session.json"
INTERVAL_HOURS = 3  # প্রতি ৩ ঘণ্টা পর পর পোস্ট হবে
next_post_time = None
last_post_log = "No posts yet."
is_posting = False

# Ensure queue file exists
if not os.path.exists(QUEUE_FILE):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=4)

def load_queue():
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_queue(queue):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=4, ensure_ascii=False)

def download_file(url, output_path):
    """Download image or video from cloud URL (Drive, Cloudinary, etc.)"""
    # Handle Google Drive direct link conversion if applicable
    if "drive.google.com" in url and "id=" in url:
        file_id = url.split("id=")[1].split("&")[0]
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
    elif "drive.google.com/file/d/" in url:
        file_id = url.split("/file/d/")[1].split("/")[0]
        url = f"https://drive.google.com/uc?export=download&id={file_id}"

    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get(url, headers=headers, stream=True, timeout=60)
    r.raise_for_status()
    with open(output_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return output_path

def get_instagram_client():
    cl = Client()
    cl.delay_range = [2, 5]
    if os.path.exists(SESSION_FILE):
        cl.load_settings(SESSION_FILE)
        return cl
    elif os.environ.get("IG_SESSION_JSON"):
        session_data = json.loads(os.environ.get("IG_SESSION_JSON"))
        cl.set_settings(session_data)
        return cl
    elif os.environ.get("IG_USERNAME") and os.environ.get("IG_PASSWORD"):
        cl.login(os.environ.get("IG_USERNAME"), os.environ.get("IG_PASSWORD"))
        cl.dump_settings(SESSION_FILE)
        return cl
    else:
        raise Exception("No Instagram session or credentials found! Please run login_local.py first.")

def post_next_item():
    global last_post_log, is_posting, next_post_time
    if is_posting:
        return
    
    queue = load_queue()
    pending_items = [item for item in queue if item.get("status") == "Pending"]
    
    if not pending_items:
        last_post_log = "Queue is empty. No pending posts found."
        return

    item = pending_items[0]
    is_posting = True
    temp_file = None
    try:
        last_post_log = f"Posting: {item.get('title', '')}..."
        media_url = item.get("media_url")
        caption = f"{item.get('title', '')}\n\n{item.get('caption', '')}\n\n{item.get('hashtags', '')}".strip()
        
        # Download media
        ext = ".mp4" if item.get("type") == "video" or media_url.endswith((".mp4", ".mov", ".mkv")) else ".jpg"
        temp_file = f"temp_{uuid.uuid4().hex}{ext}"
        download_file(media_url, temp_file)

        # Connect to Instagram
        cl = get_instagram_client()

        # Upload
        if ext == ".mp4":
            media = cl.clip_upload(temp_file, caption=caption)
        else:
            media = cl.photo_upload(temp_file, caption=caption)

        # Mark as Posted
        for q in queue:
            if q["id"] == item["id"]:
                q["status"] = "Posted"
                q["posted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                q["ig_media_id"] = str(media.id)
                break
        save_queue(queue)
        last_post_log = f"Successfully posted '{item.get('title')}' at {datetime.now().strftime('%H:%M:%S')}"
    except Exception as e:
        last_post_log = f"Failed to post: {str(e)}"
        for q in queue:
            if q["id"] == item["id"]:
                q["status"] = "Failed"
                q["error"] = str(e)
                break
        save_queue(queue)
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
        is_posting = False
        next_post_time = datetime.now() + timedelta(hours=INTERVAL_HOURS)

def scheduler_loop():
    global next_post_time
    next_post_time = datetime.now() + timedelta(minutes=1)  # First check after 1 min
    while True:
        try:
            if next_post_time and datetime.now() >= next_post_time:
                post_next_item()
        except Exception as e:
            print(f"Scheduler error: {e}")
        time.sleep(30)

# Start background thread
scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
scheduler_thread.start()

@app.route("/")
def index():
    queue = load_queue()
    pending = [q for q in queue if q.get("status") == "Pending"]
    posted = [q for q in queue if q.get("status") == "Posted"]
    failed = [q for q in queue if q.get("status") == "Failed"]
    
    countdown = "Calculating..."
    if next_post_time:
        diff = next_post_time - datetime.now()
        if diff.total_seconds() > 0:
            hours, remainder = divmod(int(diff.total_seconds()), 3600)
            mins, secs = divmod(remainder, 60)
            countdown = f"{hours}h {mins}m {secs}s"
        else:
            countdown = "Posting right now..."
            
    return render_template(
        "index.html", 
        queue=queue, 
        pending_count=len(pending), 
        posted_count=len(posted),
        failed_count=len(failed),
        countdown=countdown,
        last_log=last_post_log,
        interval_hours=INTERVAL_HOURS
    )

@app.route("/add", methods=["POST"])
def add_post():
    title = request.form.get("title", "")
    caption = request.form.get("caption", "")
    hashtags = request.form.get("hashtags", "")
    media_url = request.form.get("media_url", "").strip()
    media_type = request.form.get("media_type", "photo")

    if media_url:
        queue = load_queue()
        queue.append({
            "id": str(uuid.uuid4()),
            "title": title,
            "caption": caption,
            "hashtags": hashtags,
            "media_url": media_url,
            "type": media_type,
            "status": "Pending",
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        save_queue(queue)
    return redirect(url_for("index"))

@app.route("/bulk_add", methods=["POST"])
def bulk_add():
    """Add multiple posts from bulk text (JSON or CSV format)"""
    bulk_text = request.form.get("bulk_data", "").strip()
    if bulk_text:
        queue = load_queue()
        try:
            # Try JSON array first
            data = json.loads(bulk_text)
            for item in data:
                queue.append({
                    "id": str(uuid.uuid4()),
                    "title": item.get("title", "No Title"),
                    "caption": item.get("caption", ""),
                    "hashtags": item.get("hashtags", ""),
                    "media_url": item.get("media_url", ""),
                    "type": item.get("type", "photo"),
                    "status": "Pending",
                    "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
        except Exception:
            # Parse line by line: MediaURL | Title | Caption | Hashtags
            for line in bulk_text.splitlines():
                parts = [p.strip() for p in line.split("|")]
                if parts and parts[0]:
                    media_url = parts[0]
                    title = parts[1] if len(parts) > 1 else "Auto Post"
                    caption = parts[2] if len(parts) > 2 else ""
                    hashtags = parts[3] if len(parts) > 3 else ""
                    media_type = "video" if any(media_url.endswith(x) for x in [".mp4", ".mov", ".mkv"]) else "photo"
                    queue.append({
                        "id": str(uuid.uuid4()),
                        "title": title,
                        "caption": caption,
                        "hashtags": hashtags,
                        "media_url": media_url,
                        "type": media_type,
                        "status": "Pending",
                        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
        save_queue(queue)
    return redirect(url_for("index"))

@app.route("/post_now", methods=["POST"])
def trigger_post_now():
    threading.Thread(target=post_next_item).start()
    return redirect(url_for("index"))

@app.route("/ping")
def ping():
    return jsonify({"status": "alive", "time": datetime.now().isoformat()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
