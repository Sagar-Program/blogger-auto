#!/usr/bin/env python3
import os, sys, json, re, html, datetime as dt, random
import requests
from urllib.parse import urlencode

# =========================
# Required secrets (set in GitHub → Settings → Secrets → Actions)
# =========================
BLOG_ID = os.environ.get("BLOG_ID", "").strip()
CLIENT_ID = os.environ.get("CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN", "").strip()

# Optional
PUBLISH_IMMEDIATELY = os.environ.get("PUBLISH_IMMEDIATELY", "true").lower() == "true"
BLOG_TIMEZONE = os.environ.get("BLOG_TIMEZONE", "Asia/Kolkata")

# =========================
# Rotation and freshness
# =========================
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
MAX_SIMILARITY = 0.8  # near-duplicate title block
TITLE_FALLBACK_SUFFIXES = [" Guide", " Essentials", " Explained", " In Practice"]

def require_env():
    for var, val in [("BLOG_ID", BLOG_ID), ("CLIENT_ID", CLIENT_ID), ("CLIENT_SECRET", CLIENT_SECRET), ("REFRESH_TOKEN", REFRESH_TOKEN)]:
        if not val:
            print(f"Missing required secret: {var}", file=sys.stderr)
            sys.exit(1)

# =========================
# OAuth and Blogger API
# =========================
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

# =========================
# Freshness helpers
# =========================
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

# =========================
# Content builder (long-form, like the example)
# =========================
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
        "Personal Life and Stories": "A Micro-Story About Small Wins And Big Weeks",
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
    # Ensure category is a string label
    if isinstance(topic_category, list):
        topic_key = ", ".join([str(x) for x in topic_category])
    else:
        topic_key = str(topic_category)

    title = build_title_for_category(topic_key)
    today = dt.datetime.now().strftime("%Y-%m-%d")

    # Hero/feature image (royalty-free placeholder)
    feature_img_url = "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?w=1200&q=80"

    # Sectioned body with H2/H3 and multiple paragraphs (like the example)
    intro = f"""
<p>In the fast-changing world of everyday work and personal projects, a simple framework can turn scattered effort into reliable progress. This long-form guide walks through clear steps and examples so readers can apply the ideas today—not someday—without new tools or steep learning curves.</p>
<p>Expect a brief history, core components, practical advantages, common challenges, and a forward look—plus a concise checklist to help verify results as habits form. It’s designed for busy readers who value substance and structure.</p>
"""

    evolution = """
<h2>The Evolution Of Practical Frameworks</h2>
<h3>From Ad-Hoc To Organized</h3>
<p>Teams used to rely on ad-hoc processes and heroic sprints. Over time, conventions, patterns, and toolkits emerged so common problems didn’t need to be solved from scratch. This shift reduced friction and made iteration faster.</p>
<h3>Milestones That Matter</h3>
<ul>
  <li>Clear separation of concerns and repeatable building blocks.</li>
  <li>Open knowledge-sharing and community-driven improvements.</li>
  <li>Faster onboarding through shared language and defaults.</li>
</ul>
"""

    understanding = f"""
<h2>Understanding The Framework</h2>
<h3>What It Is</h3>
<p>Think of a framework as a practical set of decisions made once, then reused. It’s a map that reduces guesswork and keeps attention on the real work. For {html.escape(topic_key.lower())}, that means simple steps, clear roles, and visible outcomes.</p>
<h3>Core Components</h3>
<ul>
  <li><strong>User Experience:</strong> Keep the path obvious and reduce choice overload.</li>
  <li><strong>Data Flow:</strong> Ensure information moves predictably with low friction.</li>
  <li><strong>Feedback Loops:</strong> Add small checks so issues surface early.</li>
</ul>
"""

    advantages = """
<h2>Advantages</h2>
<h3>Enhanced Productivity</h3>
<p>Pre-made building blocks remove busywork. Work sessions focus on outcomes, not setup.</p>
<h3>Streamlined Processes</h3>
<p>Consistency lowers the learning curve and improves handoffs between people and tools.</p>
<h3>Quality And Scalability</h3>
<p>Shared conventions reduce defects and make growth easier, because improvements happen once and apply everywhere.</p>
"""

    challenges = """
<h2>Challenges And Considerations</h2>
<h3>The Learning Curve</h3>
<p>New structures feel slower at first. The fix is to adopt in small slices and measure the gains.</p>
<h3>Collaboration In Practice</h3>
<p>Version control, shared assets, and clear checklists keep teams aligned without heavy meetings.</p>
"""

    improved_quality = """
<h2>Improved Outcomes</h2>
<h3>Faster Debugging</h3>
<p>When the path is predictable, issues are easier to isolate and fix quickly.</p>
<h3>Consistency</h3>
<p>Similar problems get similar solutions—less surprise, more trust in results.</p>
<h3>Better Testing</h3>
<p>Repeatable steps make it simpler to automate checks and catch regressions.</p>
"""

    cost_effective = """
<h2>Cost-Effectiveness</h2>
<p>Routines reduce waste. Shorter setup times and fewer reworks compound into lower costs over weeks and months.</p>
"""

    future = """
<h2>The Road Ahead</h2>
<h3>Low-Code And No-Code</h3>
<p>Expect more building blocks that non-specialists can combine safely for simple needs.</p>
<h3>Smarter Assistance</h3>
<p>Lightweight automation continues to speed up drafting, reviewing, and testing—while humans keep control of decisions.</p>
"""

    checklist = """
<h2>Quick Checklist</h2>
<ul>
  <li>State today’s outcome in one sentence.</li>
  <li>Time-box work into 20–40 minute blocks.</li>
  <li>Split tasks to fit the block length.</li>
  <li>End with one written next action.</li>
  <li>Track one metric for seven days.</li>
</ul>
"""

    conclusion = """
<h2>Conclusion</h2>
<p>Small, reliable structures beat bursts of motivation. With a simple loop—clear outcome, short focused work, and one next action—progress compounds. Keep it lightweight, adjust once a week, and let the routine do the heavy lifting.</p>
<p><strong>Enjoyed this? Leave a comment with your thoughts or questions.</strong></p>
<p><strong>Love practical reads like this? Follow the blog for three new posts every week.</strong></p>
"""

    # Assemble final HTML
    h1 = f"<h1>{html.escape(title)}</h1>"
    byline = f"<p><em>By Automation Bot • {dt.datetime.now().strftime('%Y-%m-%d')}</em></p>"
    hero = f"""
<img src="{feature_img_url}" alt="Context image framing the article topic" />
<p><em>A contextual visual that frames the topic without distracting from the content.</em></p>
<p><small>Photo: Unsplash (CC0/Link)</small></p>
"""
    body = "\n".join([h1, byline, intro, hero, evolution, understanding, advantages, challenges, improved_quality, cost_effective, future, checklist, conclusion])

    # Labels: array of strings
    labels = [topic_key]
    return title, body, labels

# =========================
# Main
# =========================
def main():
    require_env()
    token = get_access_token()
    recent = blogger_get_recent_posts(token, BLOG_ID, days=30, max_results=50)
    recent_titles = [p.get("title", "") for p in recent if p.get("title")]

    # Pick next category with 7-day cooldown
    cat = next_category(recent)
    spins = 0
    while category_used_in_days(cat, recent, days=7) and spins < len(CATEGORY_ROTATION):
        idx = (CATEGORY_ROTATION.index(cat) + 1) % len(CATEGORY_ROTATION)
        cat = CATEGORY_ROTATION[idx]
        spins += 1

    title, html_content, labels = make_html_post(cat)

    # Avoid near-duplicate titles
    if title_is_duplicate(title, recent_titles):
        title = title + random.choice(TITLE_FALLBACK_SUFFIXES)

    post = blogger_insert_post(token, BLOG_ID, title, html_content, labels, is_draft=not PUBLISH_IMMEDIATELY)
    print(json.dumps({"postedId": post.get("id"), "url": post.get("url"), "title": post.get("title"), "labels": labels}, indent=2))

if __name__ == "__main__":
    main()
