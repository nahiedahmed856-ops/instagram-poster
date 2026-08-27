import os
import json
import time
import uuid
import requests
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect, url_for, jsonify
from instagrapi import Client

app = Flask(__name__)

# Determine reliable writable queue file location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSSIBLE_QUEUE_PATHS = [
    os.path.join(BASE_DIR, "queue.json"),
    os.path.join(os.getcwd(), "queue.json"),
    "/tmp/queue.json"
]

QUEUE_FILE = POSSIBLE_QUEUE_PATHS[0]
SESSION_FILE = os.path.join(BASE_DIR, "session.json")

INTERVAL_HOURS = 3  # প্রতি ৩ ঘণ্টা পর পর পোস্ট হবে
next_post_time = None
last_post_log = "Server started. Ready to schedule posts."
is_posting = False

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Instagram 3-Hour Auto Poster Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .card { background-color: #1e293b; border: 1px solid #334155; border-radius: 12px; }
        .badge-pending { background-color: #f59e0b; }
        .badge-posted { background-color: #10b981; }
        .badge-failed { background-color: #ef4444; }
        .stat-card { text-align: center; padding: 18px; }
        .stat-num { font-size: 2.2rem; font-weight: bold; }
        .table-dark { --bs-table-bg: #1e293b; --bs-table-border-color: #334155; }
        .btn-gradient { background: linear-gradient(45deg, #f09433, #e6683c, #dc2743, #cc2366, #bc1888); color: white; border: none; }
        .btn-gradient:hover { color: white; opacity: 0.9; }
    </style>
</head>
<body class="p-4">
<div class="container">
    <div class="d-flex justify-content-between align-items-center mb-4 pb-2 border-bottom border-secondary">
        <div>
            <h2 class="fw-bold mb-0">📸 Instagram Auto-Poster</h2>
            <p class="text-secondary mb-0">Scheduled Posting Every {{ interval_hours }} Hours (No API Required)</p>
        </div>
        <div>
            <form action="/post_now" method="POST" onsubmit="return confirm('Do you want to post the next item right now?');">
                <button type="submit" class="btn btn-danger fw-bold">⚡ Post Next Item Now</button>
            </form>
        </div>
    </div>

    <!-- Status & Stats Row -->
    <div class="row g-3 mb-4">
        <div class="col-md-3">
            <div class="card stat-card">
                <div class="text-secondary small">NEXT POST IN</div>
                <div class="stat-num text-warning" id="timer-box">{{ countdown }}</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card stat-card">
                <div class="text-secondary small">PENDING QUEUE</div>
                <div class="stat-num text-primary">{{ pending_count }}</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card stat-card">
                <div class="text-secondary small">POSTED SO FAR</div>
                <div class="stat-num text-success">{{ posted_count }}</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card stat-card">
                <div class="text-secondary small">FAILED POSTS</div>
                <div class="stat-num text-danger">{{ failed_count }}</div>
            </div>
        </div>
    </div>

    <!-- System Log Alert -->
    <div class="alert alert-dark border-secondary d-flex align-items-center" role="alert">
        <span class="badge bg-secondary me-2">Log</span>
        <span>{{ last_log }}</span>
    </div>

    <div class="row g-4">
        <!-- Add Single Post Form -->
        <div class="col-md-6">
            <div class="card p-3 h-100">
                <h5 class="fw-bold text-info mb-3">➕ Add Single Post</h5>
                <form action="/add" method="POST">
                    <div class="mb-2">
                        <label class="form-label small">Direct Image / Video URL (Google Drive / Cloudinary / Catbox):</label>
                        <input type="url" name="media_url" class="form-control bg-dark text-white border-secondary" placeholder="https://..." required>
                    </div>
                    <div class="row g-2 mb-2">
                        <div class="col-8">
                            <label class="form-label small">Title / Main Header:</label>
                            <input type="text" name="title" class="form-control bg-dark text-white border-secondary" placeholder="Amazing sunset...">
                        </div>
                        <div class="col-4">
                            <label class="form-label small">Media Type:</label>
                            <select name="media_type" class="form-select bg-dark text-white border-secondary">
                                <option value="photo">Photo</option>
                                <option value="video">Video / Reel</option>
                            </select>
                        </div>
                    </div>
                    <div class="mb-2">
                        <label class="form-label small">Caption Body:</label>
                        <textarea name="caption" rows="2" class="form-control bg-dark text-white border-secondary" placeholder="Write your full caption here..."></textarea>
                    </div>
                    <div class="mb-3">
                        <label class="form-label small">Hashtags:</label>
                        <input type="text" name="hashtags" class="form-control bg-dark text-white border-secondary" placeholder="#viral #instagram #reels">
                    </div>
                    <button type="submit" class="btn btn-gradient w-100 fw-bold">Add to 3-Hour Queue</button>
                </form>
            </div>
        </div>

        <!-- Bulk Add Form for 1k items -->
        <div class="col-md-6">
            <div class="card p-3 h-100">
                <h5 class="fw-bold text-success mb-3">📦 Bulk Upload (Up to 1,000 items)</h5>
                <p class="text-secondary small mb-2">Paste 1 post per line in format:<br><code>Media_URL | Title | Caption | #Hashtags</code></p>
                <form action="/bulk_add" method="POST">
                    <div class="mb-3">
                        <textarea name="bulk_data" rows="8" class="form-control bg-dark text-white border-secondary font-monospace" placeholder="https://catbox.moe/example1.jpg | Sunset in Bali | Vacation vibes | #travel #beach&#10;https://catbox.moe/example2.mp4 | Gym Workout | Monday motivation | #fitness #gym" required></textarea>
                    </div>
                    <button type="submit" class="btn btn-success w-100 fw-bold">Add All to Queue</button>
                </form>
            </div>
        </div>
    </div>

    <!-- Posts Queue Table -->
    <div class="card p-3 mt-4">
        <h5 class="fw-bold mb-3">📋 Scheduled Queue (Total: {{ queue|length }})</h5>
        <div class="table-responsive">
            <table class="table table-dark table-hover align-middle">
                <thead>
                    <tr class="text-secondary">
                        <th>#</th>
                        <th>Type</th>
                        <th>Title / Caption</th>
                        <th>Media URL</th>
                        <th>Status</th>
                        <th>Time Info</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in queue %}
                    <tr>
                        <td>{{ loop.index }}</td>
                        <td>
                            {% if item.type == 'video' %}
                            <span class="badge bg-danger">🎬 Reel/Video</span>
                            {% else %}
                            <span class="badge bg-primary">🖼️ Photo</span>
                            {% endif %}
                        </td>
                        <td>
                            <strong>{{ item.title }}</strong><br>
                            <small class="text-secondary">{{ item.caption[:50] }}... {{ item.hashtags }}</small>
                        </td>
                        <td>
                            <a href="{{ item.media_url }}" target="_blank" class="text-info text-truncate d-inline-block" style="max-width: 200px;">{{ item.media_url }}</a>
                        </td>
                        <td>
                            {% if item.status == 'Posted' %}
                            <span class="badge badge-posted">✅ Posted</span>
                            {% elif item.status == 'Pending' %}
                            <span class="badge badge-pending">⏳ Pending</span>
                            {% else %}
                            <span class="badge badge-failed">❌ {{ item.error or 'Failed' }}</span>
                            {% endif %}
                        </td>
                        <td class="small text-secondary">
                            {% if item.posted_at %}
                            Posted: {{ item.posted_at }}
                            {% else %}
                            Added: {{ item.added_at }}
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="6" class="text-center text-secondary py-4">No posts in queue. Add some above!</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
    let totalSeconds = {{ remaining_seconds }};
    const timerBox = document.getElementById("timer-box");

    if (totalSeconds > 0) {
        setInterval(() => {
            if (totalSeconds <= 0) {
                location.reload();
            } else {
                totalSeconds--;
                let hours = Math.floor(totalSeconds / 3600);
                let minutes = Math.floor((totalSeconds % 3600) / 60);
                let seconds = totalSeconds % 60;
                timerBox.innerText = `${hours}h ${minutes}m ${seconds}s`;
            }
        }, 1000);
    } else {
        setTimeout(() => { location.reload(); }, 15000);
    }
</script>
</body>
</html>
"""

def get_writable_queue_path():
    for p in POSSIBLE_QUEUE_PATHS:
        try:
            if os.path.exists(p):
                return p
            # Test creating
            with open(p, "w", encoding="utf-8") as f:
                json.dump([], f)
            return p
        except Exception:
            continue
    return POSSIBLE_QUEUE_PATHS[0]

def load_queue():
    path = get_writable_queue_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []

def save_queue(queue):
    path = get_writable_queue_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving queue to {path}: {e}")

def download_file(url, output_path):
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
        raise Exception("No Instagram session or credentials found! Please upload session.json.")

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
        
        ext = ".mp4" if item.get("type") == "video" or any(media_url.endswith(x) for x in [".mp4", ".mov", ".mkv"]) else ".jpg"
        temp_file = os.path.join(BASE_DIR, f"temp_{uuid.uuid4().hex}{ext}")
        download_file(media_url, temp_file)

        cl = get_instagram_client()

        if ext == ".mp4":
            media = cl.clip_upload(temp_file, caption=caption)
        else:
            media = cl.photo_upload(temp_file, caption=caption)

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
    next_post_time = datetime.now() + timedelta(minutes=1)
    while True:
        try:
            if next_post_time and datetime.now() >= next_post_time:
                post_next_item()
        except Exception as e:
            print(f"Scheduler error: {e}")
        time.sleep(30)

scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
scheduler_thread.start()

@app.route("/", methods=["GET"])
def index():
    queue = load_queue()
    pending = [q for q in queue if q.get("status") == "Pending"]
    posted = [q for q in queue if q.get("status") == "Posted"]
    failed = [q for q in queue if q.get("status") == "Failed"]
    
    countdown = "Calculating..."
    remaining_seconds = 0
    if next_post_time:
        diff = next_post_time - datetime.now()
        if diff.total_seconds() > 0:
            remaining_seconds = int(diff.total_seconds())
            hours, remainder = divmod(remaining_seconds, 3600)
            mins, secs = divmod(remainder, 60)
            countdown = f"{hours}h {mins}m {secs}s"
        else:
            countdown = "Posting right now..."
            
    return render_template_string(
        HTML_TEMPLATE, 
        queue=queue, 
        pending_count=len(pending), 
        posted_count=len(posted),
        failed_count=len(failed),
        countdown=countdown,
        remaining_seconds=remaining_seconds,
        last_log=last_post_log,
        interval_hours=INTERVAL_HOURS
    )

@app.route("/add", methods=["GET", "POST"])
def add_post():
    if request.method == "POST":
        try:
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
        except Exception as e:
            print(f"Error in add_post: {e}")
    return redirect(url_for("index"))

@app.route("/bulk_add", methods=["GET", "POST"])
def bulk_add():
    if request.method == "POST":
        try:
            bulk_text = request.form.get("bulk_data", "").strip()
            if bulk_text:
                queue = load_queue()
                try:
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
        except Exception as e:
            print(f"Error in bulk_add: {e}")
    return redirect(url_for("index"))

@app.route("/post_now", methods=["GET", "POST"])
def trigger_post_now():
    try:
        threading.Thread(target=post_next_item).start()
    except Exception as e:
        print(f"Error triggering post_now: {e}")
    return redirect(url_for("index"))

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "alive", "time": datetime.now().isoformat()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
