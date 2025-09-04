import os
import json
import time
import datetime as dt
from typing import List, Dict, Any
import requests
from slugify import slugify
from rapidfuzz import fuzz, process
import markdown
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# ====== CONFIG ======
BLOG_ID = os.getenv("BLOGGER_BLOG_ID", "YOUR_BLOG_ID_HERE")
SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_PATH = "token.json"
CLIENT_SECRET_PATH = "client_secret.json"
HISTORY_PATH = "post_history.json"   # remembers recent topics/titles
MAX_HISTORY_DAYS = 30
TOPIC_COOLDOWN_DAYS = 7
TITLE_SIMILARITY_BLOCK_DAYS = 30
TITLE_SIMILARITY_THRESHOLD = 80  # 0..100
POST_LABELS = ["Automated", "Editorial"]

ALLOWED_TOPICS = [
    "Personal Life and Stories",
    "Food and Recipes",
    "Travel",
    "How-To Guides and Tutorials",
    "Product Reviews",
    "Money and Finance",
    "Productivity",
    "Health and Fitness",
    "Fashion",
    "Lists and Roundups",
]

SEASONALITY = [
    "beginner",
    "advanced",
    "budget-friendly",
    "time-saving",
    "seasonal picks",
    "this week",
    "fresh ideas",
    "step-by-step",
    "expert tips",
]

AUDIENCES = [
    "students",
    "busy professionals",
    "parents",
    "solo travelers",
    "beginners",
    "creators",
    "remote workers",
]

TRENDS = [
    "2025 update",
    "new tools",
    "current best practices",
    "what’s working now",
    "latest insights",
]

# ====== OAUTH ======
def get_credentials() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds

# ====== BLOGGER API ======
API_BASE = "https://www.googleapis.com/blogger/v3"

def list_recent_posts(creds: Credentials, days: int = MAX_HISTORY_DAYS) -> List[Dict[str, Any]]:
    url = f"{API_BASE}/blogs/{BLOG_ID}/posts"
    headers = {"Authorization": f"Bearer {creds.token}"}
    params = {"maxResults": 50, "orderBy": "PUBLISHED"}
    posts = []
    while True:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        posts.extend(items)
        next_page = data.get("nextPageToken")
        if not next_page or len(posts) >= 200:
            break
        params["pageToken"] = next_page
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    filtered = []
    for p in posts:
        published = p.get("published")
        try:
            pub_dt = dt.datetime.fromisoformat(published.replace("Z", "+00:00"))
        except Exception:
            continue
        if pub_dt >= cutoff:
            filtered.append(p)
    return filtered

def create_blogger_post(creds: Credentials, title: str, html_content: str, labels: List[str]) -> Dict[str, Any]:
    url = f"{API_BASE}/blogs/{BLOG_ID}/posts/"
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }
    payload = {
        "kind": "blogger#post",
        "blog": {"id": BLOG_ID},
        "title": title,
        "content": html_content,
        "labels": labels,
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

# ====== HISTORY / FRESHNESS ======
def load_history() -> Dict[str, Any]:
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"posts": []}

def save_history(hist: Dict[str, Any]):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)

def prune_history(hist: Dict[str, Any]):
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=MAX_HISTORY_DAYS)
    keep = []
    for p in hist.get("posts", []):
        t = dt.datetime.fromisoformat(p["utc_published"])
        if t >= cutoff:
            keep.append(p)
    hist["posts"] = keep

def topic_blocked_recent(hist: Dict[str, Any], topic: str) -> bool:
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=TOPIC_COOLDOWN_DAYS)
    for p in hist.get("posts", []):
        if p["topic"] == topic:
            t = dt.datetime.fromisoformat(p["utc_published"])
            if t >= cutoff:
                return True
    return False

def title_too_similar(hist: Dict[str, Any], title: str) -> bool:
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=TITLE_SIMILARITY_BLOCK_DAYS)
    for p in hist.get("posts", []):
        t = dt.datetime.fromisoformat(p["utc_published"])
        if t >= cutoff:
            score = fuzz.token_sort_ratio(p["title"].lower(), title.lower())
            if score >= TITLE_SIMILARITY_THRESHOLD:
                return True
    return False

def pick_fresh_topic(hist: Dict[str, Any]) -> str:
    # rotate through topics but skip any blocked by cooldown
    for topic in ALLOWED_TOPICS:
        if not topic_blocked_recent(hist, topic):
            return topic
    # if all blocked, pick the one used longest ago
    last_used = {}
    for t in ALLOWED_TOPICS:
        last_used[t] = dt.datetime.min
    for p in hist.get("posts", []):
        if p["topic"] in ALLOWED_TOPICS:
            last_used[p["topic"]] = max(last_used[p["topic"]], dt.datetime.fromisoformat(p["utc_published"]))
    return sorted(last_used.items(), key=lambda x: x[11])

# ====== CONTENT GENERATION (NO LLM) ======
def generate_angle(topic: str) -> str:
    # Simple deterministic “fresh” angle using date + rotating modifiers
    today = dt.datetime.utcnow().date()
    seed = int(today.strftime("%Y%m%d"))
    idx1 = seed % len(SEASONALITY)
    idx2 = (seed // 3) % len(AUDIENCES)
    idx3 = (seed // 7) % len(TRENDS)
    return f"{SEASONALITY[idx1]} angle for {AUDIENCES[idx2]} with {TRENDS[idx3]}"

def make_title(topic: str, angle: str) -> str:
    core = topic.split(":")
    angle_bits = angle.replace("angle", "").strip()
    title = f"{core}: {angle_bits.title()}"
    # keep ~8–12 words by trimming if too long
    parts = title.split()
    if len(parts) > 12:
        title = " ".join(parts[:12])
    return title

def lorem_paragraphs(n=3) -> List[str]:
    base = [
        "This section explains the core ideas with clear, practical guidance.",
        "Each step is designed to be easy to follow and act on today.",
        "Where useful, examples illustrate the approach in real scenarios.",
        "Keep what works, adjust what doesn’t, and iterate with feedback.",
    ]
    out = []
    for i in range(n):
        p = " ".join(base[i % len(base):] + base[: i % len(base)])
        out.append(p)
    return out

def generate_markdown(topic: str, angle: str, title: str) -> str:
    date_str = dt.datetime.now().strftime("%B %d, %Y")
    # Enforce consistent headings and spacing; include image with credits
    feature_alt = f"{topic} — feature image"
    feature_url = "https://example.com/feature.jpg"
    feature_caption = "A representative visual for the topic."
    feature_credit = "Photo: Example Creator via Unsplash (Free license)"

    md_lines = []
    md_lines.append(f"# {title}")
    md_lines.append(f"By Automated Editorial · {date_str}")
    md_lines.append("")
    md_lines.append(f"<!-- Topic: {topic} | Angle: {angle} -->")
    md_lines.append("")
    md_lines.append("Meta Title: " + title[:58])
    md_lines.append("Meta Description: Practical, current insights with clear steps and examples.")
    md_lines.append("")
    md_lines.append(f"![{feature_alt}]({feature_url})")
    md_lines.append(f"_{feature_caption}_")
    md_lines.append(f"{feature_credit}")
    md_lines.append("")
    md_lines.append("## TL;DR")
    md_lines.append("- Key takeaways in a few bullets.")
    md_lines.append("- Actionable steps with simple examples.")
    md_lines.append("- Fresh angle aligned with current interests.")
    md_lines.append("")
    md_lines.append("## Introduction")
    for p in lorem_paragraphs(2):
        md_lines.append(p)
        md_lines.append("")
    md_lines.append("## Main Ideas")
    md_lines.append("### Idea One")
    for p in lorem_paragraphs(1):
        md_lines.append(p)
        md_lines.append("")
    md_lines.append("### Idea Two")
    for p in lorem_paragraphs(1):
        md_lines.append(p)
        md_lines.append("")
    md_lines.append("## Quick Checklist")
    md_lines.append("- Define the goal.")
    md_lines.append("- Prepare minimal tools.")
    md_lines.append("- Take the first small step.")
    md_lines.append("- Review the result and refine.")
    md_lines.append("")
    md_lines.append("## Conclusion")
    for p in lorem_paragraphs(1):
        md_lines.append(p)
        md_lines.append("")
    md_lines.append("> Enjoyed this read? Leave a comment and subscribe for three new posts every week.")
    md_lines.append("")
    return "\n".join(md_lines)

# ====== MARKDOWN TO HTML + TYPOGRAPHY CSS ======
BASE_CSS = """
<style>
:root {
  --font-body: system-ui, -apple-system, Segoe UI, Roboto, Inter, Arial, sans-serif;
}
article { max-width: 760px; margin: 0 auto; padding: 24px; color: #111; }
article, article p { font-family: var(--font-body); font-size: 17px; line-height: 1.68; }
article h1 { font-size: 34px; line-height: 1.25; margin: 40px 0 12px; }
article h2 { font-size: 26px; line-height: 1.3; margin: 36px 0 10px; }
article h3 { font-size: 19px; line-height: 1.35; margin: 28px 0 8px; }
article p { margin: 0 0 14px; }
article ul, article ol { margin: 0 0 16px 20px; }
article li { margin: 6px 0; }
article img { width: 100%; height: auto; border-radius: 6px; }
article figure { margin: 0 0 14px; }
article figcaption { font-size: 14px; color: #555; margin-top: 6px; font-style: italic; }
article .credit { font-size: 13px; color: #666; }
hr { border: none; border-top: 1px solid #eee; margin: 24px 0; }
blockquote { border-left: 3px solid #ddd; padding-left: 12px; color: #444; margin: 16px 0; }
</style>
"""

def markdown_with_figure(md: str) -> str:
    """
    Convert Markdown to HTML and wrap the first image block in <figure><img/><figcaption/><small class="credit"></small></figure>.
    Expects pattern:
    ![alt](url)
    _caption_
    Photo: credit line
    """
    lines = md.splitlines()
    out = []
    i = 0
    used_figure = False
    while i < len(lines):
        line = lines[i]
        if (not used_figure) and line.strip().startswith("![") and "](" in line:
            alt = line[line.index("![")+2: line.index("](")]
            url = line[line.index("](")+2:].rstrip(")")
            cap = ""
            cred = ""
            if i + 1 < len(lines) and lines[i+1].strip().startswith("_") and lines[i+1].strip().endswith("_"):
                cap = lines[i+1].strip().strip("_")
                i += 1
            if i + 1 < len(lines) and lines[i+1].strip().lower().startswith("photo:"):
                cred = lines[i+1].strip()
                i += 1
            fig_html = f'<figure><img src="{url}" alt="{alt}"/>' \
                       f'<figcaption>{cap}</figcaption>' \
                       f'<div class="credit">{cred}</div></figure>'
            out.append(fig_html)
            used_figure = True
        else:
            out.append(line)
        i += 1
    html_body = markdown.markdown("\n".join(out), extensions=["extra", "sane_lists"])
    return f"{BASE_CSS}<article>{html_body}</article>"

# ====== MAIN ======
def main():
    creds = get_credentials()
    # Load and refresh local history
    hist = load_history()
    prune_history(hist)

    # Fetch recent from Blogger and add to local history (titles + topics from content comment)
    recent = list_recent_posts(creds, days=MAX_HISTORY_DAYS)
    # Try to parse <!-- Topic: ... | Angle: ... -->
    for p in recent:
        content = p.get("content", "")
        title = p.get("title", "")
        pub = p.get("published")
        try:
            utc_published = dt.datetime.fromisoformat(pub.replace("Z", "+00:00")).isoformat()
        except Exception:
            continue
        topic = None
        if "<!-- Topic:" in content:
            # naive parse
            try:
                frag = content.split("<!-- Topic:", 1)[11]
                topic = frag.split("|", 1).strip()
            except Exception:
                topic = None
        hist["posts"].append({
            "title": title,
            "topic": topic or "",
            "utc_published": utc_published
        })

    prune_history(hist)
    # Pick a fresh topic and angle
    attempt = 0
    while True:
        attempt += 1
        topic = pick_fresh_topic(hist)
        angle = generate_angle(topic)
        title = make_title(topic, angle)
        if not topic_blocked_recent(hist, topic) and not title_too_similar(hist, title):
            break
        if attempt > len(ALLOWED_TOPICS) + 5:
            # give up similarity and proceed with least conflict
            break

    md = generate_markdown(topic, angle, title)
    html = markdown_with_figure(md)

    # Create post
    post = create_blogger_post(creds, title, html, POST_LABELS)

    # Save to local history
    hist["posts"].append({
        "title": title,
        "topic": topic,
        "utc_published": dt.datetime.utcnow().isoformat()
    })
    prune_history(hist)
    save_history(hist)

    print("Posted:", post.get("url"))

if __name__ == "__main__":
    main()
