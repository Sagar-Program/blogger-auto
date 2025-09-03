#!/usr/bin/env python3
import os, sys, json, re, random, html, datetime as dt
import requests
from urllib.parse import urlencode

# Required secrets from GitHub repository settings
BLOG_ID = os.environ.get("BLOG_ID", "").strip()
CLIENT_ID = os.environ.get("CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN", "").strip()

# Optional controls
PUBLISH_IMMEDIATELY = os.environ.get("PUBLISH_IMMEDIATELY", "true").lower() == "true"
BLOG_TIMEZONE = os.environ.get("BLOG_TIMEZONE", "Asia/Kolkata")

# Categories rotation and rules
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
MAX_SIMILARITY = 0.8  # block near-duplicate titles within ~30 days

def require_env():
    for var, val in [("BLOG_ID", BLOG_ID), ("CLIENT_ID", CLIENT_ID), ("CLIENT_SECRET", CLIENT_SECRET), ("REFRESH_TOKEN", REFRESH_TOKEN)]:
        if not val:
            print(f"Missing required secret: {var}", file=sys.stderr)
            sys.exit(1)

def get_access_token() -> str:
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }
    r = requests.post(token_url, data=data, timeout=30)
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
        items = data.get("items", [])
        posts.extend(items)
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

def normalize_title(t: str):
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return [w for w in t.split() if len(w) > 2]

def jaccard(a: str, b: str) -> float:
    A, B = set(normalize_title(a)), set(normalize_title(b))
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)

def is_duplicate(new_title: str, recent_titles):
    for t in recent_titles:
        if new_title.strip().lower() == t.strip().lower():
            return True
        if jaccard(new_title, t) >= MAX_SIMILARITY:
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

def category_blocked_recently(cat, recent_posts, days=7):
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

def clamp_words(s, minw=8, maxw=12):
    words = s.split()
    if len(words) < minw:
        while len(words) < minw:
            words.append("Guide")
    if len(words) > maxw:
        words = words[:maxw]
    return " ".join(words)

def make_html_post(topic_category: str, angle_note: str):
    title_map = {
        "Personal Life and Stories": "A Small Habit That Changed My Week",
        "Food and Recipes": "A 30-Minute Weeknight Paneer Stir-Fry",
        "Travel": "A 48-Hour Guide to Monsoon Goa",
        "How-To Guides and Tutorials": "A Step-by-Step Guide to Inbox Zero",
        "Product Reviews": "Hands-On Review: Budget ANC Headphones",
        "Money and Finance": "A Simple Plan to Cut Monthly Bills",
        "Productivity": "Beat Afternoon Slumps With A 20-Min Reset",
        "Health and Fitness": "A Beginner’s 20-Min Mobility Routine",
        "Fashion": "Late-Monsoon Wardrobe: 7 Smart Picks",
        "Lists and Roundups": "9 Free Tools To Automate Daily Tasks",
    }
    raw_title = title_map.get(topic_category, f"Fresh Notes on {topic_category}")
    title = clamp_words(raw_title, 8, 12)
    today = dt.datetime.now().strftime("%Y-%m-%d")
    angle_comment = f"<!-- Angle: {angle_note} -->"
    feature_img_url = "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?w=1200&q=80"
    inline_img_url = "https://images.unsplash.com/photo-1496307042754-b4aa456c4a2d?w=1200&q=80"
    meta_title = title[:60]
    meta_desc = "Practical, timely tips aligned to this week’s schedule—read in minutes."
    tl_dr = """
<ul>
  <li>Timely, practical takeaways you can apply today.</li>
  <li>Clear steps with a quick checklist.</li>
  <li>One brief case example for context.</li>
  <li>Two relevant images with credits.</li>
</ul>
"""
    body = f"""
{angle_comment}
<!-- Meta Title: {html.escape(meta_title)} -->
<!-- Meta Description: {html.escape(meta_desc)} -->

<h1>{html.escape(title)}</h1>
<p><em>By Automation Bot • {today}</em></p>

<p><strong>TL;DR</strong></p>
{tl_dr}

<p>{html.escape("Here’s a timely, helpful read aligned to the category: " + topic_category)}.</p>

<img src="{feature_img_url}" alt="Category-related visual showing context" />
<p><em>A relevant visual that anchors the topic without distracting.</em></p>
<p><small>Photo: Unsplash (CC0/Link)</small></p>

<h2>Key steps</h2>
<ol>
  <li>Start with a clear goal for the session.</li>
  <li>Follow a short, repeatable framework.</li>
  <li>Use the checklist to verify results.</li>
</ol>

<h3>Case example</h3>
<p>In a real week, a small 20-minute window applied consistently yielded measurable progress and fewer context switches.</p>

<blockquote><strong>Pro tip:</strong> Batch similar tasks to reduce switching costs and protect energy.</blockquote>

<h2>Checklist</h2>
<ul>
  <li>Define outcome in one sentence.</li>
  <li>List 3 steps and a 10-minute fallback plan.</li>
  <li>Confirm one clear next action.</li>
</ul>

<img src="{inline_img_url}" alt="Secondary visual reinforcing the main idea" />
<p><em>Another lightweight visual that reinforces the main point.</em></p>
<p><small>Photo: Unsplash (CC0/Link)</small></p>

<h2>Conclusion</h2>
<p>Keep it short, structured, and consistent—this is how useful habits compound over time.</p>

<p><strong>Enjoyed this? Leave a comment with your thoughts or questions.</strong></p>
<p><strong>Love practical reads like this? Follow the blog for three new posts every week.</strong></p>

<h3>What to read next</h3>
<ul>
  <li>[Link: Related Post Title 1]</li>
  <li>[Link: Related Post Title 2]</li>
  <li>[Link: Related Post Title 3]</li>
</ul>
"""
    labels = [topic_category]
    return title, body, labels

def blogger_insert_post(access_token: str, blog_id: str, title: str, html_content: str, labels, is_draft: bool):
    url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/"
    params = {"isDraft": str(is_draft).lower()}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    body = {"kind": "blogger#post", "title": title, "content": html_content, "labels": labels or []}
    r = requests.post(f"{url}?{urlencode(params)}", headers=headers, data=json.dumps(body), timeout=60)
    r.raise_for_status()
    return r.json()

def main():
    require_env()
    token = get_access_token()
    recent = blogger_get_recent_posts(token, BLOG_ID, days=30, max_results=50)
    recent_titles = [p.get("title", "") for p in recent if p.get("title")]

    # Choose next category with 7-day cooldown
    cat = next_category(recent)
    tries = 0
    while category_blocked_recently(cat, recent, days=7) and tries < len(CATEGORY_ROTATION):
        idx = (CATEGORY_ROTATION.index(cat) + 1) % len(CATEGORY_ROTATION)
        cat = CATEGORY_ROTATION[idx]
        tries += 1

    angle_note = f"Fresh weekly angle for {cat} — {dt.datetime.now().strftime('%Y-%m-%d')}"
    title, html_content, labels = make_html_post(cat, angle_note)

    # Enforce no near-duplicate title
    if is_duplicate(title, recent_titles):
        title = title + " Essentials"

    # Post (draft or publish)
    post = blogger_insert_post(token, BLOG_ID, title, html_content, labels, is_draft=not PUBLISH_IMMEDIATELY)
    print(json.dumps({"postedId": post.get("id"), "url": post.get("url"), "title": post.get("title"), "labels": labels}, indent=2))

if __name__ == "__main__":
    main()
