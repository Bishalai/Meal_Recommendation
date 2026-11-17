"""
Recommendation engine.

The engine is plain pandas/scikit-learn code: it does not depend on Django,
so it can also be reused outside of the web application (see `app/
recommendation.py` for the original standalone prototype).

Data lives in CSV files inside `core/data/`:
    food.csv           catalogue of dishes
    user_info.csv      one row per user (diet, allergies, tags, ...)
    user_data.csv      recommendation / rating history
    disease_list.csv   diseases and the ingredients to avoid
    ingredients_list.csv  nutrition values per ingredient (per 100 g)

Public functions used by the API:
    recommendmeal(time, username)      -> dict of food fields
    give_rating(food, rating, time, username) -> None
    calculate_user_macronutrients(username)   -> [kcal, carb_min, carb_max,
                                                  fat_min, fat_max,
                                                  protein_min, protein_max]
    calculate_macronutrients(ingredients)     -> [kcal, carb, fat, protein]
"""

import datetime
import math
import os
import random
import threading
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# CSV files ship with the app, so the path is always relative to this file.
DATA_DIR = Path(__file__).resolve().parent / "data"
TODAY = datetime.date.today().strftime("%d/%m/%Y")

LIFESTYLE_FACTORS = {
    "sedentary": 1.2,
    "lightlyactive": 1.375,
    "moderateactive": 1.55,
    "veryactive": 1.725,
    "extraactive": 1.9,
}

# how the two signals are blended when both are available
CONTENT_WEIGHT = 0.6   # similarity between the user's tags and each dish
COLLABORATIVE_WEIGHT = 0.4  # ratings of users with a similar taste

# values that appear in the CSVs when a field was left empty
EMPTY_VALUES = {"", "nan", "none", "null", "placeholder", "n/a"}


def clean_text(value):
    """
    Normalise a CSV text cell.

    Empty cells arrive from pandas as `NaN` (a float) or as the string
    `'nan'`/`'placeholder'`; all of them become `''` so the caller can simply
    test `if not tags:` instead of crashing on a float.
    """
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in EMPTY_VALUES else text


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
def load_req_data(filename, data_path=DATA_DIR):
    """Read a CSV file into a pandas DataFrame."""
    return pd.read_csv(os.path.join(data_path, filename), encoding="cp1252")


def load_data_to_csv(filename, dataframe, data_path=DATA_DIR):
    """Append a DataFrame to an existing CSV file (no header written)."""
    csv_path = os.path.join(data_path, filename)
    dataframe.to_csv(csv_path, mode="a", encoding="cp1252", index=False, header=False)


def write_data_to_csv(filename, dataframe, data_path=DATA_DIR):
    """Overwrite a CSV file with the given DataFrame."""
    csv_path = os.path.join(data_path, filename)
    dataframe.to_csv(csv_path, encoding="cp1252", index=False)


# ---------------------------------------------------------------------------
# Data frames used when a user signs up or adds a food
# ---------------------------------------------------------------------------
def user_dataframe(username, name, age, weight, height, sex, lifestyle, tags,
                   diet, disease, allergy):
    """Row for `user_info.csv`."""
    return pd.DataFrame(
        {
            "username": [username],
            "name": [name],
            "age": [age],
            "weight": [weight],
            "height": [height],
            "sex": [sex],
            "lifestyle": [lifestyle],
            "tags": [tags],
            "diet": [diet],
            "disease": [disease],
            "allergy": [allergy],
        }
    )


def user_datframe(user_name, date, time, food, rating):
    """Row for `user_data.csv` (rating history)."""
    return pd.DataFrame(
        {
            "username": [user_name],
            "date": [date],
            "time": [time],
            "food": [food],
            "rating": [rating],
        }
    )


def food_dataframe(user_name, name, description, nutrition, ingredient, time,
                   diet, type_food):
    """Row for `user_food.csv` (foods created by users)."""
    return pd.DataFrame(
        {
            "username": [user_name],
            "name": [name],
            "date": [TODAY],
            "description": [description],
            "nutrition": [nutrition],
            "ingredient": [ingredient],
            "time": [time],
            "diet": [diet],
            "type": [type_food],
        }
    )


# ---------------------------------------------------------------------------
# Datasets
#
# They are re-read at the start of every recommendation so that users or foods
# added after the server started are picked up.  `_data_lock` keeps the swap
# consistent when several requests run at the same time.
# ---------------------------------------------------------------------------
_data_lock = threading.RLock()

foods = load_req_data("food.csv")
users = load_req_data("user_info.csv")


def _refresh_datasets():
    """Re-read the food catalogue and the user list from disk."""
    global foods, users
    with _data_lock:
        foods = load_req_data("food.csv")
        users = load_req_data("user_info.csv")


# ---------------------------------------------------------------------------
# Small helpers around the food catalogue
# ---------------------------------------------------------------------------
def combine_features(row):
    """Bag-of-words document describing a dish."""
    return f"{row['name']} {row['description']} {row['ingredients']} {row['diet']}"


def get_name_from_index(index):
    return foods[foods.index == index]["name"].values[0]


def compare_with_foodvalue(index, column, value):
    return foods[foods.index == index][column].values[0] == value


def _food_nutrition(index):
    """`nutrition` column -> [kcal, carbohydrate, fat, protein]."""
    nutrition = foods[foods.index == index]["nutrition"].values[0]
    return list(map(float, nutrition.split(",")))


# ---------------------------------------------------------------------------
# Macronutrient calculations
# ---------------------------------------------------------------------------
def calculate_macronutrients(obtained_ingredients_list):
    """
    Sum the macros of a list of ingredients.

    `obtained_ingredients_list` is a list of [ingredient_name, weight_in_grams],
    e.g. [['Paneer', 20], ['Curd', 40]].
    Returns [energy(kcal), carbohydrate(g), fat(g), protein(g)].
    """
    ingredients_list = load_req_data("ingredients_list.csv").fillna(0)
    macro_nut = [0.0, 0.0, 0.0, 0.0]
    for name, weight in obtained_ingredients_list:
        rows = ingredients_list.loc[ingredients_list["ingredient"] == name]
        if rows.empty:
            continue  # unknown ingredient, skip it
        row = rows.iloc[0]

        def nutrient(column):
            # a missing nutrient cell must not poison the total with NaN
            value = row[column]
            return 0.0 if pd.isna(value) else float(value)

        macro_nut[0] += nutrient("energy") * (weight / 100)
        macro_nut[1] += nutrient("carbohydrate") * (weight / 100)
        macro_nut[2] += nutrient("fat") * (weight / 100)
        macro_nut[3] += nutrient("protein") * (weight / 100)
    return [round(value, 3) for value in macro_nut]


def calculate_user_macronutrients(username):
    """
    Daily macro targets for a user (Harris-Benedict + activity factor).

    Returns [kcal, carb_min, carb_max, fat_min, fat_max, protein_min, protein_max].
    Raises ValueError when the profile is too incomplete to compute anything.
    """
    _refresh_datasets()
    current_user = users.loc[users["username"] == username]
    if current_user.empty:
        raise ValueError(f"unknown user: {username}")
    current_user = current_user.iloc[0]

    # an empty cell comes back from pandas as NaN: report it instead of
    # returning a JSON document full of `NaN` values
    missing = [
        field for field in ("weight", "height", "age")
        if pd.isna(current_user[field])
    ]
    if missing:
        raise ValueError(
            "your profile is incomplete - fill in " + ", ".join(missing) + " first"
        )

    weight = float(current_user["weight"])
    height = float(current_user["height"])
    age = float(current_user["age"])
    sex = clean_text(current_user["sex"]).upper()
    lifestyle = clean_text(current_user["lifestyle"])

    # Harris-Benedict equation
    if sex == "M":
        bmr = 66.5 + (13.75 * weight) + (5.003 * height) - (6.75 * age)
    elif sex == "F":
        bmr = 655.1 + (9.53 * weight) + (1.850 * height) - (4.676 * age)
    else:
        bmr = 2000

    alpha = LIFESTYLE_FACTORS.get(lifestyle, 1.2)
    calories = alpha * bmr

    macros = [
        calories,              # energy
        calories * 0.45 / 4,   # carbs 45-60 % of calories
        calories * 0.60 / 4,
        calories * 0.20 / 9,   # fat 20-35 %
        calories * 0.35 / 9,
        calories * 0.10 / 4,   # protein 10-35 %
        calories * 0.35 / 4,
    ]
    return [round(value, 3) for value in macros]


# ---------------------------------------------------------------------------
# Filters - each one removes dishes the user must not see
# ---------------------------------------------------------------------------
def check_veg(sorted_similar_foods, username):
    """Remove non-vegetarian dishes for vegetarian users."""
    rows = users.loc[users["username"] == username]
    if rows.empty:
        return sorted_similar_foods
    diet = clean_text(rows["diet"].values[0])
    if diet == "vegetarian":
        sorted_similar_foods = [
            food for food in sorted_similar_foods
            if foods[foods.index == food[0]]["diet"].values[0] != "non-vegetarian"
        ]
    return sorted_similar_foods


def check_allergy(sorted_similar_foods, username):
    """Remove dishes containing an allergen or an ingredient bad for a disease."""
    diseases = load_req_data("disease_list.csv")
    current_user = users.loc[users["username"] == username]
    if current_user.empty:
        return sorted_similar_foods
    current_user = current_user.iloc[0]

    # empty allergy / disease cells arrive as NaN -> clean_text turns them
    # into '' so nothing is excluded instead of crashing on a float
    excluded = [item for item in clean_text(current_user["allergy"]).split(",") if item]

    for disease in clean_text(current_user["disease"]).split(","):
        rows = diseases[diseases["disease"] == disease]
        if rows.empty:
            continue
        excluded += [item for item in clean_text(rows["excluded_ingredients"].values[0]).split(",") if item]

    filtered = []
    for food in sorted_similar_foods:
        ingredients = str(foods[foods.index == food[0]]["ingredients"].values[0]).split(",")
        if not any(item in ingredients for item in excluded):
            filtered.append(food)
    return filtered


def check_time(sorted_similar_foods, time):
    """Only keep dishes that can be eaten at breakfast / lunch / dinner."""
    filtered = []
    for food in sorted_similar_foods:
        times = str(foods[foods.index == food[0]]["time"].values[0]).split(",")
        if time in times:
            filtered.append(food)
    return filtered


def remove_recently_recommended(sorted_similar_foods, username, history=None):
    """Filter out the 5 dishes recommended most recently to this user."""
    if history is None:
        history = load_req_data("user_data.csv")
    history = history.copy()
    history["date"] = pd.to_datetime(history["date"], dayfirst=True)
    history.sort_values(["date", "username"], inplace=True)

    recent = history.loc[history["username"] == username].tail(5)
    recent_foods = recent["food"].values

    return [food for food in sorted_similar_foods
            if get_name_from_index(food[0]) not in recent_foods]


# ---------------------------------------------------------------------------
# Scoring - three signals are combined into one ranking
#
#   1. content-based  : cosine similarity between the user's taste tags and
#                       every dish (needs tags, otherwise it is skipped)
#   2. collaborative  : users who rated like this user in the past are used
#                       to predict how much this user would like a dish
#                       (needs ratings, otherwise it is skipped)
#   3. popularity     : Bayesian average rating over the whole community
#                       (used as the cold-start fallback when both of the
#                       above are missing - a brand new user with no tags)
# ---------------------------------------------------------------------------
def content_scores(username):
    """{dish index: 0..1 similarity} or None when the user has no usable tags."""
    rows = users.loc[users["username"] == username]
    if rows.empty:
        return None
    tags = clean_text(rows["tags"].values[0])
    if not tags:
        return None  # no tags -> cold start for this signal

    documents = pd.concat(
        [foods.apply(combine_features, axis=1), pd.Series([tags])],
        ignore_index=True,
    )
    try:
        count_matrix = CountVectorizer(stop_words="english").fit_transform(documents)
    except ValueError:
        return None  # tags contained nothing but stop words

    # similarity of the last document (the user) with every dish
    similarities = cosine_similarity(count_matrix[-1:, :], count_matrix[:-1])[0]
    if not np.any(similarities):
        return None
    return {index: float(score) for index, score in enumerate(similarities)}


def collaborative_scores(username, history=None):
    """
    User-based collaborative filtering over the rating history.

    Returns {dish index: 0..1 predicted score} or None when there is not
    enough signal (new user, or nobody with a comparable taste).
    """
    if history is None:
        history = load_req_data("user_data.csv")
    history = history.dropna(subset=["username", "food", "rating"])
    if history.empty:
        return None

    ratings = history.pivot_table(
        index="username", columns="food", values="rating", aggfunc="mean"
    )
    if ratings.empty or ratings.shape[0] < 2 or username not in ratings.index:
        return None  # collaborative filtering needs at least one other user

    matrix = ratings.to_numpy(dtype=float)
    rated = ~np.isnan(matrix)

    # mean-centre every user so a generous rater is not compared unfairly
    counts = rated.sum(axis=1)
    means = np.divide(
        np.nansum(matrix, axis=1),
        counts,
        out=np.full(matrix.shape[0], np.nan),
        where=counts > 0,
    )
    centred = np.where(rated, matrix - means[:, None], 0.0)

    similarities = cosine_similarity(centred)
    me = list(ratings.index).index(username)
    my_similarities = similarities[me].copy()
    my_similarities[me] = 0.0
    if not np.any(my_similarities > 0):
        return None  # nobody rated the same dishes

    # weighted average of the neighbours' centred ratings
    weights = my_similarities[:, None] * rated.astype(float)
    denominator = np.abs(weights).sum(axis=0)
    predicted_centred = np.divide(
        (my_similarities @ centred),
        denominator,
        out=np.zeros(matrix.shape[1]),
        where=denominator > 0,
    )
    available = denominator > 0

    # centred rating -> 0..1 through a sigmoid
    scores = 1.0 / (1.0 + np.exp(-np.clip(predicted_centred, -20, 20)))

    # my own past ratings: never push a dish I disliked back to the top
    my_ratings = matrix[me]
    disliked = rated[me] & (my_ratings <= 2)
    scores[disliked] *= 0.4

    name_to_index = dict(zip(ratings.columns, foods.index))
    result = {}
    for column, score, ok in zip(ratings.columns, scores, available):
        index = name_to_index.get(column)
        if ok and index is not None:
            result[index] = float(score)
    return result or None


def popularity_scores(history=None):
    """
    Community fallback used for a cold start: the Bayesian average rating of
    every dish (shrunk towards the global mean so a single 5-star rating does
    not beat 40 solid 4-star ratings).  Returns {dish index: 0..1} or None
    when nobody has rated anything yet.
    """
    if history is None:
        history = load_req_data("user_data.csv")
    history = history.dropna(subset=["food", "rating"])
    if history.empty:
        return None

    stats = history.groupby("food")["rating"].agg(["mean", "count"])
    global_mean = history["rating"].mean()
    shrinkage = 3.0
    score = (stats["count"] * stats["mean"] + shrinkage * global_mean) / (
        stats["count"] + shrinkage
    )

    name_to_index = dict(zip(foods["name"], foods.index))
    result = {}
    for food_name, value in score.items():
        index = name_to_index.get(food_name)
        if index is not None:
            result[index] = float(value) / 5.0
    return result or None


def score_dishes(username, history=None):
    """
    Rank every dish for this user.

    Returns (sorted [(dish index, score)], method) where `method` explains
    which signal(s) produced the ranking - it is shown in the web interface.
    """
    if history is None:
        history = load_req_data("user_data.csv")

    content = content_scores(username)
    collaborative = collaborative_scores(username, history)
    popularity = popularity_scores(history)

    if content is not None and collaborative is not None:
        combined = {
            index: CONTENT_WEIGHT * value + COLLABORATIVE_WEIGHT * collaborative.get(index, 0.0)
            for index, value in content.items()
        }
        method = "hybrid: your taste tags + users with a similar taste"
    elif content is not None:
        combined = content
        method = "content-based: matched to your taste tags"
    elif collaborative is not None:
        combined = collaborative
        method = "collaborative: liked by users with a similar taste"
    elif popularity is not None:
        combined = popularity
        method = "cold start: popular dishes (add taste tags for personal picks)"
    else:
        # nothing to go on yet - pick from the whole catalogue
        combined = {index: 1.0 for index in foods.index}
        method = "cold start: full catalogue"

    if content is None and collaborative is None and popularity is None:
        items = list(combined.items())
        random.shuffle(items)  # variety for the very first recommendations
        return items, method

    return sorted(combined.items(), key=lambda item: item[1], reverse=True), method


# ---------------------------------------------------------------------------
# Building the answer sent back to the client
# ---------------------------------------------------------------------------
def _companion_index(sorted_similar_foods, top_index):
    """
    A staple is served with a curry and vice-versa: return the index of the
    best companion dish, or None when there is no companion.
    """
    top_type = foods[foods.index == top_index]["type"].values[0]
    wanted = "curry" if top_type == "staple" else "staple" if top_type == "curry" else None
    if wanted is None:
        return None
    for index, _score in sorted_similar_foods:
        if compare_with_foodvalue(index, "type", wanted):
            return index
    return None


def get_final_rec(sorted_similar_foods):
    """Build the response payload: the top dish plus its companion."""
    if not sorted_similar_foods:
        raise LookupError("no dish matches the user's profile for this time of day")

    top_index = sorted_similar_foods[0][0]
    result = foods.loc[foods.index == top_index].to_dict("list")

    companion_index = _companion_index(sorted_similar_foods, top_index)
    if companion_index is not None:
        companion = foods.loc[foods.index == companion_index].to_dict("list")
        for key, values in companion.items():
            result[key] = tuple(result.get(key, [])) + tuple(values)
    return result


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------
def update_userdata(rec_food, time, rating, username):
    """Append a recommendation to the user's history (one entry per time slot)."""
    history = load_req_data("user_data.csv").copy()
    history["date"] = pd.to_datetime(history["date"], dayfirst=True)

    today = pd.to_datetime(TODAY, dayfirst=True)
    already_rated = (
        (history["username"] == username)
        & (history["date"] == today)
        & (history["time"] == time)
    ).any()
    if already_rated:
        return

    load_data_to_csv("user_data.csv", user_datframe(username, TODAY, time, rec_food, rating))


def remove_duplicates(filename, subset=("username", "date", "time")):
    """Drop duplicate rows from a CSV file."""
    df = load_req_data(filename).drop_duplicates(subset=list(subset))
    write_data_to_csv(filename, df)


def remove_duplicate_users(filename):
    """Keep only the first row of every user in a CSV file."""
    remove_duplicates(filename, subset=("username",))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def recommendmeal_detailed(time, username):
    """
    Recommend a dish (plus a companion) for `username` at `time`.

    Returns {"food": ..., "method": ...} where `method` says which signal
    produced the ranking (hybrid / content / collaborative / cold start).
    Raises LookupError when no dish survives the filters and ValueError when
    the user is unknown.
    """
    _refresh_datasets()
    if users.loc[users["username"] == username].empty:
        raise ValueError(f"unknown user: {username}")

    history = load_req_data("user_data.csv")

    # rank every dish with the hybrid scorer, then apply the hard filters
    sorted_similar_foods, method = score_dishes(username, history)
    sorted_similar_foods = check_veg(sorted_similar_foods, username)
    sorted_similar_foods = check_allergy(sorted_similar_foods, username)
    sorted_similar_foods = check_time(sorted_similar_foods, time)
    sorted_similar_foods = remove_recently_recommended(
        sorted_similar_foods, username, history
    )

    return {"food": get_final_rec(sorted_similar_foods), "method": method}


def recommendmeal(time, username):
    """
    Same as `recommendmeal_detailed` but returns only the food payload.
    """
    return recommendmeal_detailed(time, username)["food"]


def give_rating(rec_food, username, time, rating):
    """Store the rating of a recommended dish in the user's history."""
    if isinstance(rec_food, (list, tuple)):
        rec_food = "".join(rec_food)
    update_userdata(rec_food=rec_food, time=time, rating=rating, username=username)
    remove_duplicates("user_data.csv")
