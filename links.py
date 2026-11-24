"""Clickable reference links for a topic - search-shaped, authoritative, and honestly labelled.

When the daemon answers a factual question or the model returns an explanation, a reader usually wants
somewhere to read more. This module builds that little list.

Two rules keep it honest:

1. **No guessed article paths.** A search URL is stable; `/wiki/Saturn's_rings_composition` is a guess
   that may 404. So links point at *search* endpoints - Wikipedia, Britannica, and for space topics
   NASA and Space.com - which resolve for any spelling of the topic.
2. **No claim of having read them.** The label says these are reference searches, not sources the
   answer was drawn from. The local answer came from the AIML corpus; the model's came from training;
   neither browsed.

Nothing here fetches anything. It builds URLs, and the terminal renders them as clickable markdown.
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus

SPACE_TERMS = {
    "space", "nasa", "saturn", "jupiter", "mars", "venus", "mercury", "neptune", "uranus", "pluto",
    "planet", "planets", "moon", "moons", "orbit", "orbital", "galaxy", "galaxies", "star", "stars",
    "solar", "sun", "comet", "comets", "asteroid", "asteroids", "meteor", "meteors", "telescope",
    "hubble", "webb", "apollo", "voyager", "rover", "iss", "exoplanet", "nebula", "supernova",
    "cosmos", "astronomy", "astronaut", "rocket", "gravity", "black", "hole", "rings", "eclipse",
}

LEAD = re.compile(
    r"^\s*(?:please\s+)?(?:can you\s+|could you\s+)?(?:tell me about|tell me|explain|define|describe|"
    r"what is|what are|what was|what were|who is|who are|who was|where is|where are|how does|how do|"
    r"why is|why do)\s+", re.I)
TRAILING = re.compile(r"[\s?.!,;:]+$")
ARTICLES = re.compile(r"^(?:the|a|an)\s+", re.I)
STOP_TOPIC = {"it", "that", "this", "them", "those", "these", "him", "her", "you", "me", "us"}
# Social phrases are not subjects: linking them would staple a Wikipedia search onto "hello".
NON_TOPICS = {"how are you", "how are you doing", "how is it going", "whats up", "what is up",
              "hello", "hi", "hey", "yo", "thanks", "thank you", "bye", "goodbye", "good morning",
              "good afternoon", "good evening", "good night", "your name", "who are you",
              "what are you", "tell me about yourself", "what can you do", "help", "yes", "no"}


def topic(text: str) -> str:
    """The subject of a question, with the question scaffolding removed."""
    cleaned = LEAD.sub("", (text or "").strip())
    cleaned = TRAILING.sub("", cleaned)
    cleaned = ARTICLES.sub("", cleaned)
    lowered = cleaned.strip().lower()
    if lowered in STOP_TOPIC or len(lowered) < 2:
        return ""
    if lowered in NON_TOPICS:
        return ""
    if len(lowered.split()) > 6:
        return ""  # a sentence, not a subject
    return cleaned[:120]


def references(query: str, *, limit: int = 4) -> list[dict]:
    """Reference links for one topic, space topics getting their own two."""
    query = (query or "").strip()
    if not query:
        return []
    encoded = quote_plus(query)
    # Strip punctuation only: `strip(".,'s")` also eats the leading "s" of "saturn".
    words = {re.sub(r"[^a-z0-9-]", "", word) for word in re.split(r"[\s/]+", query.lower())}
    space = bool(words & SPACE_TERMS)
    links = [
        dict(label="Wikipedia (search)", site="wikipedia",
             url=f"https://en.wikipedia.org/w/index.php?search={encoded}"),
        dict(label="Britannica (search)", site="britannica",
             url=f"https://www.britannica.com/search?query={encoded}"),
    ]
    if space:
        links += [
            dict(label="NASA (search)", site="nasa", url=f"https://www.nasa.gov/?s={encoded}"),
            dict(label="Space.com (search)", site="space.com",
                 url=f"https://www.space.com/search?searchTerm={encoded}"),
        ]
    seen, unique = set(), []
    for link in links:
        if link["url"] in seen:
            continue
        seen.add(link["url"])
        unique.append(link)
    return unique[:limit]


def for_text(text: str, *, limit: int = 4) -> list[dict]:
    """Convenience: the links for the topic of an utterance, if it has one."""
    return references(topic(text), limit=limit)


def markdown(links: list[dict], *, heading: str = "Reference links") -> str:
    """A short markdown block. Says what the links are, and are not."""
    if not links:
        return ""
    lines = [f"**{heading}** · searches, not pages I read"]
    lines += [f"- [{link['label']}]({link['url']})" for link in links]
    return "\n".join(lines)


def block(text: str, *, limit: int = 4, heading: str = "Reference links") -> str:
    return markdown(for_text(text, limit=limit), heading=heading)


def has_links(text: str) -> bool:
    """True when an answer already carries markdown links, so we do not staple more on."""
    return bool(re.search(r"\]\(https?://", text or ""))
