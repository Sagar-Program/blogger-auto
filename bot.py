#!/usr/bin/env python3
import os, sys, json, re, html, datetime as dt, random
import requests
from urllib.parse import urlencode

# Secrets
BLOG_ID = os.environ.get("BLOG_ID", "").strip()
CLIENT_ID = os.environ.get("CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN", "").strip()

# Options
PUBLISH_IMMEDIATELY = os.environ.get("PUBLISH_IMMEDIATELY", "true").lower() == "true"
BLOG_TIMEZONE = os.environ.get("BLOG_TIMEZONE", "Asia/Kolkata")

CATEGORY_ROTATION = [
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
MAX_SIMILARITY = 0.8
TITLE_FALLBACK_SUFFIXES = [" Guide", " Essentials", " Explained", " In Practice"]

def require_env():
    for var, val in [("BLOG_ID", BLOG_ID), ("CLIENT_ID", CLIENT_ID), ("CLIENT_SECRET", CLIENT_SECRET), ("REFRESH_TOKEN", REFRESH_TOKEN)]:
        if not val:
            print(f"Missing required secret: {var}", file=sys.stderr)
            sys.exit(1)

def get_access_token() -> str:
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

def blogger_get_recent_posts(access_token: str, blog_id: str, days: int = 30, max_results: int = 50):
    base = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts"
    params = {"orderBy": "published", "fetchBodies": False, "maxResults": max_results}
    headers = {"Authorization": f"Bearer {access_token}"}
    posts, url = [], f"{base}?{urlencode(params)}"
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        posts.extend(data.get("items", []))
        nxt = data.get("nextPageToken")
        url = f"{base}?{urlencode({**params, 'pageToken': nxt})}" if nxt else None
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    filtered = []
    for p in posts:
        pub = p.get("published")
        try:
            pub_dt = dt.datetime.fromisoformat(pub.replace("Z", "+00:00"))
            if pub_dt >= cutoff:
                filtered.append(p)
        except Exception:
            pass
    return filtered

def blogger_insert_post(access_token: str, blog_id: str, title: str, html_content: str, labels, is_draft: bool):
    url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/"
    params = {"isDraft": str(is_draft).lower()}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    body = {"kind": "blogger#post", "title": title, "content": html_content, "labels": labels or []}
    r = requests.post(f"{url}?{urlencode(params)}", headers=headers, data=json.dumps(body), timeout=60)
    r.raise_for_status()
    return r.json()

def _norm_title(t: str):
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return [w for w in t.split() if len(w) > 2]

def _jaccard(a: str, b: str) -> float:
    A, B = set(_norm_title(a)), set(_norm_title(b))
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)

def title_is_duplicate(new_title: str, recent_titles):
    for t in recent_titles:
        if new_title.strip().lower() == t.strip().lower():
            return True
        if _jaccard(new_title, t) >= MAX_SIMILARITY:
            return True
    return False

def last_used_category(recent_posts):
    for p in recent_posts:
        labels = p.get("labels", []) or []
        for lab in labels:
            if lab in CATEGORY_ROTATION:
                return lab
    return None

def next_category(recent_posts):
    last_cat = last_used_category(recent_posts)
    if last_cat and last_cat in CATEGORY_ROTATION:
        idx = CATEGORY_ROTATION.index(last_cat)
        return CATEGORY_ROTATION[(idx + 1) % len(CATEGORY_ROTATION)]
    return CATEGORY_ROTATION

def category_used_in_days(cat, recent_posts, days=7):
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    for p in recent_posts:
        labels = p.get("labels", []) or []
        if cat in labels:
            try:
                pub_dt = dt.datetime.fromisoformat(p["published"].replace("Z", "+00:00"))
                if pub_dt >= cutoff:
                    return True
            except Exception:
                pass
    return False

def clamp_words(s, minw=8, maxw=14):
    words = s.split()
    if len(words) < minw:
        while len(words) < minw:
            words.append("Guide")
    if len(words) > maxw:
        words = words[:maxw]
    return " ".join(words)

def build_title_for_category(cat: str) -> str:
    presets = {
        "Personal Life and Stories": "Small Wins That Quietly Transform Busy Weeks",
        "Food and Recipes": "A Weeknight Paneer Stir-Fry You Can Master Fast",
        "Travel": "A 48-Hour Itinerary For Monsoon Goa That Works",
        "How-To Guides and Tutorials": "A Practical Framework To Reach Inbox Zero This Week",
        "Product Reviews": "Hands-On Test Of Budget ANC Headphones—Worth It?",
        "Money and Finance": "A Simple Plan To Cut Monthly Bills Without Pain",
        "Productivity": "Beat Afternoon Slumps With A 20-Minute Reset",
        "Health and Fitness": "A Beginner’s Mobility Routine You’ll Actually Keep",
        "Fashion": "Late-Monsoon Wardrobe: Seven Picks That Make Sense",
        "Lists and Roundups": "Nine Free Tools To Automate Repetitive Daily Tasks",
    }
    base = presets.get(cat, f"Fresh Notes On {cat}")
    return clamp_words(base, 8, 14)

def make_html_post(topic_category):
    topic_key = ", ".join(topic_category) if isinstance(topic_category, list) else str(topic_category)
    title = build_title_for_category(topic_key)
    today = dt.datetime.now().strftime("%Y-%m-%d")
    meta_desc = "Clear steps, examples, visuals, and a checklist—readable in minutes with bolded key actions and simple language."

    # Images
    feature_img_url = "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?w=1200&q=80"
    inline_img_url = "https://images.unsplash.com/photo-1496307042754-b4aa456c4a2d?w=1200&q=80"

    # Key Takeaways (scannable near the top)
    key_takeaways = """
<ul>
  <li><strong>Visible outcome:</strong> Write one clear result for today.</li>
  <li><strong>Short work blocks:</strong> 20–40 minutes beats long, unfocused sessions.</li>
  <li><strong>Always end with a next action:</strong> Reduce friction for tomorrow.</li>
</ul>
"""

    intro = f"""
<h2>Introduction</h2>
<p>Big plans fail when they’re vague and heavy. This guide shows a simple way to make steady progress in {html.escape(topic_key.lower())} with shorter paragraphs, bolded actions, and quick visuals. It’s designed for busy readers who skim first, then dive deeper.</p>
<p>You’ll see a practical workflow, concrete examples, a checklist, and a brief look ahead—so the next 20 minutes lead to real momentum.</p>
<p><strong>Key takeaways:</strong></p>
{key_takeaways}
"""

    hero = f"""
<img src="{feature_img_url}" alt="Context image framing the topic in a simple, calm style" />
<p><em>A contextual visual that frames the topic without distractions.</em></p>
<p><small>Photo: Unsplash (CC0/Link)</small></p>
"""

    history = """
<h2>Brief History</h2>
<h3>From ad-hoc to simple loops</h3>
<p>People used to rely on motivation alone. Over time, small loops—state outcome, work briefly, write next action—proved more reliable. These ideas now power most practical frameworks.</p>
<ul>
  <li>Less setup, more doing.</li>
  <li>Shared language and defaults lower friction.</li>
  <li>Fewer surprises, easier handoffs.</li>
</ul>
"""

    components = f"""
<h2>Core Components</h2>
<h3>What matters most</h3>
<ul>
  <li><strong>Outcome sentence:</strong> One line that defines success for today.</li>
  <li><strong>Time box:</strong> A focused 20–40 minute block; split tasks to fit.</li>
  <li><strong>Feedback loop:</strong> End with a written next action and one metric.</li>
</ul>
<p><em>Example ({html.escape(topic_key)}):</em> “Draft the outline with three subheads, 30 minutes. Next: add examples.”</p>
"""

    visuals = """
<h2>Visuals That Help</h2>
<ul>
  <li><strong>Simple diagram:</strong> Outcome → Focused Block → Next Action → Repeat</li>
  <li><strong>Infographic:</strong> 3 advantages, 3 pitfalls, 3 fixes</li>
</ul>
<blockquote><strong>Pro tip:</strong> Keep visuals lightweight and fast-loading; clarity beats ornament.</blockquote>
"""

    second_img = f"""
<img src="{inline_img_url}" alt="Diagram-like visual showing a small outcome–action loop" />
<p><em>A minimal loop: outcome → short block → next action → repeat.</em></p>
<p><small>Photo: Unsplash (CC0/Link)</small></p>
"""

    examples = f"""
<h2>Real Examples</h2>
<h3>Personal</h3>
<ul>
  <li><strong>Outcome:</strong> Declutter one shelf. <strong>Block:</strong> 20 minutes. <strong>Next:</strong> Donate box tomorrow.</li>
</ul>
<h3>Work</h3>
<ul>
  <li><strong>Outcome:</strong> Draft intro section. <strong>Block:</strong> 25 minutes. <strong>Next:</strong> Add two examples.</li>
</ul>
<h3>Travel</h3>
<ul>
  <li><strong>Outcome:</strong> Pick stays for 2 nights. <strong>Block:</strong> 20 minutes. <strong>Next:</strong> Save two backups.</li>
</ul>
"""

    simplify = """
<h2>Simplify The Language</h2>
<ul>
  <li>Avoid jargon; define terms on first use.</li>
  <li>Prefer short sentences. Aim for 12–18 words.</li>
  <li>Bold key actions so skimmers can act fast.</li>
</ul>
"""

    callouts = """
<h2>Callouts</h2>
<blockquote><strong>Pro tip:</strong> If energy is low, pick a 10-minute “starter task” to reduce resistance.</blockquote>
<blockquote><strong>Common mistake:</strong> Working too long. Small blocks beat marathon sessions for consistency.</blockquote>
"""

    checklist = """
<h2>Checklist</h2>
<ul>
  <li><strong>Outcome written</strong> (one sentence)</li>
  <li><strong>Time box set</strong> (20–40 minutes)</li>
  <li><strong>Task sized to fit</strong></li>
  <li><strong>Next action noted</strong></li>
  <li><strong>One metric tracked</strong> (count, minutes, attempts)</li>
</ul>
"""

    conclusion = """
<h2>Conclusion</h2>
<p>Simple structure wins: outcome, short block, next action. Add one visual, keep sentences short, and use a checklist to verify progress. Do this for a week; review once; adjust the block size if needed.</p>
<p><strong>Enjoyed this? Leave a comment with your thoughts or questions.</strong></p>
<p><strong>Love practical reads like this? Follow the blog for three new posts every week.</strong></p>
"""

    h1 = f"<h1>{html.escape(title)}</h1>"
    byline = f"<p><em>By Automation Bot • {today}</em></p>"
    meta = f"<!-- Meta Description: {html.escape(meta_desc)} -->"

    body = "\n".join([
        meta, h1, byline, intro, hero,
        history, components, visuals, second_img,
        examples, simplify, callouts, checklist, conclusion
    ])

    labels = [topic_key]
    return title, body, labels

def main():
    require_env()
    token = get_access_token()
    recent = blogger_get_recent_posts(token, BLOG_ID, days=30, max_results=50)
    recent_titles = [p.get("title", "") for p in recent if p.get("title")]

    cat = next_category(recent)
    spins = 0
    while category_used_in_days(cat, recent, days=7) and spins < len(CATEGORY_ROTATION):
        idx = (CATEGORY_ROTATION.index(cat) + 1) % len(CATEGORY_ROTATION)
        cat = CATEGORY_ROTATION[idx]; spins += 1

    title, html_content, labels = make_html_post(cat)
    if title_is_duplicate(title, recent_titles):
        title = title + random.choice(TITLE_FALLBACK_SUFFIXES)

    post = blogger_insert_post(token, BLOG_ID, title, html_content, labels, is_draft=not PUBLISH_IMMEDIATELY)
    print(json.dumps({"postedId": post.get("id"), "url": post.get("url"), "title": post.get("title"), "labels": labels}, indent=2))

if __name__ == "__main__":
    main()
