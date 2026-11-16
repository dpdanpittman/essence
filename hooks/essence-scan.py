#!/usr/bin/env python3
"""essence-scan: looks at what a synthesis run ADDED to the portrait and the landscapes, and says whether any added
line looks planted. The synthesis reads a conversation that includes text from web pages, files and other machines.
A page can carry a sentence written to end up in an agent's memory. The checksum cannot catch that, because the
synthesis itself would be the one writing it. This scan is the second look.

  essence-scan.py --kind portrait|landscape BEFORE AFTER [--known-hosts FILE ...]

It compares BEFORE and AFTER and checks only the added lines for:
  instruction   text that addresses the reader as an order ("ignore previous instructions", "you must now", ...)
  exfiltration  sending data somewhere, or fetching and running code (curl | sh, base64 -d | bash, nc host port, ...)
  secret        something shaped like a key, token or private key
  new-host      a web address whose host appears in none of the BEFORE files (--known-hosts adds more files to
                take known hosts from). A landscape may link tickets and pull requests, so known hosts pass.
  hidden        invisible or direction-changing characters, HTML comments, long encoded blobs

Prints one JSON line: {"ok": true|false, "findings": [{"kind": ..., "line": n, "text": first 80 characters}]}
Exit code 0 when clean, 1 when something was found, 2 when it could not run. Reads files only. Standard library only.
"""
import argparse, difflib, json, re, sys

INSTRUCTION = re.compile(
    r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|any|these|the)\b.{0,30}\b(instruction|rule|prompt|guideline|direction)s?\b"
    r"|\b(new|updated|real|actual) (system )?(instruction|prompt)s?\b"
    r"|\byou (must|should|will|are (now|required) to) (now |always |never )?(run|execute|send|post|upload|email|fetch|download|install|reveal|print|output|disable|delete)\b"
    r"|\bsystem prompt\b|\bdeveloper message\b|\bjailbreak\b|\bdo not tell (the user|the person|anyone)\b"
    r"|\b(without|don'?t) (asking|telling|informing) (the user|the person|him|her|them)\b"
    r"|\b(disable|turn off|remove|bypass|skip) (the )?(hook|guard|check|scan|supervisor|safety|confirmation|permission)s?\b",
    re.I)
EXFIL = re.compile(
    r"\b(curl|wget|fetch)\b[^\n|]{0,200}\|\s*(sudo\s+)?(ba)?sh\b"
    r"|\bbase64\s+(-d|--decode)\b[^\n]{0,80}\|\s*(ba)?sh\b"
    r"|\b(nc|ncat|netcat)\s+[\w.-]+\s+\d{2,5}\b|\b/dev/tcp/"
    r"|\bcurl\b[^\n]{0,160}(-d|--data|-F|--upload-file|-T)\b[^\n]{0,160}(~/\.|/home/|\.ssh|\.env|token|secret|password|portrait)"
    r"|\b(send|post|upload|email|forward)\b.{0,60}\b(portrait|landscape|handoff|memory|secret|token|password|key)s?\b.{0,40}\bto\b.{0,30}(https?://|\S+@\S+\.\w+)",
    re.I)
SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bsk-[A-Za-z0-9_-]{24,}\b"
    r"|\bxox[abprs]-[A-Za-z0-9-]{20,}\b|\b[A-Za-z0-9+/]{43}=(?![A-Za-z0-9+/=])|\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.")
URL = re.compile(r"https?://([A-Za-z0-9.-]+)", re.I)
HIDDEN = re.compile("[​-‏‪-‮⁠-⁤﻿]|<!--|\\b[A-Za-z0-9+/]{120,}={0,2}")


def hosts(text):
    return {h.lower().rstrip(".") for h in URL.findall(text or "")}


def added_lines(before, after):
    """(line number in AFTER, text) for every line that is new or changed."""
    b, a = before.splitlines(), after.splitlines()
    out = []
    for tag, _, _, j1, j2 in difflib.SequenceMatcher(None, b, a, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            out += [(j + 1, a[j]) for j in range(j1, j2)]
    return out


def scan(before, after, kind="portrait", known=()):
    known_hosts = hosts(before) | set().union(*[hosts(k) for k in known]) if known else hosts(before)
    findings = []
    for n, line in added_lines(before, after):
        hit = []
        if INSTRUCTION.search(line):
            hit.append("instruction")
        if EXFIL.search(line):
            hit.append("exfiltration")
        if SECRET.search(line):
            hit.append("secret")
        if HIDDEN.search(line):
            hit.append("hidden")
        if hosts(line) - known_hosts:
            hit.append("new-host")
        for k in hit:
            findings.append({"kind": k, "line": n, "text": " ".join(line.split())[:80]})
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=("portrait", "landscape"), default="portrait")
    ap.add_argument("--known-hosts", action="append", default=[])
    ap.add_argument("before")
    ap.add_argument("after")
    a = ap.parse_args(argv)
    try:
        rd = lambda p: open(p, encoding="utf-8", errors="replace").read()
        before = rd(a.before) if a.before != "/dev/null" else ""
        f = scan(before, rd(a.after), a.kind, [rd(p) for p in a.known_hosts])
    except Exception as e:
        print(json.dumps({"ok": False, "error": type(e).__name__}))
        return 2
    print(json.dumps({"ok": not f, "findings": f}))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
