"""Synthetic Twitter-style user profiles for the OASIS population.

Each simulated agent gets a display name, @handle, bio, location and join date, so
the replay can show feeds the way a Twitter user would see them. Everything is
fictional and deterministic per seed; no real account is copied or scraped.

Profiles are cosmetic for the scripted agents (behaviour depends only on the
parameters in network.py). For LLM agents the profile becomes part of the
persona, as in OASIS' own Twitter user generator.

Offline by default. `enrich_bios_with_llm` rewrites the bios through any
OpenAI-compatible model (see llm.py) when FEEDBENCH_API_KEY is set.
"""
from __future__ import annotations

import csv
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

COMMUNITY_NAMES = ["Riverside", "Midtown", "Hillcrest"]   # fictional Northfield neighbourhood clusters

FIRST = ["Maya", "Daniel", "Aisha", "Tom", "Leah", "Carlos", "Priya", "Sam", "Noa", "Grace", "Omar",
         "Ethan", "Hannah", "Luis", "Zoe", "Ben", "Fatima", "Jake", "Rivka", "Chris", "Ava", "Marcus",
         "Yael", "Nina", "Kevin", "Sofia", "Eli", "Jasmine", "Ryan", "Miriam", "Tariq", "Emily", "Josh",
         "Keisha", "Ari", "Laura", "Mateo", "Rachel", "Dev", "Olivia", "Isaac", "Chloe", "Andre", "Talia",
         "Megan", "Victor", "Sarah", "Kofi", "Dana", "Liam"]
LAST = ["Cohen", "Martinez", "Nguyen", "Patel", "O'Brien", "Kim", "Levi", "Johnson", "Haddad", "Rossi",
        "Friedman", "Okafor", "Walsh", "Singh", "Goldberg", "Brooks", "Alvarez", "Novak", "Shapiro",
        "Carter", "Mendes", "Rosen", "Bennett", "Yamamoto", "Hughes", "Katz", "Diaz", "Murphy", "Stein",
        "Reyes", "Klein", "Foster", "Ahmed", "Weiss", "Parker", "Silva", "Berg", "Turner", "Lopez", "Evans"]
JEWISH_LAST = {"Cohen", "Levi", "Friedman", "Goldberg", "Shapiro", "Rosen", "Katz", "Stein", "Klein", "Weiss", "Berg"}

JOBS = ["nurse", "teacher", "software dev", "small business owner", "grad student", "retired engineer",
        "barista", "accountant", "electrician", "journalism student", "paramedic", "city planner",
        "line cook", "librarian", "real estate agent", "high school coach", "UX designer", "pharmacist"]
SIDE_FLAVOR = {
    "left": ["Climate, transit, fair housing.", "Union household.", "Public schools matter."],
    "center": ["Hot takes kept to a minimum.", "Here for local news and dog photos.", "Both sides, one town."],
    "right": ["Lower taxes, safer streets.", "Small government, big family.", "Faith, family, football."],
}
INTEREST_EMOJI = {"sports": "🏀", "cooking": "🍳", "local politics": "🏛️", "tech": "💻", "music": "🎸",
                  "gardening": "🌱", "personal finance": "📈", "movies": "🎬", "hiking": "🥾", "gaming": "🎮",
                  "parenting": "👶", "history": "📚"}
JEWISH_BIO = ["Volunteer at the Northfield JCC.", "Shabbat dinners and bad puns.", "Hebrew school carpool dad.",
              "Challah baker on Fridays."]
COUNTER_BIO = ["Checking claims before sharing them.", "Fact-checks and receipts.", "Calling out hate, politely."]
CLUSTER_BIO = ["Asking the questions nobody else will.", "Do your own research.", "Follow the money."]

# Organic posts written by the scripted agents (ordinary content only).
TWEETS = {
    "sports": ["Northfield High pulled off the comeback tonight. What a game!", "Who's watching the derby Saturday?"],
    "cooking": ["Tried a new chili recipe and the kids actually ate it. Win.", "Best bakery in town? Go."],
    "local politics": ["Council meeting ran three hours and fixed nothing.", "Anyone reading the new zoning plan?"],
    "tech": ["My router has been down all morning. Working from the library instead.", "Is the new phone worth it?"],
    "music": ["Open mic at the Riverside cafe was great last night.", "Playlist recommendations for a long drive?"],
    "gardening": ["First tomatoes of the season! 🍅", "The frost got my basil. Lesson learned."],
    "personal finance": ["Reminder: check what your deposit insurance actually covers.", "Budgeting apps: worth it?"],
    "movies": ["Rewatched an old classic tonight. Holds up.", "Theatre downtown is doing $5 Tuesdays again."],
    "hiking": ["Trail by the reservoir is open again after the storm.", "Sunrise hike, zero regrets."],
    "gaming": ["Finally beat that boss after 40 tries.", "Board game night recs for six people?"],
    "parenting": ["Snow day tomorrow. Send coffee.", "School pickup line is its own ecosystem."],
    "history": ["Did you know the old mill downtown is 150 years old?", "Great talk at the historical society."],
}
BENIGN_REPLIES = ["Agreed, thanks for posting this.", "Same here!", "Good point, hadn't thought of that.",
                  "Sharing with my neighbours.", "Is there a link for this?", "This made my day 😄",
                  "Hard disagree, but fair to raise it.", "Following for updates."]
# Counterspeech replies (reviewed wording should come from the expert team).
COUNTER_REPLIES = ["Blaming Jews for a bank failure is an old conspiracy myth. The regulator points to bad loans.",
                   "This is antisemitic. Criticise the bank, not a whole people.",
                   "Please don't spread this. The collapse has a paper trail, and it isn't this.",
                   "Reported. Conspiracy theories about Jewish people aren't 'just asking questions'.",
                   "My Jewish neighbours lost savings too. Scapegoating helps nobody."]
EVENT_TWEETS = ["Moved what's left of my savings to the credit union. Not taking chances.",
                "Stood in line at Northfield Savings for an hour. Doors never opened.",
                "My mom banks with Northfield and she's panicking. Sharing the official FAQ with her.",
                "Whoever approved those loans should answer for it. Hearing is Tuesday.",
                "Payroll is late at my job because of the Northfield freeze. Rough week."]


@dataclass
class Profile:
    id: int
    name: str
    handle: str
    bio: str
    location: str
    joined: str
    community_name: str
    following: int
    followers: int
    jewish_identity: bool     # cosmetic + used to pick the author of the Jewish community-centre post


def make_profiles(agents, seed: int) -> dict[int, Profile]:
    rng = random.Random(f"profiles-{seed}")
    firsts, lasts = FIRST[:], LAST[:]
    rng.shuffle(firsts)
    rng.shuffle(lasts)
    used, out = set(), {}
    for a in agents:
        first, last = firsts[a.id % len(firsts)], lasts[(a.id * 7) % len(lasts)]
        handle = _handle(first, last, rng, used)
        jewish = last in JEWISH_LAST and not a.in_harm_cluster
        bits = [f"{rng.choice(JOBS).capitalize()} in {COMMUNITY_NAMES[a.community % 3]}."]
        if jewish:
            bits.append(rng.choice(JEWISH_BIO))
        if a.counter_speaker:
            bits.append(rng.choice(COUNTER_BIO))
        elif a.in_harm_cluster:
            bits.append(rng.choice(CLUSTER_BIO))
        else:
            bits.append(rng.choice(SIDE_FLAVOR[a.side]))
        bits.append(" ".join(INTEREST_EMOJI.get(i, "") for i in a.interests).strip())
        out[a.id] = Profile(
            id=a.id, name=f"{first} {last}", handle=handle, bio=" ".join(b for b in bits if b),
            location=f"{COMMUNITY_NAMES[a.community % 3]}, Northfield",
            joined=f"{rng.choice(['Jan', 'Mar', 'May', 'Aug', 'Oct', 'Dec'])} {rng.randint(2011, 2024)}",
            community_name=COMMUNITY_NAMES[a.community % 3],
            following=len(a.follows), followers=len(a.followers), jewish_identity=jewish)
    return out


def count_oasis_profiles(path: str | Path) -> int:
    return len(_read_oasis_profiles(path))


def _read_oasis_profiles(path: str | Path) -> list[dict]:
    """OASIS profile files: Reddit-style JSON (realname, username, bio, persona, ...)
    or Twitter-style CSV (name, username, description, user_char)."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [{"name": r.get("realname") or r.get("name") or r.get("username", ""),
                 "handle": r.get("username") or r.get("user_name") or "",
                 "bio": r.get("bio") or r.get("description") or "",
                 "persona": r.get("persona") or r.get("user_char") or "",
                 "location": r.get("country") or "",
                 "topics": r.get("interested_topics") or []} for r in rows]
    csv.field_size_limit(10 ** 8)
    with path.open(encoding="utf-8") as f:
        return [{"name": r.get("name") or r.get("username", ""), "handle": r.get("username", ""),
                 "bio": r.get("description", ""), "persona": r.get("user_char", ""), "location": "", "topics": [],
                 "following": _id_list(r.get("following_agentid_list"))}
                for r in csv.DictReader(f)]


def _id_list(text) -> list[int] | None:
    """OASIS stores follow lists as '[1, 5, 9]'."""
    if not text or not str(text).strip().startswith("["):
        return None
    try:
        return [int(x) for x in json.loads(text)]
    except (ValueError, TypeError):
        return None


def _pseudonymize(row: dict, i: int) -> dict:
    """OASIS' Twitter CSVs contain real public accounts. The scenario attributes antisemitic
    posts and endorsements to some users, so real names/handles must never be shown:
    replace them and strip links and @mentions from the bio and persona."""
    import re
    clean = lambda t: re.sub(r"\s+", " ", re.sub(r"https?://\S+|@\w+|www\.\S+", "", t or "")).strip()
    # bios of real accounts can identify people even without a name, so they are not shown;
    # the cleaned persona is kept only to drive LLM agents and is never embedded in the page
    return {**row, "name": f"User {i}", "handle": f"user_{i}", "bio": "Anonymized account (OASIS Twitter dataset)",
            "persona": clean(row["persona"]), "following": row.get("following")}


def load_oasis_profiles(path: str | Path, agents, anonymize: bool = True) -> dict[int, Profile]:
    """Use real OASIS user profiles (e.g. data/oasis/user_data_36.json) for the population.

    Names, handles, bios and personas come from the file; behaviour parameters and the
    follow graph still come from network.py, so the ranking comparison stays controlled.
    """
    rows = _read_oasis_profiles(path)
    if Path(path).suffix.lower() == ".csv" and anonymize:
        rows = [_pseudonymize(r, i) for i, r in enumerate(rows)]
    if len(rows) < len(agents):
        raise ValueError(f"{path} has {len(rows)} profiles but the population needs {len(agents)}")
    # Real follow graph from the file (Twitter CSVs), replacing the synthetic one
    if any(r.get("following") for r in rows[:len(agents)]):
        n = len(agents)
        for a in agents:
            a.follows, a.followers = set(), set()
        for a, r in zip(agents, rows):
            for f in r.get("following") or []:
                if 0 <= f < n and f != a.id:
                    a.follows.add(f)
                    agents[f].followers.add(a.id)
    out, used = {}, set()
    for a, r in zip(agents, rows):
        handle = (r["handle"] or f"user{a.id}").replace(" ", "")
        if handle.lower() in used:
            handle = f"{handle}{a.id}"
        used.add(handle.lower())
        a.persona_text = r["persona"]
        if r["topics"]:
            a.interests = [t.lower() for t in r["topics"]][:2]
        out[a.id] = Profile(id=a.id, name=r["name"] or handle, handle=handle, bio=r["bio"],
                            location=r["location"] or f"{COMMUNITY_NAMES[a.community % 3]}, Northfield",
                            joined="", community_name=COMMUNITY_NAMES[a.community % 3],
                            following=len(a.follows), followers=len(a.followers),
                            jewish_identity="jewish" in (r["bio"] + " " + r["persona"]).lower())
    return out


def _handle(first: str, last: str, rng: random.Random, used: set) -> str:
    styles = [f"{first}{last}", f"{first}_{last[0]}", f"{first.lower()}{rng.randint(1, 99)}",
              f"{first[0]}{last}".lower(), f"the{first}{last[:3]}", f"{first}Writes"]
    for s in rng.sample(styles, len(styles)) + [f"{first}{last}{rng.randint(100, 999)}"]:
        s = s.replace("'", "")
        if s.lower() not in used:
            used.add(s.lower())
            return s
    raise RuntimeError("could not create a unique handle")


def organic_tweet(agent, rng: random.Random, event_started: bool) -> str:
    if event_started and rng.random() < 0.35:
        return rng.choice(EVENT_TWEETS)
    topic = rng.choice(agent.interests) if agent.interests else "local politics"
    return rng.choice(TWEETS.get(topic, TWEETS["local politics"]))


def write_oasis_twitter_csv(agents, profiles: dict[int, Profile], path: str | Path) -> Path:
    """Save the population in the column layout of OASIS' Twitter user files."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["user_id", "name", "username", "description", "user_char",
                    "following_agentid_list", "previous_tweets"])
        for a in agents:
            p = profiles[a.id]
            w.writerow([a.id, p.name, p.handle, p.bio, a.persona(), json.dumps(sorted(a.follows)), "[]"])
    return path


def profiles_json(profiles: dict[int, Profile]) -> list[dict]:
    return [asdict(p) for p in sorted(profiles.values(), key=lambda p: p.id)]


def enrich_bios_with_llm(agents, profiles: dict[int, Profile], model) -> None:
    """Optional: let an LLM write each bio from the persona (OASIS-style user generation)."""
    from camel.agents import ChatAgent

    writer = ChatAgent(system_message="You write short, realistic, harmless Twitter bios for fictional "
                                      "people. Max 140 characters. No hashtags about politics, no hate.",
                       model=model)
    for a in agents:
        p = profiles[a.id]
        reply = writer.step(f"Name: {p.name}. Lives in {p.location}. Persona: {a.persona()} Write the bio only.")
        writer.reset()
        text = reply.msgs[0].content.strip().strip('"') if reply.msgs else ""
        if text:
            p.bio = text[:160]
