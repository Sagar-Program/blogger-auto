import os
import json
import datetime as dt
import requests
import markdown
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import google.generativeai as genai
import pytz

# ====== CONFIG ======
BLOG_ID = os.getenv("BLOGGER_BLOG_ID")
SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_PATH = "token.json"
POST_LABELS = ["Auto-Generated", "AI-Blog"]

# ====== SIMPLE CONTENT GENERATION ======
def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set.")
    genai.configure(api_key=api_key)
    return genai

def generate_simple_blog_post():
    """Generate a simple blog post without any complexity"""
    client = get_gemini_client()
    model = client.GenerativeModel('gemini-1.5-flash')
    
    prompt = """Create a short blog post (300-500 words) about one of these topics:
    - Tips for better productivity while working from home
    - Easy healthy breakfast ideas for busy people
    - How to stay motivated when learning new skills
    - Simple ways to reduce stress in daily life
    
    Format it in Markdown with a title, introduction, 2-3 main points, and conclusion.
    Make it practical and actionable."""
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"❌ Gemini API error: {e}")
        return "# Test Blog Post\n\nThis is a test post to check if the auto-blogger is working correctly.\n\n## Introduction\nThis post was generated automatically to test the blogging system.\n\n## Main Content\nIf you're reading this, it means the auto-blogger successfully posted to your blog! This is a great milestone in setting up automated content creation.\n\n## Conclusion\nThe system seems to be working well. Future posts will have more detailed and engaging content."

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
    """Create and publish post - SIMPLIFIED"""
    API_BASE = "https://www.googleapis.com/blogger/v3"
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

    print(f"📤 Attempting to publish: {title}")
    print(f"🔍 Blog ID: {BLOG_ID}")
    print(f"🔍 Content length: {len(html_content)} characters")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f"🔍 API Response Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ SUCCESS! Post published: {result.get('url')}")
            return result
        else:
            print(f"❌ API Error: {response.status_code}")
            print(f"🔍 Response text: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Failed to publish: {str(e)}")
        return None

# ====== MAIN EXECUTION ======
def main():
    print("🤖 Starting SIMPLE Blogger AutoPost...")
    print("🔍 This version removes all checks and just tries to post")
    
    try:
        # Get credentials
        creds = get_credentials()
        print("✅ Got credentials successfully")
        
        # Generate content
        print("🧠 Generating simple content...")
        markdown_content = generate_simple_blog_post()
        
        # Extract title from first line
        lines = markdown_content.split('\n')
        title = lines[0].replace('#', '').strip() if lines[0].startswith('#') else "Auto-Generated Blog Post"
        
        print(f"📝 Generated title: {title}")
        
        # Convert to HTML with basic styling
        html_content = markdown.markdown(markdown_content)
        full_html = f"""
        <div style="max-width: 700px; margin: 0 auto; font-family: Arial, sans-serif; line-height: 1.6;">
            {html_content}
            <hr style="margin: 2em 0;">
            <p style="color: #666; font-size: 0.9em;">
                This post was automatically generated by AI. 
                <a href="#" style="color: #0066cc;">Subscribe</a> for more content!
            </p>
        </div>
        """
        
        # PUBLISH (no checks, no conditions)
        print("📤 Attempting to publish (no checks)...")
        result = create_blogger_post(creds, title, full_html, POST_LABELS)
        
        if result:
            print("🎉 BLOG POST SUCCESSFULLY PUBLISHED!")
            print(f"🔗 URL: {result.get('url')}")
        else:
            print("💥 Failed to publish - check logs above for details")
            
    except Exception as e:
        print(f"💥 Critical error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
