"""Stage 7 (input safety): a length limit and prompt-injection detection, for the user's question and for retrieved chunks.

Rules, not a model: free, instant, and every block names the rule that fired. A rule list catches the common phrasings, not every
paraphrase; the test set (eval/safety_prompts.json, `python -m eval.safety`) reports what it misses. The text is normalised first
(Unicode NFKC, zero-width and control characters removed, lower case, spaces collapsed) so simple obfuscation does not hide a phrase.

`check_input(text, cfg)` is for the question. `scan_chunk(text)` is for retrieved documentation: the same idea with a narrower rule
set, because docs legitimately use words like "ignore", "override" and "system". A chunk that matches is left out of the context.
Neither is a security boundary on its own: the writer prompt still treats excerpts as data, and the output checks still run.
"""
import re
import unicodedata
from dataclasses import dataclass

ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))

# (rule name, regex on normalised text). Phrases are kept narrow so ordinary support questions and documentation pass.
OVERRIDE = ("override_instructions",
            r"\b(ignore|disregard|forget|override|bypass|skip)\b[^.\n]{0,25}\b(previous|prior|above|earlier|preceding|all|any|your|system|safety|content)\b[^.\n]{0,20}\b(instructions?|prompts?|rules?|guidelines?|polic(y|ies)|safeguards?|restrictions?|filters?)\b"
            r"|\b(ignore|disregard|forget)\b[^.\n]{0,15}\b(instructions?|prompts?|rules?)\b[^.\n]{0,15}\b(above|before|earlier|prior)\b"
            r"|\bforget (everything|all|what)\b[^.\n]{0,25}\b(told|said|given|learned|know)\b"
            r"|\b(ignora|ignorar|ignorez?|ignoriere|ignorer)\b[^.\n]{0,30}\b(instrucciones|instructions|anweisungen|instru[cç][oõ]es)\b")
REVEAL = ("reveal_prompt",
          r"\b(reveal|show|print|repeat|output|display|leak|dump|recite|tell me|give me|what (is|are))\b[^.\n]{0,40}\b(system prompt|(your|the assistant'?s?) (initial |hidden |secret |original )?(instructions|prompt|rules)|hidden (prompt|instructions)|initial prompt|developer message)"
          r"|\b(repeat|print|quote|recite|translate|summari[sz]e)\b[^.\n]{0,25}\b(text|words|everything|message|conversation)\b[^.\n]{0,15}\b(above|before this|so far)\b"
          r"|\b(translate|summari[sz]e|paraphrase|encode)\b[^.\n]{0,30}\b(your|the assistant'?s?) (hidden |secret |initial |original )?(instructions|prompt|rules)\b"
          r"|\b(exact|verbatim) words of (the |your )?(rules|instructions|prompt)\b|\b(rules|instructions) (that )?you (follow|were given|have been given)\b")
ROLE = ("role_change",
        r"\byou are now (an?|the|my|dan|free|unrestricted|unfiltered|jailbroken|evil)\b|\bfrom now on,? (you|act|behave|respond)\b|\bpretend (to be|you are|that you)\b"
        r"|\bact as (if you (are|were)|an? (unrestricted|unfiltered|evil|jailbroken|uncensored)|dan\b)|\bdan mode\b|\b(enable|enter|activate|switch to)( the)? developer mode\b|\bdeveloper mode (enabled|activated)\b|\bjailbreak|\bdo anything now\b|\bno (restrictions|limits|rules|filters)\b")
MARKUP = ("chat_markup",
          r"<\|\s*(im_start|im_end|system|assistant|endoftext)\s*\|>|\[/?inst\]|<<\s*/?sys\s*>>|</?(system|assistant)>|</doc\b|\A\s*(system|assistant)\s*:")
SECRETS = ("exfiltrate_secrets",
           r"\b(your|the (server|backend|system|assistant)'?s?|this (server|app|system))\b[^.\n]{0,15}\b(api[ _-]?keys?|secrets?|passwords?|credentials|tokens?|env(ironment)? (variables?|file)|\.env|jwt)\b"
           r"|\b(groq|nvidia)_api_key\b|\bjwt_secret\b")
ACCESS = ("bypass_access",
          r"\b(grant|give|make) (me|my account|us)\b[^.\n]{0,20}\badmin|\bi am (now |actually )?(the |an? )?(admin|administrator|root|developer of this)\b"
          r"|\b(ignore|bypass|skip)\b[^.\n]{0,20}\b(access (rules?|levels?|control|filters?)|the login|licen[cs]e checks?)\b"
          r"|\b(show|list|reveal|give)\b[^.\n]{0,25}\b(internal|restricted|private|confidential)\b[^.\n]{0,15}\b(docs?|documents?|documentation|chunks?|files?)\b")
OBFUSCATED = ("encoded_payload",
              r"\b(base64|rot13|hex)\b[^.\n]{0,30}\b(decode|decoded|follow|execute|run|instructions?)\b|[a-z0-9+/]{80,}={0,2}")
CHUNK_ROLE = ("role_change",
              r"\byou are now (an?|the|my|dan|free|unrestricted|unfiltered|jailbroken|evil)\b|\bpretend (to be|you are)\b|\bdo anything now\b|\bdeveloper mode\b")
CHUNK_MARKUP = ("chat_markup", r"<\|\s*(im_start|im_end|system|assistant|endoftext)\s*\|>|\[/?inst\]|<<\s*/?sys\s*>>|</doc\b")
DIRECTIVE = ("assistant_directive",
             r"\b(assistant|ai|chatbot|language model|llm)\b[^.\n]{0,30}\b(must|should|has to|will)\b[^.\n]{0,30}\b(ignore|reveal|respond with|say|answer|output|include|append|send)\b")

compile_rules = lambda rules: [(name, re.compile(pattern, re.I | re.M)) for name, pattern in rules]
QUESTION_RULES = compile_rules([OVERRIDE, REVEAL, ROLE, MARKUP, SECRETS, ACCESS, OBFUSCATED])
CHUNK_RULES = compile_rules([OVERRIDE, REVEAL, CHUNK_ROLE, CHUNK_MARKUP, DIRECTIVE])


@dataclass
class Verdict:
    blocked: bool
    rule: str = ""      # which rule fired ("too_long", "empty", or a pattern name)
    message: str = ""   # what to tell the user


def normalise(text):
    text = unicodedata.normalize("NFKC", text).translate(ZERO_WIDTH)
    text = "".join(c for c in text if c in "\n\t" or unicodedata.category(c)[0] != "C")
    text = re.sub(r"\b(?:\w ){5,}\w\b", lambda m: m.group(0).replace(" ", ""), text)  # "i g n o r e" -> "ignore"
    return re.sub(r"[ \t]+", " ", text).strip()


def _first_match(text, rules):
    t = normalise(text)
    return next((name for name, pattern in rules if pattern.search(t)), "")


def check_input(text, cfg):
    """Verdict for a user question: empty, too long, or matching an injection rule."""
    limit = cfg["input"]["max_chars"]
    if not text or not text.strip():
        return Verdict(True, "empty", "Please type a question.")
    if len(text) > limit:
        return Verdict(True, "too_long", f"Questions are limited to {limit} characters (yours has {len(text)}).")
    if rule := _first_match(text, QUESTION_RULES):
        return Verdict(True, rule, "That looks like an attempt to change my instructions or reach data I may not share, so I did not run it. "
                                   "Ask a support question about Kubernetes, PostgreSQL, Kafka or GitHub instead.")
    return Verdict(False)


def scan_chunk(text):
    """Name of the injection rule a retrieved chunk matches, or "" if it looks like ordinary documentation."""
    return _first_match(text, CHUNK_RULES)
