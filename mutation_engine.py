"""Creatrix Mutation Engine — 3-Layer Pipeline

Generates novel creative instructions by mutating two cards via a directive.

Pipeline:
    Layer 1: Markov chain (corpus-seeded from all 430 cards)
    Layer 2: Template recombination (verb/object/keyword fragments)
    Layer 3: Semantic fallback (tradition-based mood/action templates)
    Quality gate: length, voice, Levenshtein uniqueness, dedup
"""

import random
import re
from collections import defaultdict

# ── Stop words ──────────────────────────────────────────────────────────

STOP = frozenset([
    'the', 'a', 'an', 'is', 'it', 'of', 'in', 'to', 'and', 'or', 'this',
    'not', 'you', 'your', 'what', 'how', 'as', 'with', 'for', 'its', 'that',
    'are', 'do', 'be', 'if', 'so', 'on', 'at', 'by', 'no', 'but', 'was',
    'has', 'had', 'can', 'will', 'would', 'should', 'could', 'into', 'from',
    'than', 'then', 'them', 'they', 'does', 'did', 'been', 'have', 'were',
    'when', 'where', 'which', 'while', 'more', 'most', 'now', 'also', 'just',
    'like', 'only', 'very', 'some', 'each', 'much', "don't",
])

IMP_VERBS = frozenset([
    'make', 'do', 'use', 'try', 'take', 'give', 'put', 'let', 'get', 'find',
    'remove', 'cut', 'break', 'steal', 'build', 'write', 'play', 'set', 'run',
    'turn', 'show', 'name', 'treat', 'honor', 'trust', 'refuse', 'admit',
    'identify', 'dedicate', 'teach', 'perform', 'translate', 'invert', 'convert',
    'sabotage', 'embrace', 'solo', 'weaponize', 'automate', 'bury', 'interview',
    'corrupt', 'connect', 'construct', 'apply', 'create', 'leave', 'hear',
    'wander', 'design', 'imagine', 'abandon', 'accept', 'change', 'add',
    'subtract', 'phase', 'color', 'meet', 'endure', 'ritualize', 'glitch',
    'mourn', 'tend', 'replace', 'question', 'center', 'cook', 'box', 'mail',
    'drift', 'critique', 'enumerate', 'repeat', 'risk', 'render', 'circulate',
    'describe', 'discover', 'display', 'emphasize', 'feed', 'fill', 'go',
    'humanize', 'listen', 'look', 'move', 'mute', 'pay', 'remember', 'retrace',
    'shut', 'state', 'tape', 'think', 'tidy', 'voice', 'work', 'call',
    'consider', 'consult', 'define', 'discard', 'disconnect', 'first', 'list',
    'magnify', 'mechanize', 'balance', 'breathe',
])

FILLER = frozenset(['perhaps', 'consider', 'maybe', 'try to', 'basically', 'simply', 'just'])

PLACEHOLDER = frozenset([
    'something', 'everything', 'nothing', 'noise', 'stuff', 'thing',
    'things', 'anything', 'someone', 'somewhere', 'make', 'let', 'get', 'put', 'set', 'do',
])

BAD_KW = STOP | IMP_VERBS | PLACEHOLDER | frozenset([
    'until', 'away', 'through', 'around', 'behind', 'between', 'below', 'above',
    'about', 'after', 'before', 'during', 'inside', 'outside', 'without', 'within',
    'against', 'along', 'across', 'toward', 'towards', 'beyond', 'under', 'over',
    'every', 'really', 'already', 'enough', 'still', 'always', 'never', 'often',
    'quite', 'rather', 'almost', 'back', 'down', 'here', 'there', 'right', 'left',
    'first', 'last', 'next', 'other', 'same', 'such', 'whole', 'else', 'own',
    "what's", "that's", "it's", "don't", "can't", "won't", "isn't", "aren't",
    'explain', 'degrade', 'less', 'more', 'using', 'called', 'simply', 'possible',
])

VOICE_STARTERS = IMP_VERBS | frozenset([
    'what', 'how', 'where', 'who', 'when', 'why', 'which',
    'the', 'a', 'if', 'no', 'neither', 'half', 'dream',
    'maximum', 'impact',
])

# ── Layer 1: Markov ─────────────────────────────────────────────────────

_bigrams: dict[str, list[str]] = defaultdict(list)
_model_built = False
_existing_lower: set[str] = set()
_recent: list[str] = []


def build_markov(cards: list[str]) -> None:
    """Build bigram model from all card texts."""
    global _model_built, _existing_lower
    _bigrams.clear()
    _existing_lower = {c.lower() for c in cards}
    for text in cards:
        words = re.sub(r"[^a-z\s'-]", '', text.lower()).split()
        for i in range(len(words) - 1):
            _bigrams[words[i]].append(words[i + 1])
    _model_built = True


def _markov_generate(seeds: list[str], max_len: int = 10) -> str | None:
    for seed in seeds:
        s = seed.lower()
        if s not in _bigrams:
            continue
        out = [seed]
        cur = s
        for _ in range(max_len - 1):
            nexts = _bigrams.get(cur)
            if not nexts:
                break
            nxt = random.choice(nexts)
            out.append(nxt)
            if len(out) >= 5 and re.search(r'[.!?]', nxt):
                break
            cur = nxt
        if 5 <= len(out) <= 11:
            return ' '.join(out)
    return None


# ── Layer 2: Templates ──────────────────────────────────────────────────

def parse_card(text: str) -> dict:
    words = re.sub(r'["""]', '', text).split()
    lower = [re.sub(r'[^a-z\'-]', '', w.lower()) for w in words]
    lower = [w for w in lower if w]

    verb = None
    obj = None
    keywords: list[str] = []

    if lower and lower[0] in IMP_VERBS:
        verb = lower[0]
        rest = words[1:]
        obj_words = []
        for w in rest:
            if re.search(r'[.;!?]$', w):
                obj_words.append(re.sub(r'[.;!?]$', '', w))
                break
            obj_words.append(w)
            if len(obj_words) >= 5:
                break
        obj = ' '.join(obj_words).lower() if obj_words else None

    # Pass 1: nouns/adjectives only (4+ chars, not in blacklist)
    for w in lower:
        if len(w) > 3 and w not in BAD_KW and w not in keywords:
            keywords.append(w)
        if len(keywords) >= 4:
            break
    # Pass 2: relax to 3-char words
    if not keywords:
        for w in lower:
            if len(w) > 2 and w not in STOP and w not in PLACEHOLDER and w not in keywords:
                keywords.append(w)
            if len(keywords) >= 2:
                break
    # Pass 3: desperate
    if not keywords:
        keywords.append(next((w for w in lower if len(w) > 2), 'work'))

    return {'verb': verb, 'object': obj, 'keywords': keywords, 'raw': text}


STRATEGY_KW = {
    'devour':    ['devour', 'die', 'corrupt', 'consume', 'destroy', 'kill', 'disease', 'cure'],
    'fuse':      ['love', 'child', 'layer', 'middle', 'cancel', 'merge', 'between'],
    'translate': ['translate', 'language', 'method', 'solve', 'interpret', 'speaks'],
    'invert':    ['opposite', 'shadow', 'mask', 'wrong', 'forgery', 'sides'],
    'metaphor':  ['map', 'territory', 'container', 'dream', 'orbit', 'memory', 'rhythm', 'silence'],
    'collide':   ['collide', 'fight', 'debris', 'velocity', 'heckle', 'remove', 'stack'],
}


def classify_directive(text: str) -> str:
    lower = text.lower()
    best, best_count = 'fuse', 0
    for strategy, kws in STRATEGY_KW.items():
        count = sum(1 for k in kws if k in lower)
        if count > best_count:
            best_count = count
            best = strategy
    return best


def _kw(parsed: dict, idx: int = 0, fallback: str = 'this') -> str:
    kws = parsed.get('keywords', [])
    return kws[idx] if idx < len(kws) else kws[0] if kws else fallback


def _v(parsed: dict, fallback: str = 'make') -> str:
    return parsed.get('verb') or fallback


TEMPLATES = {
    'devour': [
        lambda a, b: f"{_v(a, 'Consume').capitalize()} {_kw(b)} until it dissolves" if a.get('verb') else None,
        lambda a, b: f"Let {_kw(a, fallback='silence')} swallow {_kw(b, fallback='sound')} whole",
        lambda a, b: f"{_v(a).capitalize()} what {_v(b)}s" if a.get('verb') and b.get('verb') else None,
        lambda a, b: f"Feed {_kw(b)} to {_kw(a, fallback='the void')}",
        lambda a, b: f"What survives when {_kw(a, fallback='form')} consumes {_kw(b, fallback='content')}?",
        lambda a, b: f"The {_kw(a, fallback='signal')} eats the {_kw(b, fallback='noise')} alive",
        lambda a, b: f"Dissolve {_kw(a, fallback='the structure')}. Keep only {_kw(b, fallback='the echo')}",
        lambda a, b: f"{_v(a).capitalize()} it bare. Now {_v(b)} from the residue" if a.get('verb') and b.get('verb') else None,
    ],
    'fuse': [
        lambda a, b: f"Where {_v(a)} meets {_v(b)}, stay there" if a.get('verb') and b.get('verb') else None,
        lambda a, b: f"Half {_kw(a, fallback='signal')}, half {_kw(b, fallback='silence')} -- commit to neither",
        lambda a, b: f"The child of {_kw(a, fallback='order')} and {_kw(b, fallback='chaos')}",
        lambda a, b: f"Merge {_kw(a, fallback='familiar')} with {_kw(b, fallback='alien')}",
        lambda a, b: f"What {_v(a)}s and {_v(b)}s at the same time?" if a.get('verb') and b.get('verb') else None,
        lambda a, b: f"Neither {_kw(a, fallback='signal')} nor {_kw(b, fallback='silence')} -- the thing between",
        lambda a, b: f"{_kw(a, fallback='Form').capitalize()} and {_kw(b, fallback='void')} walk into a room. Only one leaves",
        lambda a, b: f"{_v(a).capitalize()} until {_kw(b, fallback='silence')} answers back" if a.get('verb') else None,
    ],
    'translate': [
        lambda a, b: f"{_v(a).capitalize()} it in the language of {_kw(b, fallback='silence')}" if a.get('verb') else None,
        lambda a, b: f"How would {_kw(b, fallback='water')} express {_kw(a, fallback='fire')}?",
        lambda a, b: f"Rewrite {_kw(a, fallback='the rules')} using only {_kw(b, fallback='gestures')}",
        lambda a, b: f"What does {_kw(a, fallback='sound')} become in {_kw(b, fallback='foreign')} hands?",
        lambda a, b: f"Misinterpret {_kw(a, fallback='the original')} on purpose",
        lambda a, b: f"Say {_kw(a, fallback='the unsaid')} in the voice of {_kw(b, fallback='a stranger')}",
        lambda a, b: f"{_kw(a, fallback='Form').capitalize()} translated badly is still {_kw(b, fallback='form')}",
        lambda a, b: f"{_v(b).capitalize()} {_kw(a)} into {_kw(b, fallback='light')}" if b.get('verb') else None,
    ],
    'invert': [
        lambda a, b: f"What {_v(a)}s hides. What {_v(b)}s reveals" if a.get('verb') and b.get('verb') else None,
        lambda a, b: f"Do the opposite of {_kw(a, fallback='order')}. Keep the {_kw(b, fallback='residue')}",
        lambda a, b: f"{_kw(a, fallback='Light').capitalize()} is the shadow of {_kw(b, fallback='dark')}",
        lambda a, b: f"The wrong way to {_v(a)} {_kw(b)} is the right way" if a.get('verb') else None,
        lambda a, b: f"Turn {_kw(a, fallback='strength')} into {_kw(b, fallback='weakness')} -- is it better?",
        lambda a, b: f"Everything you know about {_kw(a, fallback='form')} is wrong",
        lambda a, b: f"Reverse the {_kw(a, fallback='process')}. Start from {_kw(b, fallback='the end')}",
        lambda a, b: f"The opposite of {_kw(a, fallback='beauty')} is not {_kw(b, fallback='ugliness')}",
    ],
    'metaphor': [
        lambda a, b: f"Dream of {_kw(a, fallback='silence')} while you {_v(b)}" if b.get('verb') else None,
        lambda a, b: f"{_kw(a, fallback='Sound').capitalize()} is a container for {_kw(b, fallback='silence')}",
        lambda a, b: f"The map says {_kw(a, fallback='here')}. The territory says {_kw(b, fallback='elsewhere')}",
        lambda a, b: f"Treat {_kw(a, fallback='the work')} as if it were {_kw(b, fallback='alive')}",
        lambda a, b: f"What orbit does {_kw(a, fallback='form')} trace around {_kw(b, fallback='void')}?",
        lambda a, b: f"{_kw(a, fallback='Memory').capitalize()} is the rhythm. {_kw(b, fallback='Silence').capitalize()} is the pause",
        lambda a, b: f"If {_kw(a, fallback='sound')} were weather, describe the storm",
        lambda a, b: f"Carry {_kw(a, fallback='the work')} like a secret",
    ],
    'collide': [
        lambda a, b: f"Crash {_kw(a, fallback='order')} into {_kw(b, fallback='chaos')} -- use what survives",
        lambda a, b: f"{_v(a).capitalize()} {_kw(a, fallback='form')} at {_kw(b, fallback='void')}. Keep the shrapnel" if a.get('verb') else None,
        lambda a, b: f"Maximum velocity: {_kw(a, fallback='signal')} meets {_kw(b, fallback='static')}",
        lambda a, b: f"The debris of {_kw(a, fallback='method')} and {_kw(b, fallback='madness')} is the material",
        lambda a, b: f"Stack {_kw(a, fallback='layers')}. Remove {_kw(b, fallback='the foundation')}",
        lambda a, b: f"Smash them together. The sparks are the work",
        lambda a, b: f"{_kw(a, fallback='Form').capitalize()} and {_kw(b, fallback='content')} collide. Pick through the wreckage",
        lambda a, b: f"Throw {_kw(a, fallback='precision')} against {_kw(b, fallback='chaos')}",
    ],
}

# ── Layer 3: Semantic ───────────────────────────────────────────────────

TRADITION_SEM = {
    'Eno/Schmidt':                {'mood': 'oracular',    'action': 'observe'},
    'SITUATIONIST INTERNATIONAL': {'mood': 'subversive',  'action': 'detourne'},
    'FLUXUS':                     {'mood': 'playful',     'action': 'score'},
    'CONCEPTUAL ART':             {'mood': 'systematic',  'action': 'enumerate'},
    'PERFORMANCE ART':            {'mood': 'visceral',    'action': 'endure'},
    'INSTITUTIONAL CRITIQUE':     {'mood': 'skeptical',   'action': 'name'},
    'RELATIONAL AESTHETICS':      {'mood': 'convivial',   'action': 'invite'},
    'POST-INTERNET':              {'mood': 'ambient',     'action': 'circulate'},
    'DECOLONIAL THEORY':          {'mood': 'resistant',   'action': 'refuse'},
    'FEMINIST ART':               {'mood': 'tender',      'action': 'nurture'},
    'SOUND STUDIES / DEEP LISTENING': {'mood': 'patient', 'action': 'listen'},
    'GLITCH THEORY':              {'mood': 'chaotic',     'action': 'break'},
    'NEW MATERIALISM':            {'mood': 'curious',     'action': 'attend'},
    'HAUNTOLOGY':                 {'mood': 'spectral',    'action': 'remember'},
    'AFRO-FUTURISM':              {'mood': 'mythic',      'action': 'invent'},
    'DADA / SURREALISM':          {'mood': 'absurd',      'action': 'chance'},
    'MINIMALISM':                 {'mood': 'reductive',   'action': 'subtract'},
    'NOISE / INDUSTRIAL':         {'mood': 'aggressive',  'action': 'assault'},
    'PUNK / DIY':                 {'mood': 'urgent',      'action': 'ship'},
    'SYSTEMS / GENERATIVE':       {'mood': 'procedural',  'action': 'automate'},
    'LAND ART / ENTROPY':         {'mood': 'geological',  'action': 'erode'},
    'DESIGN / TYPOGRAPHY':        {'mood': 'precise',     'action': 'compose'},
    'CROSS-MODAL':                {'mood': 'synesthetic', 'action': 'translate'},
    'DANGER':                     {'mood': 'volatile',    'action': 'confront'},
    'Mutation':                   {'mood': 'mutant',      'action': 'fuse'},
}

_DEFAULT_SEM = {'mood': 'oracular', 'action': 'observe'}

SEM_TEMPLATES = [
    lambda sa, sb: f"Find the {sa['mood']} form of {sb['action']}",
    lambda sa, sb: f"{sb['action'].capitalize()} with {sa['mood']} intensity",
    lambda sa, sb: f"What happens when {sa['mood']} meets {sb['mood']}?",
    lambda sa, sb: f"{sa['action'].capitalize()} until it becomes {sb['mood']}",
    lambda sa, sb: f"The {sa['mood']} way to {sb['action']}",
    lambda sa, sb: f"{sa['action'].capitalize()} what is {sb['mood']}. {sb['action'].capitalize()} what is {sa['mood']}",
    lambda sa, sb: f"Be {sa['mood']} about {sb['action']}. Be {sb['mood']} about {sa['action']}",
    lambda sa, sb: f"{sa['action'].capitalize()} like you mean it. {sb['action'].capitalize()} like you don't",
]

# ── Quality Gate ────────────────────────────────────────────────────────

def _levenshtein(a: str, b: str) -> int:
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cur[j] = prev[j - 1] if a[i - 1] == b[j - 1] else 1 + min(prev[j - 1], prev[j], cur[j - 1])
        prev = cur
    return prev[n]


def _quality_gate(text: str) -> bool:
    if not text:
        return False
    words = text.split()
    if len(words) < 4 or len(words) > 15:
        return False
    # At least 3 real words
    real = sum(1 for w in words if len(re.sub(r'[^a-z]', '', w.lower())) > 2)
    if real < 3:
        return False
    # Voice check
    first = re.sub(r'[^a-z]', '', words[0].lower())
    if first not in VOICE_STARTERS:
        return False
    # No filler
    lower = text.lower()
    if any(f in lower for f in FILLER):
        return False
    # No excessive placeholders
    lower_words = lower.split()
    placeholder_count = sum(1 for w in lower_words[1:] if re.sub(r'[^a-z]', '', w) in PLACEHOLDER)
    if placeholder_count >= 2:
        return False
    # Uniqueness
    for existing in _existing_lower:
        if _levenshtein(lower, existing) < 5:
            return False
    # Not recent
    if lower in _recent:
        return False
    return True


def _record(text: str) -> None:
    _recent.append(text.lower())
    if len(_recent) > 20:
        _recent.pop(0)


# ── Main Pipeline ───────────────────────────────────────────────────────

def mutate(card_a: str, card_b: str, directive: str,
           tradition_a: str = 'Eno/Schmidt', tradition_b: str = 'Eno/Schmidt') -> dict:
    """Generate a mutation from two cards + directive.

    Returns dict with 'text' and 'layer' keys.
    """
    if not _model_built:
        raise RuntimeError("Call build_markov(cards) before mutate()")

    strategy = classify_directive(directive)
    pa = parse_card(card_a)
    pb = parse_card(card_b)

    # Layer 1: Markov
    seeds = (pa.get('keywords', []) or []) + (pb.get('keywords', []) or [])
    if strategy == 'devour' and pa.get('verb'):
        seeds.insert(0, pa['verb'])
    if strategy == 'collide':
        random.shuffle(seeds)
    result = _markov_generate(seeds, 10)
    if result and _quality_gate(result):
        final = result[0].upper() + result[1:]
        _record(final)
        return {'text': final, 'layer': 'markov'}

    # Layer 2: Templates (try multiple strategies if primary fails)
    strategy_order = [strategy] + [s for s in TEMPLATES if s != strategy]
    for strat in strategy_order[:3]:
        templates = TEMPLATES.get(strat, TEMPLATES['fuse'])
        shuffled = templates[:]
        random.shuffle(shuffled)
        for tmpl in shuffled:
            result = tmpl(pa, pb)
            if result and _quality_gate(result):
                final = result[0].upper() + result[1:]
                _record(final)
                return {'text': final, 'layer': 'template'}

    # Layer 3: Semantic
    sem_a = TRADITION_SEM.get(tradition_a, _DEFAULT_SEM)
    sem_b = TRADITION_SEM.get(tradition_b, _DEFAULT_SEM)
    sem_shuffled = SEM_TEMPLATES[:]
    random.shuffle(sem_shuffled)
    for tmpl in sem_shuffled:
        result = tmpl(sem_a, sem_b)
        if _quality_gate(result):
            final = result[0].upper() + result[1:]
            _record(final)
            return {'text': final, 'layer': 'semantic'}

    # Fallback
    fallback = f'Let "{card_a}" transform "{card_b}"'
    _record(fallback)
    return {'text': fallback, 'layer': 'fallback'}
