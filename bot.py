import os
import json
import datetime as dt
from typing import List, Dict, Any
import requests
from slugify import slugify
from rapidfuzz import fuzz
import markdown
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ====== CONFIG ======
BLOG_ID = os.getenv("BLOGGER_BLOG_ID", "YOUR_BLOG_ID_HERE")
SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_PATH = "token.json"
HISTORY_PATH = "post_history.json"
MAX_HISTORY_DAYS = 30
TOPIC_COOLDOWN_DAYS = 7
TITLE_SIMILARITY_BLOCK_DAYS = 30
TITLE_SIMILARITY_THRESHOLD = 80
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
    if not os.path.exists(TOKEN_PATH):
        raise RuntimeError("Missing token.json for Blogger API credentials.")
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
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
        if not published:
            continue
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

# ====== HISTORY ======
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
        try:
            t = dt.datetime.fromisoformat(p["utc_published"])
        except Exception:
            continue
        if t >= cutoff:
            keep.append(p)
    hist["posts"] = keep

def topic_blocked_recent(hist: Dict[str, Any], topic: str) -> bool:
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=TOPIC_COOLDOWN_DAYS)
    for p in hist.get("posts", []):
        if p["topic"] == topic:
            try:
                t = dt.datetime.fromisoformat(p["utc_published"])
                if t >= cutoff:
                    return True
            except Exception:
                continue
    return False

def title_too_similar(hist: Dict[str, Any], title: str) -> bool:
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=TITLE_SIMILARITY_BLOCK_DAYS)
    for p in hist.get("posts", []):
        try:
            t = dt.datetime.fromisoformat(p["utc_published"])
        except Exception:
            continue
        if t >= cutoff:
            score = fuzz.token_sort_ratio(p["title"].lower(), title.lower())
            if score >= TITLE_SIMILARITY_THRESHOLD:
                return True
    return False

def pick_fresh_topic(hist: Dict[str, Any]) -> str:
    for topic in ALLOWED_TOPICS:
        if not topic_blocked_recent(hist, topic):
            return topic
    last_used = {t: dt.datetime.min for t in ALLOWED_TOPICS}
    for p in hist.get("posts", []):
        if p["topic"] in ALLOWED_TOPICS:
            try:
                last_used[p["topic"]] = max(last_used[p["topic"]], dt.datetime.fromisoformat(p["utc_published"]))
            except Exception:
                continue
    return sorted(last_used.items(), key=lambda x: x[1])[0][0]

# ====== CONTENT GENERATION ======
def generate_angle(topic: str) -> str:
    today = dt.datetime.utcnow().date()
    seed = int(today.strftime("%Y%m%d"))
    idx1 = seed % len(SEASONALITY)
    idx2 = (seed // 3) % len(AUDIENCES)
    idx3 = (seed // 7) % len(TRENDS)
    return f"{SEASONALITY[idx1]} angle for {AUDIENCES[idx2]} with {TRENDS[idx3]}"

def make_title(topic: str, angle: str) -> str:
    core = topic.split(":")[0]
    angle_bits = angle.replace("angle", "").strip()
    title = f"{core}: {angle_bits.title()}"
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
    feature_alt = f"{topic} — feature image"
    feature_url = "https://example.com/feature.jpg"
    feature_caption = "A representative visual for the topic."
    feature_credit = "Photo: Example Creator via Unsplash (Free license)"

    md_lines = [
        f"# {title}",
        f"By Automated Editorial · {date_str}",
        "",
        f"<!-- Topic: {topic} | Angle: {angle} -->",
        "",
        "Meta Title: " + title[:58],
        "Meta Description: Practical, current insights with clear steps and examples.",
        "",
        f"![{feature_alt}]({feature_url})",
        f"_{feature_caption}_",
        f"{feature_credit}",
        "",
        "## TL;DR",
        "- Key takeaways in a few bullets.",
        "- Actionable steps with simple examples.",
        "- Fresh angle aligned with current interests.",
        "",
        "## Introduction",
    ]
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
    md_lines.extend([
        "- Define the goal.",
        "- Prepare minimal tools.",
        "- Take the first small step.",
        "- Review the result and refine.",
        "",
        "## Conclusion",
    ])
    for p in lorem_paragraphs(1):
        md_lines.append(p)
        md_lines.append("")
    md_lines.append("> Enjoyed this read? Leave a comment and subscribe for three new posts every week.")
    return "\n".join(md_lines)

BASE_CSS = """<style> ... </style>"""  # unchanged

def markdown_with_figure(md: str) -> str:
    lines = md.splitlines()
    out, i, used_figure = [], 0, False
    while i < len(lines):
        line = lines[i]
        if (not used_figure) and line.strip().startswith("![") and "](" in line:
            alt = line[line.index("![")+2: line.index("](")]
            url = line[line.index("](")+2:].rstrip(")")
            cap, cred = "", ""
            if i+1 < len(lines) and lines[i+1].strip().startswith("_") and lines[i+1].strip().endswith("_"):
                cap = lines[i+1].strip().strip("_")
                i += 1
            if i+1 < len(lines) and lines[i+1].strip().lower().startswith("photo:"):
                cred = lines[i+1].strip()
                i += 1
            fig_html = f'<figure><img src="{url}" alt="{alt}"/><figcaption>{cap}</figcaption><div class="credit">{cred}</div></figure>'
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
    hist = load_history()
    prune_history(hist)

    recent = list_recent_posts(creds, days=MAX_HISTORY_DAYS)
    for p in recent:
        content = p.get("content", "")
        title = p.get("title", "")
        pub = p.get("published")
        if not pub:
            continue
        try:
            utc_published = dt.datetime.fromisoformat(pub.replace("Z", "+00:00")).isoformat()
        except Exception:
            continue
        topic = ""
        if "<!-- Topic:" in content:
            try:
                frag = content.split("<!-- Topic:", 1)[1]
                topic = frag.split("|", 1)[0].strip()
            except Exception:
                topic = ""
        hist["posts"].append({
            "title": title,
            "topic": topic,
            "utc_published": utc_published
        })

    prune_history(hist)

    attempt = 0
    while True:
        attempt += 1
        topic = pick_fresh_topic(hist)
        angle = generate_angle(topic)
        title = make_title(topic, angle)
        if not topic_blocked_recent(hist, topic) and not title_too_similar(hist, title):
            break
        if attempt > len(ALLOWED_TOPICS) + 5:
            break

    md = generate_markdown(topic, angle, title)
    html = markdown_with_figure(md)

    post = create_blogger_post(creds, title, html, POST_LABELS)

    hist["posts"].append({
        "title": title,
        "topic": topic,
        "utc_published": dt.datetime.utcnow().isoformat()
    })
    prune_history(hist)
    save_history(hist)

    print("✅ Posted:", post.get("url"))

if __name__ == "__main__":
    main()
