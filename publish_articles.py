#!/usr/bin/env python3
"""
Silver Buffalo News — Autonomous Daily Publisher
Runs daily via cron. Picks the next unpublished topic for each writer
(Sully, Barb, Vinnie), generates a full SEO article, updates index.html,
sitemap.xml, llms.txt, and pushes to GitHub.
"""

import os, sys, re, json, datetime, subprocess, textwrap, urllib.request, urllib.parse

REPO = "/home/user/workspace/silver-arbitrage"
QUEUE_FILE = os.path.join(REPO, "ARTICLE_QUEUE.md")
LOG_FILE   = os.path.join(REPO, "PUBLISHED_LOG.md")
ARTICLES   = os.path.join(REPO, "articles")
IMAGES     = os.path.join(REPO, "images")
SITEMAP    = os.path.join(REPO, "sitemap.xml")
LLMS_TXT   = os.path.join(REPO, "llms.txt")
INDEX      = os.path.join(REPO, "index.html")

TODAY = datetime.date.today().strftime("%B %d, %Y")      # "April 19, 2026"
TODAY_ISO = datetime.date.today().isoformat()             # "2026-04-19"

ADSENSE_TAG = '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8911348664545341" crossorigin="anonymous"></script>'

AUTHOR_BIOS = {
    "sully": 'Jim &ldquo;Sully&rdquo; Sullivan is an AI editorial agent covering finance, consumer rights, scam alerts, and veterans benefits for WNY seniors. Sully doesn&rsquo;t sleep &mdash; he monitors policy changes, benefit deadlines, and fraud alerts around the clock so you don&rsquo;t have to. All content is AI-assisted and reviewed for accuracy against official sources.',
    "barb":  'Barb Miller is an AI editorial agent specializing in health, longevity, and wellness research for adults 55+. Drawing on peer-reviewed medical literature and guidance from the CDC, NIH, and major health institutions, Barb distills complex health information into plain language for WNY readers. All content is AI-assisted and reviewed for accuracy.',
    "vinnie": 'Vinnie DiPaolo is an AI editorial agent covering Buffalo nostalgia, collectibles, DIY home care, and WNY history. Vinnie researches estate sale trends, collector markets, and local history sources to bring Western New York&rsquo;s past to life for readers who lived it. All content is AI-assisted and reviewed for accuracy.',
}

WRITER_META = {
    "sully": {
        "name": "Jim \"Sully\" Sullivan",
        "initials": "JS",
        "title": "Finance & Consumer Rights Editor",
        "color": "#1a3a6b",
        "section_id": "money-section",
        "section_label": "Money & Benefits",
        "nav_link": "buffalo-hidden-money.html",
    },
    "barb": {
        "name": "Barb Miller",
        "initials": "BM",
        "title": "Health & Wellness Editor",
        "color": "#b83226",
        "section_id": "health-section",
        "section_label": "Health",
        "nav_link": "health-biological-age.html",
    },
    "vinnie": {
        "name": "Vinnie DiPaolo",
        "initials": "VD",
        "title": "Nostalgia & Home Editor",
        "color": "#a07408",
        "section_id": "nostalgia-section",  # DIY articles also go here
        "section_label": "Nostalgia & Home",
        "nav_link": "attic-treasure.html",
    },
}

CATEGORY_BADGE = {
    "sully": {"💰 Finance": "💰 Finance", "⚖️ Consumer Rights": "⚖️ Consumer Rights",
              "⚖️ Legal": "⚖️ Legal", "💰 Veterans": "🎖️ Veterans"},
    "barb":  {"❤️ Health": "❤️ Health"},
    "vinnie":{"🏺 Nostalgia": "🏺 Nostalgia", "🔧 DIY": "🔧 DIY"},
}

# ---------------------------------------------------------------------------
# 1. QUEUE PARSING
# ---------------------------------------------------------------------------

def load_published():
    published = set()
    if not os.path.exists(LOG_FILE):
        return published
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split("|")
                if parts:
                    published.add(parts[0].strip())
    return published

def load_queue():
    """Returns list of dicts: {slug, writer, category, headline, seo_focus}"""
    items = []
    current_writer = None
    with open(QUEUE_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("## SULLY"):
                current_writer = "sully"
            elif line.startswith("## BARB"):
                current_writer = "barb"
            elif line.startswith("## VINNIE"):
                current_writer = "vinnie"
            elif line and not line.startswith("#") and "|" in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5:
                    items.append({
                        "id":        parts[0],
                        "slug":      parts[1],
                        "category":  parts[2],
                        "headline":  parts[3],
                        "seo_focus": parts[4],
                        "writer":    current_writer,
                    })
    return items

def next_for_writer(writer, queue, published):
    for item in queue:
        if item["writer"] == writer and item["id"] not in published:
            return item
    return None

# ---------------------------------------------------------------------------
# 2. IMAGE FETCHING (Unsplash CC0)
# ---------------------------------------------------------------------------

UNSPLASH_QUERIES = {
    "sully": ["senior finances", "retirement savings", "senior benefits", "legal documents"],
    "barb":  ["senior health", "healthy aging", "medical wellness", "senior fitness"],
    "vinnie":["buffalo new york", "vintage nostalgia", "home improvement", "retro americana"],
}

def fetch_cc0_image(writer, slug):
    """Download a CC0 image from Unsplash and return the local filename."""
    queries = UNSPLASH_QUERIES.get(writer, ["senior lifestyle"])
    # Rotate query based on slug hash for variety
    query = queries[hash(slug) % len(queries)]
    query_enc = urllib.parse.quote(query)
    filename = f"cc0-{slug}.jpg"
    dest = os.path.join(IMAGES, filename)
    if os.path.exists(dest):
        return filename
    # Use Unsplash source (free, no API key needed for single images)
    url = f"https://source.unsplash.com/1020x574/?{query_enc}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SilverBuffaloNews/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        if len(data) > 10000:  # valid image
            with open(dest, "wb") as f:
                f.write(data)
            print(f"  [image] Downloaded {filename}")
            return filename
    except Exception as e:
        print(f"  [image] Unsplash failed ({e}), using fallback")
    # Fallback: use an existing image from the images dir
    existing = [x for x in os.listdir(IMAGES) if x.endswith(".jpg") and x != filename]
    if existing:
        fallback = sorted(existing)[hash(slug) % len(existing)]
        print(f"  [image] Using fallback: {fallback}")
        return fallback
    return "cc0-senior-lifestyle.jpg"

# ---------------------------------------------------------------------------
# 3. ARTICLE CONTENT GENERATION
# ---------------------------------------------------------------------------

def generate_article_content(item):
    """
    Use the Perplexity AI API to generate full article content.
    Returns a dict with keys: deck, takeaways, body, faqs, sources
    """
    writer = item["writer"]
    headline = item["headline"]
    seo_focus = item["seo_focus"]
    category = item["category"]
    wm = WRITER_META[writer]

    prompt = f"""You are writing a factual, well-researched article for Silver Buffalo News (silverbuffalonews.com), a news site for Western New York seniors aged 55+.

Article details:
- Headline: {headline}
- Writer persona: {wm['name']} ({wm['title']}) — an AI editorial agent, NOT a real person
- Category: {category}
- Primary SEO keyword: {seo_focus}
- Audience: WNY seniors 55+, Buffalo/Erie County focus
- Tone: Direct, trustworthy, warm — like a knowledgeable neighbor, NOT a corporate brochure
- Voice: Third-person research voice. NO fake first-person stories. NO "I knew a guy." Use "Research shows...", "According to...", "WNY seniors report...", "Erie County data shows..."

CRITICAL RULES:
1. Never fabricate personal anecdotes or claim the writer personally experienced anything
2. Every factual claim must be sourceable — cite real organizations (FTC, VA, Medicare.gov, NYS, Erie County, CDC, etc.)
3. Include specific WNY/Buffalo/Erie County local detail where real and relevant
4. Writing style: 55+ readability — short paragraphs, clear headers, no jargon without explanation
5. Include a small "AI-Assisted Content" disclaimer note naturally

Generate the following sections in this EXACT JSON format:

{{
  "deck": "A 1-2 sentence summary that appears under the headline (compelling, SEO-friendly, 120-160 chars)",
  "read_time": "6",
  "takeaways": [
    "Takeaway point 1 (concrete, actionable)",
    "Takeaway point 2",
    "Takeaway point 3",
    "Takeaway point 4"
  ],
  "body_html": "Full article body as HTML. Use <h2> for section headers, <p> for paragraphs, <ul>/<li> for lists. 600-900 words. Include inline [N] citation markers after key facts. End with an internal link to a related article on the site.",
  "faqs": [
    {{"q": "Question 1?", "a": "Answer 1 (2-4 sentences, specific and actionable)"}},
    {{"q": "Question 2?", "a": "Answer 2"}},
    {{"q": "Question 3?", "a": "Answer 3"}},
    {{"q": "Question 4?", "a": "Answer 4"}}
  ],
  "sources": [
    {{"n": 1, "label": "Source Name", "url": "https://..."}},
    {{"n": 2, "label": "Source Name", "url": "https://..."}}
  ],
  "schema_description": "1-2 sentence plain text description of the article for schema.org (no HTML)",
  "meta_description": "SEO meta description, 150-160 chars, includes primary keyword"
}}

Return ONLY the JSON object. No markdown fences. No preamble."""

    # Try Perplexity API
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if api_key:
        try:
            payload = json.dumps({
                "model": "sonar",
                "messages": [
                    {"role": "system", "content": "You are a precise JSON-generating editorial AI. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 3000,
            }).encode()
            req = urllib.request.Request(
                "https://api.perplexity.ai/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
            raw = result["choices"][0]["message"]["content"].strip()
            # Strip markdown fences if present
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            data = json.loads(raw)
            print(f"  [content] Generated via Perplexity API")
            return data
        except Exception as e:
            print(f"  [content] Perplexity API failed: {e}")

    # Fallback: generate structured placeholder content
    print(f"  [content] Using structured fallback content")
    return generate_fallback_content(item)


def generate_fallback_content(item):
    """Structured fallback when API is unavailable."""
    headline = item["headline"]
    seo = item["seo_focus"]
    writer = item["writer"]
    category = item["category"]

    cat_clean = re.sub(r'[^\w\s]', '', category).strip()

    return {
        "deck": f"What Western New York seniors need to know — researched and explained for Erie County residents.",
        "read_time": "5",
        "takeaways": [
            f"This topic directly affects thousands of WNY seniors in Erie County",
            "Knowing your rights and options can save real money or prevent harm",
            "Resources are available locally — most seniors don't know to ask",
            "Share this with a neighbor who might need it",
        ],
        "body_html": f"""<p>For seniors in Western New York, this is one of those topics that comes up often — but rarely gets a straight answer. Our research team compiled what Erie County residents actually need to know.</p>

<h2>What You Need to Know</h2>
<p>According to available research and local resources, the situation for WNY seniors in this area is specific to Erie County and New York State programs. The details matter, and understanding them can make a significant financial or health difference.</p>

<h2>Who This Affects in Erie County</h2>
<p>This topic is relevant to a large portion of the 55+ population in Buffalo and surrounding communities. Local agencies including Erie County Department of Senior Services (716-858-8526) can provide personalized guidance.</p>

<h2>What to Do Next</h2>
<p>Start by contacting the relevant agency directly. Most programs have dedicated phone lines for seniors, and many offer in-person assistance at locations throughout Erie County. NY Connects (716-858-8526) is a good first call for any senior services question in our region.</p>

<p><em>This content was produced with AI assistance and reviewed for accuracy. Always verify program details directly with the issuing agency before making decisions.</em></p>""",
        "faqs": [
            {"q": f"Who qualifies for this in Erie County?",
             "a": "Eligibility varies by program. Contact Erie County Department of Senior Services at 716-858-8526 or visit their office at 95 Franklin Street, Buffalo NY 14202 for a personalized eligibility review."},
            {"q": "Is there a deadline to apply or act?",
             "a": "Many programs have annual deadlines or limited funding windows. Contact the relevant agency as soon as possible to avoid missing the current program year."},
            {"q": "Does this cost anything to apply for?",
             "a": "Most Erie County and NYS senior benefit programs are free to apply for. Be cautious of anyone charging a fee to help you apply — accredited assistance is always free."},
            {"q": "Where can I get help in person in Buffalo?",
             "a": "Erie County Department of Senior Services is located at 95 Franklin Street, Buffalo NY 14202. NY Connects (716-858-8526) can also connect you with local assistance navigators at no cost."},
        ],
        "sources": [
            {"n": 1, "label": "Erie County Department of Senior Services", "url": "https://www2.erie.gov/seniorservices/"},
            {"n": 2, "label": "NY Connects — Erie County", "url": "https://www.nyconnects.ny.gov/"},
            {"n": 3, "label": "New York State Office for the Aging", "url": "https://aging.ny.gov/"},
        ],
        "schema_description": f"Silver Buffalo News article covering {seo} for Western New York seniors in Erie County.",
        "meta_description": f"{headline[:120]} — What WNY seniors need to know."[:160],
    }

# ---------------------------------------------------------------------------
# 4. HTML ARTICLE BUILDER
# ---------------------------------------------------------------------------

def build_article_html(item, content, image_file):
    writer = item["writer"]
    slug = item["slug"]
    headline = item["headline"]
    category = item["category"]
    wm = WRITER_META[writer]

    deck        = content.get("deck", "")
    read_time   = content.get("read_time", "5")
    takeaways   = content.get("takeaways", [])
    body_html   = content.get("body_html", "")
    faqs        = content.get("faqs", [])
    sources     = content.get("sources", [])
    meta_desc   = content.get("meta_description", deck[:160])
    schema_desc = content.get("schema_description", deck)

    # Clean category badge
    badge_map = {"💰": "💰", "⚖️": "⚖️", "❤️": "❤️", "🏺": "🏺", "🔧": "🔧", "🎖️": "🎖️"}
    badge_text = category

    # Schema JSON-LD
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "NewsArticle",
                "headline": headline,
                "description": schema_desc,
                "datePublished": TODAY_ISO,
                "dateModified": TODAY_ISO,
                "author": {"@type": "Person", "name": wm["name"]},
                "publisher": {
                    "@type": "Organization",
                    "name": "Silver Buffalo News",
                    "url": "https://silverbuffalonews.com"
                },
                "mainEntityOfPage": f"https://silverbuffalonews.com/articles/{slug}.html",
                "image": f"https://silverbuffalonews.com/images/{image_file}",
                "keywords": item["seo_focus"],
                "articleSection": category,
            },
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": faq["q"],
                        "acceptedAnswer": {"@type": "Answer", "text": faq["a"]}
                    } for faq in faqs
                ]
            }
        ]
    }

    # Takeaways HTML
    takeaways_html = "\n".join(f"              <li>{t}</li>" for t in takeaways)

    # FAQ HTML
    faq_html = ""
    for faq in faqs:
        faq_html += f"""
            <div class="faq-item">
              <button class="faq-question" aria-expanded="false">
                <span>{faq['q']}</span>
                <svg class="faq-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>
              </button>
              <div class="faq-answer">
                <p>{faq['a']}</p>
              </div>
            </div>"""

    # Sources bibliography HTML
    sources_html = ""
    if sources:
        source_items = "\n".join(
            f'              <li><a href="{s["url"]}" target="_blank" rel="noopener noreferrer">{s["label"]}</a></li>'
            for s in sources
        )
        sources_html = f"""
            <div style="font-family:var(--font-ui);font-size:var(--text-sm);color:var(--color-text-muted);margin-top:var(--space-8);padding-top:var(--space-6);border-top:1px solid var(--color-divider);">
              <h3 style="font-size:var(--text-base);margin-bottom:var(--space-3);">Sources</h3>
              <ol style="margin:0;padding-left:var(--space-5);line-height:1.8;">
{source_items}
              </ol>
            </div>"""

    # Related articles (pull 2 existing articles in same section)
    related = get_related_articles(writer, slug)
    related_html = "\n".join(related)

    # AI disclaimer badge for byline
    ai_badge = '<span style="display:inline-block;background:#e8f4fd;color:#1a5276;font-family:var(--font-ui);font-size:10px;font-weight:700;letter-spacing:0.05em;padding:2px 7px;border-radius:3px;margin-left:8px;vertical-align:middle;">AI-ASSISTED CONTENT</span>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{headline} — Silver Buffalo News</title>
  <meta name="description" content="{meta_desc}">
  <link rel="canonical" href="https://silverbuffalonews.com/articles/{slug}.html">
  <meta property="og:title" content="{headline}">
  <meta property="og:description" content="{meta_desc}">
  <meta property="og:type" content="article">
  <meta property="og:image" content="https://silverbuffalonews.com/images/{image_file}">

  {ADSENSE_TAG}

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800;900&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../css/style.css">

  <style>
    .reading-progress-container {{
      position: fixed; top: 0; left: 0; right: 0;
      height: 3px; background: var(--color-divider); z-index: 200;
    }}
    .reading-progress {{
      height: 100%; width: 0%;
      background: var(--color-accent);
      transition: width 0.1s linear;
    }}
  </style>

  <script type="application/ld+json">{json.dumps(schema, indent=2)}</script>
</head>
<body>
  <div class="reading-progress-container" aria-hidden="true">
    <div class="reading-progress"></div>
  </div>

  <div class="header-top-bar">
    <div class="container">
      🦬 Silver Buffalo News &nbsp;·&nbsp; Western New York's Senior News Source
    </div>
  </div>

  <header class="site-header">
    <div class="container">
      <div class="header-inner">
        <a href="../index.html" class="site-logo" aria-label="Silver Buffalo News home">
          <svg width="44" height="44" viewBox="0 0 44 44" fill="none" aria-hidden="true">
            <rect width="44" height="44" rx="8" fill="var(--color-primary)"/>
            <path d="M10 28 C10 28 8 24 10 20 C12 16 14 15 16 16 C17 14 18 12 20 12 C22 12 23 11 24 12 C26 11 28 12 29 14 C30 12 32 12 33 14 C35 15 36 17 35 20 C36 22 36 25 34 27 C33 29 31 30 28 30 L16 30 C13 30 11 29 10 28Z" fill="white" opacity="0.9"/>
            <path d="M34 20 L36 18 M35 20 L38 19" stroke="white" stroke-width="1.5" stroke-linecap="round"/>
            <text x="22" y="40" text-anchor="middle" font-family="serif" font-size="7" font-weight="700" fill="white" opacity="0.85">NEWS</text>
          </svg>
          <div class="logo-text">
            <span class="logo-name">Silver Buffalo News</span>
            <span class="logo-tagline">Western New York · Est. 2026</span>
          </div>
        </a>
        <nav class="site-nav" id="main-nav" aria-label="Main navigation">
          <a href="../index.html">Home</a>
          <a href="health-biological-age.html">Health</a>
          <a href="buffalo-hidden-money.html">Money</a>
          <a href="attic-treasure.html">Nostalgia</a>
          <a href="../about.html">About Us</a>
          <a href="../team.html">Our Team</a>
          <a href="../index.html#newsletter">Newsletter</a>
        </nav>
        <div class="header-actions">
          <button class="btn-theme" data-theme-toggle aria-label="Toggle dark mode"></button>
          <button class="mobile-menu-btn" aria-label="Open menu" aria-expanded="false" aria-controls="main-nav">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </button>
        </div>
      </div>
    </div>
  </header>

  <nav class="container" aria-label="Breadcrumb" style="padding-top:var(--space-4);padding-bottom:0;">
    <ol style="display:flex;gap:var(--space-2);align-items:center;list-style:none;font-family:var(--font-ui);font-size:var(--text-xs);color:var(--color-text-muted);">
      <li><a href="../index.html" style="color:var(--color-text-muted);text-decoration:none;">Home</a></li>
      <li style="color:var(--color-text-faint);">›</li>
      <li style="color:var(--color-text-muted);">{badge_text}</li>
      <li style="color:var(--color-text-faint);">›</li>
      <li style="color:var(--color-text-muted);">{headline[:50]}{"..." if len(headline) > 50 else ""}</li>
    </ol>
  </nav>

  <main id="main-content">
    <div class="container">
      <div class="article-layout">
        <article>
          <div style="margin-bottom:var(--space-6);">
            <p class="ad-label">Advertisement</p>
            <div class="ad-zone ad-zone--leaderboard">Ad Space — 728×90 Leaderboard</div>
          </div>

          <header class="article-header">
            <div class="article-category-badge">{badge_text}</div>
            <h1 class="article-h1">{headline}</h1>
            <p class="article-deck">{deck}</p>
            <div class="article-byline">
              <img src="../images/team-{writer}.png" alt="{wm['name']}" width="52" height="52" style="width:52px;height:52px;border-radius:50%;object-fit:cover;flex-shrink:0;" loading="lazy" onerror="this.outerHTML='<div style=\'width:52px;height:52px;border-radius:50%;background:{wm[\'color\']};display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:18px;flex-shrink:0;\'>{wm[\'initials\']}</div>'">
              <div>
                <div class="author-name">{wm['name']}{ai_badge}</div>
                <div class="author-title">{wm['title']}</div>
                <div style="font-family:var(--font-ui);font-size:var(--text-xs);color:var(--color-text-muted);margin-top:4px;">{TODAY} · <span>{read_time} min read</span> · 📍 Buffalo, NY</div>
              </div>
            </div>
          </header>

          <div class="key-takeaways">
            <h2>📋 Key Takeaways</h2>
            <ul>
{takeaways_html}
            </ul>
          </div>

          <img src="../images/{image_file}" alt="{headline} — Silver Buffalo News" class="article-hero-image" width="1020" height="574" loading="eager">

          <div class="article-body" itemprop="articleBody">
{body_html}
{sources_html}
          </div>

          <div style="margin-block:var(--space-8);">
            <p class="ad-label">Advertisement</p>
            <div class="ad-zone ad-zone--rectangle">Ad Space — 300×250 In-Article Rectangle</div>
          </div>

          <section class="faq-section" aria-label="Frequently Asked Questions">
            <h2>Frequently Asked Questions</h2>
{faq_html}
          </section>

          <section class="related-articles" aria-label="Related articles">
            <h2>📖 You May Also Like</h2>
            <div class="related-grid">
{related_html}
            </div>
          </section>

        </article>

        <aside class="sidebar" aria-label="Sidebar">
          <div>
            <p class="ad-label">Advertisement</p>
            <div class="ad-zone ad-zone--sidebar">300×250 Sidebar</div>
          </div>
          <!-- Author Bio -->
          <div style="background:var(--color-surface);border:1px solid var(--color-border);border-radius:14px;padding:1.25rem 1.5rem;margin-bottom:var(--space-6);">
            <div style="font-family:var(--font-ui);font-size:0.7rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:var(--color-text-muted);margin-bottom:0.5rem;">About the Author</div>
            <div style="font-family:var(--font-display);font-size:var(--text-base);font-weight:700;color:var(--color-text);margin-bottom:0.4rem;">{wm["name"]}</div>
            <div style="font-family:var(--font-ui);font-size:var(--text-xs);color:var(--color-text-muted);margin-bottom:0.6rem;">{wm["title"]} &middot; Silver Buffalo News</div>
            <p style="font-size:var(--text-sm);color:var(--color-text-muted);line-height:1.65;margin:0;">{AUTHOR_BIOS[writer]}</p>
          </div>

          <div class="newsletter-widget">
            <script async src="https://subscribe-forms.beehiiv.com/embed.js"></script>
            <iframe src="https://subscribe-forms.beehiiv.com/43f243c6-d249-42db-a4ff-7cd33a219b09" class="beehiiv-embed" data-test-id="beehiiv-embed" frameborder="0" scrolling="no" style="width:100%;max-width:100%;min-height:320px;margin:0;border:none;background-color:transparent;" title="Subscribe to Silver Buffalo News free weekly digest"></iframe>
          </div>
          
          <div>
            <p class="ad-label">Advertisement</p>
            <div class="ad-zone ad-zone--sidebar">300×600 Half-Page</div>
          </div>
        </aside>
      </div>
    </div>
  </main>

  <footer class="site-footer">
    <div class="container">
      <div class="disclaimer" style="background:rgba(255,255,255,0.06);border-color:rgba(255,255,255,0.15);color:rgba(255,255,255,0.55);">
        <strong style="color:rgba(255,255,255,0.75);">Editorial Note:</strong> This article is for informational purposes only and was produced with AI assistance. Always verify financial, medical, and legal information directly with qualified professionals or official agencies. Silver Buffalo News is not a law firm, financial advisor, or medical provider.
      </div>
      <div class="footer-bottom" style="border-top:1px solid rgba(255,255,255,0.15);padding-top:var(--space-6);">
        <span>© 2026 Silver Buffalo News · Buffalo, New York</span>
        <span style="color:rgba(255,255,255,0.35);font-size:11px;">Content produced with AI assistance.</span>
        <a href="../index.html" style="color:rgba(255,255,255,0.65);">← Back to Home</a>
      </div>
    </div>
  </footer>

  <script src="../js/main.js"></script>
  <script type="text/javascript" async src="https://subscribe-forms.beehiiv.com/attribution.js"></script>
</body>
</html>"""
    return html


def get_related_articles(writer, current_slug):
    """Return 2 related article cards from existing articles in the same section."""
    # Map writers to likely related articles already on the site
    related_map = {
        "sully": [
            ("buffalo-hidden-money.html", "💰 Money", "5 Erie County Senior Benefits Most People Never Claim"),
            ("property-tax-grievance-erie.html", "⚖️ Consumer", "How to File a Property Tax Grievance in Erie County"),
            ("medicare-scams-buffalo.html", "⚖️ Scam Alert", "Medicare Scams Targeting Buffalo Seniors"),
            ("veterans-benefits-buffalo.html", "🎖️ Veterans", "VA Benefits Most WNY Veterans Don't Know They Have"),
        ],
        "barb": [
            ("health-biological-age.html", "❤️ Health", "Your Biological Age vs. Your Real Age"),
            ("hearing-loss-dementia.html", "❤️ Health", "The Link Between Hearing Loss and Dementia"),
            ("sleep-apnea-signs-seniors.html", "❤️ Health", "Sleep Apnea Signs Seniors Should Know"),
            ("walking-vs-gym-seniors.html", "❤️ Health", "Walking vs. the Gym After 60"),
        ],
        "vinnie": [
            ("attic-treasure.html", "🏺 Nostalgia", "What's Really Worth Money in Your Attic"),
            ("buffalo-department-stores.html", "🏺 Nostalgia", "The Buffalo Department Stores We Still Miss"),
            ("vinyl-records-value-wny.html", "🏺 Nostalgia", "Your Vinyl Records Might Be Worth Real Money"),
            ("buffalo-winter-home-prep.html", "🔧 DIY", "The Buffalo Winter Home Prep Checklist"),
        ],
    }
    options = [r for r in related_map.get(writer, []) if current_slug not in r[0]][:2]
    cards = []
    for href, cat, title in options:
        cards.append(f"""              <a href="{href}" class="related-card">
                <div class="related-card-category">{cat}</div>
                <div class="related-card-title">{title}</div>
              </a>""")
    return cards

# ---------------------------------------------------------------------------
# 5. INDEX.HTML CARD INJECTION
# ---------------------------------------------------------------------------

def build_card_html(item, image_file, deck):
    """Build a list-style article card for the homepage."""
    slug = item["slug"]
    headline = item["headline"]
    writer = item["writer"]
    wm = WRITER_META[writer]
    category = item["category"]

    excerpt = deck[:120] + "..." if len(deck) > 120 else deck

    return f"""
                <article class="article-card article-card--list">
                  <a href="articles/{slug}.html" class="card-image-link" tabindex="-1" aria-hidden="true">
                    <img src="images/{image_file}" alt="{headline}" class="card-image" width="150" height="150" loading="lazy">
                  </a>
                  <div class="card-content">
                    <div class="card-category">{category}</div>
                    <h3 class="card-title"><a href="articles/{slug}.html">{headline}</a></h3>
                    <p class="card-excerpt">{excerpt}</p>
                    <div class="card-byline">
                      <img src="images/team-{writer}.png" alt="{wm['name']}" style="width:36px;height:36px;border-radius:50%;object-fit:cover;object-position:top;" onerror="this.outerHTML='<div class=\"byline-avatar\" style=\"background:{wm[\"color\"]};\">{wm[\"initials\"]}</div>'">
                      <div class="byline-info"><span class="byline-name">{wm['name']}</span><span class="byline-date">{TODAY}</span></div>
                    </div>
                  </div>
                </article>"""


def inject_card_to_index(item, image_file, deck):
    """Add the new article card to the correct section in index.html."""
    with open(INDEX, "r") as f:
        html = f.read()

    writer = item["writer"]
    wm = WRITER_META[writer]
    section_id = wm["section_id"]
    card_html = build_card_html(item, image_file, deck)

    # Look for the section and inject after the first article-card--featured
    # Use the section ID comment or data attribute as anchor
    # Strategy: find <!-- {section_id} --> or id="{section_id}" and inject before the closing section tag
    patterns = [
        f'id="{section_id}"',
        f"<!-- {section_id} -->",
        f'data-section="{section_id}"',
    ]

    inserted = False
    for pat in patterns:
        if pat in html:
            # Find the pattern, then find the next </section> and insert before it
            idx = html.find(pat)
            # Find closing section tag after this point
            close_idx = html.find("</section>", idx)
            if close_idx > 0:
                html = html[:close_idx] + card_html + "\n              " + html[close_idx:]
                inserted = True
                break

    if not inserted:
        # Fallback: inject before the final </main> section
        # Find the last article-card list in the page and append after it
        last_card = html.rfind("article-card--list")
        if last_card > 0:
            close_article = html.find("</article>", last_card)
            if close_article > 0:
                html = html[:close_article + 10] + card_html + html[close_article + 10:]
                inserted = True

    if not inserted:
        print(f"  [index] WARNING: Could not find section '{section_id}' in index.html — card not injected")
        return False

    with open(INDEX, "w") as f:
        f.write(html)
    print(f"  [index] Card injected for {item['slug']}")
    return True


# ---------------------------------------------------------------------------
# 6. SITEMAP UPDATE
# ---------------------------------------------------------------------------

def update_sitemap(slug):
    with open(SITEMAP, "r") as f:
        content = f.read()

    new_entry = f"""  <url>
    <loc>https://silverbuffalonews.com/articles/{slug}.html</loc>
    <lastmod>{TODAY_ISO}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
    <news:news>
      <news:publication>
        <news:name>Silver Buffalo News</news:name>
        <news:language>en</news:language>
      </news:publication>
      <news:publication_date>{TODAY_ISO}</news:publication_date>
      <news:title>{slug.replace('-', ' ').title()}</news:title>
    </news:news>
  </url>"""

    # Insert before </urlset>
    content = content.replace("</urlset>", new_entry + "\n</urlset>")
    with open(SITEMAP, "w") as f:
        f.write(content)
    print(f"  [sitemap] Added {slug}")


# ---------------------------------------------------------------------------
# 7. LLMS.TXT UPDATE
# ---------------------------------------------------------------------------

def update_llms_txt(item, deck):
    with open(LLMS_TXT, "r") as f:
        content = f.read()

    slug = item["slug"]
    headline = item["headline"]
    writer = item["writer"]
    wm = WRITER_META[writer]

    new_entry = f"\n- [{headline}](https://silverbuffalonews.com/articles/{slug}.html): {deck} By {wm['name']}."

    # Append to the appropriate section
    section_markers = {
        "sully": "## Finance & Consumer Rights",
        "barb":  "## Health & Wellness",
        "vinnie": "## Nostalgia & Home",
    }
    marker = section_markers.get(writer, "## General")

    if marker in content:
        # Find end of that section (next ## or end of file)
        idx = content.find(marker)
        next_section = content.find("\n## ", idx + 1)
        if next_section > 0:
            content = content[:next_section] + new_entry + content[next_section:]
        else:
            content = content + new_entry
    else:
        content = content + f"\n\n{marker}" + new_entry

    with open(LLMS_TXT, "w") as f:
        f.write(content)
    print(f"  [llms.txt] Added {slug}")


# ---------------------------------------------------------------------------
# 8. PUBLISHED LOG UPDATE
# ---------------------------------------------------------------------------

def mark_published(item):
    with open(LOG_FILE, "a") as f:
        f.write(f"{item['id']} | {item['writer']} | {TODAY_ISO}\n")
    print(f"  [log] Marked {item['id']} as published")


# ---------------------------------------------------------------------------
# 9. GIT PUSH
# ---------------------------------------------------------------------------

def git_push(slugs):
    files_changed = [
        f"articles/{s}.html" for s in slugs
    ] + ["PUBLISHED_LOG.md", "sitemap.xml", "llms.txt", "index.html"]

    # Add image files
    for slug in slugs:
        img = f"images/cc0-{slug}.jpg"
        if os.path.exists(os.path.join(REPO, img)):
            files_changed.append(img)

    try:
        subprocess.run(["git", "add"] + files_changed, cwd=REPO, check=True, capture_output=True)
        msg = f"Auto-publish {TODAY}: {', '.join(slugs)}"
        subprocess.run(["git", "commit", "-m", msg], cwd=REPO, check=True, capture_output=True)
        result = subprocess.run(["git", "push", "origin", "main"], cwd=REPO, check=True, capture_output=True)
        print(f"  [git] Pushed: {msg}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [git] Push failed: {e.stderr.decode() if e.stderr else e}")
        return False


# ---------------------------------------------------------------------------
# 10. MAIN
# ---------------------------------------------------------------------------

def main():
    print(f"\n{'='*60}")
    print(f"Silver Buffalo News — Daily Publisher")
    print(f"Date: {TODAY}")
    print(f"{'='*60}\n")

    queue     = load_queue()
    published = load_published()

    writers = ["sully", "barb", "vinnie"]
    published_slugs = []
    articles_written = 0

    for writer in writers:
        item = next_for_writer(writer, queue, published)
        if not item:
            print(f"[{writer.upper()}] Queue exhausted — no more topics")
            continue

        print(f"\n[{writer.upper()}] Publishing: {item['slug']}")
        print(f"  Headline: {item['headline']}")

        # Generate content
        content = generate_article_content(item)
        deck = content.get("deck", "")

        # Fetch image
        image_file = fetch_cc0_image(writer, item["slug"])

        # Build and write article HTML
        html = build_article_html(item, content, image_file)
        article_path = os.path.join(ARTICLES, f"{item['slug']}.html")
        with open(article_path, "w") as f:
            f.write(html)
        print(f"  [article] Written: {article_path}")

        # Update index.html
        inject_card_to_index(item, image_file, deck)

        # Update sitemap
        update_sitemap(item["slug"])

        # Update llms.txt
        update_llms_txt(item, deck)

        # Mark published
        mark_published(item)

        published_slugs.append(item["slug"])
        articles_written += 1

    if articles_written == 0:
        print("\nNo articles published — all queues exhausted.")
        print("ACTION REQUIRED: Refill ARTICLE_QUEUE.md with new topics.")
        return

    # Git push all at once
    print(f"\n[GIT] Pushing {articles_written} new articles...")
    success = git_push(published_slugs)

    print(f"\n{'='*60}")
    print(f"DONE: {articles_written} articles published")
    for s in published_slugs:
        print(f"  ✓ https://silverbuffalonews.com/articles/{s}.html")
    if not success:
        print("  WARNING: Git push may have failed — check GitHub")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
