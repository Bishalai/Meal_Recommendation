#!/usr/bin/env python
"""
Generate demo users and rating history for the recommendation engine.

Collaborative filtering needs a community of users who rated dishes.  This
script invents `--count` (default 40) demo users, gives each of them taste
tags, a profile and a few hundred days of meal ratings, and appends everything
to the CSV files that `core/recommendation.py` reads:

    core/data/user_info.csv    one row per generated user
    core/data/user_data.csv    the generated ratings

The ratings are not purely random: a user mostly rates dishes that match
their own taste tags (diet, allergies and diseases are respected), which is
exactly the structure collaborative filtering needs to find "users with a
similar taste".

Demo users live only in the CSV files - they are not Django accounts and
cannot sign in; they exist so that real users get sensible collaborative
recommendations from day one.

Usage (from the `backend/` folder):

    python scripts/generate_users.py                # add 40 demo users
    python scripts/generate_users.py --count 60     # add 60
    python scripts/generate_users.py --force        # remove old demo users first
    python scripts/generate_users.py --remove       # only remove demo users
    python scripts/generate_users.py --seed 7       # reproducible output
"""

import argparse
import random
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "core" / "data"
ENCODING = "cp1252"
PREFIX = "demo_"          # generated usernames always start with this

FIRST_NAMES = [
    "ram", "shyam", "gita", "sita", "hari", "maya", "anil", "rita",
    "dipak", "sunita", "kiran", "mangal", "bina", "prakash", "nabin",
    "rinki", "sujata", "pradip", "sabina", "amrit", "kirsha", "nisha",
    "bikash", "sangita", "dinesh", "muna", "sajan", "puspa", "ranjan",
    "sabita", "gopal", "mangala", "sajan", "rita", "aadarsh", "kaushal",
    "bishal", "laxmi", "durga", "gopal", "sarmila", "anisha",
]

LIFESTYLES = ["sedentary", "lightlyactive", "moderateactive", "veryactive", "extraactive"]
LIFESTYLE_WEIGHTS = [0.25, 0.35, 0.25, 0.10, 0.05]

DIETS = ["non-vegetarian", "vegetarian"]
DIET_WEIGHTS = [0.6, 0.4]

# words that are always available as taste tags, even with a small catalogue
EXTRA_TAGS = [
    "spicy", "oily", "fried", "steamed", "curry", "snack", "sweet", "savory",
    "light", "heavy", "breakfast", "noodles", "rice", "soup",
]


def load(filename):
    return pd.read_csv(DATA_DIR / filename, encoding=ENCODING)


def save(filename, dataframe):
    dataframe.to_csv(DATA_DIR / filename, encoding=ENCODING, index=False)


def tag_pool(foods):
    """Every usable word of the catalogue: dish names + ingredients + diet."""
    words = set(EXTRA_TAGS)
    text = (
        foods["name"].fillna("").astype(str)
        + " "
        + foods["ingredients"].fillna("").astype(str)
        + " "
        + foods["diet"].fillna("").astype(str)
    )
    for line in text:
        for word in re.findall(r"[a-z]{3,}", line.lower()):
            words.add(word)
    return sorted(words)


def excluded_ingredients(user, disease_list):
    """Ingredients this demo user must not eat (allergy + diseases)."""
    excluded = set()
    if isinstance(user["allergy"], str) and user["allergy"].strip():
        excluded |= {i.strip() for i in user["allergy"].split(",") if i.strip()}
    if isinstance(user["disease"], str) and user["disease"].strip():
        for disease in user["disease"].split(","):
            rows = disease_list[disease_list["disease"] == disease.strip()]
            if not rows.empty:
                value = rows["excluded_ingredients"].values[0]
                if isinstance(value, str) and value.strip():
                    excluded |= {i.strip() for i in value.split(",") if i.strip()}
    return excluded


def food_words(food):
    text = f"{food['name']} {food['ingredients']} {food['diet']}"
    return set(re.findall(r"[a-z]{3,}", str(text).lower()))


def candidates_for(user, foods, disease_list):
    """Dishes this demo user is allowed and willing to eat."""
    blocked = excluded_ingredients(user, disease_list)
    usable = []
    for _, food in foods.iterrows():
        if user["diet"] == "vegetarian" and food["diet"] == "non-vegetarian":
            continue
        if food_words(food) & blocked:
            continue
        usable.append(food)
    # dicts behave exactly like the Series rows above
    return usable if usable else list(foods.to_dict("records"))


def choose_tags(pool, rng):
    count = rng.randint(3, 6)
    return ", ".join(rng.sample(pool, min(count, len(pool))))


def pick_ratings(user, tags, foods, disease_list, rng, today):
    """
    Pick 6-14 dishes and rate them 1-5, favouring dishes that match the tags.

    Dates and time slots are unique per user so the history keeps one row per
    (user, date, time) - the same rule `remove_duplicates()` enforces.
    """
    allowed = candidates_for(user, foods, disease_list)
    wanted = min(rng.randint(6, 14), len(allowed))
    if wanted == 0:
        return []

    scored = sorted(allowed, key=lambda f: -(len(tags & food_words(f)) + rng.random()))
    # a biased sample: mostly liked dishes, a few random ones
    favourites = scored[: max(wanted - 2, 1)]
    extras = rng.sample(scored[len(favourites):], min(2, max(len(scored) - len(favourites), 0)))
    chosen = (favourites + extras)[:wanted]

    rows, used_slots = [], set()
    for food in chosen:
        while True:
            date = today - timedelta(days=rng.randint(0, 500))
            time = rng.choice([t.strip() for t in str(food["time"]).split(",") if t.strip()] or ["lunch"])
            if (date, time) not in used_slots:
                used_slots.add((date, time))
                break

        overlap = len(tags & food_words(food))
        base = 5 if overlap >= 2 else 4 if overlap == 1 else 3
        rating = max(1, min(5, base + rng.choice([-1, 0, 0, 1])))
        rows.append({
            "username": user["username"],
            "date": date.strftime("%d/%m/%Y"),
            "time": time,
            "food": food["name"],
            "rating": rating,
        })
    return rows


def generate(count, seed):
    rng = random.Random(seed)
    today = datetime.today()

    users = load("user_info.csv")
    foods = load("food.csv")
    history = load("user_data.csv")
    disease_list = load("disease_list.csv").fillna("")

    existing_demo = int(users["username"].fillna("").astype(str).str.startswith(PREFIX).sum())
    if existing_demo:
        print(f"note: {existing_demo} demo users already exist "
              "(use --force to remove them first, --remove to only remove them)")

    pool = tag_pool(foods)
    existing = set(users["username"].dropna().astype(str))
    new_users, new_ratings = [], []

    for index in range(1, count + 1):
        username = f"{PREFIX}{rng.choice(FIRST_NAMES)}{index:02d}"
        while username in existing:
            username = f"{PREFIX}{rng.choice(FIRST_NAMES)}{index:02d}{rng.randint(1, 99)}"
        existing.add(username)

        sex = rng.choice(["M", "F"])
        age = rng.randint(18, 58)
        height = round(rng.gauss(172 if sex == "M" else 160, 7), 1)
        weight = round(rng.gauss(72 if sex == "M" else 60, 10), 1)
        tags = choose_tags(pool, rng)
        disease = "diabetes" if rng.random() < 0.1 else ""
        allergy = rng.choice(["", "", "", "peanut", "tofu", "crab", "egg"])

        user = {
            "username": username,
            "name": username,
            "age": age,
            "weight": weight,
            "height": height,
            "sex": sex,
            "lifestyle": rng.choices(LIFESTYLES, LIFESTYLE_WEIGHTS)[0],
            "tags": tags,
            "diet": rng.choices(DIETS, DIET_WEIGHTS)[0],
            "disease": disease,
            "allergy": allergy,
        }
        new_users.append(user)
        new_ratings += pick_ratings(
            user, {t.strip() for t in tags.split(",")}, foods, disease_list, rng, today
        )

    if new_users:
        users = pd.concat([users, pd.DataFrame(new_users)], ignore_index=True)
        save("user_info.csv", users)
    if new_ratings:
        history = pd.concat([history, pd.DataFrame(new_ratings)], ignore_index=True)
        save("user_data.csv", history)

    print(f"added {len(new_users)} demo users and {len(new_ratings)} ratings")
    print(f"totals: {len(users)} users, {len(history)} ratings")
    print("demo usernames start with '%s' (CSV only - they cannot sign in)" % PREFIX)


def remove():
    users = load("user_info.csv")
    history = load("user_data.csv")

    users = users[~users["username"].fillna("").astype(str).str.startswith(PREFIX)]
    history = history[~history["username"].fillna("").astype(str).str.startswith(PREFIX)]

    save("user_info.csv", users)
    save("user_data.csv", history)
    print(f"removed demo data: {len(users)} users, {len(history)} ratings left")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=40,
                        help="number of demo users to add (default: 40)")
    parser.add_argument("--seed", type=int, default=None,
                        help="random seed for reproducible data")
    parser.add_argument("--force", action="store_true",
                        help="remove existing demo users before generating")
    parser.add_argument("--remove", action="store_true",
                        help="only remove the demo users, generate nothing")
    args = parser.parse_args()

    if args.remove:
        remove()
        return
    if args.force:
        remove()
    generate(args.count, args.seed)


if __name__ == "__main__":
    sys.exit(main())
