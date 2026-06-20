"""robots.txt parsing and matching.

The Python standard library's ``urllib.robotparser`` does not faithfully handle
wildcard (``*``) / end-anchor (``$``) patterns or Google's *longest-match-wins*
precedence — and Yad2's robots.txt relies heavily on rules like
``Disallow: /*?*price=`` and ``Allow: /realestate/rent?shelter=1``. So we
implement the matcher ourselves, following Google's robots.txt specification:

* A rule's path pattern may contain ``*`` (any sequence) and ``$`` (end of URL).
* Matching is done against the URL's ``path`` + ``?query``.
* Among all matching Allow/Disallow rules, the one with the **longest** pattern
  wins; on a tie, **Allow** wins.
* If no rule matches, the URL is allowed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class _Rule:
    allow: bool
    pattern: str
    regex: re.Pattern = field(init=False)
    length: int = field(init=False)

    def __post_init__(self) -> None:
        self.regex = _compile_pattern(self.pattern)
        self.length = len(self.pattern)


def _compile_pattern(pattern: str) -> re.Pattern:
    """Translate a robots.txt path pattern into an anchored regex."""
    parts = ["^"]
    for ch in pattern:
        if ch == "*":
            parts.append(".*")
        elif ch == "$":
            parts.append("$")
        else:
            parts.append(re.escape(ch))
    return re.compile("".join(parts))


@dataclass
class RobotsRules:
    """Parsed rules + crawl-delay for the user-agent group that applies to us."""

    rules: list[_Rule]
    crawl_delay: float | None = None
    allow_all: bool = False

    def can_fetch(self, path_with_query: str) -> bool:
        if self.allow_all or not self.rules:
            return True
        best: _Rule | None = None
        for rule in self.rules:
            if rule.regex.match(path_with_query):
                if best is None:
                    best = rule
                elif rule.length > best.length:
                    best = rule
                elif rule.length == best.length and rule.allow and not best.allow:
                    best = rule
        return True if best is None else best.allow


def parse_robots(text: str, user_agent: str) -> RobotsRules:
    """Parse robots.txt text and return the rule group that applies to us.

    We select the most specific matching user-agent group: a group whose token
    (case-insensitively) appears in ``user_agent`` is preferred over the
    wildcard ``*`` group. Yad2 only publishes a ``*`` group, which we honor.
    """
    ua_lower = user_agent.lower()
    # groups: list of (agent_tokens, rules, crawl_delay)
    groups: list[tuple[set[str], list[_Rule], float | None]] = []
    cur_agents: set[str] | None = None
    cur_rules: list[_Rule] = []
    cur_delay: float | None = None
    expecting_agent = False  # are we in a run of consecutive User-agent lines?

    def flush() -> None:
        nonlocal cur_agents, cur_rules, cur_delay
        if cur_agents is not None:
            groups.append((cur_agents, cur_rules, cur_delay))
        cur_agents, cur_rules, cur_delay = None, [], None

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name = field_name.strip().lower()
        value = value.strip()

        if field_name == "user-agent":
            if not expecting_agent:
                flush()
                cur_agents = set()
            if cur_agents is None:
                cur_agents = set()
            cur_agents.add(value.lower())
            expecting_agent = True
            continue

        expecting_agent = False
        if cur_agents is None:
            continue
        if field_name == "disallow":
            if value == "":
                continue  # empty Disallow means "allow everything"
            cur_rules.append(_Rule(allow=False, pattern=value))
        elif field_name == "allow":
            if value:
                cur_rules.append(_Rule(allow=True, pattern=value))
        elif field_name == "crawl-delay":
            try:
                cur_delay = float(value)
            except ValueError:
                pass
    flush()

    # Pick the most specific applicable group.
    specific: tuple[set[str], list[_Rule], float | None] | None = None
    wildcard: tuple[set[str], list[_Rule], float | None] | None = None
    for agents, rules, delay in groups:
        for token in agents:
            if token == "*":
                wildcard = (agents, rules, delay)
            elif token and token in ua_lower:
                # Prefer the longest (most specific) matching token.
                if specific is None or len(token) > max((len(t) for t in specific[0] if t in ua_lower), default=0):
                    specific = (agents, rules, delay)

    chosen = specific or wildcard
    if chosen is None:
        return RobotsRules(rules=[], allow_all=True)
    _agents, rules, delay = chosen
    return RobotsRules(rules=rules, crawl_delay=delay)
