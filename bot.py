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
import random

# ====== CONFIG ======
BLOG_ID = os.getenv("BLOGGER_BLOG_ID")
SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_PATH = "token.json"
HISTORY_PATH = "posted_topics.json"
POST_LABELS = ["Automated", "AI-Generated"]
BLOG_TZ = pytz.timezone(os.getenv("BLOG_TIMEZONE", "Asia/Kolkata"))
TEMPLATE_PATH = "blog_template.md"

# Available topics with subtopics to avoid repetition
TOPICS = {
    "Personal Life and Stories": [
        "childhood memories", "life lessons", "personal growth", 
        "daily routines", "mindfulness practices", "relationship advice"
    ],
    "Food and Recipes": [
        "quick breakfast", "healthy lunch", "dinner recipes",
        "vegetarian dishes", "dessert ideas", "meal prep"
    ],
    "Travel": [
        "budget travel", "solo traveling", "family vacations",
        "adventure trips", "cultural experiences", "travel tips"
    ],
    "How-To Guides and Tutorials": [
        "DIY projects", "software tutorials", "cooking techniques",
        "fitness routines", "productivity hacks", "learning skills"
    ],
    "Product Reviews": [
        "tech gadgets", "kitchen appliances", "beauty products",
        "book reviews", "software tools", "fitness equipment"
    ]
}

# ====== TEMPLATE SYSTEM ======
def load_template():
    """Load the blog template from file"""
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            return f.read()
    return """
# {title}
**By Automated Editorial · {date}**
<!-- Topic: {topic} | Angle: {angle} -->
{content}
"""

def save_template(template_content):
    """Save template to file"""
    with open(TEMPLATE_PATH, 'w', encoding='utf-8') as f:
        f.write(template_content)

def render_template(template, variables):
    """Render template with variables"""
    for key, value in variables.items():
        placeholder = "{" + key + "}"
        template = template.replace(placeholder, str(value))
    return template

# ====== TOPIC HISTORY ======
def load_history():
    """Load posted topics history"""
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {"posted_topics": [], "last_posted_dates": {}}
    return {"posted_topics": [], "last_posted_dates": {}}

def save_history(history):
    """Save history to file"""
    with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2)

def get_fresh_topic(history):
    """Get a topic that hasn't been posted recently"""
    available_topics = []
    
    for main_topic, subtopics in TOPICS.items():
        # Check if main topic was posted in last 7 days
        last_posted = history["last_posted_dates"].get(main_topic)
        if last_posted:
            last_date = dt.datetime.fromisoformat(last_posted)
            if (dt.datetime.now() - last_date).days < 7:
                continue
        
        # Add available subtopics
        for subtopic in subtopics:
            full_topic = f"{main_topic}: {subtopic}"
            if full_topic not in history["posted_topics"][-10:]:  # Last 10 posts
                available_topics.append((main_topic, subtopic))
    
    if available_topics:
        return random.choice(available_topics)
    
    # If all topics recently used, pick the oldest one
    oldest_topic = min(history["last_posted_dates"].items(), key=lambda x: x[1])
    main_topic = oldest_topic[0]
    subtopic = random.choice(TOPICS[main_topic])
    return (main_topic, subtopic)

# ====== GEMINI CLIENT ======
def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set.")
    genai.configure(api_key=api_key)
    return genai

def generate_blog_content(topic, subtopic):
    """Generate blog content using template"""
    client = get_gemini_client()
    model = client.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""Create a comprehensive blog post about {subtopic} under the main category {topic}.

    Requirements:
    - Word count: 800-1200 words
    - Format: Markdown with H1, H2, H3 headings
    - Include: Introduction, main content with 3-4 sections, conclusion
    - Tone: Professional yet engaging
    - Add 3-4 bullet points for TL;DR section
    - Add 3 key takeaways at the end
    
    Output only the content body (no title or meta tags)."""

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"❌ Gemini API error: {e}")
        return f"# {subtopic}\n\nThis is a blog post about {subtopic} under {topic} category."

# ====== BLOGGER API ======
def get_credentials():
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

def create_blogger_post(creds, title, html_content, labels):
    """Create and publish post"""
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
        "labels": labels + ["AI-Generated"],
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Error creating post: {e}")
        raise

# ====== MAIN EXECUTION ======
def main():
    print("🤖 Starting Blogger AutoPost with Template System...")
    
    # Load history and template
    history = load_history()
    template = load_template()
    
    # Get fresh topic
    main_topic, subtopic = get_fresh_topic(history)
    full_topic = f"{main_topic}: {subtopic}"
    
    print(f"🎯 Selected Topic: {full_topic}")
    
    # Generate content
    print("🧠 Generating content with Gemini...")
    content = generate_blog_content(main_topic, subtopic)
    
    # Prepare template variables
    template_vars = {
        "title": f"{main_topic}: {subtopic}",
        "date": dt.datetime.now().strftime("%B %d, %Y"),
        "topic": main_topic,
        "angle": subtopic,
        "meta_title": f"{subtopic} - Complete Guide 2025",
        "meta_description": f"Learn everything about {subtopic} with our comprehensive guide. Tips, techniques, and best practices.",
        "content": content,
        "image_alt": f"{subtopic} illustration",
        "image_url": "https://example.com/placeholder.jpg",
        "image_caption": "Visual representation of the topic",
        "image_credit": "AI Generated Image",
        "bullet_point_1": f"Key insight about {subtopic}",
        "bullet_point_2": f"Practical tip for {subtopic}",
        "bullet_point_3": f"Common mistake to avoid in {subtopic}",
        "bullet_point_4": f"Quick win for {subtopic}",
        "takeaway_1": f"Main lesson about {subtopic}",
        "takeaway_2": f"Actionable advice for {subtopic}",
        "takeaway_3": f"Future trend in {subtopic}",
        "introduction": f"This guide covers everything you need to know about {subtopic}...",
        "conclusion": f"In summary, {subtopic} offers great opportunities for...",
    }
    
    # Render template
    print("⚙️ Rendering template...")
    final_content = render_template(template, template_vars)
    
    # Convert to HTML
    print("🔄 Converting to HTML...")
    html_content = markdown.markdown(final_content)
    styled_html = f"""
    <style>
    article {{
        max-width: 700px;
        margin: 0 auto;
        line-height: 1.6;
        font-size: 18px;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }}
    article h1 {{ font-size: 2.5em; margin-bottom: 0.5em; }}
    article h2 {{ font-size: 1.8em; margin: 1.5em 0 0.5em 0; }}
    article h3 {{ font-size: 1.3em; margin: 1.2em 0 0.5em 0; }}
    </style>
    <article>{html_content}</article>
    """
    
    # Publish
    print("📤 Publishing post...")
    try:
        creds = get_credentials()
        result = create_blogger_post(creds, template_vars["title"], styled_html, [main_topic, subtopic])
        
        # Update history
        history["posted_topics"].append(full_topic)
        history["last_posted_dates"][main_topic] = dt.datetime.now().isoformat()
        save_history(history)
        
        print(f"✅ Success! Post published: {result.get('url')}")
        print(f"📊 History updated: {len(history['posted_topics'])} posts tracked")
        
    except Exception as e:
        print(f"❌ Failed to publish: {e}")

if __name__ == "__main__":
    main()
