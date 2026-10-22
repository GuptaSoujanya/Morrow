"""Planted positive fixture. Every line below exists to make one check fire.

Instruments expected to fire here: semgrep (python packs), bandit, ruff (F401, F821),
gitleaks dir (fake AWS key and fake GitHub token: both are made up, not real credentials).
"""

import os
import pickle
import subprocess

import yaml


def run(cmd):
    return subprocess.call(cmd, shell=True)


def calc(expr):
    return eval(expr)


def load(blob):
    return pickle.loads(blob)


def parse(text):
    return yaml.load(text)


def bad():
    return undefined_name


AWS_ACCESS_KEY_ID = "AKIAZ3X7Q2W6V5T4L2M3"
GITHUB_TOKEN = "ghp_Q7v3K9pL2mN8xR4tY6wZ1aB5cD0eF3gH7jK2"
