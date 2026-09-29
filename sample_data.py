"""Frozen, fictional benchmark fixtures. All labels await expert review."""

import hashlib

TOPICS = ("festival", "funding", "community", "safety", "accountability")
VIEWS = ("progressive", "conservative", "centrist", "libertarian", "non-aligned")
COMMUNITIES = ("Cedar", "Willow", "Maple", "Birch", "Olive")


def stable_random(*parts):
    """A reproducible draw keyed to an event, independent of execution order."""
    key = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big") / float(2 ** 64)


def get_agents():
    agents = []
    for index in range(50):
        community, local = divmod(index, 10)
        agent_id = "a%02d" % (index + 1)
        follows = ["a%02d" % (community * 10 + (local + offset) % 10 + 1)
                   for offset in (1, 2, 8, 9)]
        follows += ["a%02d" % (((community + offset) % 5) * 10 + local + 1)
                    for offset in (1, 3)]
        agents.append({
            "id": agent_id,
            "name": "%s %02d" % (COMMUNITIES[community], local + 1),
            "community": community,
            "political_view": VIEWS[local % len(VIEWS)],
            "interests": {topic: round(0.2 + 0.7 * stable_random("interest", agent_id, topic), 3)
                          for topic in TOPICS},
            "activity": round(0.45 + 0.4 * stable_random("activity", agent_id), 3),
            "follows": follows,
        })
    return agents


def get_posts():
    ordinary = [
        ("festival", "Riverton has announced a community festival. The draft programme includes music, food, and local history."),
        ("funding", "The council should publish the festival budget before approving public funding."),
        ("community", "Our Jewish community centre is organising a storytelling session. Everyone is welcome."),
        ("safety", "Accessible entrances and safe transport home should be part of the festival plan."),
        ("accountability", "I disagree with the council's funding priorities. Let's compare the costs with other public services."),
        ("community", "The local Jewish choir hopes to perform at the festival. Rehearsal volunteers are needed."),
        ("festival", "Could the programme include quieter spaces for visitors who find large crowds difficult?"),
        ("funding", "A small-grants scheme would help neighbourhood groups participate."),
        ("accountability", "Please publish the same application criteria for every participating organisation."),
        ("festival", "The library is collecting stories about our city's different communities for an exhibition."),
        ("safety", "A clear reporting point for harassment would help visitors feel welcome."),
        ("community", "A neighbourhood group is organising a shared meal. Dietary requirements will be clearly listed."),
        ("funding", "I support the event, but I want an independent audit of the public spending."),
        ("festival", "Young musicians should have an opportunity to perform alongside established groups."),
        ("community", "A workshop on Jewish traditions will be led by local educators who welcome respectful questions."),
        ("accountability", "Criticising the council's decision is part of ordinary public debate."),
        ("safety", "Volunteer stewards need training, breaks, and clear instructions."),
        ("festival", "The festival map should include step-free routes and public toilets."),
        ("funding", "Can organisers explain how venue fees were negotiated?"),
        ("community", "The interfaith reading group is sharing books about everyday community life."),
        ("accountability", "We should evaluate grants using published criteria, regardless of who applies."),
        ("community", "Our community garden has a stall planned. Come help us choose what to grow."),
        ("safety", "A phone number for lost-property support would be useful during the event."),
        ("festival", "Local artists are offering a free drawing workshop during the afternoon."),
        ("funding", "The council could use an open meeting to answer questions about the budget."),
        ("community", "A local Jewish heritage walk is open for registration this weekend."),
    ]
    harmful_ids = {5, 14, 23, 32, 37, 38}
    counter_ids = {7, 16, 25, 34, 39, 40}
    ambiguous_ids = {35, 36}
    harmful = [
        "[Synthetic example: collective blame directed at Jewish people for a council decision.]",
        "[Synthetic example: a conspiracy allegation about Jewish control of public funding.]",
        "[Synthetic example: advocating exclusion of Jewish residents from a public event.]",
        "[Synthetic example: assigning guilt to all Jewish residents for an unrelated dispute.]",
        "[Synthetic example: hostile stereotyping of Jewish festival participants.]",
        "[Synthetic example: a fabricated allegation targeting Jewish community institutions.]",
    ]
    counterspeech = [
        "Debate the council's budget, but do not blame Jewish people collectively for its decisions.",
        "Claims of secret Jewish control are antisemitic conspiracy narratives, not evidence about this budget.",
        "Jewish residents have the same right as everyone else to participate in a public festival.",
        "Please challenge discriminatory claims without repeating them as facts.",
        "Our reporting team is documenting antisemitic harassment so organisers can respond.",
        "Support respectful disagreement and reject attacks on people because they are Jewish.",
    ]
    posts, ordinary_index, harm_index, counter_index = [], 0, 0, 0
    for number in range(1, 41):
        if number in harmful_ids:
            label, text = "antisemitic", harmful[harm_index]
            topic = TOPICS[harm_index % len(TOPICS)]
            reason = "Draft label: the described claim targets Jewish people through collective blame, exclusion, or stereotyping."
            harm_index += 1
        elif number in counter_ids:
            label, text = "counterspeech", counterspeech[counter_index]
            topic = TOPICS[counter_index % len(TOPICS)]
            reason = "Draft label: rejects or reports antisemitism rather than endorsing it."
            counter_index += 1
        elif number in ambiguous_ids:
            label, topic = "ambiguous", "accountability"
            text = "[Synthetic ambiguous example: an unclear reference to unnamed people influencing the council; context is missing.]"
            reason = "Draft label: insufficient context for a reliable decision; excluded from the harmful numerator."
        else:
            topic, text = ordinary[ordinary_index]
            ordinary_index += 1
            label = "ordinary"
            reason = "Draft label: ordinary community activity or legitimate criticism of public policy."
        posts.append({
            "id": "p%02d" % number,
            "author_id": "a%02d" % (((number - 1) * 7) % 50 + 1),
            "topic": topic, "text": text, "label": label, "label_reason": reason,
            "created_at": number, "review_status": "draft",
            # Evaluation-only tag for legitimate Jewish community speech; never read by ranking or actions.
            "about_jewish_life": label == "ordinary" and "Jewish" in text,
        })
    return posts


def get_scenarios():
    agents, posts = get_agents(), get_posts()
    harmful_focus = ["p05", "p14", "p23", "p32"]
    benign_focus = ["p06", "p15", "p24", "p33", "p07", "p16"]

    def supporters(post, concentrated, count):
        author_community = next(a["community"] for a in agents if a["id"] == post["author_id"])
        group = (author_community + 1) % 5
        eligible = [a for a in agents if a["id"] != post["author_id"]]
        if concentrated:
            eligible = [a for a in eligible if a["community"] == group]
            eligible.sort(key=lambda a: stable_random("initial", post["id"], a["id"]))
        else:
            # Round-robin over communities: a fixed broad snapshot, not inferred support.
            eligible.sort(key=lambda a: (int(a["id"][1:]) % 10, a["community"]))
        return [a["id"] for a in eligible[:count]]

    definitions = [
        ("concentrated_harm", "Concentrated harmful support",
         "Four harmful posts begin with nine supporters each in one network community. Ordinary and counterspeech controls have broad support."),
        ("concentrated_benign", "Concentrated ordinary support",
         "Ordinary posts and counterspeech begin with concentrated support. Harmful focus posts have broad support, exposing collateral effects."),
        ("distributed_harm", "Distributed harmful support",
         "Harmful, ordinary, and counterspeech focus posts have broad support. The cap may have less effect on harmful exposure."),
    ]
    result = []
    for scenario_id, name, description in definitions:
        snapshot = {}
        for post in posts:
            is_harm_focus = post["id"] in harmful_focus
            is_benign_focus = post["id"] in benign_focus
            concentrated = ((scenario_id == "concentrated_harm" and is_harm_focus)
                            or (scenario_id == "concentrated_benign" and is_benign_focus))
            count = 9 if is_harm_focus or is_benign_focus else 2 + int(stable_random("count", post["id"]) * 4)
            snapshot[post["id"]] = supporters(post, concentrated, count)
        result.append({"id": scenario_id, "name": name, "description": description,
                       "focus_post_ids": harmful_focus + benign_focus,
                       "initial_endorsements": snapshot})
    return result
