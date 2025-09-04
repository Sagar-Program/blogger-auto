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
import google.generativeai as genai
import pytz

# ====== CONFIG ======
BLOG_ID = os.getenv("BLOGGER_BLOG_ID")
SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_PATH = "token.json"
HISTORY_PATH = "post_history.json"
MAX_HISTORY_DAYS = 30
TOPIC_COOLDOWN_DAYS = 7
TITLE_SIMILARITY_BLOCK_DAYS = 30
TITLE_SIMILARITY_THRESHOLD = 65
POST_LABELS = ["Automated", "AI-Generated"]
BLOG_TZ = pytz.timezone(os.getenv("BLOG_TIMEZONE", "Asia/Kolkata"))
TODAY_10AM = dt.datetime.now(BLOG_TZ).replace(hour=10, minute=0, second=0, microsecond=0)

ALLOWED_TOPICS = [
    "Personal Life and Stories", "Food and Recipes", "Travel",
    "How-To Guides and Tutorials", "Product Reviews", "Money and Finance",
    "Productivity", "Health and Fitness", "Fashion", "Lists and Roundups",
]

# ====== GEMINI CLIENT ======
def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set.")
    genai.configure(api_key=api_key)
    return genai

def generate_blog_post_with_gemini(topic: str, angle: str, history_titles: List[str]) -> Dict[str, str]:
    """
    Calls the Gemini API to generate a full blog post based on the master prompt.
    Returns a dict with 'title', 'content_md', 'meta_title', 'meta_description'.
    """
    client = get_gemini_client()
    model = client.GenerativeModel('gemini-1.5-flash')

    system_prompt = f"""You are an expert blog writer and content formatter for an automated Blogger site. Generate fully formatted Markdown posts. Never repeat the same topic or near-duplicate title. Proactively source fresh, relevant angles so each post feels timely and useful.

    Topic for this post: {topic}
    Chosen angle: {angle}

    Freshness and variety rules:
    - Avoid these recent titles: {history_titles[-10:]}
    - No duplicate topics within 7 days.
    - Avoid near-duplicate titles within 30 days.

    Follow all formatting, structure, SEO, and style rules from the master prompt precisely.
    Output ONLY the raw Markdown text, ready to be published.
    """

    try:
        response = model.generate_content(system_prompt + f"Generate a fresh, detailed blog post about {topic} from this angle: {angle}.")
        generated_content = response.text

        lines = generated_content.strip().split('\n')
        title = lines[0].replace('#', '').strip() if lines[0].startswith('#') else "Generated Blog Post"
        
        meta_title, meta_description = "", ""
        for i, line in enumerate(lines):
            if line.lower().startswith("meta title:"):
                meta_title = line.split(":", 1)[1].strip()
            elif line.lower().startswith("meta description:"):
                meta_description = line.split(":", 1)[1].strip()

        return {
            "title": title,
            "content_md": generated_content,
            "meta_title": meta_title or title[:60],
            "meta_description": meta_description or "A practical guide with actionable insights."
        }

    except Exception as e:
        print(f"❌ Gemini API error: {e}")
        return {
            "title": f"{topic}: Fallback Post",
            "content_md": f"# {topic}: Fallback Post\n\nThis is a fallback post. The AI content generator encountered an error: {e}",
            "meta_title": f"{topic}: Fallback Post",
            "meta_description": "A fallback post."
        }

# ====== SIMPLIFIED OAUTH ======
def get_credentials() -> Credentials:
    if not os.path.exists(TOKEN_PATH):
        raise RuntimeError("Missing token.json. Please set the TOKEN_JSON secret in GitHub.")
    
    with open(TOKEN_PATH, 'r') as f:
        token_data = json.load(f)

    creds = Credentials(
        token=token_data.get('token'),
        refresh_token=token_data.get('refresh_token'),
        token_uri=token_data.get('token_uri'),
        client_id=token_data.get('client_id'),
        client_secret=token_data.get('client_secret'),
        scopes=token_data.get('scopes')
    )

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return creds

# ====== BLOGGER API ======
API_BASE = "https://www.googleapis.com/blogger/v3"

def list_recent_posts(creds: Credentials, max_results: int = 50) -> List[Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {creds.token}"}
    params = {"maxResults": max_results, "orderBy": "PUBLISHED"}
    all_posts = []
    url = f"{API_BASE}/blogs/{BLOG_ID}/posts"

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        all_posts.extend(data.get("items", []))
    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching posts: {e}")
    return all_posts

def create_blogger_post(creds: Credentials, title: str, html_content: str, labels: List[str], publish_time: dt.datetime = None) -> Dict[str, Any]:
    url = f"{API_BASE}/blogs/{BLOG_ID}/posts/"
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }

    publish_time_rfc3339 = None
    if publish_time:
        publish_time_utc = publish_time.astimezone(pytz.utc)
        publish_time_rfc3339 = publish_time_utc.isoformat()

    payload = {
        "kind": "blogger#post",
        "blog": {"id": BLOG_ID},
        "title": title,
        "content": html_content,
        "labels": labels,
    }
    if publish_time_rfc3339:
        payload["published"] = publish_time_rfc3339

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Error creating post: {e}")
        raise

# ====== HISTORY & FRESHNESS LOGIC ======
def load_history() -> Dict[str, Any]:
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {"posts": []}
    return {"posts": []}

def save_history(history: Dict[str, Any]):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def update_history_from_blog(creds: Credentials, history: Dict[str, Any]):
    recent_posts = list_recent_posts(creds, max_results=50)
    cutoff = dt.datetime.now(pytz.utc) - dt.timedelta(days=MAX_HISTORY_DAYS)

    for post in recent_posts:
        title = post.get("title", "")
        published_str = post.get("published", "")
        content = post.get("content", "")

        topic = "Unknown"
        if "<!-- Topic:" in content:
            try:
                topic_line = content.split("<!-- Topic:")[1].split("-->")[0].strip()
                topic = topic_line.split("|")[0].strip()
            except IndexError:
                pass

        try:
            published_dt = dt.datetime.fromisoformat(published_str.replace('Z', '+00:00'))
            if published_dt < cutoff:
                continue
            published_utc_str = published_dt.isoformat()
        except (ValueError, AttributeError):
            published_utc_str = dt.datetime.now(pytz.utc).isoformat()

        post_exists = any(p.get("title") == title and p.get("utc_published") == published_utc_str for p in history["posts"])
        if not post_exists:
            history["posts"].append({
                "title": title,
                "topic": topic,
                "utc_published": published_utc_str
            })
    prune_history(history)

def prune_history(history: Dict[str, Any]):
    if "posts" not in history:
        history["posts"] = []
        return

    cutoff = dt.datetime.now(pytz.utc) - dt.timedelta(days=MAX_HISTORY_DAYS)
    history["posts"] = [
        p for p in history["posts"]
        if dt.datetime.fromisoformat(p["utc_published"]).replace(tzinfo=pytz.utc) >= cutoff
    ]

def is_topic_on_cooldown(history: Dict[str, Any], topic: str, cooldown_days: int = TOPIC_COOLDOWN_DAYS) -> bool:
    cutoff = dt.datetime.now(pytz.utc) - dt.timedelta(days=cooldown_days)
    for post in history.get("posts", []):
        if post.get("topic") == topic:
            try:
                post_time = dt.datetime.fromisoformat(post["utc_published"]).replace(tzinfo=pytz.utc)
                if post_time >= cutoff:
                    return True
            except (KeyError, ValueError):
                continue
    return False

def is_title_too_similar(history: Dict[str, Any], new_title: str, threshold: int = TITLE_SIMILARITY_THRESHOLD, block_days: int = TITLE_SIMILARITY_BLOCK_DAYS) -> bool:
    """Checks if a new title is too similar to recent posts."""
    cutoff = dt.datetime.now(pytz.utc) - dt.timedelta(days=block_days)
    for post in history.get("posts", []):
        try:
            post_time = dt.datetime.fromisoformat(post["utc_published"]).replace(tzinfo=pytz.utc)
            if post_time >= cutoff:
                similarity = fuzz.token_sort_ratio(new_title.lower(), post["title"].lower())
                # ADD DEBUG INFO HERE:
                if similarity >= threshold:
                    print(f"🔍 DEBUG: Title '{new_title}' is {similarity}% similar to '{post['title']}' (block threshold: {threshold}%)")
                    return True
                else:
                    print(f"🔍 DEBUG: Title '{new_title}' is {similarity}% similar to '{post['title']}' (OK)")
        except (KeyError, ValueError):
            continue
    return False
    cutoff = dt.datetime.now(pytz.utc) - dt.timedelta(days=block_days)
    for post in history.get("posts", []):
        try:
            post_time = dt.datetime.fromisoformat(post["utc_published"]).replace(tzinfo=pytz.utc)
            if post_time >= cutoff:
                similarity = fuzz.token_sort_ratio(new_title.lower(), post["title"].lower())
                if similarity >= threshold:
                    return True
        except (KeyError, ValueError):
            continue
    return False

def select_fresh_topic(history: Dict[str, Any]) -> str:
    available_topics = [t for t in ALLOWED_TOPICS if not is_topic_on_cooldown(history, t)]
    if available_topics:
        return available_topics[0]

    topic_last_used = {}
    for topic in ALLOWED_TOPICS:
        last_used = dt.datetime.min.replace(tzinfo=pytz.utc)
        for post in history["posts"]:
            if post["topic"] == topic:
                try:
                    post_time = dt.datetime.fromisoformat(post["utc_published"]).replace(tzinfo=pytz.utc)
                    if post_time > last_used:
                        last_used = post_time
                except (KeyError, ValueError):
                    pass
        topic_last_used[topic] = last_used
    return min(topic_last_used.items(), key=lambda x: x[1])[0]

def generate_fresh_angle(topic: str) -> str:
    seed = hash(f"{dt.date.today()}{topic}") % (10 ** 8)
    angles = [
        f"A beginner's guide to {topic}",
        f"Advanced techniques for {topic} in 2025",
        f"Budget-friendly tips for {topic}",
        f"How to save time with {topic}",
        f"The ultimate seasonal guide to {topic}",
        f"This week's best ideas for {topic}",
        f"Unexpected ways to master {topic}",
        f"A step-by-step tutorial on {topic}",
        f"Expert secrets for better {topic}",
    ]
    return angles[seed % len(angles)]

# ====== MARKDOWN TO HTML CONVERSION ======
BASE_CSS = """
<style>
article {
    max-width: 700px;
    margin: 0 auto;
    line-height: 1.6;
    font-size: 18px;
    color: #333;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
}
article h1 {
    font-size: 32px;
    margin-top: 1.5em;
    margin-bottom: 0.5em;
}
article h2 {
    font-size: 24px;
    margin-top: 1.5em;
    margin-bottom: 0.5em;
}
article h3 {
    font-size: 20px;
    margin-top: 1.5em;
    margin-bottom: 0.5em;
}
article img {
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    margin: 1.5em 0;
}
article figure {
    margin: 2em 0;
    text-align: center;
}
article figcaption {
    font-style: italic;
    margin-top: 0.5em;
    color: #666;
    font-size: 0.9em;
}
article .credit {
    font-size: 0.8em;
    color: #999;
    margin-top: 0.25em;
}
</style>
"""

def convert_markdown_to_html(markdown_text: str) -> str:
    html_content = markdown.markdown(markdown_text, extensions=['extra', 'sane_lists'])
    return f"{BASE_CSS}\n<article>\n{html_content}\n</article>"

# ====== MAIN EXECUTION ======
def main():
    print("🤖 Starting Blogger AutoPost...")
    
    try:
        creds = get_credentials()
        print("🔍 DEBUG: Got credentials successfully")
        print("🔍 DEBUG: Token:", creds.token[:20] + "..." if creds.token else "None")
    except Exception as e:
        print(f"❌ Failed to get credentials: {e}")
        return

    history = load_history()
    print("📖 Loaded local history.")
    
    try:
        update_history_from_blog(creds, history)
        print("🔄 Updated history from live blog.")
    except Exception as e:
        print(f"⚠️  Could not update history from blog: {e}. Using local history only.")

    prune_history(history)
    recent_titles = [p["title"] for p in history["posts"]]

    selected_topic = select_fresh_topic(history)
    selected_angle = generate_fresh_angle(selected_topic)
    print(f"🎯 Selected Topic: {selected_topic}")
    print(f"🎯 Selected Angle: {selected_angle}")

    print("🧠 Generating content with Gemini...")
    generated_post = generate_blog_post_with_gemini(selected_topic, selected_angle, recent_titles)
    post_title = generated_post["title"]
    post_markdown = generated_post["content_md"]

    if is_title_too_similar(history, post_title):
        print(f"⚠️  Generated title too similar to recent posts: '{post_title}'. Aborting.")
        return

    print("⚙️ Converting Markdown to HTML...")
    post_html = convert_markdown_to_html(post_markdown)

    publish_immediately = os.getenv("PUBLISH_IMMEDIATELY", "false").lower() == "true"
    publish_time = None if publish_immediately else TODAY_10AM

    # DEBUG: Add debug information
    print("🔍 DEBUG: Generated Title:", post_title)
    print("🔍 DEBUG: HTML Content Length:", len(post_html))
    print("🔍 DEBUG: Publish Time:", publish_time)
    print("🔍 DEBUG: Blog ID:", BLOG_ID)
    
    # Test if we can at least LIST posts successfully
    try:
        test_posts = list_recent_posts(creds, max_results=1)
        print("🔍 DEBUG: Can list posts?", "Yes" if test_posts else "No")
        if test_posts:
            print("🔍 DEBUG: Latest post title:", test_posts[0].get('title', 'Unknown'))
    except Exception as e:
        print(f"🔍 DEBUG: Error listing posts: {e}")

    print("📤 Publishing post...")
    try:
        result = create_blogger_post(creds, post_title, post_html, POST_LABELS, publish_time)
        post_url = result.get('url', 'Unknown URL')
        print(f"✅ Success! Post published: {post_url}")
        
        history["posts"].append({
            "title": post_title,
            "topic": selected_topic,
            "utc_published": dt.datetime.now(pytz.utc).isoformat()
        })
        prune_history(history)
        save_history(history)
        print("💾 History saved.")

    except Exception as e:
        print(f"❌ Failed to publish post: {e}")
        # Additional debug for publish error
        print("🔍 DEBUG: Full error details:", str(e))

if __name__ == "__main__":
    main()
