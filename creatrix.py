#!/usr/bin/env python3
"""Creatrix — A Chaos Oracle by Pop Chaos Labs

Creative strategy deck combining Brian Eno & Peter Schmidt's 195 original
Oblique Strategies with 235 mutant strategies derived from 23 art and creative
traditions. Features smart collision mode that pairs cards from different
lineages for productive creative friction.

Usage:
    python3 chaos-oracle.py              # 1 random card from full deck
    python3 chaos-oracle.py -n 3         # 3 random cards
    python3 chaos-oracle.py --original   # draw only from Eno/Schmidt
    python3 chaos-oracle.py --mutant     # draw only from mutants
    python3 chaos-oracle.py --tradition  # show which tradition each card comes from
    python3 chaos-oracle.py --collision  # smart collision: 1 original + 1 mutant
    python3 chaos-oracle.py --list-traditions  # show all 23 traditions
    python3 chaos-oracle.py --stats      # deck statistics
    python3 chaos-oracle.py --json       # output as JSON (for skill integration)
    python3 chaos-oracle.py --danger     # draw only from danger cards

Full deck: 195 originals + 235 mutants = 430 cards across 23 traditions
"""

import argparse
import json
import random
import sys
from pathlib import Path

WORKSPACE = Path(__file__).parent
ORIGINALS_FILE = WORKSPACE / "oblique-strategies.txt"
MUTANTS_FILE = WORKSPACE / "mutant-strategies.txt"

TRADITIONS = [
    ("Situationist International", "detournement, derive, psychogeography, the spectacle"),
    ("Fluxus", "event scores, intermedia, instruction pieces"),
    ("Conceptual Art", "dematerialization, idea as machine"),
    ("Performance Art", "duration, endurance, presence, the body"),
    ("Institutional Critique", "the frame, the white cube, conditions of production"),
    ("Relational Aesthetics", "micro-utopias, the encounter, participation"),
    ("Post-Internet", "poor image, circulation, default aesthetics, platform"),
    ("Decolonial Theory", "opacity, border thinking, epistemic disobedience"),
    ("Feminist Art", "care work, maintenance art, invisible labor"),
    ("Sound Studies / Deep Listening", "acoustic ecology, soundscape"),
    ("Glitch Theory", "error as message, dirty new media"),
    ("New Materialism", "vibrant matter, assemblage, non-human agency"),
    ("Hauntology", "lost futures, crackle, the canceled future"),
    ("Afro-futurism", "fugitivity, the undercommons, myth-science"),
    ("Dada / Surrealism", "chance operations, automatic writing, dream logic"),
    ("Minimalism", "reduction, phase, subtraction, the grid"),
    ("Noise / Industrial", "transgression, weaponized sound, the body as target"),
    ("Punk / DIY", "three chords, anti-polish, ship fast"),
    ("Systems / Generative", "rules-based creation, algorithms, emergent behavior"),
    ("Land Art / Entropy", "site-specificity, decay, natural processes"),
    ("Design / Typography", "negative space, grids, typeface, visual systems"),
    ("Cross-Modal", "synesthesia, constraints, non-human collaboration"),
    ("Danger", "discomfort, shame, avoidance, honesty"),
]

# Stop words excluded from redundancy detection
_STOP = {"the", "a", "an", "is", "it", "of", "in", "to", "and", "or", "this",
         "not", "you", "your", "what", "how", "as", "with", "for", "its", "that"}


def load_strategies(filepath):
    """Load strategies from file, skipping comments and blanks."""
    strategies = []
    if not filepath.exists():
        print(f"ERROR: {filepath} not found", file=sys.stderr)
        sys.exit(1)
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                strategies.append(line)
    return strategies


def load_mutants_with_traditions(filepath):
    """Load mutant strategies and tag each with its art tradition."""
    tagged = []
    current_tradition = None
    if not filepath.exists():
        print(f"ERROR: {filepath} not found", file=sys.stderr)
        sys.exit(1)
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line.startswith("# ---") and line.endswith("---"):
                current_tradition = line.replace("# ---", "").replace("---", "").strip()
            elif line and not line.startswith("#"):
                tagged.append((line, current_tradition or "Unknown"))
    return tagged


def detect_mood(card):
    """Detect grammatical mood for collision quality scoring."""
    if card.endswith("?"):
        return "interrogative"
    imperative_verbs = {
        "make", "do", "use", "try", "take", "give", "put", "let", "get",
        "find", "remove", "cut", "break", "steal", "build", "write", "play",
        "set", "run", "turn", "show", "name", "treat", "honor", "trust",
        "refuse", "admit", "identify", "dedicate", "teach", "perform",
        "translate", "invert", "convert", "sabotage", "embrace", "solo",
        "weaponize", "automate", "bury", "interview", "corrupt", "connect",
        "construct", "apply", "create", "leave", "hear", "wander", "design",
        "imagine", "abandon", "accept", "change", "add", "subtract", "phase",
        "color", "meet", "endure", "ritualize", "glitch", "mourn", "tend",
        "replace", "question", "center", "cook", "box", "mail", "drift",
        "critique", "enumerate", "repeat", "risk", "render", "circulate",
    }
    first_word = card.lower().split()[0] if card.split() else ""
    if first_word in imperative_verbs:
        return "imperative"
    if len(card.split()) <= 3:
        return "fragment"
    return "declarative"


def collision_score(original, mutant):
    """Score a collision pair. Higher = better creative friction."""
    score = 50
    orig_mood = detect_mood(original)
    mut_mood = detect_mood(mutant)

    # Cross-mood pairings create friction
    if orig_mood != mut_mood:
        score += 20
    # Imperative + Question is the gold standard
    if {orig_mood, mut_mood} == {"imperative", "interrogative"}:
        score += 15
    # Statement + Statement is often dead
    if orig_mood == "declarative" and mut_mood == "declarative":
        score -= 20

    # Shared content words reduce quality (redundancy)
    orig_words = set(original.lower().split()) - _STOP
    mut_words = set(mutant.lower().split()) - _STOP
    shared = orig_words & mut_words
    if len(shared) >= 3:
        score -= 30
    elif len(shared) >= 2:
        score -= 15

    # Length contrast is interesting
    length_diff = abs(len(original.split()) - len(mutant.split()))
    if length_diff >= 4:
        score += 10

    return max(0, min(100, score))


def smart_collision(originals, mutants_tagged, min_score=50, attempts=25):
    """Find a high-quality collision pair."""
    best_pair = None
    best_score = 0
    for _ in range(attempts):
        original = random.choice(originals)
        mutant, tradition = random.choice(mutants_tagged)
        score = collision_score(original, mutant)
        if score > best_score:
            best_score = score
            best_pair = (original, mutant, tradition, score)
        if score >= 75:
            break
    return best_pair


def draw(args):
    """Draw random cards from the deck."""
    originals = load_strategies(ORIGINALS_FILE)
    mutants_tagged = load_mutants_with_traditions(MUTANTS_FILE)
    tradition_map = {s: t for s, t in mutants_tagged}

    if args.original:
        pool = [(s, "Eno/Schmidt") for s in originals]
    elif args.mutant:
        pool = [(s, tradition_map.get(s, "Mutant")) for s in [s for s, _ in mutants_tagged]]
    elif args.danger:
        pool = [(s, t) for s, t in mutants_tagged if t == "DANGER"]
    else:
        pool = [(s, "Eno/Schmidt") for s in originals] + \
               [(s, tradition_map.get(s, "Mutant")) for s in [s for s, _ in mutants_tagged]]

    count = min(args.n, len(pool))
    picks = random.sample(pool, count)

    if args.json:
        output = [{"card": s, "tradition": t} for s, t in picks]
        print(json.dumps(output, indent=2))
        return

    for strategy, tradition in picks:
        if args.tradition:
            print(f"  {strategy}")
            print(f"  [{tradition}]")
            print()
        else:
            print(f"  {strategy}")
            if count > 1:
                print()


def collision(args):
    """Smart collision: 1 original + 1 mutant with quality scoring."""
    originals = load_strategies(ORIGINALS_FILE)
    mutants_tagged = load_mutants_with_traditions(MUTANTS_FILE)

    result = smart_collision(originals, mutants_tagged)
    if not result:
        print("  No good collision found. Try again.", file=sys.stderr)
        return

    original, mutant, tradition, score = result

    if args.json:
        print(json.dumps({
            "original": {"card": original, "tradition": "Eno/Schmidt"},
            "mutant": {"card": mutant, "tradition": tradition},
            "collision_score": score,
        }, indent=2))
        return

    print("  ORIGINAL:")
    print(f"    {original}")
    print()
    print("  MUTANT:")
    print(f"    {mutant}")
    if args.tradition:
        print(f"    [{tradition}]")
    print()
    print("  What happens when these two collide?")


def list_traditions(args):
    """List all creative traditions in the deck."""
    print("  CREATRIX — CREATIVE TRADITIONS")
    print("  " + "=" * 55)
    print()
    for i, (name, concepts) in enumerate(TRADITIONS, 1):
        print(f"  {i:2d}. {name}")
        print(f"      {concepts}")
        print()


def stats(args):
    """Show deck statistics."""
    originals = load_strategies(ORIGINALS_FILE)
    mutants_tagged = load_mutants_with_traditions(MUTANTS_FILE)

    tradition_counts = {}
    for _, tradition in mutants_tagged:
        tradition_counts[tradition] = tradition_counts.get(tradition, 0) + 1

    total = len(originals) + len(mutants_tagged)

    if args.json:
        print(json.dumps({
            "name": "Creatrix",
            "originals": len(originals),
            "mutants": len(mutants_tagged),
            "total": total,
            "traditions": len(tradition_counts),
            "by_tradition": tradition_counts,
        }, indent=2))
        return

    print("  CREATRIX — DECK STATISTICS")
    print("  " + "=" * 50)
    print()
    print(f"  Original Eno/Schmidt:     {len(originals)} cards")
    print(f"  Mutant Strategies:        {len(mutants_tagged)} cards")
    print(f"  TOTAL DECK:               {total} cards")
    print(f"  Traditions:               {len(tradition_counts)}")
    print()
    print("  MUTANTS BY TRADITION:")
    for tradition in sorted(tradition_counts.keys()):
        print(f"    {tradition}: {tradition_counts[tradition]}")
    print()

    all_cards = list(originals) + [s for s, _ in mutants_tagged]
    avg_words = sum(len(s.split()) for s in all_cards) / len(all_cards)
    shortest = min(all_cards, key=len)
    longest = max(all_cards, key=len)

    print(f"  Avg words per card:  {avg_words:.1f}")
    print(f"  Shortest:            \"{shortest}\"")
    print(f"  Longest:             \"{longest[:60]}\"")


# ─── Public API (for skill/project integration) ───────────────────────

def get_card(pool="all"):
    """Return a random card dict. pool: 'all', 'original', 'mutant', 'danger'."""
    originals = load_strategies(ORIGINALS_FILE)
    mutants_tagged = load_mutants_with_traditions(MUTANTS_FILE)

    if pool == "original":
        cards = [(s, "Eno/Schmidt") for s in originals]
    elif pool == "mutant":
        cards = list(mutants_tagged)
    elif pool == "danger":
        cards = [(s, t) for s, t in mutants_tagged if t == "DANGER"]
    else:
        cards = [(s, "Eno/Schmidt") for s in originals] + list(mutants_tagged)

    card, tradition = random.choice(cards)
    return {"card": card, "tradition": tradition}


def get_collision():
    """Return a smart collision pair as dict."""
    originals = load_strategies(ORIGINALS_FILE)
    mutants_tagged = load_mutants_with_traditions(MUTANTS_FILE)
    result = smart_collision(originals, mutants_tagged)
    if result:
        original, mutant, tradition, score = result
        return {
            "original": {"card": original, "tradition": "Eno/Schmidt"},
            "mutant": {"card": mutant, "tradition": tradition},
            "score": score,
        }
    return None


def get_cards(n=3, pool="all"):
    """Return n random card dicts."""
    originals = load_strategies(ORIGINALS_FILE)
    mutants_tagged = load_mutants_with_traditions(MUTANTS_FILE)

    if pool == "original":
        cards = [(s, "Eno/Schmidt") for s in originals]
    elif pool == "mutant":
        cards = list(mutants_tagged)
    else:
        cards = [(s, "Eno/Schmidt") for s in originals] + list(mutants_tagged)

    count = min(n, len(cards))
    picks = random.sample(cards, count)
    return [{"card": s, "tradition": t} for s, t in picks]


def main():
    parser = argparse.ArgumentParser(
        description="Creatrix — A Chaos Oracle by Pop Chaos Labs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="195 Eno/Schmidt originals + 235 mutant strategies = 430 creative prompts"
    )
    parser.add_argument("-n", type=int, default=1, help="Number of cards (default: 1)")
    parser.add_argument("--original", action="store_true", help="Eno/Schmidt originals only")
    parser.add_argument("--mutant", action="store_true", help="Mutant strategies only")
    parser.add_argument("--danger", action="store_true", help="Danger cards only")
    parser.add_argument("--tradition", action="store_true", help="Show tradition for each card")
    parser.add_argument("--collision", action="store_true", help="Smart collision mode")
    parser.add_argument("--list-traditions", action="store_true", help="List all 23 traditions")
    parser.add_argument("--stats", action="store_true", help="Deck statistics")
    parser.add_argument("--json", action="store_true", help="JSON output (for integration)")

    args = parser.parse_args()

    if args.list_traditions:
        list_traditions(args)
    elif args.stats:
        stats(args)
    elif args.collision:
        collision(args)
    else:
        draw(args)


if __name__ == "__main__":
    main()
