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
    'consider', 'consult', 'define', 'discard', 'disconnect', 'list',
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
    'those', 'these', 'even', 'done', 'meant', 'owed', 'sudden', 'actually',
    'recently', 'suddenly', "wouldn't", "couldn't", "shouldn't", 'itself',
    'himself', 'herself', 'themselves', 'myself', 'maybe', 'either', 'another',
    'reveals', 'survives', 'hurts', 'hides', 'becomes', 'carries', 'shows',
    'controls', 'remains', 'frightened', 'disconnected', 'embarrassing',
    'performing', 'repeating', 'lives', 'means', 'says', 'serves', 'exists',
    'needs', 'wants', 'seems', 'looks', 'feels', 'different', 'deeply',
    'worse', 'worst', 'real', 'lowest', 'missing',
    'avoid', 'capture', 'safe', 'sure', 'hard', 'long', 'quite', 'fast',
    'slow', 'big', 'silence', 'taught', 'paid', 'open', 'close', 'began',
    'spoken', 'chosen', 'driven',
])

VOICE_STARTERS = IMP_VERBS | frozenset([
    'what', 'how', 'where', 'who', 'when', 'why', 'which',
    'the', 'a', 'if', 'no', 'neither', 'half', 'dream',
    'maximum', 'impact',
    # Template-specific verbs
    'hollow', 'dissolve', 'strip', 'graft', 'breed', 'sew',
    'say', 'misinterpret', 'whisper', 'rewrite', 'everything',
    'reverse', 'swap', 'carry', 'weigh', 'crash', 'throw',
    'pick', 'stack', 'force', 'detonate', 'drag',
])

# ── Layer 1: Markov ─────────────────────────────────────────────────────

_bigrams: dict[str, list[str]] = defaultdict(list)
_model_built = False
_existing_lower: set[str] = set()
_recent: list[str] = []
_noun_scores: dict[str, int] = {}
_recent_template_ids: list[str] = []
_all_word_lists: list[list[str]] = []


def build_markov(cards: list[str]) -> None:
    """Build bigram model + noun scores from all card texts."""
    global _model_built, _existing_lower
    _bigrams.clear()
    _noun_scores.clear()
    _all_word_lists.clear()
    _existing_lower = {c.lower() for c in cards}
    for text in cards:
        words = re.sub(r"[^a-z\s'-]", '', text.lower()).split()
        _all_word_lists.append(words)
        for i in range(len(words) - 1):
            _bigrams[words[i]].append(words[i + 1])
    # Fix 1: Noun-quality scoring — words after verbs are likely nouns
    for words in _all_word_lists:
        for i in range(len(words) - 1):
            if words[i] in IMP_VERBS:
                nxt = words[i + 1]
                if nxt and len(nxt) > 2 and nxt not in STOP:
                    _noun_scores[nxt] = _noun_scores.get(nxt, 0) + 1
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
        if 5 <= len(out) <= 9:
            return ' '.join(out)
    return None


# ── Layer 2: Templates ──────────────────────────────────────────────────

_NOUN_SUFFIXES = re.compile(r'(?:tion|sion|ness|ment|ity|ence|ance|ism|ist|ure|age)$')
_ADJ_SUFFIXES = re.compile(r'(?:ful|less|ous|ive|ent|ant|ible|able|ical|etic)$')
_VERB_SUFFIXES = re.compile(r'(?:ized|ated|ified|izing|ating|ifying)$')


def parse_card(text: str) -> dict:
    words = re.sub(r'["""]', '', text).split()
    lower = [re.sub(r'[^a-z\'-]', '', w.lower()) for w in words]
    lower = [w for w in lower if w]

    verb = None
    obj = None
    keywords: list[str] = []
    nouns: list[str] = []
    adjectives: list[str] = []

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

    # Fix 1+3: Scored keyword extraction with POS classification
    candidates = []
    seen = set()
    for w in lower:
        if len(w) > 3 and w not in BAD_KW and w not in seen:
            # Skip verb forms — they make bad template fills
            if _VERB_SUFFIXES.search(w):
                continue
            # Skip 3rd person forms of known verbs (breaks→break, happens→happen)
            if w.endswith('s') and len(w) > 4 and (w[:-1] in IMP_VERBS or w[:-1] in BAD_KW):
                continue
            if w.endswith('es') and len(w) > 5 and (w[:-2] in IMP_VERBS or w[:-2] in BAD_KW):
                continue
            noun_score = _noun_scores.get(w, 0) + (2 if _NOUN_SUFFIXES.search(w) else 0)
            is_adj = bool(_ADJ_SUFFIXES.search(w))
            candidates.append((w, noun_score, is_adj))
            seen.add(w)
        if len(candidates) >= 6:
            break
    # Sort by noun score descending
    candidates.sort(key=lambda x: -x[1])
    for w, _, is_adj in candidates:
        if len(keywords) < 4:
            keywords.append(w)
        if is_adj:
            if w not in adjectives:
                adjectives.append(w)
        else:
            if w not in nouns:
                nouns.append(w)

    # Pass 2: relax to 3-char words (still check BAD_KW to prevent verb/adverb leaks)
    if not keywords:
        for w in lower:
            if len(w) > 2 and w not in BAD_KW and w not in keywords:
                keywords.append(w)
            if len(keywords) >= 2:
                break
    # Pass 3: desperate
    if not keywords:
        keywords.append(next((w for w in lower if len(w) > 2), 'work'))
    if not nouns:
        nouns.append(keywords[0] if keywords else 'work')

    return {'verb': verb, 'object': obj, 'keywords': keywords, 'nouns': nouns,
            'adjectives': adjectives, 'raw': text}


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


def _kw(parsed: dict, idx: int = 0, fallback: str = 'work') -> str:
    """Return keyword as a grammatical noun phrase with article."""
    kws = parsed.get('keywords', [])
    word = kws[idx] if idx < len(kws) else kws[0] if kws else None
    if word is None:
        return f'the {fallback}'
    return f'the {word}'


def _tn(parsed: dict) -> str:
    """Return pre-picked tradition-themed noun for this card."""
    return parsed.get('_tn', 'work')


def _v(parsed: dict, fallback: str = 'make') -> str:
    return parsed.get('verb') or fallback


TEMPLATES = {
    'devour': [
        lambda a, b: f"{_v(a).capitalize()} the {_tn(b)} until only {_tn(a)} remains" if a.get('verb') else None,
        lambda a, b: f"Hollow out the {_tn(a)}. Fill it with {_tn(b)}",
        lambda a, b: f"Feed the {_tn(a)} to the {_tn(b)}",
        lambda a, b: f"What does {_tn(a)} taste like after {_tn(b)} consumes it?",
        lambda a, b: f"Let the {_tn(b)} rot. Plant {_tn(a)} in the remains",
        lambda a, b: f"Dissolve the {_tn(b)}. Keep only the stain",
        lambda a, b: f"Strip it down to {_tn(a)}. Then strip that too",
        lambda a, b: f"The {_tn(a)} swallowed the {_tn(b)}. What changed inside?",
    ],
    'fuse': [
        lambda a, b: f"Half {_tn(a)}, half {_tn(b)} -- commit to neither",
        lambda a, b: f"Graft the {_tn(b)} onto the {_tn(a)}. Where does it take?",
        lambda a, b: f"Make a {_tn(a)} entirely from {_tn(b)}",
        lambda a, b: f"{_v(a).capitalize()} the {_tn(b)} and the {_tn(a)} at once" if a.get('verb') else None,
        lambda a, b: f"Breed {_tn(a)} with {_tn(b)}. Raise the runt",
        lambda a, b: f"Sew the {_tn(a)} to the {_tn(b)}. Follow the seam",
        lambda a, b: f"Find where {_tn(a)} becomes {_tn(b)}. Work only there",
        lambda a, b: f"What would the child of {_tn(a)} and {_tn(b)} rebel against?",
    ],
    'translate': [
        lambda a, b: f"Say {_tn(a)} in the language of {_tn(b)}",
        lambda a, b: f"Misinterpret the {_tn(a)} on purpose. Keep the error",
        lambda a, b: f"Translate {_tn(b)} into {_tn(a)}. Lose something on the way",
        lambda a, b: f"{_v(a).capitalize()} it as if {_tn(b)} were the only alphabet" if a.get('verb') else None,
        lambda a, b: f"Whisper the {_tn(a)} through {_tn(b)}. What distorts?",
        lambda a, b: f"Rewrite the {_tn(a)} using only {_tn(b)}",
        lambda a, b: f"What accent does {_tn(b)} give to {_tn(a)}?",
        lambda a, b: f"Write instructions for {_tn(a)} in a language you forgot",
    ],
    'invert': [
        lambda a, b: f"Do the opposite of {_tn(a)}. Notice what you protect",
        lambda a, b: f"Turn the {_tn(a)} inside out. Is {_tn(b)} still there?",
        lambda a, b: f"The wrong way to handle the {_tn(a)} is the right way",
        lambda a, b: f"Everything you know about the {_tn(a)} is wrong. Start over",
        lambda a, b: f"Reverse the {_tn(a)}. Start from {_tn(b)}",
        lambda a, b: f"Swap the {_tn(a)} and the {_tn(b)}. Which improved?",
        lambda a, b: f"{_v(a).capitalize()} it backwards. What does {_tn(b)} reveal?" if a.get('verb') else None,
        lambda a, b: f"The {_tn(a)} is hiding behind the {_tn(b)}. Expose it",
    ],
    'metaphor': [
        lambda a, b: f"Carry the {_tn(a)} like a secret through the {_tn(b)}",
        lambda a, b: f"What orbit does {_tn(a)} trace around {_tn(b)}?",
        lambda a, b: f"Treat the {_tn(a)} as if it were alive and angry",
        lambda a, b: f"If the {_tn(a)} could speak, what would it say about the {_tn(b)}?",
        lambda a, b: f"Weigh the {_tn(a)} against the {_tn(b)}. Which is heavier?",
        lambda a, b: f"Dream of {_tn(a)} while you {_v(b)} the {_tn(b)}" if b.get('verb') else None,
        lambda a, b: f"The {_tn(a)} is a door. The {_tn(b)} is behind it",
        lambda a, b: f"What would {_tn(a)} look like from inside the {_tn(b)}?",
    ],
    'collide': [
        lambda a, b: f"Crash {_tn(a)} into {_tn(b)}. Use what survives",
        lambda a, b: f"Throw {_tn(a)} at {_tn(b)} at full speed. Keep the shrapnel",
        lambda a, b: f"Pick through the wreckage of {_tn(a)} and {_tn(b)}",
        lambda a, b: f"Stack {_tn(a)} on {_tn(b)}. Remove the load-bearing one",
        lambda a, b: f"Force {_tn(a)} and {_tn(b)} together. Keep only what fused",
        lambda a, b: f"Detonate the {_tn(a)} inside the {_tn(b)}. What survived?",
        lambda a, b: f"Drag {_tn(b)} across {_tn(a)} until something catches fire",
        lambda a, b: f"The {_tn(a)} and {_tn(b)} collided. Sift through the dust",
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

# Concrete noun pools per tradition — used in template layer instead of keywords
TRADITION_NOUNS = {
    'Eno/Schmidt': ['process', 'accident', 'edge', 'garden', 'tape', 'wire', 'gap'],
    'SITUATIONIST INTERNATIONAL': ['map', 'billboard', 'route', 'spectacle', 'wall', 'street'],
    'FLUXUS': ['postcard', 'instruction', 'score', 'box', 'title', 'event'],
    'CONCEPTUAL ART': ['system', 'list', 'rule', 'sentence', 'document', 'plan'],
    'PERFORMANCE ART': ['body', 'gesture', 'skin', 'breath', 'floor', 'hour'],
    'INSTITUTIONAL CRITIQUE': ['frame', 'label', 'wall', 'receipt', 'name', 'contract'],
    'RELATIONAL AESTHETICS': ['table', 'meal', 'invitation', 'guest', 'gift', 'conversation'],
    'POST-INTERNET': ['file', 'screen', 'pixel', 'thumbnail', 'feed', 'copy'],
    'DECOLONIAL THEORY': ['border', 'tongue', 'root', 'wound', 'center', 'margin'],
    'FEMINIST ART': ['thread', 'kitchen', 'labor', 'mirror', 'care', 'needle'],
    'SOUND STUDIES / DEEP LISTENING': ['room', 'echo', 'breath', 'field', 'hum', 'ground'],
    'GLITCH THEORY': ['signal', 'artifact', 'codec', 'noise', 'pixel', 'static'],
    'NEW MATERIALISM': ['grain', 'surface', 'ecology', 'mineral', 'hum', 'fossil'],
    'HAUNTOLOGY': ['tape', 'ghost', 'memory', 'ruin', 'signal', 'dust'],
    'AFRO-FUTURISM': ['orbit', 'drum', 'void', 'code', 'ship', 'rhythm'],
    'DADA / SURREALISM': ['scissors', 'dream', 'hat', 'accident', 'mirror', 'clock'],
    'MINIMALISM': ['grid', 'silence', 'edge', 'gap', 'phase', 'tone'],
    'NOISE / INDUSTRIAL': ['metal', 'machine', 'concrete', 'wire', 'pressure', 'teeth'],
    'PUNK / DIY': ['tape', 'dirt', 'stage', 'fist', 'demo', 'wall'],
    'SYSTEMS / GENERATIVE': ['rule', 'seed', 'loop', 'pattern', 'clock', 'chain'],
    'LAND ART / ENTROPY': ['dirt', 'stone', 'weather', 'root', 'fossil', 'rust'],
    'DESIGN / TYPOGRAPHY': ['grid', 'margin', 'weight', 'space', 'surface', 'ink'],
    'CROSS-MODAL': ['smell', 'weight', 'temperature', 'tongue', 'skin', 'color'],
    'DANGER': ['wound', 'mirror', 'edge', 'confession', 'nerve', 'bone'],
    'Mutation': ['fragment', 'residue', 'debris', 'chimera', 'wreckage', 'splice'],
}
_DEFAULT_NOUNS = TRADITION_NOUNS['Eno/Schmidt']

SEM_TEMPLATES = [
    lambda sa, sb: f"Find the {sa['mood']} form of {sb['action']}",
    lambda sa, sb: f"{sb['action'].capitalize()} with {sa['mood']} intensity",
    lambda sa, sb: f"What happens when {sa['mood']} meets {sb['mood']}?",
    lambda sa, sb: f"{sa['action'].capitalize()} until it becomes {sb['mood']}",
    lambda sa, sb: f"Take the {sa['mood']} approach to {sb['action']}",
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
    # Fix 5: Grammar post-check — catch broken syntax
    broken_patterns = [
        re.compile(r'\b(the|a|an)\s+(make|do|use|try|take|give|break|steal|build|write|play|set|run|turn|show)\b', re.I),
        re.compile(r'\b(of|in|to|from|with)\s+(is|are|was|were)\b', re.I),
        re.compile(r'\b(its|your|their|our)\s*[.!?]?\s*$', re.I),
        re.compile(r'\b(\w+)\s+\1\b', re.I),
        re.compile(r'\b(the|a)\s+(the|a)\b', re.I),
        re.compile(r'\bthe\s+\w+ly\b', re.I),  # "the directly", "the honestly" — adverbs
        re.compile(r'\bthe\s+(anyone|everyone|someone|nobody|somebody|nothing|everything|something)\b', re.I),
        re.compile(r"\bthe\s+\w+'s\b", re.I),  # "the children's" — possessives
        re.compile(r"\bthe\s+\w+'t\b", re.I),  # "the don't", "the can't" — contractions
        re.compile(r'\bthe\s+\w+\s+the\s+\w+\s+the\b', re.I),  # triple "the" in 5 words
    ]
    for pattern in broken_patterns:
        if pattern.search(text):
            return False
    # Not recent
    if lower in _recent:
        return False
    return True


def _record(text: str) -> None:
    _recent.append(text.lower())
    if len(_recent) > 20:
        _recent.pop(0)


# ── Variant Engine (post-processing) ──────────────────────────────────

def _variant_gate(text: str) -> bool:
    """Lighter quality gate for post-processed variants."""
    if not text:
        return False
    words = text.split()
    if len(words) < 4 or len(words) > 15:
        return False
    real = sum(1 for w in words if len(re.sub(r'[^a-z]', '', w.lower())) > 2)
    if real < 3:
        return False
    lower = text.lower()
    if any(f in lower for f in FILLER):
        return False
    for existing in _existing_lower:
        if _levenshtein(lower, existing) < 5:
            return False
    if lower in _recent:
        return False
    return True


def _pick_variant(text: str, tn_a: str, tn_b: str) -> str:
    """Generate up to 6 variants, pick one randomly.

    Variants: raw, first-clause, second-clause, inverted, compressed, negated.
    """
    variants = [text]  # E: raw original

    # A/B: Split at natural breaks → first and second clauses
    for sep in ['. ', ' -- ', ', ']:
        if sep in text:
            parts = text.split(sep, 1)
            first_half = parts[0].strip().rstrip('.')
            second_half = parts[1].strip()
            if len(first_half.split()) >= 4:
                variants.append(first_half)
            if second_half and len(second_half.split()) >= 4:
                variants.append(second_half[0].upper() + second_half[1:])
            break

    # D: Inverted — swap the two tradition nouns
    if tn_a and tn_b and tn_a != tn_b:
        lower = text.lower()
        if tn_a in lower and tn_b in lower:
            inv = re.sub(r'\b' + re.escape(tn_a) + r'\b', '\x00', text, flags=re.I)
            inv = re.sub(r'\b' + re.escape(tn_b) + r'\b', tn_a, inv, flags=re.I)
            inv = inv.replace('\x00', tn_b)
            if inv != text:
                variants.append(inv)

    # C: Compressed — drop articles before tradition nouns
    compressed = text
    for noun in [tn_a, tn_b]:
        if noun:
            compressed = re.sub(r'\bthe\s+(' + re.escape(noun) + r')\b', r'\1',
                                compressed, flags=re.I)
    if compressed != text and len(compressed.split()) >= 4:
        variants.append(compressed)

    # F: Negated wildcard
    words = text.split()
    first_clean = re.sub(r'[^a-z]', '', words[0].lower())
    if first_clean in IMP_VERBS:
        negated = "Don't " + words[0].lower() + " " + " ".join(words[1:])
        variants.append(negated)

    # Filter and pick
    valid = [v for v in variants if _variant_gate(v)]
    if not valid:
        return text
    chosen = random.choice(valid)
    return chosen[0].upper() + chosen[1:]


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

    # Tradition noun pools for template layer
    nouns_a = TRADITION_NOUNS.get(tradition_a, _DEFAULT_NOUNS)
    nouns_b = TRADITION_NOUNS.get(tradition_b, _DEFAULT_NOUNS)

    # Layer 1: Markov — DISABLED (produces broken grammar too often)
    # Goes straight to template layer which produces consistently cleaner output.

    # Layer 2: Templates (try multiple strategies if primary fails)
    strategy_order = [strategy] + [s for s in TEMPLATES if s != strategy]
    for strat in strategy_order[:3]:
        templates = TEMPLATES.get(strat, TEMPLATES['fuse'])
        # Fix 2: Template fingerprint dedup
        indexed = [(t, f"{strat}:{i}") for i, t in enumerate(templates)]
        random.shuffle(indexed)
        for tmpl, tid in indexed:
            if tid in _recent_template_ids:
                continue
            # Re-pick tradition nouns for each attempt (variety + no collision)
            pa['_tn'] = random.choice(nouns_a)
            nb_candidates = [n for n in nouns_b if n != pa['_tn']]
            pb['_tn'] = random.choice(nb_candidates or nouns_b)
            result = tmpl(pa, pb)
            if result and _quality_gate(result):
                raw = result[0].upper() + result[1:]
                final = _pick_variant(raw, pa.get('_tn', ''), pb.get('_tn', ''))
                _record(final)
                _recent_template_ids.append(tid)
                if len(_recent_template_ids) > 5:
                    _recent_template_ids.pop(0)
                return {'text': final, 'layer': 'template'}

    # Layer 3: Semantic
    sem_a = TRADITION_SEM.get(tradition_a, _DEFAULT_SEM)
    sem_b = TRADITION_SEM.get(tradition_b, _DEFAULT_SEM)
    sem_shuffled = SEM_TEMPLATES[:]
    random.shuffle(sem_shuffled)
    for tmpl in sem_shuffled:
        result = tmpl(sem_a, sem_b)
        if _quality_gate(result):
            raw = result[0].upper() + result[1:]
            final = _pick_variant(raw, '', '')
            _record(final)
            return {'text': final, 'layer': 'semantic'}

    # Fallback
    fallback = f'Let "{card_a}" transform "{card_b}"'
    _record(fallback)
    return {'text': fallback, 'layer': 'fallback'}
